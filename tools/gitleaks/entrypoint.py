#!/usr/bin/env python3
"""
Gitleaks one-shot scanner Job.

The repo already lives on the shared PV at $REPO_PATH (cloned by ci-utils'
dispatcher). This container does not clone anything. It runs gitleaks against
that path, then POSTs results back to ci-utils and exits.

Result contract (v3):
    POST /results/{job_id}/gitleaks
    { "tool_meta": {...}, "data": [ <gitleaks finding>, ... ] }

Exit codes:
    0  scan ran and results were POSTed (findings may be empty)
    1  hard failure (missing env, scan crashed, POST failed) -> dispatcher retries
"""
import json  # parse gitleaks JSON report from disk
import os  # read Job env vars and check paths
import subprocess  # run gitleaks CLI
import sys  # stderr messages and process exit code

import requests  # POST results back to ci-utils

GITLEAKS_VERSION = os.getenv("GITLEAKS_VERSION", "8.18.0")  # fallback version label


def gitleaks_version() -> str:
    """Probe binary version for tool_meta; fall back to env default."""
    try:
        out = subprocess.run(
            ["gitleaks", "version"], capture_output=True, text=True, timeout=15  # quick probe
        )
        v = (out.stdout or out.stderr or "").strip()  # version may print to either stream
        return v or GITLEAKS_VERSION  # empty output → use default
    except Exception:
        return GITLEAKS_VERSION  # binary missing or timed out


def main() -> int:
    """Run gitleaks once and POST findings; return process exit code."""
    job_id = os.getenv("JOB_ID")  # orchestrator job identifier
    repo_path = os.getenv("REPO_PATH")  # pre-cloned repo on shared PV
    ci_utils_url = os.getenv("CI_UTILS_URL")  # where to POST results

    if not job_id or not repo_path or not ci_utils_url:
        print("Missing required env: JOB_ID, REPO_PATH, CI_UTILS_URL", file=sys.stderr)
        return 1  # hard fail so Job is retried / marked failed

    if not os.path.isdir(repo_path):
        print(f"REPO_PATH does not exist: {repo_path}", file=sys.stderr)
        return 1  # clone step did not produce a directory

    report_path = f"/tmp/gitleaks-{job_id}.json"  # unique report path per job

    try:
        proc = subprocess.run(
            [
                "gitleaks", "detect",  # secret detection mode
                "--source", repo_path,  # scan this tree only
                "--report-format", "json",  # machine-readable output
                "--report-path", report_path,  # write findings here
                "--no-git",  # scan files, not full history
                "--exit-code", "0",   # findings must not fail the process
            ],
            timeout=600, capture_output=True, text=True,  # 10 min cap; capture logs
        )
        # --exit-code 0 means gitleaks returns 0 even with findings; a non-zero
        # here is a real execution error.
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "gitleaks failed", file=sys.stderr)
            return 1  # real crash, not "secrets found"
    except subprocess.TimeoutExpired:
        print("gitleaks scan timed out", file=sys.stderr)
        return 1  # do not POST partial garbage

    findings = []  # default empty when no report file
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                content = f.read().strip()  # empty file = no secrets
            if content:
                parsed = json.loads(content)  # expect a JSON array
                if isinstance(parsed, list):
                    findings = parsed  # native gitleaks objects
        except Exception as exc:
            print(f"Failed to parse gitleaks report: {exc}", file=sys.stderr)
            return 1  # corrupt report is a hard failure

    payload = {
        "tool_meta": {"version": gitleaks_version(), "config": "default"},  # provenance
        "data": findings,  # raw list for aggregator parse
    }

    try:
        resp = requests.post(
            f"{ci_utils_url.rstrip('/')}/results/{job_id}/gitleaks",  # v3 results URL
            json=payload, timeout=30,  # short timeout for result delivery
        )
        resp.raise_for_status()  # non-2xx → exception
    except Exception as exc:
        print(f"Failed to POST results: {exc}", file=sys.stderr)
        return 1  # dispatcher will retry Job if configured

    print(f"gitleaks: posted {len(findings)} findings for job {job_id}")  # stdout for logs
    return 0  # success (even if findings list is empty)


if __name__ == "__main__":
    sys.exit(main())  # container entrypoint exit code
