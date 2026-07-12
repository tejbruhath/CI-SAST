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
import json
import os
import subprocess
import sys

import requests

GITLEAKS_VERSION = os.getenv("GITLEAKS_VERSION", "8.18.0")


def gitleaks_version() -> str:
    try:
        out = subprocess.run(
            ["gitleaks", "version"], capture_output=True, text=True, timeout=15
        )
        v = (out.stdout or out.stderr or "").strip()
        return v or GITLEAKS_VERSION
    except Exception:
        return GITLEAKS_VERSION


def main() -> int:
    job_id = os.getenv("JOB_ID")
    repo_path = os.getenv("REPO_PATH")
    ci_utils_url = os.getenv("CI_UTILS_URL")

    if not job_id or not repo_path or not ci_utils_url:
        print("Missing required env: JOB_ID, REPO_PATH, CI_UTILS_URL", file=sys.stderr)
        return 1

    if not os.path.isdir(repo_path):
        print(f"REPO_PATH does not exist: {repo_path}", file=sys.stderr)
        return 1

    report_path = f"/tmp/gitleaks-{job_id}.json"

    try:
        proc = subprocess.run(
            [
                "gitleaks", "detect",
                "--source", repo_path,
                "--report-format", "json",
                "--report-path", report_path,
                "--no-git",
                "--exit-code", "0",   # findings must not fail the process
            ],
            timeout=600, capture_output=True, text=True,
        )
        # --exit-code 0 means gitleaks returns 0 even with findings; a non-zero
        # here is a real execution error.
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "gitleaks failed", file=sys.stderr)
            return 1
    except subprocess.TimeoutExpired:
        print("gitleaks scan timed out", file=sys.stderr)
        return 1

    findings = []
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                content = f.read().strip()
            if content:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    findings = parsed
        except Exception as exc:
            print(f"Failed to parse gitleaks report: {exc}", file=sys.stderr)
            return 1

    payload = {
        "tool_meta": {"version": gitleaks_version(), "config": "default"},
        "data": findings,
    }

    try:
        resp = requests.post(
            f"{ci_utils_url.rstrip('/')}/results/{job_id}/gitleaks",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"Failed to POST results: {exc}", file=sys.stderr)
        return 1

    print(f"gitleaks: posted {len(findings)} findings for job {job_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
