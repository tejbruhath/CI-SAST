---
title: Orchestration (Celery)
source: ci-utils/ciutils/celery.py, ci-utils/sentriq/tasks.py
---

# Orchestration (Celery)

> Runs the Sentriq pipeline as a single Celery task that clones the target, executes every adapter, aggregates findings, persists them, triages with an LLM, and generates fixes.

## Role in the pipeline

The orchestration layer is the entry point for a scan. A pipeline stage or API enqueues `sentriq.run_scan`, which performs all work in one worker process. It coordinates the [executor](03-executor.md), [adapters](02-adapters.md), [aggregator](04-aggregator.md), and [DeepSeek](05-deepseek.md) modules, and writes a [`ProvenanceEvent`](06-data-model.md) after every significant step so the scan is fully auditable.

## How it works

`ciutils/celery.py` bootstraps a standard Django-backed Celery app and auto-discovers tasks. `sentriq/tasks.py` defines the single `@shared_task` named `sentriq.run_scan` that drives the entire pipeline.

When a scan is enqueued, the task:

1. Loads the `Scan` row, sets `status = RUNNING`, records the requested adapter list, and writes the first `ProvenanceEvent`.
2. Creates a scratch working directory with `executor.make_scratch`.
3. For `STATIC` pipelines only, it clones the target repository with `executor.git_clone`; dynamic pipelines skip this step.
4. Runs every adapter returned by `for_pipeline(scan.pipeline)` through `executor.run_tool`, collecting raw findings, success/failure lists, and a provenance record per adapter.
5. Deduplicates raw findings with `deduplicate()`.
6. Persists the final findings as `Finding` rows.
7. If `LLM_ENABLED` is true, triages each finding with DeepSeek and, only for real findings whose severity is at least `FIX_MIN_SEVERITY`, generates a `FixSuggestion`.
8. Finalizes the scan status as `COMPLETE`, `PARTIAL`, or `FAILED`, writes a final provenance event, and cleans up the scratch directory.

This design replaces the older Kubernetes-Job dispatcher. Tools now run in-process via the executor, so there is no POST-back result API and no per-tool Kubernetes resource gating.

## Code walkthrough

The Celery app is configured in `ci-utils/ciutils/celery.py`:

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")

app = Celery("sentriq")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

This loads settings prefixed with `CELERY_` and discovers tasks from installed Django apps, which is how `sentriq.run_scan` becomes available.

The task starts by transitioning the scan to `RUNNING` and recording the start:

```python
@shared_task(name="sentriq.run_scan")
def run_scan(scan_id: str) -> dict:
    scan = Scan.objects.get(id=scan_id)
    scan.status = Scan.RUNNING
    scan.tools_requested = [a.NAME for a in for_pipeline(scan.pipeline)]
    scan.save(update_fields=["status", "tools_requested"])
    ProvenanceEvent.record(ProvenanceEvent.SCAN, "scan started", scan=scan,
                           pipeline=scan.pipeline, target=scan.target)
```

A scratch directory is created and cleaned up in a `finally` block:

```python
    work_dir = executor.make_scratch(str(scan.id))
    try:
        ...
    finally:
        executor.cleanup(work_dir)
```

For static pipelines, the repository is cloned; a clone failure immediately fails the scan and returns:

```python
        if scan.pipeline == STATIC:
            try:
                executor.git_clone(scan.target, scan.ref, work_dir)
                ProvenanceEvent.record(ProvenanceEvent.SCAN, "repo cloned",
                                       scan=scan)
            except Exception as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                scan.status = Scan.FAILED
                scan.error = f"clone failed: {detail}"[:2000]
                scan.finished_at = timezone.now()
                scan.save()
                ProvenanceEvent.record(ProvenanceEvent.SCAN, "clone failed",
                                       scan=scan, error=detail[:500])
                return {"scan": str(scan.id), "status": scan.status}
```

`_run_tools` loops over the pipeline adapters and executes each one through the executor. It writes a `ProvenanceEvent` for every adapter that completes or fails:

