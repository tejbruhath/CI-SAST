"""
Local tool executor — replaces the old k8s-Job dispatch.

Runs each scanner as its official Docker container via the host Docker daemon
(the worker container has /var/run/docker.sock mounted). The tool reads/writes a
bind-mounted work dir; we read its native output file back out and hand it to
the adapter's parser.

DinD volume-path note: `docker run -v SRC:DST` resolves SRC on the HOST daemon.
So the work dir must exist at the SAME absolute path on host and inside the
worker. docker-compose achieves this by bind-mounting ${SENTRIQ_DATA_DIR} to the
identical path in the worker (see docker-compose.yml). `git_clone` and the
executor therefore just use local paths and they transparently match the host.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from typing import List, Optional

from . import config
from .adapters.base import BaseAdapter
from .schema import Finding, STATIC

logger = logging.getLogger("sentriq.executor")


@dataclass
class ToolRun:
    tool: str
    findings: List[Finding]
    ok: bool
    exit_code: int
    duration_s: float
    stderr_tail: str = ""
    error: str = ""


# ---- repo clone (static pipeline) -------------------------------------------
# Never let git block on an interactive credential prompt: a private or missing
# repo would otherwise hang the whole subprocess until the timeout. Fail fast.
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def git_clone(repo_url: str, ref: str, dest: str) -> None:
    """Shallow-clone `repo_url` at `ref` into `dest`.

    If SENTRIQ_GIT_TOKEN is set, it is injected into https URLs so private repos
    can be cloned (also the token used later to push fix PRs)."""
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    url = _authed_url(repo_url)
    if ref in ("HEAD", "", None):
        subprocess.run(["git", "clone", "--depth", "1", url, dest],
                       check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                       capture_output=True, text=True, env=_GIT_ENV)
    else:
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True,
                       capture_output=True, text=True, env=_GIT_ENV)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dest,
                       check=True, capture_output=True, text=True, env=_GIT_ENV)
        subprocess.run(["git", "fetch", "--depth", "1", "origin", ref], cwd=dest,
                       check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                       capture_output=True, text=True, env=_GIT_ENV)
        subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest,
                       check=True, capture_output=True, text=True, env=_GIT_ENV)


def _authed_url(repo_url: str) -> str:
    """Inject SENTRIQ_GIT_TOKEN into an https git URL when present."""
    token = config.GIT_TOKEN
    if token and repo_url.startswith("https://") and "@" not in repo_url[8:]:
        return "https://" + token + "@" + repo_url[len("https://"):]
    return repo_url


# ---- docker run --------------------------------------------------------------
def _docker_argv(adapter: BaseAdapter, target: str, work_dir: str) -> List[str]:
    argv = ["docker", "run", "--rm"]
    if adapter.PIPELINE != STATIC:
        # dynamic scanners hit a network target (possibly on the host/staging).
        argv += ["--network", config.SCANNER_NETWORK]
    argv += ["-v", f"{work_dir}:{adapter.MOUNT}", adapter.IMAGE]
    argv += adapter.command(target, adapter.MOUNT)
    return argv


def run_tool(adapter: BaseAdapter, target: str, work_dir: str,
             timeout: int) -> ToolRun:
    """Run one scanner container and parse its output into Findings.

    `work_dir` is the host/worker-shared dir mounted into the container. For
    static tools it already contains the cloned source; for dynamic tools it is
    an empty scratch dir the tool writes its report into.
    """
    import time
    argv = _docker_argv(adapter, target, work_dir)
    logger.info("[%s] exec: %s", adapter.NAME, " ".join(argv))
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ToolRun(adapter.NAME, [], False, 124, timeout,
                       error="scan timed out")
    except Exception as exc:  # docker missing, image pull fail, etc.
        return ToolRun(adapter.NAME, [], False, -1, time.monotonic() - started,
                       error=str(exc))
    dur = time.monotonic() - started

    out_path = os.path.join(work_dir, adapter.OUTPUT_FILE)
    raw = ""
    if os.path.exists(out_path):
        with open(out_path, "r", errors="replace") as f:
            raw = f.read()

    # Many scanners exit non-zero when they FIND something; a written output
    # file is the real success signal, not the exit code.
    if not raw and proc.returncode != 0:
        return ToolRun(adapter.NAME, [], False, proc.returncode, dur,
                       stderr_tail=(proc.stderr or "")[-500:],
                       error="no output produced")
    try:
        findings = adapter.parse(raw, target)
    except Exception as exc:
        logger.exception("[%s] parse error", adapter.NAME)
        return ToolRun(adapter.NAME, [], False, proc.returncode, dur,
                       error=f"parse error: {exc}")
    return ToolRun(adapter.NAME, findings, True, proc.returncode, dur,
                   stderr_tail=(proc.stderr or "")[-500:])


def apply_fix_and_push(repo_url: str, base_ref: str, branch: str,
                       diff: str, commit_msg: str, work_dir: str) -> None:
    """Clone `repo_url`, branch off `base_ref`, apply the unified `diff`, commit
    and push `branch`. Raises on any failure (caller records pr_status=failed).

    Uses a full (non-shallow) clone of the base branch so the push has history.
    """
    if not diff.strip():
        raise RuntimeError("empty diff — nothing to apply")
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)
    url = _authed_url(repo_url)
    base = base_ref if base_ref not in ("HEAD", "", None) else None

    def git(*args, **kw):
        subprocess.run(["git", *args], cwd=work_dir, check=True,
                       capture_output=True, text=True, env=_GIT_ENV, **kw)

    clone = ["git", "clone", "--depth", "20"]
    if base:
        clone += ["--branch", base]
    clone += [url, work_dir]
    subprocess.run(clone, check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                   capture_output=True, text=True, env=_GIT_ENV)

    git("config", "user.email", "bot@sentriq.local")
    git("config", "user.name", "Sentriq Bot")
    git("checkout", "-b", branch)

    # Apply the patch. DeepSeek emits `a/`+`b/` prefixed unified diffs, so the
    # default -p1 strip is correct. --3way is more forgiving of slight drift.
    patch = os.path.join(work_dir, ".sentriq.patch")
    with open(patch, "w") as f:
        f.write(diff if diff.endswith("\n") else diff + "\n")
    try:
        git("apply", "--3way", ".sentriq.patch")
    except subprocess.CalledProcessError:
        # fall back to a plain apply (some diffs lack the blobs --3way needs)
        git("apply", ".sentriq.patch")
    os.remove(patch)

    git("add", "-A")
    git("commit", "-m", commit_msg)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=work_dir,
                   check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                   capture_output=True, text=True, env=_GIT_ENV)


def make_scratch(scan_id: str) -> str:
    """A per-scan work dir under the shared data root (host-path-matched)."""
    d = os.path.join(config.REPOS_DIR, f"{scan_id}-{uuid.uuid4().hex[:6]}")
    os.makedirs(d, exist_ok=True)
    return d


def cleanup(work_dir: str) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)
