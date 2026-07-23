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
from __future__ import annotations  # allow forward type hints without quotes

import logging  # structured task logs for operators
import os  # path joins and file existence checks
from concurrent.futures import ThreadPoolExecutor  # fan out LLM calls per batch

from celery import shared_task  # register functions as Celery tasks
from celery.signals import worker_ready  # hook when a worker process boots
from django.conf import settings  # read Celery time limits etc.
from django.utils import timezone  # timezone-aware timestamps

from . import config, crypto, executor  # app config, token crypto, tool runner
from .adapters import for_pipeline  # adapters for static or dynamic pipeline
from .aggregator import deduplicate  # merge duplicate fingerprints across tools
from .schema import SEV_SCORE, STATIC, summarize  # severity ranks and summary helper
from .models import Scan, Finding, Triage, FixSuggestion, HitlAction, ProvenanceEvent, UserProfile

logger = logging.getLogger("sentriq.tasks")  # module-level logger name


def _read_source(repo_dir: str, rel_file) -> str:
    """Full text of a finding's file, or "" when there isn't one (dynamic
    findings, missing file, binary). Fix generation diffs against this exact
    text, so it must not be reformatted."""
    if not rel_file:
        return ""  # no file path (e.g. pure DAST finding)
    path = os.path.join(repo_dir, rel_file)  # join under clone root
    # Guard against a tool reporting a path outside the repo (e.g. "../../etc").
    if not os.path.abspath(path).startswith(os.path.abspath(repo_dir) + os.sep):
        logger.warning("refusing to read %s outside repo dir", rel_file)
        return ""  # path traversal blocked
    if not os.path.isfile(path):
        return ""  # missing or not a regular file
    try:
        with open(path, "r", errors="replace") as f:  # replace bad bytes
            return f.read()  # full file text for LLM context
    except OSError:
        return ""  # I/O errors yield empty rather than crash


def _context_snippet(source: str, line, radius: int = 12) -> str:
    """Line-numbered window around a finding, for triage context/citations.
    Numbered on purpose: triage cites lines, it never authors a diff."""
    if not source or line is None:
        return ""  # nothing useful to show the model
    lines = source.splitlines()  # split once for indexing
    lo = max(0, line - 1 - radius)  # clamp window start to file start
    hi = min(len(lines), line - 1 + radius + 1)  # clamp window end
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(lo, hi))  # 1-based labels


def _run_tools(scan: Scan, work_dir: str):
    """Run the adapters selected for this scan; return (findings, done, failed).

    Saves tools_done/tools_failed after each adapter (not just at the end) so
    progress_pct climbs during the run instead of jumping 0 -> 80 at once.
    """
    findings, done, failed = [], [], []  # accumulators for this scan run
    allowed_tools = set(scan.selected_tools or [a.NAME for a in for_pipeline(scan.pipeline)])
    for adapter in for_pipeline(scan.pipeline):  # respect registry order
        if adapter.NAME not in allowed_tools:
            continue  # user deselected this tool
        run = executor.run_tool(adapter, scan.target, work_dir,
                                timeout=config.TOOL_TIMEOUT_SECONDS)  # Docker run
        if run.ok:
            findings.extend(run.findings)  # append normalized Finding objects
            done.append(adapter.NAME)  # track success for status UI
            ProvenanceEvent.record(
                ProvenanceEvent.SCAN, f"{adapter.NAME} completed", scan=scan,
                tool=adapter.NAME, findings=len(run.findings),
                duration_s=round(run.duration_s, 1))  # audit successful tool run
        else:
            failed.append(adapter.NAME)  # track failure without aborting others
            ProvenanceEvent.record(
                ProvenanceEvent.SCAN, f"{adapter.NAME} failed", scan=scan,
                tool=adapter.NAME, error=run.error,
                stderr=run.stderr_tail[-200:])  # last stderr for debugging
        scan.tools_done = done  # progressive save so UI progress moves
        scan.tools_failed = failed
        scan.save(update_fields=["tools_done", "tools_failed"])
        logger.info("[%s] %s -> ok=%s findings=%d", scan.id, adapter.NAME,
                    run.ok, len(run.findings))
    return findings, done, failed  # raw list + tool outcomes


