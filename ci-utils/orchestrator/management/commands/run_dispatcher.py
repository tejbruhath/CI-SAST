"""
The ci-utils dispatcher: the single long-running orchestration loop.

Exactly ONE of these runs (singleton -- ci-utils Deployment is 1 replica). It is
the only process that mutates k8s Jobs, the repo filesystem, and job state
transitions. The DRF API only records inbound results into Redis and wakes this
loop via an event.

Each tick:
  1. reconcile_results  -- results that arrived -> mark tool done, delete its Job
  2. reconcile_failures -- Jobs that died without a result -> retry or give up
  3. cleanups           -- delete repo workspace after artifacts were fetched
  4. dispatch           -- oldest-job-first, gated by the namespace ResourceQuota

Crash recovery (arch doc s9): all state is in Redis + k8s, so on restart the
first tick reconciles received results and failed Jobs automatically.
"""
import logging  # Structured logs for clone, dispatch, and reconcile paths.
import os  # Build workspace and artifact filesystem paths.
import shutil  # Remove clone workspaces on failure or cleanup.
import subprocess  # Run git clone/fetch/checkout as external processes.

from django.core.management.base import BaseCommand  # Django management command base class.

from orchestrator import aggregator, config, k8s_client as k8s, redis_store as store  # Core deps.

logger = logging.getLogger("orchestrator.dispatcher")  # Logger for the dispatcher loop.

TERMINAL = ("complete", "partial", "failed")  # Statuses that need no further work.


# ---- repo clone --------------------------------------------------------------
def clone_repo(job_id: str, repo_url: str, commit_sha: str) -> None:  # Materialize repo under REPOS_DIR.
    workspace = os.path.join(config.REPOS_DIR, job_id)  # Per-job directory on the shared volume.
    if os.path.exists(workspace):
        shutil.rmtree(workspace, ignore_errors=True)  # Start clean if a partial clone remains.
    if commit_sha in ("HEAD", "", None):  # Tip clone: shallow and fast.
        subprocess.run(["git", "clone", "--depth", "1", repo_url, workspace],
                       check=True, timeout=config.CLONE_TIMEOUT_SECONDS,  # Fail on error or timeout.
                       capture_output=True, text=True)  # Capture stderr for logging on failure.
    else:  # Pin to a specific commit SHA with a shallow fetch.
        os.makedirs(workspace, exist_ok=True)  # Empty dir for git init.
        subprocess.run(["git", "init"], cwd=workspace, check=True,
                       capture_output=True, text=True)  # New repo without remote history.
        subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=workspace,
                       check=True, capture_output=True, text=True)  # Point origin at the URL.
        subprocess.run(["git", "fetch", "--depth", "1", "origin", commit_sha],
                       cwd=workspace, check=True,
                       timeout=config.CLONE_TIMEOUT_SECONDS,  # Abort slow fetches.
                       capture_output=True, text=True)  # Fetch only the needed commit.
        subprocess.run(["git", "checkout", "FETCH_HEAD"], cwd=workspace,
                       check=True, capture_output=True, text=True)  # Detach at fetched commit.


def ensure_cloned(job_id: str, job: dict) -> bool:  # Clone once; True means workspace is ready.
    if store.is_cloned(job_id):
        return True  # Already cloned earlier; skip network work.
    try:
        logger.info("[%s] cloning %s @ %s", job_id, job["repo_url"],
                    job.get("commit_sha"))  # Trace clone start for ops.
        clone_repo(job_id, job["repo_url"], job.get("commit_sha", "HEAD"))  # Perform git work.
        store.mark_cloned(job_id)  # Persist success so retries do not re-clone.
        return True  # Ready for tool dispatch.
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)  # Prefer git stderr if present.
        logger.error("[%s] clone failed: %s", job_id, detail)  # Surface failure reason.
        store.set_status(job_id, "failed")  # Terminal failure; no scanners will run.
        store.remove_from_queue(job_id)  # Stop future dispatch attempts for this job.
        return False  # Caller skips dispatch for this job.


# ---- finalize ----------------------------------------------------------------
def maybe_finalize(job_id: str) -> None:  # If all tools settled, write mega-artifact and close.
    if store.tools_pending(job_id) or store.tools_running(job_id):
        return  # Still work in flight; wait for later ticks.
    done = store.tools_done(job_id)  # Tools that produced results.
    failed = store.tools_failed(job_id)  # Tools that exhausted retries.
    if not done and not failed:
        return  # Nothing terminal yet (edge case empty state).
    if store.get_status(job_id) in TERMINAL:
        return  # Already finalized; avoid double writes.

    job = store.get_job(job_id)  # Need ci_context and project_key for aggregation.
    results = {t: store.get_result(job_id, t) for t in done}  # Only successful tool payloads.
    artifact = aggregator.aggregate(job_id, job, results)  # Build v3 mega-artifact dict.

    out_dir = os.path.join(config.ARTIFACTS_DIR, job_id)  # Per-job artifact folder.
    os.makedirs(out_dir, exist_ok=True)  # Ensure directory exists before write.
    import json  # Local import keeps top-level deps minimal for this command.
    with open(os.path.join(out_dir, "mega-artifact.json"), "w") as f:
        json.dump(artifact, f, indent=2)  # Pretty-print for human debugging.

    status = "partial" if failed else "complete"  # Partial if any tool gave up.
    store.set_status(job_id, status)  # Mark job terminal in Redis.
    store.remove_from_queue(job_id)  # No longer a dispatch candidate.
    logger.info("[%s] %s — %d findings (failed tools: %s)", job_id, status,
                artifact["summary"]["total_findings"], sorted(failed) or "none")


