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
import base64  # Basic auth header for SonarQube token
import os  # Job env configuration
import subprocess  # run sonar-scanner CLI
import sys  # stderr + exit codes
import time  # poll interval sleeps

import requests  # SonarQube API + results POST

SCANNER_VERSION = os.getenv("SONAR_SCANNER_VERSION", "5.0.1.3006")  # client version label
POLL_ATTEMPTS = int(os.getenv("SONAR_POLL_ATTEMPTS", "40"))  # max CE poll loops
POLL_INTERVAL = int(os.getenv("SONAR_POLL_INTERVAL", "3"))  # seconds between polls


def get_json(url: str, token: str):
    """GET JSON from SonarQube using token as Basic username."""
    auth = base64.b64encode(f"{token}:".encode()).decode().strip()  # user: empty password
    resp = requests.get(url, headers={"Authorization": f"Basic {auth}"}, timeout=30)
    resp.raise_for_status()  # non-2xx raises
    return resp.json()  # parsed object


def post_results(ci_utils_url: str, job_id: str, payload: dict) -> None:
    """Deliver Sonar issues payload to orchestrator results endpoint."""
    resp = requests.post(
        f"{ci_utils_url.rstrip('/')}/results/{job_id}/sonarqube",  # v3 route
        json=payload, timeout=30,
    )
    resp.raise_for_status()


def parse_report_task(path: str) -> dict:
    """Parse sonar-scanner's report-task.txt key=value file."""
    out = {}  # key → value map
    if os.path.exists(path):
        with open(path) as f:
            for line in f.read().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)  # first = only
                    out[k.strip()] = v.strip()
    return out  # may be empty if file missing


def main() -> int:
    """Scan → wait CE → fetch issues → POST; fail hard on any error."""
    job_id = os.getenv("JOB_ID")  # orchestrator job id
    repo_path = os.getenv("REPO_PATH")  # shared clone path
    ci_utils_url = os.getenv("CI_UTILS_URL")  # results base URL
    project_key = os.getenv("SONAR_PROJECT_KEY")  # Sonar project key
    token = os.getenv("SONAR_TOKEN")  # server auth token
    host = os.getenv("SONAR_HOST")  # e.g. http://sonarqube:9000

    if not all([job_id, repo_path, ci_utils_url, project_key, token, host]):
        print("Missing required env: JOB_ID, REPO_PATH, CI_UTILS_URL, "
              "SONAR_PROJECT_KEY, SONAR_TOKEN, SONAR_HOST", file=sys.stderr)
        return 1

    if not os.path.isdir(repo_path):
        print(f"REPO_PATH does not exist: {repo_path}", file=sys.stderr)
        return 1

    host = host.rstrip("/")  # normalize trailing slash
    cmd = [
        "sonar-scanner",  # CLI entrypoint
        f"-Dsonar.projectKey={project_key}",  # unique project id on server
        f"-Dsonar.projectName={project_key}",  # display name
        "-Dsonar.sources=.",  # scan whole tree relative to base dir
        f"-Dsonar.host.url={host}",  # SonarQube server
        f"-Dsonar.token={token}",  # auth for upload
        "-Dsonar.qualitygate.wait=false",  # do not block on QG; we poll CE ourselves
        f"-Dsonar.projectBaseDir={repo_path}",  # analysis root
        "-Dsonar.scm.disabled=true",  # avoid git blame delays in Jobs
    ]

    try:
        result = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=900  # 15 min
        )
    except subprocess.TimeoutExpired:
        print("sonar-scanner timed out", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(result.stderr[-1000:] if result.stderr else "sonar-scanner failed",
              file=sys.stderr)  # tail of error log
        return 1

    task = parse_report_task(os.path.join(repo_path, ".scannerwork", "report-task.txt"))
    ce_task_id = task.get("ceTaskId")  # async server-side analysis id
    server_version = task.get("serverVersion")  # for tool_meta

    if not ce_task_id:
        print("ceTaskId not found in report-task.txt", file=sys.stderr)
        return 1  # cannot poll without id

    # Poll the async Compute Engine task.
    success = False  # set True only on SUCCESS
    for _ in range(POLL_ATTEMPTS):
        try:
            res = get_json(f"{host}/api/ce/task?id={ce_task_id}", token)  # CE status
        except Exception as exc:
            print(f"CE poll request failed: {exc}", file=sys.stderr)
            return 1
        status = (res or {}).get("task", {}).get("status", "PENDING")  # task state
        if status == "SUCCESS":
            success = True  # analysis finished cleanly
            break
        if status in ("FAILED", "CANCELED"):
            print(f"CE task terminal status: {status}", file=sys.stderr)
            return 1  # do not invent empty findings
        time.sleep(POLL_INTERVAL)  # wait before next poll

    if not success:
        print("CE task did not complete within poll window", file=sys.stderr)
        return 1  # do NOT post a fake empty result; let dispatcher retry

    # CE task succeeded -> an empty issue set here is a genuine result.
    time.sleep(2)  # brief settle so issues index is queryable
    try:
        data = get_json(
            f"{host}/api/issues/search?componentKeys={project_key}"
            f"&statuses=OPEN,CONFIRMED,REOPENED&ps=500",  # open issues page
            token,
        ) or {"issues": []}
    except Exception as exc:
        print(f"Failed to fetch issues: {exc}", file=sys.stderr)
        return 1

    payload = {
        "tool_meta": {
            "scanner_version": SCANNER_VERSION,  # client CLI version
            "server_version": server_version,  # SonarQube server version
            "edition": "community",  # documented edition assumption
            "quality_profile": "Sonar way",  # default profile label
        },
        "data": data,  # issues search JSON body
    }

    try:
        post_results(ci_utils_url, job_id, payload)  # deliver to orchestrator
    except Exception as exc:
        print(f"Failed to POST results: {exc}", file=sys.stderr)
        return 1

    print(f"sonarqube: posted {len(data.get('issues', []))} issues for job {job_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())  # Job container entrypoint