def _persist_findings(scan: Scan, findings) -> list:
    rows = []  # ORM Finding rows we create
    for f in findings:
        row = Finding.objects.create(  # one DB row per normalized finding
            scan=scan, tool=f.tool, pipeline=f.pipeline, type=f.type,
            severity=f.severity, severity_score=f.severity_score,
            rule_id=f.rule_id, message=f.message, file=f.file, line=f.line,
            url=f.url, details=f.details, fingerprint=f.fingerprint)
        rows.append(row)
    ProvenanceEvent.record(ProvenanceEvent.NORMALIZE,
                           "findings aggregated + persisted", scan=scan,
                           count=len(rows))  # audit persistence step
    return rows


TRIAGE_BATCH_SIZE = 100  # DeepSeek concurrent-request ceiling


def _triage_one(row, work_dir: str, fix_floor: float):
    """Call DeepSeek for one finding. Runs on a worker thread — no DB access
    here (threads getting their own DB connections is how the triage/fix
    writes end up invisible inside a test's wrapping transaction, and in
    production it's a connection per finding with nothing to close them)."""
    from . import deepseek  # LLM client; imported inside to keep import graph light

    source = _read_source(work_dir, row.file)  # full file for fix generation
    snippet = _context_snippet(source, row.line)  # numbered window for triage
    t = deepseek.triage(_finding_dict(row), snippet)  # real / FP / noise verdict
    fx = None  # fix only if real and severe enough
    if t.verdict == Triage.REAL and row.severity_score >= fix_floor:
        fx = deepseek.generate_fix(_finding_dict(row), file_text=source)
    return row, t, fx  # caller writes DB on main thread


