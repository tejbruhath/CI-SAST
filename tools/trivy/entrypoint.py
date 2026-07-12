#!/usr/bin/env python3
"""
Trivy one-shot scanner Job.

Filesystem vulnerability scan of $REPO_PATH (already on the shared PV).
Secret scanning is intentionally NOT enabled (--scanners vuln only) --
gitleaks is the dedicated secret signal in this pipeline.

Result contract (v3):
    POST /results/{job_id}/trivy
    { "tool_meta": {...}, "data": { "Results": [...] } }

Exit codes:
    0  scan ran and results were POSTed
    1  hard failure -> dispatcher retries
"""
import json
import os
import subprocess
import sys

import requests

TRIVY_VERSION = os.getenv("TRIVY_VERSION", "0.50.0")


def trivy_version() -> str:
    try:
        out = subprocess.run(
            ["trivy", "--version"], capture_output=True, text=True, timeout=15
        )
        for line in (out.stdout or "").splitlines():
            if line.lower().startswith("version:"):
                return line.split(":", 1)[1].strip()
        return TRIVY_VERSION
    except Exception:
        return TRIVY_VERSION


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

    report_path = f"/tmp/trivy-{job_id}.json"

    try:
        proc = subprocess.run(
            [
                "trivy", "filesystem",
                "--scanners", "vuln",      # vuln only; no secret/config scanning
                "--format", "json",
                "--output", report_path,
                "--exit-code", "0",
                "--no-progress",
                repo_path,
            ],
            timeout=900, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "trivy failed", file=sys.stderr)
            return 1
    except subprocess.TimeoutExpired:
        print("trivy scan timed out", file=sys.stderr)
        return 1

    data = {"Results": []}
    db_meta = {}
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                content = f.read().strip()
            if content:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    data = parsed
                    meta = parsed.get("Metadata", {}) or {}
                    vdb = meta.get("VulnerabilityDB", {}) or {}
                    db_meta = {
                        "type": "vulnerability-db",
                        "updated_at": vdb.get("UpdatedAt"),
                        "next_update_at": vdb.get("NextUpdate"),
                    }
        except Exception as exc:
            print(f"Failed to parse trivy report: {exc}", file=sys.stderr)
            return 1

    payload = {
        "tool_meta": {
            "version": trivy_version(),
            "scanners": ["vuln"],
            "db": db_meta or None,
        },
        "data": data,
    }

    try:
        resp = requests.post(
            f"{ci_utils_url.rstrip('/')}/results/{job_id}/trivy",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"Failed to POST results: {exc}", file=sys.stderr)
        return 1

    n = sum(len(r.get("Vulnerabilities") or []) for r in data.get("Results", []))
    print(f"trivy: posted {n} vulnerabilities for job {job_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