# ---- reconcilers -------------------------------------------------------------
def reconcile_results() -> None:  # Promote tools whose results arrived via the API.
    for job_id in store.all_job_ids():  # Every known job, including post-queue ones.
        if store.get_status(job_id) in TERMINAL:
            continue  # Skip finished jobs entirely.
        for tool in list(store.tools_running(job_id)):  # Snapshot set before mutating.
            if store.has_result(job_id, tool):  # API already stored a payload.
                store.move_tool(job_id, tool, "running", "done")  # Mark tool successful.
                attempt = store.attempts_get(job_id, tool)  # Which Job name to delete.
                k8s.delete_job(k8s.job_name(tool, job_id, attempt))  # Free cluster resources.
                logger.info("[%s] %s done (result received); Job deleted",
                            job_id, tool)
        maybe_finalize(job_id)  # Close job if this was the last tool.


def reconcile_failures() -> None:  # Retry or fail tools whose k8s Jobs died without results.
    for job_id in store.all_job_ids():
        if store.get_status(job_id) in TERMINAL:
            continue  # Nothing to reconcile for finished jobs.
        for tool in list(store.tools_running(job_id)):  # Tools still marked running.
            if store.has_result(job_id, tool):
                continue  # handled by reconcile_results
            phase = k8s.job_phase(job_id, tool)  # Inspect newest Job status in k8s.
            # 'succeeded' with no result, 'failed', or 'absent' (TTL-reaped
            # without a result) all count as a failed attempt.
            if phase in ("failed", "succeeded", "absent"):  # Treat as a failed attempt.
                attempts = store.attempts_get(job_id, tool)  # How many times we launched.
                k8s.delete_job(k8s.job_name(tool, job_id, attempts))  # Clean up the dead Job.
                if attempts < config.MAX_RETRIES:  # Still budget left for another try.
                    store.move_tool(job_id, tool, "running", "pending")  # Back to dispatch queue.
                    store.requeue(job_id)  # Ensure job is on the pending ZSET again.
                    logger.warning("[%s] %s attempt %d %s -> retrying",
                                   job_id, tool, attempts, phase)
                else:
                    store.move_tool(job_id, tool, "running", "failed")  # Give up on this tool.
                    logger.error("[%s] %s exhausted %d attempts (%s) -> giving up",
                                 job_id, tool, attempts, phase)
        maybe_finalize(job_id)  # May become partial/complete after failures settle.


def do_cleanup(job_id: str) -> None:  # Free disk and Redis after artifact was fetched.
    repo_path = os.path.join(config.REPOS_DIR, job_id)  # Clone workspace path.
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path, ignore_errors=True)  # Delete source tree to reclaim PVC space.
        logger.info("[%s] repo workspace removed", job_id)
    # Best-effort: ensure no scanner Jobs linger, then drop Redis state.
    for tool in config.TOOLS:  # Try deleting any remaining Job objects.
        attempt = store.attempts_get(job_id, tool)
        if attempt:
            k8s.delete_job(k8s.job_name(tool, job_id, attempt))  # Ignore 404 inside delete_job.
    store.delete_job_keys(job_id)  # Remove all Redis keys for idle-zero-footprint.
    logger.info("[%s] job state cleared (idle-zero-footprint)", job_id)


# ---- dispatch ----------------------------------------------------------------
def dispatch(job_id: str, tool: str, job: dict) -> None:  # Launch one scanner Job for a tool.
    attempt = store.attempts_incr(job_id, tool)  # Bump counter first; names use this number.
    j = k8s.build_job(tool, job_id, job.get("project_key", ""),
                      job.get("sonar_token", ""), attempt)  # Build V1Job body.
    k8s.create_job(j)  # Submit Job to the API server.
    store.move_tool(job_id, tool, "pending", "running")  # Reflect cluster reality in Redis.
    if store.get_status(job_id) == "queued":
        store.set_status(job_id, "running")  # First tool moves job out of queued.
    logger.info("[%s] dispatched %s (attempt %d) as %s", job_id, tool, attempt,
                k8s.job_name(tool, job_id, attempt))