def _triage_and_fix(scan: Scan, rows, work_dir: str) -> None:
    if not config.LLM_ENABLED:
        logger.info("[%s] LLM disabled; skipping triage/fix", scan.id)
        return  # feature flag off: leave findings untriaged

    # "none" disables patch generation only — findings are still triaged. An
    # unreachable floor is how we skip fixes without skipping the LLM verdict.
    if scan.auto_fix_severity == "none":
        logger.info("[%s] auto-fix disabled; triage only", scan.id)
        fix_floor = float("inf")  # no severity can meet this threshold
    else:
        fix_floor = SEV_SCORE.get(scan.auto_fix_severity, 3)  # numeric bar for fixes

    scan.triage_total = len(rows)  # denominator for progress UI
    scan.triage_done = 0
    scan.save(update_fields=["triage_total", "triage_done"])

    # Batched + fanned out: each finding is one independent HTTP call to
    # DeepSeek, so within a batch they run concurrently on worker threads.
    # Batches of 100 cap in-flight requests at DeepSeek's concurrency
    # ceiling; triage_done is saved after each batch so progress_pct moves
    # instead of sitting at 80% for the whole triage phase. All DB writes
    # happen back on the calling thread once a batch's futures resolve.
    for start in range(0, len(rows), TRIAGE_BATCH_SIZE):  # slice into batches
        batch = rows[start:start + TRIAGE_BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            results = list(pool.map(
                lambda row: _triage_one(row, work_dir, fix_floor), batch))  # parallel

        for row, t, fx in results:  # sequential DB writes after batch finishes
            Triage.objects.create(
                finding=row, verdict=t.verdict, confidence=t.confidence,
                rationale=t.rationale, citation=t.citation,
                model=config.DEEPSEEK_MODEL)  # store model id for auditability
            ProvenanceEvent.record(ProvenanceEvent.TRIAGE, f"triaged: {t.verdict}",
                                   scan=scan, finding=row, verdict=t.verdict,
                                   confidence=t.confidence)
            if fx is not None and fx.ok:
                FixSuggestion.objects.create(
                    finding=row, diff=fx.diff, explanation=fx.explanation,
                    model=config.DEEPSEEK_MODEL,
                    context_strategy=fx.context_strategy)  # auto-generated, not yet approved
                ProvenanceEvent.record(ProvenanceEvent.FIX, "fix generated",
                                       scan=scan, finding=row)

        scan.triage_done = start + len(batch)  # progress after each batch
        scan.save(update_fields=["triage_done"])


def _finding_dict(row: Finding) -> dict:
    return {  # lean dict for LLM prompts (no ORM objects)
        "tool": row.tool, "type": row.type, "severity": row.severity,
        "rule_id": row.rule_id, "message": row.message, "file": row.file,
        "line": row.line, "details": row.details,
    }


@shared_task(name="sentriq.generate_fix")
def generate_fix_for_finding(finding_id: str) -> dict:
    """On-demand fix generation for a single finding.

    Re-clones the scan target, reads the affected file, asks the LLM for a fix,
    and stores it as PROPOSED (the user must still Approve in the UI). Idempotent
    for successful fixes; FAILED / empty-diff rows are deleted so RETRY works.
    Never raises.
    """
    from . import deepseek

    try:
        row = Finding.objects.select_related("scan").get(id=finding_id)
    except Finding.DoesNotExist:
        logger.warning("generate_fix: finding %s not found", finding_id)
        return {"finding": finding_id, "status": "not_found"}

    existing = row.fixes.first()  # newest fix if any
    if existing:
        # Successful proposal/approval — do not stack duplicates.
        if existing.status != FixSuggestion.FAILED and (existing.diff or "").strip():
            return {"finding": finding_id, "status": "exists", "fix": str(existing.id)}
        # Secrets guidance (and other guidance-only fixes) have empty diff but
        # a non-FAILED status — keep those too.
        if existing.status != FixSuggestion.FAILED and (existing.explanation or "").strip():
            return {"finding": finding_id, "status": "exists", "fix": str(existing.id)}
        existing.delete()  # FAILED or empty → allow retry

    scan = row.scan  # parent scan for clone target and provenance
    ProvenanceEvent.record(ProvenanceEvent.FIX, "on-demand fix generation started",
                           scan=scan, finding=row)

    work_dir = ""  # set if scratch created; cleaned in finally
    try:
        work_dir = executor.make_scratch(f"fix-{finding_id}")  # temp workspace
        executor.git_clone(scan.target, scan.ref, work_dir)  # fresh checkout
        source = _read_source(work_dir, row.file)  # file text for the model
        fx = deepseek.generate_fix(_finding_dict(row), file_text=source)
        if fx.ok:
            fix = FixSuggestion.objects.create(
                finding=row, diff=fx.diff, explanation=fx.explanation,
                status=FixSuggestion.PROPOSED, model=config.DEEPSEEK_MODEL,
                context_strategy=fx.context_strategy)  # HITL next
            ProvenanceEvent.record(ProvenanceEvent.FIX, "on-demand fix generated",
                                   scan=scan, finding=row, fix=str(fix.id))
            return {"finding": finding_id, "status": "created", "fix": str(fix.id)}
        # Persist failure so the UI can clear FIXING… and offer RETRY.
        fix = FixSuggestion.objects.create(
            finding=row, diff="", explanation=fx.explanation or "fix generation failed",
            status=FixSuggestion.FAILED, model=config.DEEPSEEK_MODEL)
        ProvenanceEvent.record(ProvenanceEvent.FIX, "on-demand fix failed",
                               scan=scan, finding=row, fix=str(fix.id),
                               error=fx.explanation)
        return {"finding": finding_id, "status": "failed", "reason": fx.explanation,
                "fix": str(fix.id)}
    except Exception as exc:
        logger.exception("generate_fix failed for finding %s", finding_id)
        reason = str(exc)[:500]
        fix = FixSuggestion.objects.create(
            finding=row, diff="", explanation=reason,
            status=FixSuggestion.FAILED, model=config.DEEPSEEK_MODEL)
        ProvenanceEvent.record(ProvenanceEvent.FIX, "on-demand fix errored",
                               scan=scan, finding=row, fix=str(fix.id), error=reason)
        return {"finding": finding_id, "status": "error", "reason": reason,
                "fix": str(fix.id)}
    finally:
        if work_dir:
            executor.cleanup(work_dir)  # always remove temp clone


@shared_task(name="sentriq.reap_orphaned_scans")
def reap_orphaned_scans() -> dict:
    """Mark RUNNING/QUEUED scans that outlived the task time limit as FAILED."""
    limit = getattr(settings, "CELERY_TASK_TIME_LIMIT", 3600)  # seconds, default 1h
    cutoff = timezone.now() - timezone.timedelta(seconds=limit)  # older than limit
    stale = Scan.objects.filter(
        status__in=(Scan.RUNNING, Scan.QUEUED), created_at__lt=cutoff)
    count = 0
    for scan in stale:
        scan.status = Scan.FAILED  # unstick UI from "running" forever
        scan.error = "orphaned: worker died mid-scan"
        scan.finished_at = timezone.now()
        scan.save(update_fields=["status", "error", "finished_at"])
        ProvenanceEvent.record(ProvenanceEvent.SCAN, "orphaned scan reaped",
                               scan=scan, error=scan.error)
        count += 1
        logger.warning("reaped orphaned scan %s (created %s)", scan.id, scan.created_at)
    return {"reaped": count}


@worker_ready.connect  # fire once when Celery worker process is ready
def _schedule_reap_on_boot(sender, **kwargs):
    """Run the orphan reaper once when a Celery worker starts."""
    reap_orphaned_scans.delay()  # async: clean up after prior worker crashes


@shared_task(name="sentriq.create_pr")
def create_pr(fix_id: str, user_id=None) -> dict:
    """Apply an approved fix to the repo and open a GitHub PR (Task B8).

    clone → branch sentriq/fix-<finding> → git apply diff → commit → push →
    open PR. Records pr_url / pr_status / pr_error on the FixSuggestion.

    When ``user_id`` is supplied and the user has a stored GitHub OAuth token,
    that token is used for GitHub API calls; otherwise the shared
    ``SENTRIQ_GIT_TOKEN`` is used.
    """
    from . import scm  # GitHub helpers: parse repo, open PR
    fix = FixSuggestion.objects.select_related("finding__scan").get(id=fix_id)
    finding = fix.finding
    scan = finding.scan

    repo = scm.parse_repo(scan.target)  # owner/name or None if unsupported
    if repo is None:
        fix.pr_status = FixSuggestion.PR_FAILED
        fix.pr_error = f"unsupported repo URL for PR automation: {scan.target}"
        fix.save(update_fields=["pr_status", "pr_error"])
        return {"fix": str(fix.id), "pr_status": fix.pr_status}

    user_token = None  # prefer per-user OAuth over shared PAT
    if user_id is not None:
        try:
            profile = UserProfile.objects.get(user_id=user_id)
            user_token = crypto.decrypt_token(profile.github_access_token)
        except UserProfile.DoesNotExist:
            user_token = None  # fall back to shared token in scm/executor

    branch = f"sentriq/fix-{str(finding.id)[:8]}"  # short unique branch name
    fix.pr_status = FixSuggestion.PR_CREATING  # UI shows in-progress
    fix.branch = branch
    fix.pr_error = ""
    fix.save(update_fields=["pr_status", "branch", "pr_error"])
    ProvenanceEvent.record(ProvenanceEvent.HITL, "PR creation started",
                           scan=scan, finding=finding, branch=branch)

    work_dir = executor.make_scratch(f"pr-{finding.id}")  # temp clone for apply/push
    try:
        base = scm.default_branch(repo, token=user_token)  # usually main or master
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
                                    work_dir, token=user_token)  # git apply + push
        url = scm.open_pr(repo, branch, base, title, body, token=user_token)
        fix.pr_status = FixSuggestion.PR_OPEN
        fix.pr_url = url  # store for UI deep-link
        fix.save(update_fields=["pr_status", "pr_url"])
        ProvenanceEvent.record(ProvenanceEvent.HITL, "PR opened", scan=scan,
                               finding=finding, pr_url=url, branch=branch)
        logger.info("[%s] PR opened: %s", scan.id, url)
        return {"fix": str(fix.id), "pr_status": "open", "pr_url": url}
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)  # prefer git stderr
        fix.pr_status = FixSuggestion.PR_FAILED
        fix.pr_error = str(detail)[:2000]  # cap stored error length
        fix.save(update_fields=["pr_status", "pr_error"])
        ProvenanceEvent.record(ProvenanceEvent.HITL, "PR creation failed",
                               scan=scan, finding=finding, error=str(detail)[:500])
        logger.exception("[%s] PR creation failed", scan.id)
        return {"fix": str(fix.id), "pr_status": "failed"}
    finally:
        executor.cleanup(work_dir)  # remove temp workspace always


