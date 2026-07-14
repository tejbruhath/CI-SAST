"""
Celery orchestration — the Sentriq pipeline (single-pipeline core loop).

run_scan(scan_id):
  clone/prepare -> run applicable tool adapters -> normalize -> aggregate+dedup
  -> persist Findings -> DeepSeek triage (real/FP/noise) -> DeepSeek fix for
  real, high-severity findings -> finalize. Provenance is written at every
  stage.

Replaces the old k8s-Job dispatcher + result-callback design: tools now run
locally (executor.run_tool) and results come back in-process, so there is no
POST-back API and no ResourceQuota gating.
"""
from __future__ import annotations

import logging
import os

from celery import shared_task
from django.utils import timezone

from . import config, executor
from .adapters import for_pipeline
from .aggregator import deduplicate
from .schema import SEV_SCORE, STATIC, summarize
from .models import Scan, Finding, Triage, FixSuggestion, HitlAction, ProvenanceEvent

logger = logging.getLogger("sentriq.tasks")


def _read_source(repo_dir: str, rel_file) -> str:
    """Full text of a finding's file, or "" when there isn't one (dynamic
    findings, missing file, binary). Fix generation diffs against this exact
    text, so it must not be reformatted."""
    if not rel_file:
        return ""
    path = os.path.join(repo_dir, rel_file)
    # Guard against a tool reporting a path outside the repo (e.g. "../../etc").
    if not os.path.abspath(path).startswith(os.path.abspath(repo_dir) + os.sep):
        logger.warning("refusing to read %s outside repo dir", rel_file)
        return ""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _context_snippet(source: str, line, radius: int = 12) -> str:
    """Line-numbered window around a finding, for triage context/citations.
    Numbered on purpose: triage cites lines, it never authors a diff."""
    if not source or line is None:
        return ""
    lines = source.splitlines()
    lo = max(0, line - 1 - radius)
    hi = min(len(lines), line - 1 + radius + 1)
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(lo, hi))


def _run_tools(scan: Scan, work_dir: str):
    """Run the adapters selected for this scan; return (findings, done, failed)."""
    findings, done, failed = [], [], []
    allowed_tools = set(scan.selected_tools or [a.NAME for a in for_pipeline(scan.pipeline)])
    for adapter in for_pipeline(scan.pipeline):
        if adapter.NAME not in allowed_tools:
            continue
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


def _triage_and_fix(scan: Scan, rows, work_dir: str) -> None:
    if not config.LLM_ENABLED:
        logger.info("[%s] LLM disabled; skipping triage/fix", scan.id)
        return
    # imported here so tool-only runs don't require httpx at import time
    from . import deepseek

    # "none" disables patch generation only — findings are still triaged. An
    # unreachable floor is how we skip fixes without skipping the LLM verdict.
    if scan.auto_fix_severity == "none":
        logger.info("[%s] auto-fix disabled; triage only", scan.id)
        fix_floor = float("inf")
    else:
        fix_floor = SEV_SCORE.get(scan.auto_fix_severity, 3)
    for row in rows:
        source = _read_source(work_dir, row.file)
        snippet = _context_snippet(source, row.line)
        t = deepseek.triage(_finding_dict(row), snippet)
        Triage.objects.create(
            finding=row, verdict=t.verdict, confidence=t.confidence,
            rationale=t.rationale, citation=t.citation,
            model=config.DEEPSEEK_MODEL)
        ProvenanceEvent.record(ProvenanceEvent.TRIAGE, f"triaged: {t.verdict}",
                               scan=scan, finding=row, verdict=t.verdict,
                               confidence=t.confidence)
        # Only spend fix-generation tokens on real findings at/above the policy.
        if t.verdict == Triage.REAL and row.severity_score >= fix_floor:
            fx = deepseek.generate_fix(_finding_dict(row), file_text=source)
            if fx.ok:
                fix = FixSuggestion.objects.create(
                    finding=row, diff=fx.diff, explanation=fx.explanation,
                    model=config.DEEPSEEK_MODEL)
                # Auto-approve non-critical fixes so PR can be created without HITL.
                if row.severity != "critical":
                    fix.status = FixSuggestion.APPROVED
                    fix.save(update_fields=["status"])
                    HitlAction.objects.create(
                        finding=row, action=HitlAction.APPROVE,
                        actor="sentriq-auto",
                        note=f"Auto-approved per scan policy (>= {scan.auto_fix_severity})")
                ProvenanceEvent.record(ProvenanceEvent.FIX, "fix generated",
                                       scan=scan, finding=row)