```python
def _run_tools(scan: Scan, work_dir: str):
    """Run every adapter for the scan's pipeline; return (findings, done, failed)."""
    findings, done, failed = [], [], []
    for adapter in for_pipeline(scan.pipeline):
        run = executor.run_tool(adapter, scan.target, work_dir,
                                timeout=config.TOOL_TIMEOUT_SECONDS)
        if run.ok:
            findings.extend(run.findings)
            done.append(adapter.NAME)
            ProvenanceEvent.record(
                ProvenanceEvent.SCAN, f"{adapter.NAME} completed", scan=scan,
                tool=adapter.NAME, findings=len(run.findings),
                duration_s=round(run.duration_s, 1))
        else:
            failed.append(adapter.NAME)
            ProvenanceEvent.record(
                ProvenanceEvent.SCAN, f"{adapter.NAME} failed", scan=scan,
                tool=adapter.NAME, error=run.error,
                stderr=run.stderr_tail[-200:])
        logger.info("[%s] %s -> ok=%s findings=%d", scan.id, adapter.NAME,
                    run.ok, len(run.findings))
    return findings, done, failed
```

After the tool loop, the task deduplicates, persists findings, and records the aggregation event:

```python
        raw_findings, done, failed = _run_tools(scan, work_dir)
        findings = deduplicate(raw_findings)
        rows = _persist_findings(scan, findings)
        _triage_and_fix(scan, rows, work_dir)
```

`_persist_findings` creates a `Finding` row for each normalized result and emits a `NORMALIZE` provenance event:

```python
def _persist_findings(scan: Scan, findings) -> list:
    rows = []
    for f in findings:
        row = Finding.objects.create(
            scan=scan, tool=f.tool, pipeline=f.pipeline, type=f.type,
            severity=f.severity, severity_score=f.severity_score,
            rule_id=f.rule_id, message=f.message, file=f.file, line=f.line,
            url=f.url, details=f.details, fingerprint=f.fingerprint)
        rows.append(row)
    ProvenanceEvent.record(ProvenanceEvent.NORMALIZE,
                           "findings aggregated + persisted", scan=scan,
                           count=len(rows))
    return rows
```

`_triage_and_fix` is gated by `LLM_ENABLED` and only spends fix-generation tokens on real, high-severity findings:

```python
def _triage_and_fix(scan: Scan, rows, work_dir: str) -> None:
    if not config.LLM_ENABLED:
        logger.info("[%s] LLM disabled; skipping triage/fix", scan.id)
        return
    # imported here so tool-only runs don't require httpx at import time
    from . import deepseek

    fix_floor = SEV_SCORE.get(config.FIX_MIN_SEVERITY, 3)
    for row in rows:
        snippet = _context_snippet(work_dir, row.file, row.line)
        t = deepseek.triage(_finding_dict(row), snippet)
        Triage.objects.create(
            finding=row, verdict=t.verdict, confidence=t.confidence,
            rationale=t.rationale, citation=t.citation,
            model=config.DEEPSEEK_MODEL)
        ProvenanceEvent.record(ProvenanceEvent.TRIAGE, f"triaged: {t.verdict}",
                               scan=scan, finding=row, verdict=t.verdict,
                               confidence=t.confidence)
        # Only spend fix-generation tokens on real, high-severity findings.
        if t.verdict == Triage.REAL and row.severity_score >= fix_floor:
            fx = deepseek.generate_fix(_finding_dict(row), snippet)
            if fx.ok:
                FixSuggestion.objects.create(
                    finding=row, diff=fx.diff, explanation=fx.explanation,
                    model=config.DEEPSEEK_MODEL)
                ProvenanceEvent.record(ProvenanceEvent.FIX, "fix generated",
                                       scan=scan, finding=row)
```

`_context_snippet` reads source lines around a finding to give the LLM context, and safely returns an empty string for dynamic findings or missing files:

```python
def _context_snippet(repo_dir: str, rel_file, line, radius: int = 12) -> str:
    """Read a few lines of source around a finding for LLM context. Empty
    string when unavailable (dynamic findings, missing file, etc.)."""
    if not rel_file or line is None:
        return ""
    path = os.path.join(repo_dir, rel_file)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    lo = max(0, line - 1 - radius)
    hi = min(len(lines), line - 1 + radius + 1)
    numbered = [f"{i+1}: {lines[i].rstrip()}" for i in range(lo, hi)]
    return "\n".join(numbered)
```

Finally, the scan status is resolved, persisted, and returned:

