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
import re  # Parse Sonar effort strings like "1h30min".
from datetime import datetime, timezone  # ISO timestamps and epoch conversions.
from typing import Any, Dict, List, Optional  # Type hints for findings and job payloads.

from . import config  # SCHEMA_VERSION, REPOS_DIR, SONAR_HOST for paths and links.

SEV_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 1}  # Sortable severity ranks.

# gitleaks rule keywords that denote high-value credentials -> critical tier
_CRITICAL_SECRET_KEYWORDS = (  # Substrings that elevate secret severity to critical.
    "aws", "gcp", "azure", "private-key", "privatekey", "rsa",  # Cloud/crypto keys.
    "stripe", "paypal", "square", "github", "gitlab", "slack",  # Payment and SCM tokens.
    "twilio", "sendgrid", "npm", "pypi", "digitalocean",  # SaaS and package registry secrets.
)

_TRIVY_SEV = {  # Map Trivy uppercase severities onto our lowercase taxonomy.
    "CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium",
    "LOW": "low", "UNKNOWN": "low",  # Unknown treated as low, not critical.
}
_SONAR_SEV = {  # Map Sonar severities onto our shared severity scale.
    "BLOCKER": "critical", "CRITICAL": "high", "MAJOR": "medium",
    "MINOR": "low", "INFO": "info",
}
_SONAR_TYPE = {  # Map Sonar issue types onto frontend-friendly type strings.
    "BUG": "bug", "VULNERABILITY": "vulnerability",
    "CODE_SMELL": "code_smell", "SECURITY_HOTSPOT": "security_hotspot",
}


def _iso_to_epoch(iso: Optional[str]) -> Optional[int]:  # Convert ISO datetime to unix seconds.
    if not iso or iso in ("n/a", ""):  # Placeholder or empty values are not real times.
        return None
    try:
        s = iso.replace("Z", "+00:00")  # fromisoformat needs explicit UTC offset, not Z.
        return int(datetime.fromisoformat(s).timestamp())  # Integer epoch for sorting/UI.
    except Exception:
        return None  # Bad timestamps become null instead of crashing aggregation.


def _rel(path: str, job_id: str) -> str:  # Strip scan-time absolute prefix to repo-relative path.
    if not path:
        return "unknown"  # Empty path cannot be displayed meaningfully.
    prefix = f"{config.REPOS_DIR}/{job_id}/"  # Expected mount prefix for this job clone.
    if path.startswith(prefix):
        path = path[len(prefix):]  # Drop /repos/{job_id}/ so paths survive PV cleanup.
    elif path.startswith(config.REPOS_DIR + "/"):
        path = path[len(config.REPOS_DIR) + 1:]  # Drop bare /repos/ if job_id segment differs.
    return path.lstrip("/") or "unknown"  # Normalize leading slashes; empty becomes unknown.


def _effort_minutes(effort: Optional[str]) -> Optional[int]:  # Parse Sonar effort into minutes.
    if not effort:
        return None  # No effort/debt string available.
    total = 0  # Accumulate minutes from all unit chunks.
    for num, unit in re.findall(r"(\d+)(h|min|d)", effort):  # Match 2h, 30min, 1d style tokens.
        n = int(num)  # Numeric quantity for this unit.
        total += n * {"h": 60, "min": 1, "d": 480}[unit]  # Convert hours/days to minutes.
    return total or None  # None if nothing matched rather than zero.


