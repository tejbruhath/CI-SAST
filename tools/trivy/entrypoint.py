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
import json  # parse Trivy JSON report
import os  # Job env vars and path checks
import subprocess  # run trivy CLI
import sys  # stderr + exit codes

import requests  # POST results to ci-utils

TRIVY_VERSION = os.getenv("TRIVY_VERSION", "0.50.0")  # fallback version string


def trivy_version() -> str:
    """Read `trivy --version` for tool_meta, else env default."""
    try:
        out = subprocess.run(
            ["trivy", "--version"], capture_output=True, text=True, timeout=15  # quick probe
        )
        for line in (out.stdout or "").splitlines():
            if line.lower().startswith("version:"):  # parse "Version: x.y.z"
                return line.split(":", 1)[1].strip()
        return TRIVY_VERSION  # unexpected format
    except Exception:
        return TRIVY_VERSION  # binary missing


def main() -> int:
    """Scan filesystem for vulns and POST Trivy JSON to orchestrator."""
    job_id = os.getenv("JOB_ID")  # job identity for result route
    repo_path = os.getenv("REPO_PATH")  # shared PV clone path
    ci_utils_url = os.getenv("CI_UTILS_URL")  # results endpoint base

    if not job_id or not repo_path or not ci_utils_url:
        print("Missing required env: JOB_ID, REPO_PATH, CI_UTILS_URL", file=sys.stderr)
        return 1

    if not os.path.isdir(repo_path):
        print(f"REPO_PATH does not exist: {repo_path}", file=sys.stderr)
        return 1

    report_path = f"/tmp/trivy-{job_id}.json"  # per-job report file

    try:
        proc = subprocess.run(
            [
                "trivy", "filesystem",  # scan local tree (not container image)
                "--scanners", "vuln",      # vuln only; no secret/config scanning
                "--format", "json",  # structured report
                "--output", report_path,  # write to disk for parse
                "--exit-code", "0",  # findings are not process failure
                "--no-progress",  # quieter logs in k8s
                repo_path,  # scan root
            ],
            timeout=900, capture_output=True, text=True,  # 15 min cap
        )
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "trivy failed", file=sys.stderr)
            return 1  # real execution error
    except subprocess.TimeoutExpired:
        print("trivy scan timed out", file=sys.stderr)
        return 1

    data = {"Results": []}  # empty default if no report
    db_meta = {}  # vulnerability DB freshness metadata
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                content = f.read().strip()
            if content:
                parsed = json.loads(content)  # full Trivy document
                if isinstance(parsed, dict):
                    data = parsed  # keep Results + Metadata
                    meta = parsed.get("Metadata", {}) or {}
                    vdb = meta.get("VulnerabilityDB", {}) or {}
                    db_meta = {
                        "type": "vulnerability-db",  # label for consumers
                        "updated_at": vdb.get("UpdatedAt"),  # last DB refresh
                        "next_update_at": vdb.get("NextUpdate"),  # next expected
                    }
        except Exception as exc:
            print(f"Failed to parse trivy report: {exc}", file=sys.stderr)
            return 1

    payload = {
        "tool_meta": {
            "version": trivy_version(),  # binary version string
            "scanners": ["vuln"],  # document intentional scanner set
            "db": db_meta or None,  # None when Metadata missing
        },
        "data": data,  # native Trivy JSON for aggregator
    }

    try:
        resp = requests.post(
            f"{ci_utils_url.rstrip('/')}/results/{job_id}/trivy",  # v3 route
            json=payload, timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"Failed to POST results: {exc}", file=sys.stderr)
        return 1

    n = sum(len(r.get("Vulnerabilities") or []) for r in data.get("Results", []))  # count CVEs
    print(f"trivy: posted {n} vulnerabilities for job {job_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())  # k8s Job exit code