def dispatch_pass() -> None:  # Capacity-aware oldest-first multi-tool dispatch loop.
    hard, used_reported = k8s.read_quota()  # Hard ceilings and controller-reported usage.

    # Compute usage authoritatively from our own running set rather than trusting
    # the quota controller's eventually-consistent status.used (which lags a
    # freshly-created Job by ~1s). Use the larger of the two to stay safe.
    # Both requests.* AND limits.* dimensions are tracked -- checking only
    # requests previously let this approve a dispatch that fit the requests
    # quota but blew the separate limits.cpu/limits.memory quota, which k8s's
    # admission control then rejected forever (see k8s_client.read_quota()).
    rcpu_running = rmem_running = lcpu_running = lmem_running = 0.0  # Our own usage totals.
    for jid in store.all_job_ids():  # Sum resources of tools we believe are running.
        for t in store.tools_running(jid):
            res = config.TOOL_RESOURCES[t]  # Footprint for this tool.
            rcpu_running += k8s.cpu_to_millicores(res["requests"]["cpu"])  # Request CPU millicores.
            rmem_running += k8s.mem_to_bytes(res["requests"]["memory"])  # Request memory bytes.
            lcpu_running += k8s.cpu_to_millicores(res["limits"]["cpu"])  # Limit CPU millicores.
            lmem_running += k8s.mem_to_bytes(res["limits"]["memory"])  # Limit memory bytes.
    rcpu_used = max(used_reported["requests.cpu"], rcpu_running)  # Take max to avoid undercount.
    rmem_used = max(used_reported["requests.memory"], rmem_running)
    lcpu_used = max(used_reported["limits.cpu"], lcpu_running)
    lmem_used = max(used_reported["limits.memory"], lmem_running)

    progress = True  # Outer loop continues while we still dispatch something.
    while progress:
        progress = False  # Assume no dispatch until we succeed once this scan.
        for job_id in store.pending_job_ids():   # oldest -> newest
            if store.get_status(job_id) in TERMINAL:
                continue  # Skip terminal jobs still lingering on the ZSET.
            pend = store.tools_pending(job_id)  # Tools not yet launched for this job.
            # cheapest pending tool (TOOLS is ordered cheapest-first)
            tool = next((t for t in config.TOOLS if t in pend), None)  # Prefer cheaper tools first.
            if tool is None:
                continue  # No pending tools; maybe waiting on running ones.
            res = config.TOOL_RESOURCES[tool]  # Resource cost of the next tool.
            rc = k8s.cpu_to_millicores(res["requests"]["cpu"])  # Incremental request CPU.
            rm = k8s.mem_to_bytes(res["requests"]["memory"])  # Incremental request memory.
            lc = k8s.cpu_to_millicores(res["limits"]["cpu"])  # Incremental limit CPU.
            lm = k8s.mem_to_bytes(res["limits"]["memory"])  # Incremental limit memory.
            if (rcpu_used + rc > hard["requests.cpu"] or rmem_used + rm > hard["requests.memory"]
                    or lcpu_used + lc > hard["limits.cpu"] or lmem_used + lm > hard["limits.memory"]):
                # this job's next tool isn't capacity-available; let newer jobs try
                continue  # Quota would be exceeded; try other jobs' cheaper tools.
            job = store.get_job(job_id)  # Load repo_url and secrets for clone/dispatch.
            if not ensure_cloned(job_id, job):
                continue  # Clone failed; job already marked failed.
            dispatch(job_id, tool, job)  # Create the k8s Job and update Redis sets.
            rcpu_used += rc; rmem_used += rm  # Account for the just-dispatched footprint.
            lcpu_used += lc; lmem_used += lm
            progress = True  # We made progress; re-scan from oldest after one dispatch.
            break   # re-evaluate from the oldest job after every dispatch


class Command(BaseCommand):  # Django management command: `python manage.py run_dispatcher`.
    help = "Run the ci-utils scan dispatcher loop (singleton)."  # Shown in manage.py help.

    def handle(self, *args, **opts):  # Entry point when the command starts.
        k8s.init()  # Load kubeconfig and create API clients once.
        known = store.all_job_ids()  # Jobs present at startup for crash recovery.
        logger.info("Dispatcher starting. Recovering %d known job(s): %s",
                    len(known), known or "none")
        while True:  # Infinite loop: this process is the long-running orchestrator.
            try:
                events = store.wait_events(config.DISPATCHER_TICK_SECONDS)  # Block or timeout tick.
                cleanups = [e.split(":", 1)[1] for e in events
                            if e.startswith("cleanup:")]  # Extract job ids from cleanup events.
                # Reconcile + dispatch runs every tick (event-driven, but the
                # blpop timeout also gives us a periodic reconcile so k8s Job
                # failures without an inbound result are still caught).
                reconcile_results()  # Results first so successes are not treated as failures.
                reconcile_failures()  # Then handle dead Jobs without results.
                for cid in cleanups:
                    do_cleanup(cid)  # Free repo + Redis after artifact fetch.
                dispatch_pass()  # Launch more tools if quota allows.
            except Exception as exc:
                logger.exception("dispatcher tick error: %s", exc)  # Log and keep the loop alive.
