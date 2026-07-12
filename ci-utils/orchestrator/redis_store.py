"""
Redis-backed job/queue state for ci-utils.

Implements the schema from the v3 architecture doc (s4.1). This module is the
ONLY place that knows Redis key layout. Everything the old in-memory `jobs`
dict held now lives here, so a ci-utils restart loses nothing in-flight.

Key layout:
    queue:pending                 ZSET  score=enqueued_at epoch, member=job_id
    job:{id}                      HASH  status, repo_url, commit_sha,
                                        project_key, sonar_token, ci_context(json),
                                        enqueued_at, cloned
    job:{id}:tools_pending        SET
    job:{id}:tools_running        SET
    job:{id}:tools_done           SET
    job:{id}:tools_failed         SET
    job:{id}:results:{tool}       STRING (json: {tool_meta, data})
    job:{id}:{tool}:attempts      STRING (int)
    dispatcher:events             LIST  ("wake" | "cleanup:{id}")
"""
import json
import time
from typing import Any, Dict, List, Optional

import redis

from . import config

_client: Optional[redis.Redis] = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
    return _client


# ---- keys --------------------------------------------------------------------
def _job(job_id: str) -> str: return f"job:{job_id}"
def _pending(job_id: str) -> str: return f"job:{job_id}:tools_pending"
def _running(job_id: str) -> str: return f"job:{job_id}:tools_running"
def _done(job_id: str) -> str: return f"job:{job_id}:tools_done"
def _failed(job_id: str) -> str: return f"job:{job_id}:tools_failed"
def _result(job_id: str, tool: str) -> str: return f"job:{job_id}:results:{tool}"
def _attempts(job_id: str, tool: str) -> str: return f"job:{job_id}:{tool}:attempts"

QUEUE = "queue:pending"
EVENTS = "dispatcher:events"


# ---- job lifecycle -----------------------------------------------------------
def create_job(job_id: str, req: Dict[str, Any]) -> None:
    r = client()
    now = time.time()
    pipe = r.pipeline()
    pipe.hset(_job(job_id), mapping={
        "status": "queued",
        "repo_url": req["repo_url"],
        "commit_sha": req.get("commit_sha", "HEAD"),
        "project_key": req["project_key"],
        "sonar_token": req.get("sonar_token", ""),
        "ci_context": json.dumps(req.get("ci_context", {})),
        "enqueued_at": now,
        "cloned": "0",
    })
    pipe.sadd(_pending(job_id), *config.TOOLS)
    pipe.zadd(QUEUE, {job_id: now})
    pipe.execute()


def job_exists(job_id: str) -> bool:
    return bool(client().exists(_job(job_id)))


def get_job(job_id: str) -> Dict[str, Any]:
    data = client().hgetall(_job(job_id))
    if "ci_context" in data:
        try:
            data["ci_context"] = json.loads(data["ci_context"])
        except Exception:
            data["ci_context"] = {}
    return data


def set_status(job_id: str, status: str) -> None:
    client().hset(_job(job_id), "status", status)


def get_status(job_id: str) -> Optional[str]:
    return client().hget(_job(job_id), "status")


def enqueued_at(job_id: str) -> float:
    v = client().hget(_job(job_id), "enqueued_at")
    return float(v) if v else time.time()


def mark_cloned(job_id: str) -> None:
    client().hset(_job(job_id), "cloned", "1")


def is_cloned(job_id: str) -> bool:
    return client().hget(_job(job_id), "cloned") == "1"


# ---- queue -------------------------------------------------------------------
def pending_job_ids() -> List[str]:
    """Job ids ordered oldest -> newest (lowest score first)."""
    return client().zrange(QUEUE, 0, -1)


def remove_from_queue(job_id: str) -> None:
    client().zrem(QUEUE, job_id)


def requeue(job_id: str) -> None:
    """Re-add to the queue preserving original age (for retries)."""
    client().zadd(QUEUE, {job_id: enqueued_at(job_id)})


# ---- tool sets ---------------------------------------------------------------
def tools_pending(job_id: str) -> set: return set(client().smembers(_pending(job_id)))
def tools_running(job_id: str) -> set: return set(client().smembers(_running(job_id)))
def tools_done(job_id: str) -> set: return set(client().smembers(_done(job_id)))
def tools_failed(job_id: str) -> set: return set(client().smembers(_failed(job_id)))


def move_tool(job_id: str, tool: str, src: str, dst: str) -> None:
    keymap = {"pending": _pending, "running": _running, "done": _done, "failed": _failed}
    client().smove(keymap[src](job_id), keymap[dst](job_id), tool)


# ---- results -----------------------------------------------------------------
def set_result(job_id: str, tool: str, payload: Dict[str, Any]) -> None:
    client().set(_result(job_id, tool), json.dumps(payload))


def get_result(job_id: str, tool: str) -> Optional[Dict[str, Any]]:
    raw = client().get(_result(job_id, tool))
    return json.loads(raw) if raw else None


def has_result(job_id: str, tool: str) -> bool:
    return bool(client().exists(_result(job_id, tool)))


# ---- attempts ----------------------------------------------------------------
def attempts_incr(job_id: str, tool: str) -> int:
    return int(client().incr(_attempts(job_id, tool)))


def attempts_get(job_id: str, tool: str) -> int:
    v = client().get(_attempts(job_id, tool))
    return int(v) if v else 0


# ---- events ------------------------------------------------------------------
def push_event(msg: str = "wake") -> None:
    client().rpush(EVENTS, msg)


def request_cleanup(job_id: str) -> None:
    client().rpush(EVENTS, f"cleanup:{job_id}")


def wait_events(timeout: float) -> List[str]:
    """Block up to `timeout`s for one event, then drain any others queued."""
    r = client()
    events: List[str] = []
    first = r.blpop(EVENTS, timeout=timeout)
    if first:
        events.append(first[1])
        while True:
            nxt = r.lpop(EVENTS)
            if nxt is None:
                break
            events.append(nxt)
    return events


# ---- cleanup -----------------------------------------------------------------
def delete_job_keys(job_id: str) -> None:
    r = client()
    keys = [
        _job(job_id), _pending(job_id), _running(job_id),
        _done(job_id), _failed(job_id),
    ]
    for tool in config.TOOLS:
        keys.append(_result(job_id, tool))
        keys.append(_attempts(job_id, tool))
    pipe = r.pipeline()
    pipe.zrem(QUEUE, job_id)
    pipe.delete(*keys)
    pipe.execute()


def all_job_ids() -> List[str]:
    """Every job id currently known (for crash-recovery reconciliation)."""
    ids = set(client().zrange(QUEUE, 0, -1))
    for key in client().scan_iter(match="job:*"):
        # only the base hash key "job:{id}" (no extra colon segment)
        parts = key.split(":")
        if len(parts) == 2:
            ids.add(parts[1])
    return list(ids)
