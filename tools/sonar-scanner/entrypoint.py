#!/usr/bin/env python3
"""
sonar-scanner one-shot Job (SonarQube client side).

Runs the sonar-scanner CLI against $REPO_PATH (already on the shared PV),
waits for the async Compute Engine task on the SonarQube server, fetches the
issues, and POSTs them to ci-utils.

Result contract (v3):
    POST /results/{job_id}/sonarqube
    { "tool_meta": {...}, "data": { "issues": [...], "components": [...] } }

Failure-mode fix (v3 architecture doc s6.3): on ANY failure (scanner error,
missing ceTaskId, CE task failed/canceled, poll timeout) this exits NON-ZERO
and POSTs NOTHING. The Job then fails and ci-utils' dispatcher retries it,
instead of silently reporting a false zero-finding result. An empty issue set
is only ever reported when the CE task genuinely SUCCEEDS.
"""
import base64
import os
import subprocess
import sys
import time

import requests

SCANNER_VERSION = os.getenv("SONAR_SCANNER_VERSION", "5.0.1.3006")
POLL_ATTEMPTS = int(os.getenv("SONAR_POLL_ATTEMPTS", "40"))
POLL_INTERVAL = int(os.getenv("SONAR_POLL_INTERVAL", "3"))


def get_json(url: str, token: str):
    auth = base64.b64encode(f"{token}:".encode()).decode().strip()
    resp = requests.get(url, headers={"Authorization": f"Basic {auth}"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def post_results(ci_utils_url: str, job_id: str, payload: dict) -> None:
    resp = requests.post(
        f"{ci_utils_url.rstrip('/')}/results/{job_id}/sonarqube",
        json=payload, timeout=30,
    )
    resp.raise_for_status()


def parse_report_task(path: str) -> dict:
    out = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f.read().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    return out


def main() -> int:
    job_id = os.getenv("JOB_ID")
    repo_path = os.getenv("REPO_PATH")
    ci_utils_url = os.getenv("CI_UTILS_URL")
    project_key = os.getenv("SONAR_PROJECT_KEY")
    token = os.getenv("SONAR_TOKEN")
    host = os.getenv("SONAR_HOST")

    if not all([job_id, repo_path, ci_utils_url, project_key, token, host]):
        print("Missing required env: JOB_ID, REPO_PATH, CI_UTILS_URL, "
              "SONAR_PROJECT_KEY, SONAR_TOKEN, SONAR_HOST", file=sys.stderr)
        return 1

    if not os.path.isdir(repo_path):
        print(f"REPO_PATH does not exist: {repo_path}", file=sys.stderr)
        return 1

    host = host.rstrip("/")
    cmd = [
        "sonar-scanner",
        f"-Dsonar.projectKey={project_key}",
        f"-Dsonar.projectName={project_key}",
        "-Dsonar.sources=.",
        f"-Dsonar.host.url={host}",
        f"-Dsonar.token={token}",
        "-Dsonar.qualitygate.wait=false",
        f"-Dsonar.projectBaseDir={repo_path}",
        "-Dsonar.scm.disabled=true",
    ]

    try:
        result = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=900
        )
    except subprocess.TimeoutExpired:
        print("sonar-scanner timed out", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(result.stderr[-1000:] if result.stderr else "sonar-scanner failed",
              file=sys.stderr)
        return 1

    task = parse_report_task(os.path.join(repo_path, ".scannerwork", "report-task.txt"))
    ce_task_id = task.get("ceTaskId")
    server_version = task.get("serverVersion")

    if not ce_task_id:
        print("ceTaskId not found in report-task.txt", file=sys.stderr)
        return 1

    # Poll the async Compute Engine task.
    success = False
    for _ in range(POLL_ATTEMPTS):
        try:
            res = get_json(f"{host}/api/ce/task?id={ce_task_id}", token)
        except Exception as exc:
            print(f"CE poll request failed: {exc}", file=sys.stderr)
            return 1
        status = (res or {}).get("task", {}).get("status", "PENDING")
        if status == "SUCCESS":
            success = True
            break
        if status in ("FAILED", "CANCELED"):
            print(f"CE task terminal status: {status}", file=sys.stderr)
            return 1
        time.sleep(POLL_INTERVAL)

    if not success:
        print("CE task did not complete within poll window", file=sys.stderr)
        return 1  # do NOT post a fake empty result; let dispatcher retry

    # CE task succeeded -> an empty issue set here is a genuine result.
    time.sleep(2)
    try:
        data = get_json(
            f"{host}/api/issues/search?componentKeys={project_key}"
            f"&statuses=OPEN,CONFIRMED,REOPENED&ps=500",
            token,
        ) or {"issues": []}
    except Exception as exc:
        print(f"Failed to fetch issues: {exc}", file=sys.stderr)
        return 1

    payload = {
        "tool_meta": {
            "scanner_version": SCANNER_VERSION,
            "server_version": server_version,
            "edition": "community",
            "quality_profile": "Sonar way",
        },
        "data": data,
    }

    try:
        post_results(ci_utils_url, job_id, payload)
    except Exception as exc:
        print(f"Failed to POST results: {exc}", file=sys.stderr)
        return 1

    print(f"sonarqube: posted {len(data.get('issues', []))} issues for job {job_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
