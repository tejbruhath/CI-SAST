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
from __future__ import annotations  # allow modern type hints without runtime eval

import logging  # structured logs for clone/scan/apply failures
import os  # filesystem paths, env, and existence checks
import shutil  # recursive delete of work dirs between runs
import subprocess  # spawn git and docker as child processes
import tempfile  # (imported for callers/tests; work dirs use REPOS_DIR)
import uuid  # unique suffix so concurrent scans never share a folder
from dataclasses import dataclass  # lightweight result object for one tool run
from typing import List, Optional  # type hints for lists and optional tokens

from . import config  # timeouts, tokens, data dirs, scanner network
from .adapters.base import BaseAdapter  # scanner plugin contract (image/cmd/parse)
from .schema import Finding, STATIC  # normalized finding type + pipeline kind

logger = logging.getLogger("sentriq.executor")  # module logger under sentriq tree


@dataclass
class ToolRun:
    tool: str  # adapter name that produced this result
    findings: List[Finding]  # parsed issues (empty on hard failure)
    ok: bool  # True when output parsed cleanly enough to trust
    exit_code: int  # container/process exit code (124 = our timeout)
    duration_s: float  # wall-clock seconds spent running the tool
    stderr_tail: str = ""  # last stderr bytes for debugging failed scans
    error: str = ""  # human-readable failure reason when ok is False


# ---- repo clone (static pipeline) -------------------------------------------
# Never let git block on an interactive credential prompt: a private or missing
# repo would otherwise hang the whole subprocess until the timeout. Fail fast.
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}  # non-interactive git


def git_clone(repo_url: str, ref: str, dest: str) -> None:
    """Shallow-clone `repo_url` at `ref` into `dest`.

    If SENTRIQ_GIT_TOKEN is set, it is injected into https URLs so private repos
    can be cloned (also the token used later to push fix PRs)."""
    if os.path.exists(dest):  # wipe stale tree so clone is always clean
        shutil.rmtree(dest, ignore_errors=True)  # ignore errors if already gone
    os.makedirs(dest, exist_ok=True)  # ensure parent path exists before git
    url = _authed_url(repo_url)  # inject PAT into https when configured
    if ref in ("HEAD", "", None):  # default branch / no specific commit
        subprocess.run(["git", "clone", "--depth", "1", url, dest],  # shallow tip only
                       check=True, timeout=config.CLONE_TIMEOUT_SECONDS,  # fail on error/timeout
                       capture_output=True, text=True, env=_GIT_ENV)  # no prompt; capture logs
    else:  # pin to a branch, tag, or SHA via fetch+checkout
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True,  # empty repo at dest
                       capture_output=True, text=True, env=_GIT_ENV)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dest,  # point at remote
                       check=True, capture_output=True, text=True, env=_GIT_ENV)
        subprocess.run(["git", "fetch", "--depth", "1", "origin", ref], cwd=dest,  # one commit
                       check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                       capture_output=True, text=True, env=_GIT_ENV)
        subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest,  # materialize tree
                       check=True, capture_output=True, text=True, env=_GIT_ENV)


def _authed_url(repo_url: str, token: Optional[str] = None) -> str:
    """Inject a token into an https git URL when present.

    Prefers the caller's token (the acting user's OAuth token) and falls back to
    the shared SENTRIQ_GIT_TOKEN, so a push is attributed to the person who
    approved the fix rather than to whoever owns the PAT.
    """
    token = token or config.GIT_TOKEN  # user token wins; else shared PAT
    if token and repo_url.startswith("https://") and "@" not in repo_url[8:]:  # avoid double auth
        return "https://" + token + "@" + repo_url[len("https://"):]  # embed token in netloc
    return repo_url  # ssh or already-authed URLs pass through unchanged


# ---- docker run --------------------------------------------------------------
def _docker_argv(adapter: BaseAdapter, target: str, work_dir: str) -> List[str]:
    argv = ["docker", "run", "--rm"]  # remove container after exit
    if adapter.PIPELINE != STATIC:  # dynamic tools need reachability to target URL
        # dynamic scanners hit a network target (possibly on the host/staging).
        argv += ["--network", config.SCANNER_NETWORK]  # join compose/host network
    argv += ["-v", f"{work_dir}:{adapter.MOUNT}", adapter.IMAGE]  # bind work dir into image
    argv += adapter.command(target, adapter.MOUNT)  # tool-specific CLI after image
    return argv  # full argv list ready for subprocess.run