```python
        scan.tools_done = done
        scan.tools_failed = failed
        scan.summary = summarize(findings)
        scan.status = Scan.PARTIAL if failed else Scan.COMPLETE
        if not done and failed:
            scan.status = Scan.FAILED
        scan.finished_at = timezone.now()
        scan.save()
        ProvenanceEvent.record(ProvenanceEvent.SCAN, f"scan {scan.status}",
                               scan=scan, findings=len(rows),
                               tools_done=done, tools_failed=failed)
        logger.info("[%s] %s — %d findings (failed: %s)", scan.id, scan.status,
                    len(rows), failed or "none")
        return {"scan": str(scan.id), "status": scan.status,
                "findings": len(rows)}
```

## Diagram

```mermaid
sequenceDiagram
    participant Caller as API / CLI
    participant CW as Celery Worker
    participant DB as Scan / Finding
    participant Ex as executor
    participant Ad as adapters
    participant Ag as aggregator
    participant LLM as deepseek
    participant PV as ProvenanceEvent

    Caller->>CW: send_task('sentriq.run_scan', scan_id)
    CW->>DB: status=RUNNING; save()
    CW->>PV: SCAN 'scan started'
    CW->>Ex: make_scratch(scan.id)
    alt pipeline == STATIC
        CW->>Ex: git_clone(target, ref, work_dir)
        CW->>PV: SCAN 'repo cloned'
    end
    loop for_pipeline(pipeline)
        CW->>Ad: adapter
        CW->>Ex: run_tool(adapter, target, work_dir)
        alt run.ok
            CW->>PV: SCAN '{NAME} completed'
        else run.ok == false
            CW->>PV: SCAN '{NAME} failed'
        end
    end
    CW->>Ag: deduplicate(raw_findings)
    CW->>DB: bulk create Finding rows
    CW->>PV: NORMALIZE 'findings aggregated + persisted'
    opt LLM_ENABLED
        loop each row
            CW->>CW: _context_snippet(work_dir, file, line)
            CW->>LLM: triage(finding, snippet)
            CW->>DB: create Triage
            CW->>PV: TRIAGE 'triaged: {verdict}'
            alt verdict == REAL && severity_score >= fix_floor
                CW->>LLM: generate_fix(finding, snippet)
                CW->>DB: create FixSuggestion
                CW->>PV: FIX 'fix generated'
            end
        end
    end
    CW->>DB: status=COMPLETE/PARTIAL/FAILED; save()
    CW->>PV: SCAN 'scan {status}'
    CW->>Ex: cleanup(work_dir)
    CW-->>Caller: {scan, status, findings}
```

## Key decisions & gotchas

- **Single-task pipeline.** All work from clone through fix generation runs inside one Celery task. This removes distributed coordination but means a worker crash loses the whole scan.
- **In-process tool execution.** `executor.run_tool` invokes adapters in the worker process; there is no separate Kubernetes Job per tool and no result-callback HTTP endpoint.
- **Provenance at every stage.** `ProvenanceEvent.record` is called on start, clone, each adapter completion/failure, persistence, triage, fix generation, and finalization. This is the audit trail.
- **Static-only clone.** `git_clone` is only called when `scan.pipeline == STATIC`. Dynamic pipelines must already have a reachable target at scan time.
- **Fix token budget.** Fixes are generated only for findings triaged as `REAL` with `severity_score >= SEV_SCORE[FIX_MIN_SEVERITY]`. This limits expensive LLM calls.
- **`deepseek` is lazily imported.** The module is imported inside `_triage_and_fix` so worker environments that only run tools do not need `httpx` installed at import time.
- **Status resolution.** `PARTIAL` means at least one tool succeeded but another failed; `FAILED` is used when no tools succeeded and at least one failed.
- **Scratch cleanup is unconditional.** The `finally` block calls `executor.cleanup(work_dir)` regardless of success or failure.

## Related docs

- [03-executor.md](03-executor.md) — scratch directories, cloning, and adapter invocation
- [02-adapters.md](02-adapters.md) — the adapters selected by `for_pipeline`
- [04-aggregator.md](04-aggregator.md) — `deduplicate()` and finding normalization
- [05-deepseek.md](05-deepseek.md) — `triage()` and `generate_fix()`
- [06-data-model.md](06-data-model.md) — `Scan`, `Finding`, `Triage`, `FixSuggestion`, and `ProvenanceEvent`
- [08-api.md](08-api.md) — how scans are enqueued