# ---- metadata ----------------------------------------------------------------
def _build_metadata(job_id: str, ci: Dict[str, Any]) -> Dict[str, Any]:  # One shared context block.
    commit_ts = ci.get("CI_COMMIT_TIMESTAMP")  # Commit time from GitLab CI variables.
    pipeline_ts = ci.get("CI_PIPELINE_CREATED_AT")  # Pipeline creation time if present.
    now = datetime.now(timezone.utc)  # Generation time for this mega-artifact.
    return {
        "schema_version": config.SCHEMA_VERSION,  # Report schema consumers should expect.
        "job_id": job_id,  # Our short internal job identifier.
        "generated_at": now.isoformat(),  # ISO timestamp of aggregation.
        "generated_at_epoch": int(now.timestamp()),  # Epoch twin for easy sorting.
        "repo": {  # Project identity from CI context.
            "name": ci.get("CI_PROJECT_NAME", "n/a"),  # Human project name.
            "path": ci.get("CI_PROJECT_PATH", "n/a"),  # group/project path.
            "url": ci.get("CI_PROJECT_URL", "n/a"),  # Web URL for the project.
            "id": ci.get("CI_PROJECT_ID", "n/a"),  # Numeric GitLab project id.
            "visibility": ci.get("CI_PROJECT_VISIBILITY", "n/a"),  # public/private/internal.
        },
        "branch": ci.get("CI_COMMIT_BRANCH", ci.get("CI_COMMIT_REF_NAME", "n/a")),  # Branch or ref name.
        "commit": {  # Commit details for provenance.
            "sha": ci.get("CI_COMMIT_SHA", "n/a"),  # Full commit hash.
            "short_sha": ci.get("CI_COMMIT_SHORT_SHA", "n/a"),  # Abbreviated hash for UI.
            "author_name": ci.get("CI_COMMIT_AUTHOR", "n/a"),  # Commit author string.
            "message": ci.get("CI_COMMIT_MESSAGE", "n/a"),  # Commit message body.
            "timestamp": commit_ts or "n/a",  # Original ISO string if any.
            "timestamp_epoch": _iso_to_epoch(commit_ts),  # Numeric time or null.
        },
        "pipeline": {  # Pipeline identity for deep links and audit.
            "id": ci.get("CI_PIPELINE_ID", "n/a"),  # Global pipeline id.
            "iid": ci.get("CI_PIPELINE_IID", "n/a"),  # Project-local pipeline number.
            "url": ci.get("CI_PIPELINE_URL", "n/a"),  # Browser URL for the pipeline.
            "source": ci.get("CI_PIPELINE_SOURCE", "n/a"),  # push, merge_request_event, etc.
            "created_at": pipeline_ts or "n/a",  # Original creation timestamp string.
            "created_at_epoch": _iso_to_epoch(pipeline_ts),  # Epoch form if parseable.
        },
        "job": {  # CI job that triggered the scan request.
            "id": ci.get("CI_JOB_ID", "n/a"),
            "name": ci.get("CI_JOB_NAME", "n/a"),
            "stage": ci.get("CI_JOB_STAGE", "n/a"),
            "url": ci.get("CI_JOB_URL", "n/a"),
        },
        "runner": {  # Runner metadata for ops debugging.
            "id": ci.get("CI_RUNNER_ID", "n/a"),
            "description": ci.get("CI_RUNNER_DESCRIPTION", "n/a"),
            "tags": ci.get("CI_RUNNER_TAGS", []),  # Tag list if provided.
            "version": ci.get("CI_RUNNER_VERSION", "n/a"),
        },
        "gitlab": {  # User and server info from GitLab CI env.
            "user_login": ci.get("GITLAB_USER_LOGIN", "n/a"),
            "user_email": ci.get("GITLAB_USER_EMAIL", "n/a"),
            "user_name": ci.get("GITLAB_USER_NAME", "n/a"),
            "ci_server_version": ci.get("CI_SERVER_VERSION", "n/a"),
        },
    }