def run_tool(adapter: BaseAdapter, target: str, work_dir: str,
             timeout: int) -> ToolRun:
    """Run one scanner container and parse its output into Findings.

    `work_dir` is the host/worker-shared dir mounted into the container. For
    static tools it already contains the cloned source; for dynamic tools it is
    an empty scratch dir the tool writes its report into.
    """
    import time  # local import keeps module load light
    argv = _docker_argv(adapter, target, work_dir)  # build docker CLI args
    logger.info("[%s] exec: %s", adapter.NAME, " ".join(argv))  # audit command line
    started = time.monotonic()  # start timer (monotonic avoids clock skew)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)  # run scanner
    except subprocess.TimeoutExpired:  # tool exceeded allowed wall time
        return ToolRun(adapter.NAME, [], False, 124, timeout,  # 124 mirrors timeout(1)
                       error="scan timed out")
    except Exception as exc:  # docker missing, image pull fail, etc.
        return ToolRun(adapter.NAME, [], False, -1, time.monotonic() - started,  # unknown crash
                       error=str(exc))
    dur = time.monotonic() - started  # successful process completion duration

    out_path = os.path.join(work_dir, adapter.OUTPUT_FILE)  # expected report path
    raw = ""  # default when tool wrote nothing
    if os.path.exists(out_path):  # prefer file over stdout for parsers
        with open(out_path, "r", errors="replace") as f:  # replace bad bytes
            raw = f.read()  # full report text for adapter.parse

    # Many scanners exit non-zero when they FIND something; a written output
    # file is the real success signal, not the exit code.
    if not raw and proc.returncode != 0:  # hard fail: no report and bad exit
        return ToolRun(adapter.NAME, [], False, proc.returncode, dur,
                       stderr_tail=(proc.stderr or "")[-500:],  # keep last stderr
                       error="no output produced")
    try:
        findings = adapter.parse(raw, target)  # normalize vendor JSON into Findings
    except Exception as exc:  # malformed report must not crash the scan job
        logger.exception("[%s] parse error", adapter.NAME)
        return ToolRun(adapter.NAME, [], False, proc.returncode, dur,
                       error=f"parse error: {exc}")
    return ToolRun(adapter.NAME, findings, True, proc.returncode, dur,  # success path
                   stderr_tail=(proc.stderr or "")[-500:])


def apply_fix_and_push(repo_url: str, base_ref: str, branch: str,
                       diff, commit_msg: str, work_dir: str,
                       token: Optional[str] = None) -> List[str]:
    """Clone `repo_url`, branch off `base_ref`, apply the fix(es), commit and
    push `branch`. Raises on any failure (caller records pr_status=failed).

    `diff` is either one unified diff (string) or an ordered list of
    (label, diff) pairs — the batch case, where every approved fix lands on ONE
    branch as one commit each, so the user gets a single reviewable PR.

    Returns the labels that applied. In batch mode a patch that will not apply
    is SKIPPED rather than failing the whole PR: one stale diff must not block
    every other approved fix. Single-diff mode keeps raising, since there the
    failure is the whole job.

    Uses a shallow-but-real clone of the base branch so the push has history.
    """
    single = isinstance(diff, str)  # True = one patch; False = batch of labeled patches
    patches = [("fix", diff)] if single else list(diff)  # normalize to (label, text) pairs
    if not patches or all(not d.strip() for _, d in patches):  # nothing useful to apply
        raise RuntimeError("empty diff — nothing to apply")
    if os.path.exists(work_dir):  # clean previous PR attempt at same path
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)  # empty dir for clone target
    url = _authed_url(repo_url, token)  # auth for private clone and push
    base = base_ref if base_ref not in ("HEAD", "", None) else None  # None => remote default

    def git(*args, **kw):  # tiny helper: always run git in work_dir with checks
        subprocess.run(["git", *args], cwd=work_dir, check=True,
                       capture_output=True, text=True, env=_GIT_ENV, **kw)

    clone = ["git", "clone", "--depth", "20"]  # shallow history enough for 3way apply
    if base:  # pin clone to requested base branch when known
        clone += ["--branch", base]
    clone += [url, work_dir]  # destination is our scratch work_dir
    subprocess.run(clone, check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                   capture_output=True, text=True, env=_GIT_ENV)

    git("config", "user.email", "bot@sentriq.local")  # required identity for commit
    git("config", "user.name", "Sentriq Bot")  # shown as commit author
    git("checkout", "-b", branch)  # new branch for the fix PR

    applied = []  # labels of patches that committed successfully
    for label, one in patches:  # apply each approved fix independently
        if not one.strip():  # skip empty patch strings
            continue
        # DeepSeek diffs are `a/`+`b/` prefixed, so the default -p1 strip is
        # right. --3way is more forgiving of drift; plain apply is the fallback
        # for diffs lacking the blobs --3way needs.
        patch = os.path.join(work_dir, ".sentriq.patch")  # temp file for git apply
        with open(patch, "w") as f:
            f.write(one if one.endswith("\n") else one + "\n")  # git wants trailing newline
        try:
            try:
                git("apply", "--3way", ".sentriq.patch")  # prefer merge-friendly apply
            except subprocess.CalledProcessError:  # fall back without 3way
                git("apply", ".sentriq.patch")
        except subprocess.CalledProcessError:  # both apply modes failed
            os.remove(patch)  # clean temp patch file
            if single:  # single mode: one failure fails the job
                raise
            logger.warning("[pr] skipping patch that does not apply: %s", label)
            git("checkout", "--", ".")  # drop any partial --3way conflict state
            continue  # try remaining patches in the batch
        os.remove(patch)  # applied cleanly; remove temp file
        git("add", "-A")  # stage all changes from this patch
        git("commit", "-m", commit_msg if single else f"{commit_msg}: {label}")  # one commit each
        applied.append(label)  # record success for return value

    if not applied:  # batch where every patch failed
        raise RuntimeError("no approved fix applied cleanly to the base branch")

    subprocess.run(["git", "push", "-u", "origin", branch], cwd=work_dir,  # publish branch
                   check=True, timeout=config.CLONE_TIMEOUT_SECONDS,
                   capture_output=True, text=True, env=_GIT_ENV)
    return applied  # labels the caller can report as landed


def make_scratch(scan_id: str) -> str:
    """A per-scan work dir under the shared data root (host-path-matched)."""
    d = os.path.join(config.REPOS_DIR, f"{scan_id}-{uuid.uuid4().hex[:6]}")  # unique path
    os.makedirs(d, exist_ok=True)  # create empty scratch tree
    return d  # absolute path shared with host docker


def cleanup(work_dir: str) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)  # best-effort delete; never raise
