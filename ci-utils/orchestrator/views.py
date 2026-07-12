"""
DRF HTTP API for ci-utils.

This layer is deliberately thin: it validates input and reads/writes Redis.
It NEVER touches k8s or the repo filesystem -- all cluster/state mutation is
owned by the single dispatcher process (see management/commands/run_dispatcher).
That keeps the API safely runnable as multiple gunicorn workers.
"""
import json
import logging
import os
import uuid

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import config, redis_store as store
from .serializers import JobRequestSerializer

logger = logging.getLogger("orchestrator.api")


@api_view(["GET"])
def health(request):
    try:
        store.client().ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return Response({"status": "healthy" if redis_ok else "degraded",
                     "service": "ci-utils", "redis": redis_ok})


@api_view(["POST"])
def create_job(request):
    ser = JobRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    req = ser.validated_data

    job_id = str(uuid.uuid4())[:8]
    store.create_job(job_id, req)
    store.push_event("wake")  # nudge the dispatcher to schedule immediately
    logger.info("[%s] queued repo=%s commit=%s", job_id,
                req["repo_url"], req.get("commit_sha"))
    return Response({"job_id": job_id}, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
def save_results(request, job_id, tool):
    if tool not in config.TOOLS:
        return Response({"detail": "unknown tool"}, status=status.HTTP_404_NOT_FOUND)
    if not store.job_exists(job_id):
        return Response({"detail": "unknown job"}, status=status.HTTP_404_NOT_FOUND)

    # Accept either the v3 envelope {tool_meta, data} or a bare payload.
    body = request.data
    if isinstance(body, dict) and "data" in body:
        payload = {"tool_meta": body.get("tool_meta", {}), "data": body["data"]}
    else:
        payload = {"tool_meta": {}, "data": body}

    store.set_result(job_id, tool, payload)
    store.push_event("wake")  # dispatcher does the done-transition + Job delete
    logger.info("[%s] received results for %s", job_id, tool)
    return Response({"status": "saved"})


@api_view(["GET"])
def job_status(request, job_id):
    if not store.job_exists(job_id):
        return Response({"detail": "unknown job"}, status=status.HTTP_404_NOT_FOUND)
    return Response({
        "status": store.get_status(job_id),
        "tools_pending": sorted(store.tools_pending(job_id)),
        "tools_running": sorted(store.tools_running(job_id)),
        "tools_done": sorted(store.tools_done(job_id)),
        "tools_failed": sorted(store.tools_failed(job_id)),
    })


@api_view(["GET"])
def list_artifacts(request):
    """Autoindex-shaped listing of archived artifacts, for the frontend.
    Mirrors nginx `autoindex_format json` so the SPA data layer is unchanged."""
    base = config.ARTIFACTS_DIR
    out = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if os.path.exists(os.path.join(base, name, "mega-artifact.json")):
                out.append({"name": name, "type": "directory"})
    return Response(out)


@api_view(["GET"])
def raw_artifact(request, job_id):
    """Serve an archived mega-artifact.json without side effects (frontend read).
    Unlike GET /job/{id}/artifacts this does NOT trigger cleanup."""
    path = os.path.join(config.ARTIFACTS_DIR, job_id, "mega-artifact.json")
    if not os.path.exists(path):
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    with open(path) as f:
        return Response(json.load(f))


@api_view(["GET"])
def get_artifacts(request, job_id):
    if not store.job_exists(job_id):
        return Response({"detail": "unknown job"}, status=status.HTTP_404_NOT_FOUND)

    st = store.get_status(job_id)
    if st not in ("complete", "partial"):
        return Response({"detail": f"job not ready (status={st})"},
                        status=status.HTTP_425_TOO_EARLY)

    path = os.path.join(config.ARTIFACTS_DIR, job_id, "mega-artifact.json")
    if not os.path.exists(path):
        return Response({"detail": "artifact missing"},
                        status=status.HTTP_404_NOT_FOUND)
    with open(path) as f:
        artifact = json.load(f)

    # Repo cleanup happens after the artifact is fetched (arch doc s7.1).
    # Dispatcher owns FS/k8s mutation, so request it via an event.
    store.request_cleanup(job_id)
    return Response(artifact)