def _build_tools(results: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:  # Tool meta only.
    def meta(tool):  # Extract tool_meta from one tool result envelope.
        r = results.get(tool) or {}  # Missing tool yields empty dict.
        return r.get("tool_meta") or {}  # Prefer nested tool_meta; default empty.
    return {
        "gitleaks": meta("gitleaks"),  # Version/runtime meta from gitleaks run.
        "trivy": meta("trivy"),  # Version/runtime meta from trivy run.
        "sonarqube": meta("sonarqube"),  # Version/runtime meta from sonar run.
    }


# ---- per-tool findings -------------------------------------------------------
def _gitleaks_findings(data: Any, job_id: str) -> List[Dict[str, Any]]:  # Normalize gitleaks list.
    out = []  # Accumulated normalized secret findings.
    items = data if isinstance(data, list) else []  # Gitleaks emits a JSON array of leaks.
    for f in items:  # Each raw finding from the scanner.
        rule = f.get("RuleID", "unknown")  # Rule that matched the secret pattern.
        lower = rule.lower()  # Case-insensitive keyword matching for critical tier.
        sev = "critical" if any(k in lower for k in _CRITICAL_SECRET_KEYWORDS) else "high"
        file = _rel(f.get("File", "unknown"), job_id)  # Repo-relative path for UI.
        line = f.get("StartLine")  # Starting line of the secret match.
        # Rebuild from the repo-relative file, NOT gitleaks' own Fingerprint --
        # gitleaks embeds the source path it was handed (/repos/{job_id}/...)
        # into its Fingerprint, and job_id changes every scan, so trusting it
        # yields a different fingerprint each run and smart-delete could never
        # match/resolve the same secret across scans.
        fp = f"{rule}:{file}:{line}"  # Stable fingerprint independent of job_id path.
        out.append({
            "id": fp,  # Unique id for this finding instance.
            "rule_id": rule,  # Original gitleaks rule id.
            "type": "secret",  # Taxonomy type for frontend filters.
            "severity": sev,  # critical or high based on rule keywords.
            "severity_score": SEV_SCORE[sev],  # Numeric score for sorting.
            "message": f"Secret: {rule} in {file}:{line}",  # Human-readable summary line.
            "file": file,  # Repo-relative path.
            "line": line,  # Line number if known.
            "fingerprint": fp,  # Stable key for dedupe across scans.
            "url": None,  # Gitleaks has no external issue URL.
            "details": {"secret_type": rule, "entropy": f.get("Entropy")},  # Extra scanner fields.
        })
    return out  # List of normalized secret findings.


def _trivy_findings(data: Any, job_id: str) -> List[Dict[str, Any]]:  # Normalize Trivy FS scan JSON.
    out = []  # Accumulated vulnerability findings.
    if not isinstance(data, dict):
        return out  # Unexpected shape; nothing to map.
    for res in data.get("Results", []) or []:  # Each target (file/package class) result.
        target = res.get("Target", "unknown")  # File or image target path.
        pkg_type = res.get("Type") or res.get("Class")  # Package ecosystem or result class.
        for v in res.get("Vulnerabilities") or []:  # Individual CVEs under this target.
            if not isinstance(v, dict):
                continue  # Skip malformed vulnerability entries.
            sev = _TRIVY_SEV.get(v.get("Severity", "UNKNOWN"), "low")  # Map to our scale.
            vid = v.get("VulnerabilityID", "unknown")  # e.g. CVE-2024-...
            pkg = v.get("PkgName", "unknown")  # Affected package name.
            title = v.get("Title") or v.get("Description") or "No description"  # Prefer short title.
            file = _rel(target, job_id)  # Repo-relative target path.
            cvss = None  # Best CVSS v3 score if any source provides it.
            for src in (v.get("CVSS") or {}).values():  # Iterate vendor CVSS objects.
                if isinstance(src, dict) and src.get("V3Score"):
                    cvss = src["V3Score"]  # First V3Score wins.
                    break
            out.append({
                "id": f"{vid}:{file}:{pkg}",  # Composite id for this vuln instance.
                "rule_id": vid,  # Vulnerability identifier as rule.
                "type": "vulnerability",  # Taxonomy type for filters.
                "severity": sev,  # Normalized severity string.
                "severity_score": SEV_SCORE[sev],  # Numeric severity for ranking.
                "message": f"{pkg}: {title[:120]}",  # Truncated package + title summary.
                "file": file,  # Path associated with the finding.
                "line": None,  # Trivy FS vulns usually have no source line.
                "fingerprint": f"{vid}:{file}:{pkg}",  # Stable dedupe key.
                "url": v.get("PrimaryURL"),  # Advisory URL if provided.
                "details": {
                    "package_name": pkg,  # Package that is vulnerable.
                    "installed_version": v.get("InstalledVersion"),  # Version found in the tree.
                    "fixed_version": v.get("FixedVersion"),  # Version that remediates, if any.
                    "cvss_score": cvss,  # Optional CVSS number.
                    "pkg_type": pkg_type,  # Ecosystem/class from the Results entry.
                },
            })
    return out  # List of normalized vulnerability findings.


def _sonar_findings(data: Any, job_id: str, project_key: str) -> List[Dict[str, Any]]:  # Normalize Sonar.
    out = []  # Accumulated Sonar issues.
    if not isinstance(data, dict):
        return out  # Bad payload shape.
    # component key -> path map (sonar issues carry "project:path" components)
    comp_paths = {}  # Map component key to filesystem path when provided.
    for c in data.get("components", []) or []:  # Sonar embeds component path metadata.
        if c.get("path"):
            comp_paths[c.get("key")] = c.get("path")  # Prefer explicit path field.
    host = config.SONAR_HOST.rstrip("/")  # Base URL for deep links without trailing slash.
    for i in data.get("issues", []) or []:  # Each Sonar issue object.
        rule = i.get("rule", "unknown")  # Sonar rule key (e.g. python:S1234).
        if rule.startswith("secrets:"):
            continue  # secret detection removed from sonar; gitleaks owns secrets
        sev = _SONAR_SEV.get(i.get("severity", "INFO"), "info")  # Map severity to ours.
        comp = i.get("component", "")  # Component key like project:path.
        path = comp_paths.get(comp)  # Prefer path from components table.
        if not path:
            path = comp.split(":", 1)[1] if ":" in comp else comp  # Fallback: strip project prefix.
        file = _rel(path, job_id)  # Repo-relative file path.
        key = i.get("key", "unknown")  # Sonar issue key used as id/fingerprint.
        stype = i.get("type", "CODE_SMELL")  # Raw Sonar type enum.
        out.append({
            "id": key,  # Sonar issue key as unique id.
            "rule_id": rule,  # Rule that raised the issue.
            "type": _SONAR_TYPE.get(stype, "code_smell"),  # Normalized type string.
            "severity": sev,  # Our severity taxonomy.
            "severity_score": SEV_SCORE[sev],  # Numeric score for UI sort.
            "message": i.get("message", "Sonar issue"),  # Human message from Sonar.
            "file": file,  # Repo-relative path.
            "line": i.get("line"),  # Optional line number.
            "fingerprint": key,  # Stable across re-aggregations.
            "url": (f"{host}/project/issues?open={key}&id={project_key}"  # Deep link when host set.
                    if host else None),
            "details": {
                "sonar_type": stype,  # Original Sonar type enum.
                "effort_minutes": _effort_minutes(i.get("effort") or i.get("debt")),  # Fix effort.
                "tags": i.get("tags", []),  # Sonar tags for filtering.
            },
        })
    return out  # List of normalized Sonar findings.


# ---- summary -----------------------------------------------------------------
def _build_summary(gl, tv, sq) -> Dict[str, Any]:  # Counts for dashboards and CI gates.
    by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}  # Severity counters.
    by_type: Dict[str, int] = {}  # Counts keyed by finding type.
    by_file: Dict[str, int] = {}  # Counts keyed by file path.
    for arr in (gl, tv, sq):  # Walk all three tool finding lists.
        for f in arr:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1  # Increment severity bucket.
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1  # Increment type bucket.
            if f["file"] and f["file"] != "unknown":  # Ignore unknown paths in file stats.
                by_file[f["file"]] = by_file.get(f["file"], 0) + 1  # Findings per file.
    by_sev = {k: v for k, v in by_sev.items() if v or k in ("critical", "high", "medium", "low")}
    return {
        "total_findings": len(gl) + len(tv) + len(sq),  # Grand total across tools.
        "files_affected": len(by_file),  # Distinct files with at least one finding.
        "by_tool": {"gitleaks": len(gl), "trivy": len(tv), "sonarqube": len(sq)},  # Per-tool totals.
        "by_severity": by_sev,  # Severity histogram (info dropped if zero).
        "by_type": by_type,  # Type histogram.
        "by_file": by_file,  # Per-file finding counts.
    }


def aggregate(job_id: str, job: Dict[str, Any],
              results: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:  # Public entrypoint.
    ci = job.get("ci_context", {}) or {}  # GitLab CI bag stored at enqueue time.
    project_key = job.get("project_key", "")  # Needed for Sonar deep links.

    def data_of(tool):  # Pull the raw scanner payload for one tool.
        r = results.get(tool) or {}  # Envelope or empty.
        return r.get("data")  # Inner data field (list/dict per tool).

    gl = _gitleaks_findings(data_of("gitleaks"), job_id)  # Normalize secrets.
    tv = _trivy_findings(data_of("trivy"), job_id)  # Normalize vulnerabilities.
    sq = _sonar_findings(data_of("sonarqube"), job_id, project_key)  # Normalize Sonar issues.

    return {
        "metadata": _build_metadata(job_id, ci),  # Shared run context once.
        "tools": _build_tools(results),  # Tool version/meta block.
        "gitleaks": gl,  # Normalized secret findings list.
        "trivy": tv,  # Normalized vulnerability findings list.
        "sonarqube": sq,  # Normalized Sonar findings list.
        "summary": _build_summary(gl, tv, sq),  # Aggregated counts for consumers.
    }
