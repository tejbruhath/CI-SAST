"""
Aggregates per-tool scanner results into the v3.0.0 mega-artifact.

Schema (per the findings-report spec): six top-level blocks in order
    metadata -> tools -> gitleaks -> trivy -> sonarqube -> summary

Key behaviours:
  * whole-run context (repo/commit/pipeline/...) hoisted into `metadata` once,
    NOT repeated per finding.
  * `file` is repo-relative -- the scan-time /repos/{job_id}/ prefix is stripped
    because that path dies with the repo PV.
  * finding `type` taxonomy + numeric `severity_score` for frontend filtering.
  * gitleaks severity is tiered by rule class (cloud/payment = critical).
  * SonarQube `secrets:*` rules are dropped -- gitleaks is the secret signal;
    sonar/trivy secret detection is intentionally removed from this pipeline.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import config

SEV_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 1}

# gitleaks rule keywords that denote high-value credentials -> critical tier
_CRITICAL_SECRET_KEYWORDS = (
    "aws", "gcp", "azure", "private-key", "privatekey", "rsa",
    "stripe", "paypal", "square", "github", "gitlab", "slack",
    "twilio", "sendgrid", "npm", "pypi", "digitalocean",
)

_TRIVY_SEV = {
    "CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium",
    "LOW": "low", "UNKNOWN": "low",
}
_SONAR_SEV = {
    "BLOCKER": "critical", "CRITICAL": "high", "MAJOR": "medium",
    "MINOR": "low", "INFO": "info",
}
_SONAR_TYPE = {
    "BUG": "bug", "VULNERABILITY": "vulnerability",
    "CODE_SMELL": "code_smell", "SECURITY_HOTSPOT": "security_hotspot",
}


def _iso_to_epoch(iso: Optional[str]) -> Optional[int]:
    if not iso or iso in ("n/a", ""):
        return None
    try:
        s = iso.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return None


def _rel(path: str, job_id: str) -> str:
    if not path:
        return "unknown"
    prefix = f"{config.REPOS_DIR}/{job_id}/"
    if path.startswith(prefix):
        path = path[len(prefix):]
    elif path.startswith(config.REPOS_DIR + "/"):
        path = path[len(config.REPOS_DIR) + 1:]
    return path.lstrip("/") or "unknown"


def _effort_minutes(effort: Optional[str]) -> Optional[int]:
    if not effort:
        return None
    total = 0
    for num, unit in re.findall(r"(\d+)(h|min|d)", effort):
        n = int(num)
        total += n * {"h": 60, "min": 1, "d": 480}[unit]
    return total or None


# ---- metadata ----------------------------------------------------------------
def _build_metadata(job_id: str, ci: Dict[str, Any]) -> Dict[str, Any]:
    commit_ts = ci.get("CI_COMMIT_TIMESTAMP")
    pipeline_ts = ci.get("CI_PIPELINE_CREATED_AT")
    now = datetime.now(timezone.utc)
    return {
        "schema_version": config.SCHEMA_VERSION,
        "job_id": job_id,
        "generated_at": now.isoformat(),
        "generated_at_epoch": int(now.timestamp()),
        "repo": {
            "name": ci.get("CI_PROJECT_NAME", "n/a"),
            "path": ci.get("CI_PROJECT_PATH", "n/a"),
            "url": ci.get("CI_PROJECT_URL", "n/a"),
            "id": ci.get("CI_PROJECT_ID", "n/a"),
            "visibility": ci.get("CI_PROJECT_VISIBILITY", "n/a"),
        },
        "branch": ci.get("CI_COMMIT_BRANCH", ci.get("CI_COMMIT_REF_NAME", "n/a")),
        "commit": {
            "sha": ci.get("CI_COMMIT_SHA", "n/a"),
            "short_sha": ci.get("CI_COMMIT_SHORT_SHA", "n/a"),
            "author_name": ci.get("CI_COMMIT_AUTHOR", "n/a"),
            "message": ci.get("CI_COMMIT_MESSAGE", "n/a"),
            "timestamp": commit_ts or "n/a",
            "timestamp_epoch": _iso_to_epoch(commit_ts),
        },
        "pipeline": {
            "id": ci.get("CI_PIPELINE_ID", "n/a"),
            "iid": ci.get("CI_PIPELINE_IID", "n/a"),
            "url": ci.get("CI_PIPELINE_URL", "n/a"),
            "source": ci.get("CI_PIPELINE_SOURCE", "n/a"),
            "created_at": pipeline_ts or "n/a",
            "created_at_epoch": _iso_to_epoch(pipeline_ts),
        },
        "job": {
            "id": ci.get("CI_JOB_ID", "n/a"),
            "name": ci.get("CI_JOB_NAME", "n/a"),
            "stage": ci.get("CI_JOB_STAGE", "n/a"),
            "url": ci.get("CI_JOB_URL", "n/a"),
        },
        "runner": {
            "id": ci.get("CI_RUNNER_ID", "n/a"),
            "description": ci.get("CI_RUNNER_DESCRIPTION", "n/a"),
            "tags": ci.get("CI_RUNNER_TAGS", []),
            "version": ci.get("CI_RUNNER_VERSION", "n/a"),
        },
        "gitlab": {
            "user_login": ci.get("GITLAB_USER_LOGIN", "n/a"),
            "user_email": ci.get("GITLAB_USER_EMAIL", "n/a"),
            "user_name": ci.get("GITLAB_USER_NAME", "n/a"),
            "ci_server_version": ci.get("CI_SERVER_VERSION", "n/a"),
        },
    }


def _build_tools(results: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    def meta(tool):
        r = results.get(tool) or {}
        return r.get("tool_meta") or {}
    return {
        "gitleaks": meta("gitleaks"),
        "trivy": meta("trivy"),
        "sonarqube": meta("sonarqube"),
    }


# ---- per-tool findings -------------------------------------------------------
def _gitleaks_findings(data: Any, job_id: str) -> List[Dict[str, Any]]:
    out = []
    items = data if isinstance(data, list) else []
    for f in items:
        rule = f.get("RuleID", "unknown")
        lower = rule.lower()
        sev = "critical" if any(k in lower for k in _CRITICAL_SECRET_KEYWORDS) else "high"
        file = _rel(f.get("File", "unknown"), job_id)
        line = f.get("StartLine")
        fp = f.get("Fingerprint") or f"{rule}:{file}:{line}"
        out.append({
            "id": fp,
            "rule_id": rule,
            "type": "secret",
            "severity": sev,
            "severity_score": SEV_SCORE[sev],
            "message": f"Secret: {rule} in {file}:{line}",
            "file": file,
            "line": line,
            "fingerprint": fp,
            "url": None,
            "details": {"secret_type": rule, "entropy": f.get("Entropy")},
        })
    return out


def _trivy_findings(data: Any, job_id: str) -> List[Dict[str, Any]]:
    out = []
    if not isinstance(data, dict):
        return out
    for res in data.get("Results", []) or []:
        target = res.get("Target", "unknown")
        pkg_type = res.get("Type") or res.get("Class")
        for v in res.get("Vulnerabilities") or []:
            if not isinstance(v, dict):
                continue
            sev = _TRIVY_SEV.get(v.get("Severity", "UNKNOWN"), "low")
            vid = v.get("VulnerabilityID", "unknown")
            pkg = v.get("PkgName", "unknown")
            title = v.get("Title") or v.get("Description") or "No description"
            file = _rel(target, job_id)
            cvss = None
            for src in (v.get("CVSS") or {}).values():
                if isinstance(src, dict) and src.get("V3Score"):
                    cvss = src["V3Score"]
                    break
            out.append({
                "id": f"{vid}:{file}:{pkg}",
                "rule_id": vid,
                "type": "vulnerability",
                "severity": sev,
                "severity_score": SEV_SCORE[sev],
                "message": f"{pkg}: {title[:120]}",
                "file": file,
                "line": None,
                "fingerprint": f"{vid}:{file}:{pkg}",
                "url": v.get("PrimaryURL"),
                "details": {
                    "package_name": pkg,
                    "installed_version": v.get("InstalledVersion"),
                    "fixed_version": v.get("FixedVersion"),
                    "cvss_score": cvss,
                    "pkg_type": pkg_type,
                },
            })
    return out


def _sonar_findings(data: Any, job_id: str, project_key: str) -> List[Dict[str, Any]]:
    out = []
    if not isinstance(data, dict):
        return out
    # component key -> path map (sonar issues carry "project:path" components)
    comp_paths = {}
    for c in data.get("components", []) or []:
        if c.get("path"):
            comp_paths[c.get("key")] = c.get("path")
    host = config.SONAR_HOST.rstrip("/")
    for i in data.get("issues", []) or []:
        rule = i.get("rule", "unknown")
        if rule.startswith("secrets:"):
            continue  # secret detection removed from sonar; gitleaks owns secrets
        sev = _SONAR_SEV.get(i.get("severity", "INFO"), "info")
        comp = i.get("component", "")
        path = comp_paths.get(comp)
        if not path:
            path = comp.split(":", 1)[1] if ":" in comp else comp
        file = _rel(path, job_id)
        key = i.get("key", "unknown")
        stype = i.get("type", "CODE_SMELL")
        out.append({
            "id": key,
            "rule_id": rule,
            "type": _SONAR_TYPE.get(stype, "code_smell"),
            "severity": sev,
            "severity_score": SEV_SCORE[sev],
            "message": i.get("message", "Sonar issue"),
            "file": file,
            "line": i.get("line"),
            "fingerprint": key,
            "url": (f"{host}/project/issues?open={key}&id={project_key}"
                    if host else None),
            "details": {
                "sonar_type": stype,
                "effort_minutes": _effort_minutes(i.get("effort") or i.get("debt")),
                "tags": i.get("tags", []),
            },
        })
    return out


# ---- summary -----------------------------------------------------------------
def _build_summary(gl, tv, sq) -> Dict[str, Any]:
    by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    by_type: Dict[str, int] = {}
    by_file: Dict[str, int] = {}
    for arr in (gl, tv, sq):
        for f in arr:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
            if f["file"] and f["file"] != "unknown":
                by_file[f["file"]] = by_file.get(f["file"], 0) + 1
    by_sev = {k: v for k, v in by_sev.items() if v or k in ("critical", "high", "medium", "low")}
    return {
        "total_findings": len(gl) + len(tv) + len(sq),
        "files_affected": len(by_file),
        "by_tool": {"gitleaks": len(gl), "trivy": len(tv), "sonarqube": len(sq)},
        "by_severity": by_sev,
        "by_type": by_type,
        "by_file": by_file,
    }


def aggregate(job_id: str, job: Dict[str, Any],
              results: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    ci = job.get("ci_context", {}) or {}
    project_key = job.get("project_key", "")

    def data_of(tool):
        r = results.get(tool) or {}
        return r.get("data")

    gl = _gitleaks_findings(data_of("gitleaks"), job_id)
    tv = _trivy_findings(data_of("trivy"), job_id)
    sq = _sonar_findings(data_of("sonarqube"), job_id, project_key)

    return {
        "metadata": _build_metadata(job_id, ci),
        "tools": _build_tools(results),
        "gitleaks": gl,
        "trivy": tv,
        "sonarqube": sq,
        "summary": _build_summary(gl, tv, sq),
    }
