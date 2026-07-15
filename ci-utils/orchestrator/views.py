"""
DRF HTTP API for ci-utils.

This layer is deliberately thin: it validates input and reads/writes Redis.
It NEVER touches k8s or the repo filesystem -- all cluster/state mutation is
owned by the single dispatcher process (see management/commands/run_dispatcher).
That keeps the API safely runnable as multiple gunicorn workers.
"""
import json  # Load mega-artifact.json from disk into Python dicts.
import logging  # Structured request/job logs for operators.
import os  # Path joins and existence checks for artifact files.
import uuid  # Generate short unique job ids for new scans.

from rest_framework import status  # HTTP status codes for Response objects.
from rest_framework.decorators import api_view  # Mark functions as DRF view handlers.
from rest_framework.response import Response  # JSON response wrapper for DRF.

from . import config, redis_store as store  # Shared config constants and Redis helpers.
from .serializers import JobRequestSerializer  # Validates create-job request bodies.

logger = logging.getLogger("orchestrator.api")  # Named logger for API-layer messages.


@api_view(["GET"])  # Health is a simple GET with no body.
def health(request):  # Probe used by k8s/load balancers and ops checks.
    try:
        store.client().ping()  # Round-trip Redis to prove the broker is up.
        redis_ok = True  # Ping succeeded; Redis is reachable.
    except Exception:
        redis_ok = False  # Any error means Redis is down or misconfigured.
    return Response({"status": "healthy" if redis_ok else "degraded",  # Degraded if Redis fails.
                     "service": "ci-utils", "redis": redis_ok})  # Identify service + Redis flag.


@api_view(["POST"])  # Create job only accepts POST with a JSON body.
def create_job(request):  # Enqueue a scan; dispatcher will clone and launch tools.
    ser = JobRequestSerializer(data=request.data)  # Bind raw JSON to the serializer.
    ser.is_valid(raise_exception=True)  # 400 automatically if fields are invalid.
    req = ser.validated_data  # Cleaned dict after validation.

    job_id = str(uuid.uuid4())[:8]  # Short id keeps k8s Job names within limits.
    store.create_job(job_id, req)  # Persist job hash, tool sets, and queue entry.
    store.push_event("wake")  # nudge the dispatcher to schedule immediately
    logger.info("[%s] queued repo=%s commit=%s", job_id,  # Audit who/what was queued.
                req["repo_url"], req.get("commit_sha"))
    return Response({"job_id": job_id}, status=status.HTTP_202_ACCEPTED)  # Accepted for async work.


@api_view(["POST"])  # Scanners POST their findings here after finishing.
def save_results(request, job_id, tool):  # Store one tool's result JSON for a job.
    if tool not in config.TOOLS:  # Reject unknown tool names early.
        return Response({"detail": "unknown tool"}, status=status.HTTP_404_NOT_FOUND)
    if not store.job_exists(job_id):  # Job must already have been created.
        return Response({"detail": "unknown job"}, status=status.HTTP_404_NOT_FOUND)

    # Accept either the v3 envelope {tool_meta, data} or a bare payload.
    body = request.data  # Parsed JSON body from the scanner container.
    if isinstance(body, dict) and "data" in body:  # Prefer envelope with tool_meta.
        payload = {"tool_meta": body.get("tool_meta", {}), "data": body["data"]}
    else:
        payload = {"tool_meta": {}, "data": body}  # Wrap bare payloads for uniform storage.

    store.set_result(job_id, tool, payload)  # Serialize result into Redis string key.
    store.push_event("wake")  # dispatcher does the done-transition + Job delete
    logger.info("[%s] received results for %s", job_id, tool)  # Trace inbound tool completion.
    return Response({"status": "saved"})  # Ack so the scanner can exit cleanly.


@api_view(["GET"])  # Status polling is read-only.
def job_status(request, job_id):  # Return overall status plus per-tool set membership.
    if not store.job_exists(job_id):  # 404 if job id is unknown or cleaned up.
        return Response({"detail": "unknown job"}, status=status.HTTP_404_NOT_FOUND)
    return Response({
        "status": store.get_status(job_id),  # queued | running | complete | partial | failed.
        "tools_pending": sorted(store.tools_pending(job_id)),  # Not yet dispatched.
        "tools_running": sorted(store.tools_running(job_id)),  # Jobs currently in cluster.
        "tools_done": sorted(store.tools_done(job_id)),  # Finished with a stored result.
        "tools_failed": sorted(store.tools_failed(job_id)),  # Exhausted retries without success.
    })


@api_view(["GET"])  # List endpoint for the SPA artifact browser.
def list_artifacts(request):
    """Autoindex-shaped listing of archived artifacts, for the frontend.
    Mirrors nginx `autoindex_format json` so the SPA data layer is unchanged."""
    base = config.ARTIFACTS_DIR  # Root directory holding per-job artifact folders.
    out = []  # Accumulator for autoindex-shaped directory entries.
    if os.path.isdir(base):  # Skip listing if artifacts volume is missing.
        for name in sorted(os.listdir(base)):  # Stable sort for predictable UI order.
            if os.path.exists(os.path.join(base, name, "mega-artifact.json")):  # Only complete archives.
                out.append({"name": name, "type": "directory"})  # Match nginx autoindex JSON shape.
    return Response(out)  # SPA expects a list of {name, type} objects.


@api_view(["GET"])  # Frontend read path without side effects.
def raw_artifact(request, job_id):
    """Serve an archived mega-artifact.json without side effects (frontend read).
    Unlike GET /job/{id}/artifacts this does NOT trigger cleanup."""
    path = os.path.join(config.ARTIFACTS_DIR, job_id, "mega-artifact.json")  # Expected artifact path.
    if not os.path.exists(path):  # Missing file means not ready or already gone.
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    with open(path) as f:  # Read JSON from disk on demand.
        return Response(json.load(f))  # Return parsed mega-artifact as HTTP JSON.


@api_view(["GET"])  # CI pipeline path: fetch then free resources.
def get_artifacts(request, job_id):  # Return artifact and schedule workspace cleanup.
    if not store.job_exists(job_id):  # Job must still exist in Redis.
        return Response({"detail": "unknown job"}, status=status.HTTP_404_NOT_FOUND)

    st = store.get_status(job_id)  # Only terminal success-ish states expose artifacts.
    if st not in ("complete", "partial"):  # Still running or hard-failed.
        return Response({"detail": f"job not ready (status={st})"},
                        status=status.HTTP_425_TOO_EARLY)  # 425 signals "try again later".

    path = os.path.join(config.ARTIFACTS_DIR, job_id, "mega-artifact.json")  # On-disk artifact location.
    if not os.path.exists(path):  # Status said ready but file missing is an error.
        return Response({"detail": "artifact missing"},
                        status=status.HTTP_404_NOT_FOUND)
    with open(path) as f:
        artifact = json.load(f)  # Load full mega-artifact into memory once.

    # Repo cleanup happens after the artifact is fetched (arch doc s7.1).
    # Dispatcher owns FS/k8s mutation, so request it via an event.
    store.request_cleanup(job_id)  # Ask dispatcher to delete repo + Redis keys.
    return Response(artifact)  # Deliver findings report to the CI client.
