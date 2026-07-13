"""trivy adapter — dependency/CVE scanning (SCA/static). Parser ported from the
proven ci-utils aggregator; extracts CVSS, package + fixed-version metadata."""
from __future__ import annotations

import json
from typing import List

from .base import BaseAdapter, register, Finding, STATIC

WORKDIR = "/work"

_TRIVY_SEV = {
    "CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium",
    "LOW": "low", "UNKNOWN": "low",
}


def _rel(path: str) -> str:
    if not path:
        return "unknown"
    p = path
    if p.startswith(WORKDIR + "/"):
        p = p[len(WORKDIR) + 1:]
    return p.lstrip("/") or "unknown"


@register
class TrivyAdapter(BaseAdapter):
    NAME = "trivy"
    IMAGE = "aquasec/trivy:latest"
    PIPELINE = STATIC
    OUTPUT_FILE = "output.json"

    def command(self, target: str, workdir: str) -> List[str]:
        # vuln only — gitleaks owns secrets; keeps trivy fast (time-to-findings).
        return [
            "filesystem", "--scanners", "vuln",
            "--format", "json",
            "--output", f"{workdir}/{self.OUTPUT_FILE}",
            workdir,
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output) if raw_output.strip() else {}
        except json.JSONDecodeError:
            return []
        if not isinstance(data, dict):
            return []
        out: List[Finding] = []
        for res in data.get("Results", []) or []:
            file = _rel(res.get("Target", "unknown"))
            pkg_type = res.get("Type") or res.get("Class")
            for v in res.get("Vulnerabilities") or []:
                if not isinstance(v, dict):
                    continue
                vid = v.get("VulnerabilityID", "unknown")
                pkg = v.get("PkgName", "unknown")
                title = v.get("Title") or v.get("Description") or "No description"
                cvss = None
                for src in (v.get("CVSS") or {}).values():
                    if isinstance(src, dict) and src.get("V3Score"):
                        cvss = src["V3Score"]
                        break
                out.append(Finding(
                    tool=self.NAME, pipeline=STATIC, type="vulnerability",
                    severity=_TRIVY_SEV.get(v.get("Severity", "UNKNOWN"), "low"),
                    rule_id=vid,
                    message=f"{pkg}: {title[:120]}",
                    file=file, line=None, url=v.get("PrimaryURL"),
                    details={
                        "package_name": pkg,
                        "installed_version": v.get("InstalledVersion"),
                        "fixed_version": v.get("FixedVersion"),
                        "cvss_score": cvss,
                        "pkg_type": pkg_type,
                        "cwe": v.get("CweIDs", []),
                    },
                    fingerprint=f"trivy:{vid}:{file}:{pkg}",
                ))
        return out


if __name__ == "__main__":
    import json as _j
    raw = _j.dumps({"Results": [{
        "Target": "/work/requirements.txt", "Type": "pip",
        "Vulnerabilities": [{
            "VulnerabilityID": "CVE-2024-1234", "PkgName": "django",
            "Severity": "HIGH", "Title": "SQL injection",
            "PrimaryURL": "https://x", "InstalledVersion": "4.2.0",
            "FixedVersion": "4.2.16", "CVSS": {"nvd": {"V3Score": 7.5}}}]}]})
    fs = TrivyAdapter().parse(raw, "")
    assert len(fs) == 1 and fs[0].severity == "high"
    assert fs[0].file == "requirements.txt"
    assert fs[0].details["fixed_version"] == "4.2.16"
    assert fs[0].details["cvss_score"] == 7.5
    assert TrivyAdapter().parse("not json", "") == []
    print("trivy adapter self-test passed:", fs[0].to_dict())
