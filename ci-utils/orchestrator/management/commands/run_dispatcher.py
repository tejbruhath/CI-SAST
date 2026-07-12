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
import logging
import os
import shutil
import subprocess

from django.core.management.base import BaseCommand

from orchestrator import aggregator, config, k8s_client as k8s, redis_store as store

logger = logging.getLogger("orchestrator.dispatcher")

TERMINAL = ("complete", "partial", "failed")


# ---- repo clone --------------------------------------------------------------
def clone_repo(job_id: str, repo_url: str, commit_sha: str) -> None:
    workspace = os.path.join(config.REPOS_DIR, job_id)
    if os.path.exists(workspace):
        shutil.rmtree(workspace, ignore_errors=True)
    if commit_sha in ("HEAD", "", None):
        subprocess.run(["git", "clone", "--depth", "1", repo_url, workspace],
                       check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                       capture_output=True, text=True)
    else:
        os.makedirs(workspace, exist_ok=True)
        subprocess.run(["git", "init"], cwd=workspace, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=workspace,
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "fetch", "--depth", "1", "origin", commit_sha],
                       cwd=workspace, check=True,
                       timeout=config.CLONE_TIMEOUT_SECONDS,
                       capture_output=True, text=True)
        subprocess.run(["git", "checkout", "FETCH_HEAD"], cwd=workspace,
                       check=True, capture_output=True, text=True)


def ensure_cloned(job_id: str, job: dict) -> bool:
    if store.is_cloned(job_id):
        return True
    try:
        logger.info("[%s] cloning %s @ %s", job_id, job["repo_url"],
                    job.get("commit_sha"))
        clone_repo(job_id, job["repo_url"], job.get("commit_sha", "HEAD"))
        store.mark_cloned(job_id)
        return True
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        logger.error("[%s] clone failed: %s", job_id, detail)
        store.set_status(job_id, "failed")
        store.remove_from_queue(job_id)
        return False


# ---- finalize ----------------------------------------------------------------
def maybe_finalize(job_id: str) -> None:
    if store.tools_pending(job_id) or store.tools_running(job_id):
        return
    done = store.tools_done(job_id)
    failed = store.tools_failed(job_id)
    if not done and not failed:
        return
    if store.get_status(job_id) in TERMINAL:
        return

    job = store.get_job(job_id)
    results = {t: store.get_result(job_id, t) for t in done}
    artifact = aggregator.aggregate(job_id, job, results)

    out_dir = os.path.join(config.ARTIFACTS_DIR, job_id)
    os.makedirs(out_dir, exist_ok=True)
    import json
    with open(os.path.join(out_dir, "mega-artifact.json"), "w") as f:
        json.dump(artifact, f, indent=2)

    status = "partial" if failed else "complete"
    store.set_status(job_id, status)
    store.remove_from_queue(job_id)
    logger.info("[%s] %s — %d findings (failed tools: %s)", job_id, status,
                artifact["summary"]["total_findings"], sorted(failed) or "none")


# ---- reconcilers -------------------------------------------------------------
def reconcile_results() -> None:
    for job_id in store.all_job_ids():
        if store.get_status(job_id) in TERMINAL:
            continue
        for tool in list(store.tools_running(job_id)):
            if store.has_result(job_id, tool):
                store.move_tool(job_id, tool, "running", "done")
                attempt = store.attempts_get(job_id, tool)
                k8s.delete_job(k8s.job_name(tool, job_id, attempt))
                logger.info("[%s] %s done (result received); Job deleted",
                            job_id, tool)
        maybe_finalize(job_id)


def reconcile_failures() -> None:
    for job_id in store.all_job_ids():
        if store.get_status(job_id) in TERMINAL:
            continue
        for tool in list(store.tools_running(job_id)):
            if store.has_result(job_id, tool):
                continue  # handled by reconcile_results
            phase = k8s.job_phase(job_id, tool)
            # 'succeeded' with no result, 'failed', or 'absent' (TTL-reaped
            # without a result) all count as a failed attempt.
            if phase in ("failed", "succeeded", "absent"):
                attempts = store.attempts_get(job_id, tool)
                k8s.delete_job(k8s.job_name(tool, job_id, attempts))
                if attempts < config.MAX_RETRIES:
                    store.move_tool(job_id, tool, "running", "pending")
                    store.requeue(job_id)
                    logger.warning("[%s] %s attempt %d %s -> retrying",
                                   job_id, tool, attempts, phase)
                else:
                    store.move_tool(job_id, tool, "running", "failed")
                    logger.error("[%s] %s exhausted %d attempts (%s) -> giving up",
                                 job_id, tool, attempts, phase)
        maybe_finalize(job_id)