def _user_token(user_id):
    """Decrypted GitHub OAuth token for a user, or None to fall back to the PAT."""
    if user_id is None:
        return None
    try:
        return crypto.decrypt_token(
            UserProfile.objects.get(user_id=user_id).github_access_token)
    except UserProfile.DoesNotExist:
        return None  # no profile: use shared SENTRIQ_GIT_TOKEN


@shared_task(name="sentriq.create_batch_pr")
def create_batch_pr(repo_full_name: str, user_id=None) -> dict:
    """Open ONE pull request containing every APPROVED fix for a repo.

    This is the "Create PR" button. It is deliberately scoped to approved work
    only: a generated-but-unapproved fix is the AI's opinion, not the user's
    decision, and must never reach a PR. Fixes already in a PR are skipped so
    pressing the button twice does not reopen the same work.
    """
    from . import scm

    fixes = list(
        FixSuggestion.objects
        .select_related("finding__scan")
        .filter(finding__scan__requested_by_id=user_id,  # tenant ownership
                finding__scan__target__icontains=repo_full_name,  # repo match
                status__in=[FixSuggestion.APPROVED, FixSuggestion.EDITED],
                pr_status=FixSuggestion.PR_NONE)  # not already opened
        .order_by("-finding__severity_score", "created_at"))  # worst first
    if not fixes:
        return {"status": "empty", "count": 0}

    scan = fixes[0].finding.scan  # any scan for this target is fine for clone
    repo = scm.parse_repo(scan.target)
    if repo is None:
        return {"status": "failed", "count": 0,
                "error": f"unsupported repo URL: {scan.target}"}

    token = _user_token(user_id)  # OAuth or None
    branch = f"sentriq/fixes-{timezone.now():%Y%m%d-%H%M%S}"  # unique batch branch
    for fx in fixes:
        fx.pr_status = FixSuggestion.PR_CREATING  # mark all as in-progress
        fx.branch = branch
        fx.pr_error = ""
        fx.save(update_fields=["pr_status", "branch", "pr_error"])
    ProvenanceEvent.record(ProvenanceEvent.HITL, "batch PR started", scan=scan,
                           branch=branch, fixes=len(fixes))

    work_dir = executor.make_scratch(f"batchpr-{scan.id}")
    try:
        base = scm.default_branch(repo, token=token)
        patches = [(f"{fx.finding.rule_id} in {fx.finding.file}", fx.diff)
                   for fx in fixes]  # labeled diffs for multi-patch apply
        applied = executor.apply_fix_and_push(
            scan.target, base, branch, patches,
            "[Sentriq] approved security fix", work_dir, token=token)

        lines = "\n".join(
            f"- **{fx.finding.severity}** `{fx.finding.rule_id}` in "
            f"`{fx.finding.file}` — {fx.explanation}" for fx in fixes)  # PR body list
        title = f"[Sentriq] {len(applied)} approved security fix" + ("es" if len(applied) != 1 else "")
        body = ("Every fix in this PR was explicitly approved in Sentriq before "
                "it was included. Nothing else was touched.\n\n"
                f"{lines}\n\n---\n_Generated by Sentriq. Review before merge._")
        url = scm.open_pr(repo, branch, base, title, body, token=token)

        for fx in fixes:
            fx.pr_status = FixSuggestion.PR_OPEN  # all share one PR URL
            fx.pr_url = url
            fx.save(update_fields=["pr_status", "pr_url"])
        ProvenanceEvent.record(ProvenanceEvent.HITL, "batch PR opened", scan=scan,
                               pr_url=url, branch=branch, applied=len(applied))
        logger.info("[batch-pr] %s fixes -> %s", len(applied), url)
        return {"status": "open", "pr_url": url, "branch": branch,
                "count": len(applied)}
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        for fx in fixes:
            fx.pr_status = FixSuggestion.PR_FAILED  # fail the whole batch together
            fx.pr_error = str(detail)[:2000]
            fx.save(update_fields=["pr_status", "pr_error"])
        ProvenanceEvent.record(ProvenanceEvent.HITL, "batch PR failed", scan=scan,
                               error=str(detail)[:500])
        logger.exception("[batch-pr] failed")
        return {"status": "failed", "count": 0, "error": str(detail)[:300]}
    finally:
        executor.cleanup(work_dir)