def _finding_dict(row: Finding) -> dict:
    return {
        "tool": row.tool, "type": row.type, "severity": row.severity,
        "rule_id": row.rule_id, "message": row.message, "file": row.file,
        "line": row.line, "details": row.details,
    }


@shared_task(name="sentriq.create_pr")
def create_pr(fix_id: str) -> dict:
    """Apply an approved fix to the repo and open a GitHub PR (Task B8).

    clone → branch sentriq/fix-<finding> → git apply diff → commit → push →
    open PR. Records pr_url / pr_status / pr_error on the FixSuggestion.
    """
    from . import scm
    fix = FixSuggestion.objects.select_related("finding__scan").get(id=fix_id)
    finding = fix.finding
    scan = finding.scan

    repo = scm.parse_repo(scan.target)
    if repo is None:
        fix.pr_status = FixSuggestion.PR_FAILED
        fix.pr_error = f"unsupported repo URL for PR automation: {scan.target}"
        fix.save(update_fields=["pr_status", "pr_error"])
        return {"fix": str(fix.id), "pr_status": fix.pr_status}

    branch = f"sentriq/fix-{str(finding.id)[:8]}"
    fix.pr_status = FixSuggestion.PR_CREATING
    fix.branch = branch
    fix.pr_error = ""
    fix.save(update_fields=["pr_status", "branch", "pr_error"])
    ProvenanceEvent.record(ProvenanceEvent.HITL, "PR creation started",
                           scan=scan, finding=finding, branch=branch)

    work_dir = executor.make_scratch(f"pr-{finding.id}")
    try:
        base = scm.default_branch(repo)
        title = f"[Sentriq] fix {finding.severity} {finding.rule_id} in {finding.file}"
        body = (f"Automated fix for a **{finding.severity}** finding from "
                f"`{finding.tool}`.\n\n**Rule:** {finding.rule_id}\n"
                f"**Location:** {finding.file}"
                + (f":{finding.line}" if finding.line else "") + "\n\n"
                f"**Finding:** {finding.message}\n\n"
                f"**Fix rationale:** {fix.explanation}\n\n"
                f"---\n_Generated by Sentriq ({fix.model}). Review before merge._")
        executor.apply_fix_and_push(scan.target, base, branch, fix.diff,
                                    f"{title}\n\nSentriq automated security fix.",
                                    work_dir)
        url = scm.open_pr(repo, branch, base, title, body)
        fix.pr_status = FixSuggestion.PR_OPEN
        fix.pr_url = url
        fix.save(update_fields=["pr_status", "pr_url"])
        ProvenanceEvent.record(ProvenanceEvent.HITL, "PR opened", scan=scan,
                               finding=finding, pr_url=url, branch=branch)
        logger.info("[%s] PR opened: %s", scan.id, url)
        return {"fix": str(fix.id), "pr_status": "open", "pr_url": url}
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        fix.pr_status = FixSuggestion.PR_FAILED
        fix.pr_error = str(detail)[:2000]
        fix.save(update_fields=["pr_status", "pr_error"])
        ProvenanceEvent.record(ProvenanceEvent.HITL, "PR creation failed",
                               scan=scan, finding=finding, error=str(detail)[:500])
        logger.exception("[%s] PR creation failed", scan.id)
        return {"fix": str(fix.id), "pr_status": "failed"}
    finally:
        executor.cleanup(work_dir)


@shared_task(name="sentriq.run_scan")
def run_scan(scan_id: str) -> dict:
    scan = Scan.objects.get(id=scan_id)
    scan.status = Scan.RUNNING
    if not scan.tools_requested:
        scan.tools_requested = [a.NAME for a in for_pipeline(scan.pipeline)]
    scan.save(update_fields=["status", "tools_requested"])
    ProvenanceEvent.record(ProvenanceEvent.SCAN, "scan started", scan=scan,
                           pipeline=scan.pipeline, target=scan.target)

    work_dir = executor.make_scratch(str(scan.id))
    try:
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

        raw_findings, done, failed = _run_tools(scan, work_dir)
        findings = deduplicate(raw_findings)
        rows = _persist_findings(scan, findings)
        _triage_and_fix(scan, rows, work_dir)

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
    except Exception as exc:
        # Any unhandled error must mark the scan FAILED — never leave it stuck
        # at "running" (which the UI would show forever).
        logger.exception("[%s] pipeline error", scan.id)
        scan.status = Scan.FAILED
        scan.error = f"pipeline error: {exc}"[:2000]
        scan.finished_at = timezone.now()
        scan.save()
        ProvenanceEvent.record(ProvenanceEvent.SCAN, "scan errored", scan=scan,
                               error=str(exc)[:500])
        return {"scan": str(scan.id), "status": scan.status}
    finally:
        executor.cleanup(work_dir)