def do_cleanup(job_id: str) -> None:
    repo_path = os.path.join(config.REPOS_DIR, job_id)
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path, ignore_errors=True)
        logger.info("[%s] repo workspace removed", job_id)
    # Best-effort: ensure no scanner Jobs linger, then drop Redis state.
    for tool in config.TOOLS:
        attempt = store.attempts_get(job_id, tool)
        if attempt:
            k8s.delete_job(k8s.job_name(tool, job_id, attempt))
    store.delete_job_keys(job_id)
    logger.info("[%s] job state cleared (idle-zero-footprint)", job_id)


# ---- dispatch ----------------------------------------------------------------
def dispatch(job_id: str, tool: str, job: dict) -> None:
    attempt = store.attempts_incr(job_id, tool)
    j = k8s.build_job(tool, job_id, job.get("project_key", ""),
                      job.get("sonar_token", ""), attempt)
    k8s.create_job(j)
    store.move_tool(job_id, tool, "pending", "running")
    if store.get_status(job_id) == "queued":
        store.set_status(job_id, "running")
    logger.info("[%s] dispatched %s (attempt %d) as %s", job_id, tool, attempt,
                k8s.job_name(tool, job_id, attempt))


def dispatch_pass() -> None:
    hard, used_reported = k8s.read_quota()

    # Compute usage authoritatively from our own running set rather than trusting
    # the quota controller's eventually-consistent status.used (which lags a
    # freshly-created Job by ~1s). Use the larger of the two to stay safe.
    cpu_running = mem_running = 0.0
    for jid in store.all_job_ids():
        for t in store.tools_running(jid):
            req = config.TOOL_RESOURCES[t]["requests"]
            cpu_running += k8s.cpu_to_millicores(req["cpu"])
            mem_running += k8s.mem_to_bytes(req["memory"])
    cpu_used = max(used_reported["cpu"], cpu_running)
    mem_used = max(used_reported["memory"], mem_running)

    progress = True
    while progress:
        progress = False
        for job_id in store.pending_job_ids():   # oldest -> newest
            if store.get_status(job_id) in TERMINAL:
                continue
            pend = store.tools_pending(job_id)
            # cheapest pending tool (TOOLS is ordered cheapest-first)
            tool = next((t for t in config.TOOLS if t in pend), None)
            if tool is None:
                continue
            req = config.TOOL_RESOURCES[tool]["requests"]
            rc = k8s.cpu_to_millicores(req["cpu"])
            rm = k8s.mem_to_bytes(req["memory"])
            if cpu_used + rc > hard["cpu"] or mem_used + rm > hard["memory"]:
                # this job's next tool isn't capacity-available; let newer jobs try
                continue
            job = store.get_job(job_id)
            if not ensure_cloned(job_id, job):
                continue
            dispatch(job_id, tool, job)
            cpu_used += rc
            mem_used += rm
            progress = True
            break   # re-evaluate from the oldest job after every dispatch


class Command(BaseCommand):
    help = "Run the ci-utils scan dispatcher loop (singleton)."

    def handle(self, *args, **opts):
        k8s.init()
        known = store.all_job_ids()
        logger.info("Dispatcher starting. Recovering %d known job(s): %s",
                    len(known), known or "none")
        while True:
            try:
                events = store.wait_events(config.DISPATCHER_TICK_SECONDS)
                cleanups = [e.split(":", 1)[1] for e in events
                            if e.startswith("cleanup:")]
                # Reconcile + dispatch runs every tick (event-driven, but the
                # blpop timeout also gives us a periodic reconcile so k8s Job
                # failures without an inbound result are still caught).
                reconcile_results()
                reconcile_failures()
                for cid in cleanups:
                    do_cleanup(cid)
                dispatch_pass()
            except Exception as exc:
                logger.exception("dispatcher tick error: %s", exc)
