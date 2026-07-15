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
import json  # Serialize ci_context and tool result payloads as JSON strings.
import time  # Epoch timestamps for enqueue order and defaults.
from typing import Any, Dict, List, Optional  # Type hints for clearer function contracts.

import redis  # Official Redis client used for all key operations.

from . import config  # REDIS_URL and TOOLS list live in shared config.

_client: Optional[redis.Redis] = None  # Module-level singleton; created on first use.


def client() -> redis.Redis:  # Lazy-connect so import works without Redis up.
    global _client  # Mutate the module singleton, not a local name.
    if _client is None:  # First caller creates the shared connection pool client.
        _client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)  # Strings not bytes.
    return _client  # Reuse the same client for all subsequent calls.


# ---- keys --------------------------------------------------------------------
def _job(job_id: str) -> str: return f"job:{job_id}"  # Base HASH for job metadata.
def _pending(job_id: str) -> str: return f"job:{job_id}:tools_pending"  # SET of tools not started.
def _running(job_id: str) -> str: return f"job:{job_id}:tools_running"  # SET of tools in-flight.
def _done(job_id: str) -> str: return f"job:{job_id}:tools_done"  # SET of tools with results.
def _failed(job_id: str) -> str: return f"job:{job_id}:tools_failed"  # SET of tools that gave up.
def _result(job_id: str, tool: str) -> str: return f"job:{job_id}:results:{tool}"  # Result JSON string.
def _attempts(job_id: str, tool: str) -> str: return f"job:{job_id}:{tool}:attempts"  # Retry counter.

QUEUE = "queue:pending"  # ZSET of job_ids ordered by enqueue time.
EVENTS = "dispatcher:events"  # LIST the dispatcher blocks on for wake/cleanup.


# ---- job lifecycle -----------------------------------------------------------
def create_job(job_id: str, req: Dict[str, Any]) -> None:  # Atomically insert a new scan job.
    r = client()  # Shared Redis connection.
    now = time.time()  # Score for queue ordering and enqueued_at field.
    pipe = r.pipeline()  # Batch writes so partial creates cannot linger.
    pipe.hset(_job(job_id), mapping={  # Store all job fields on one HASH.
        "status": "queued",  # Initial lifecycle state before dispatch.
        "repo_url": req["repo_url"],  # Git remote to clone.
        "commit_sha": req.get("commit_sha", "HEAD"),  # Pin to commit or default tip.
        "project_key": req["project_key"],  # Sonar project identifier.
        "sonar_token": req.get("sonar_token", ""),  # Optional Sonar credentials.
        "ci_context": json.dumps(req.get("ci_context", {})),  # Nested dict stored as JSON text.
        "enqueued_at": now,  # Preserve age for fair requeue.
        "cloned": "0",  # Flag: repo not on disk yet (Redis stores strings).
    })
    pipe.sadd(_pending(job_id), *config.TOOLS)  # All tools start pending in dispatch order.
    pipe.zadd(QUEUE, {job_id: now})  # Append to pending queue by enqueue timestamp.
    pipe.execute()  # Send the pipeline as one round-trip.


def job_exists(job_id: str) -> bool:  # True if the job HASH key is still present.
    return bool(client().exists(_job(job_id)))  # exists returns 0/1; bool for Python callers.


def get_job(job_id: str) -> Dict[str, Any]:  # Load full job HASH with ci_context decoded.
    data = client().hgetall(_job(job_id))  # All fields as a flat string dict.
    if "ci_context" in data:  # Decode JSON field back to a Python dict.
        try:
            data["ci_context"] = json.loads(data["ci_context"])  # Parse stored JSON string.
        except Exception:
            data["ci_context"] = {}  # Corrupt JSON falls back to empty context.
    return data  # Caller gets strings plus nested ci_context.


def set_status(job_id: str, status: str) -> None:  # Update lifecycle status field only.
    client().hset(_job(job_id), "status", status)  # e.g. queued → running → complete.


def get_status(job_id: str) -> Optional[str]:  # Read current status or None if missing.
    return client().hget(_job(job_id), "status")  # HASH field get; None if key/field absent.


def enqueued_at(job_id: str) -> float:  # Original enqueue time for fair requeue scoring.
    v = client().hget(_job(job_id), "enqueued_at")  # Stored as stringified float.
    return float(v) if v else time.time()  # Fallback to now if field missing.


def mark_cloned(job_id: str) -> None:  # Remember that the workspace clone succeeded.
    client().hset(_job(job_id), "cloned", "1")  # "1" means true in string-only Redis.


def is_cloned(job_id: str) -> bool:  # Skip re-cloning when the flag is already set.
    return client().hget(_job(job_id), "cloned") == "1"  # Compare against string true.


# ---- queue -------------------------------------------------------------------
def pending_job_ids() -> List[str]:
    """Job ids ordered oldest -> newest (lowest score first)."""
    return client().zrange(QUEUE, 0, -1)  # Full ZSET range, ascending by score.