@shared_task(name="sentriq.run_scan")
def run_scan(scan_id: str) -> dict:
    scan = Scan.objects.get(id=scan_id)  # load scan row by UUID/id
    scan.status = Scan.RUNNING  # UI shows active work
    if not scan.tools_requested:
        scan.tools_requested = [a.NAME for a in for_pipeline(scan.pipeline)]
    scan.save(update_fields=["status", "tools_requested"])
    ProvenanceEvent.record(ProvenanceEvent.SCAN, "scan started", scan=scan,
                           pipeline=scan.pipeline, target=scan.target)

    work_dir = executor.make_scratch(str(scan.id))  # per-scan temp directory
    try:
        if scan.pipeline == STATIC:  # static needs a local clone of source
            try:
                executor.git_clone(scan.target, scan.ref, work_dir)
                ProvenanceEvent.record(ProvenanceEvent.SCAN, "repo cloned",
                                       scan=scan)
            except Exception as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                scan.status = Scan.FAILED  # cannot scan without source
                scan.error = f"clone failed: {detail}"[:2000]
                scan.finished_at = timezone.now()
                scan.save()
                ProvenanceEvent.record(ProvenanceEvent.SCAN, "clone failed",
                                       scan=scan, error=detail[:500])
                return {"scan": str(scan.id), "status": scan.status}

        raw_findings, done, failed = _run_tools(scan, work_dir)  # all selected tools
        findings = deduplicate(raw_findings)  # drop fingerprint duplicates
        rows = _persist_findings(scan, findings)  # write Finding rows
        _triage_and_fix(scan, rows, work_dir)  # LLM triage + optional fixes

        scan.tools_done = done
        scan.tools_failed = failed
        scan.summary = summarize(findings)  # rollup counts for list UI
        scan.status = Scan.PARTIAL if failed else Scan.COMPLETE  # some tools failed?
        if not done and failed:
            scan.status = Scan.FAILED  # every tool failed -> overall failure
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
        executor.cleanup(work_dir)  # always delete scratch, even on success