def remove_from_queue(job_id: str) -> None:  # Drop job from the dispatch ZSET.
    client().zrem(QUEUE, job_id)  # No-op if already removed.


def requeue(job_id: str) -> None:
    """Re-add to the queue preserving original age (for retries)."""
    client().zadd(QUEUE, {job_id: enqueued_at(job_id)})  # Keep original score for fairness.


# ---- tool sets ---------------------------------------------------------------
def tools_pending(job_id: str) -> set: return set(client().smembers(_pending(job_id)))  # Pending tools.
def tools_running(job_id: str) -> set: return set(client().smembers(_running(job_id)))  # Running tools.
def tools_done(job_id: str) -> set: return set(client().smembers(_done(job_id)))  # Successful tools.
def tools_failed(job_id: str) -> set: return set(client().smembers(_failed(job_id)))  # Failed tools.


def move_tool(job_id: str, tool: str, src: str, dst: str) -> None:  # Atomic SET→SET transition.
    keymap = {"pending": _pending, "running": _running, "done": _done, "failed": _failed}  # Name→key fn.
    client().smove(keymap[src](job_id), keymap[dst](job_id), tool)  # Redis SMOVE is atomic.


# ---- results -----------------------------------------------------------------
def set_result(job_id: str, tool: str, payload: Dict[str, Any]) -> None:  # Persist tool output JSON.
    client().set(_result(job_id, tool), json.dumps(payload))  # Overwrite any previous result.


def get_result(job_id: str, tool: str) -> Optional[Dict[str, Any]]:  # Load and parse tool result.
    raw = client().get(_result(job_id, tool))  # STRING key or None.
    return json.loads(raw) if raw else None  # Decode JSON when present.


def has_result(job_id: str, tool: str) -> bool:  # True if a result key exists.
    return bool(client().exists(_result(job_id, tool)))  # Used by reconciler before moving tools.


# ---- attempts ----------------------------------------------------------------
def attempts_incr(job_id: str, tool: str) -> int:  # Bump retry counter; returns new value.
    return int(client().incr(_attempts(job_id, tool)))  # INCR creates key starting at 1.


def attempts_get(job_id: str, tool: str) -> int:  # Read attempt count without mutating.
    v = client().get(_attempts(job_id, tool))  # May be None before first dispatch.
    return int(v) if v else 0  # Zero means never launched.


# ---- events ------------------------------------------------------------------
def push_event(msg: str = "wake") -> None:  # Nudge the dispatcher event loop.
    client().rpush(EVENTS, msg)  # Append to the right of the LIST.


def request_cleanup(job_id: str) -> None:  # Ask dispatcher to free repo + Redis keys.
    client().rpush(EVENTS, f"cleanup:{job_id}")  # Typed event with job id payload.


def wait_events(timeout: float) -> List[str]:
    """Block up to `timeout`s for one event, then drain any others queued."""
    r = client()  # Local alias for clarity in the drain loop.
    events: List[str] = []  # Collected messages for this tick.
    first = r.blpop(EVENTS, timeout=timeout)  # Block until event or timeout.
    if first:  # first is (list_name, value) or None on timeout.
        events.append(first[1])  # Keep the message body only.
        while True:  # Non-blocking drain of any backlog.
            nxt = r.lpop(EVENTS)  # Pop left; None means empty.
            if nxt is None:
                break  # List drained; stop collecting.
            events.append(nxt)  # Queue additional wake/cleanup messages.
    return events  # Empty list if the timeout fired with no events.


# ---- cleanup -----------------------------------------------------------------
def delete_job_keys(job_id: str) -> None:  # Remove all Redis keys for one job.
    r = client()  # Shared Redis connection for all key ops below.
    keys = [  # Fixed keys that always exist for a job.
        _job(job_id), _pending(job_id), _running(job_id),
        _done(job_id), _failed(job_id),
    ]
    for tool in config.TOOLS:  # Per-tool result and attempt keys.
        keys.append(_result(job_id, tool))
        keys.append(_attempts(job_id, tool))
    pipe = r.pipeline()  # Atomic-ish multi-key delete + queue remove.
    pipe.zrem(QUEUE, job_id)  # Ensure job is not left in the pending ZSET.
    pipe.delete(*keys)  # Drop HASH, SETs, and STRING keys together.
    pipe.execute()  # Commit the cleanup pipeline.


def all_job_ids() -> List[str]:
    """Every job id currently known (for crash-recovery reconciliation)."""
    ids = set(client().zrange(QUEUE, 0, -1))  # Start with jobs still in the queue.
    for key in client().scan_iter(match="job:*"):  # Cursor scan avoids blocking KEYS.
        # only the base hash key "job:{id}" (no extra colon segment)
        parts = key.split(":")  # Split Redis key into segments.
        if len(parts) == 2:  # Exactly job:{id} means base HASH, not tools/results.
            ids.add(parts[1])  # Collect the job id portion.
    return list(ids)  # Deduplicated list of known jobs for reconcilers.
