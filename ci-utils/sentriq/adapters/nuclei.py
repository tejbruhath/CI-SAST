from .base import BaseAdapter, register, Finding, DYNAMIC

import json
from typing import Any, Dict, List, Optional


@register
class NucleiAdapter(BaseAdapter):
    NAME = "nuclei"
    IMAGE = "projectdiscovery/nuclei:latest"
    PIPELINE = DYNAMIC
    OUTPUT_FILE = "output.jsonl"

    def command(self, target: str, workdir: str) -> List[str]:
        return [
            "-u", target,
            "-jsonl",
            "-o", f"{workdir}/{self.OUTPUT_FILE}",
            "-silent",
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        findings: List[Finding] = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            info = obj.get("info") or {}
            classification = info.get("classification") or {}

            template_id = obj.get("template-id", "")
            host = obj.get("host")
            matched_at = obj.get("matched-at")

            cve_ids = classification.get("cve-id") or []
            finding_type = "vulnerability" if cve_ids else "dast"

            references = info.get("reference")
            if isinstance(references, list) and references:
                url: Optional[str] = references[0]
            else:
                url = None

            details: Dict[str, Any] = {
                "tags": info.get("tags") or [],
                "cve": cve_ids,
                "cwe": classification.get("cwe-id") or [],
                "cvss_score": classification.get("cvss-score"),
                "matcher": obj.get("matcher-name"),
                "host": host,
            }

            findings.append(
                Finding(
                    tool="nuclei",
                    pipeline=DYNAMIC,
                    type=finding_type,
                    severity=info.get("severity"),
                    rule_id=template_id,
                    message=info.get("name") or template_id,
                    file=matched_at or host,
                    line=None,
                    url=url,
                    details=details,
                    fingerprint=f"nuclei:{template_id}:{matched_at}",
                )
            )

        return findings


if __name__ == "__main__":
    from ..schema import validate

    sample = """
{"template-id":"CVE-2021-44228","type":"http","host":"http://target","matched-at":"http://target/api/login","info":{"name":"Log4j RCE","severity":"critical","tags":["cve","rce","log4j"],"classification":{"cve-id":["CVE-2021-44228"],"cwe-id":["CWE-502"],"cvss-score":10.0},"reference":["https://example.com/cve-2021-44228"]},"matcher-name":"jndi"}

this is not json
{"template-id":"exposed-panel","type":"http","host":"http://target","matched-at":"http://target/admin","info":{"name":"Exposed Admin Panel","severity":"high","tags":["panel","config"],"classification":{"cwe-id":["CWE-200"]},"reference":["https://example.com/exposed-panel"]},"matcher-name":"word"}
"""

    adapter = NucleiAdapter()
    findings = adapter.parse(sample, "http://target")

    assert len(findings) == 2, f"expected 2 findings, got {len(findings)}"

    cve_finding = findings[0]
    assert cve_finding.type == "vulnerability"
    assert cve_finding.severity == "critical"
    assert cve_finding.file == "http://target/api/login"
    assert cve_finding.fingerprint == "nuclei:CVE-2021-44228:http://target/api/login"

    dast_finding = findings[1]
    assert dast_finding.type == "dast"
    assert dast_finding.file == "http://target/admin"
    assert dast_finding.fingerprint == "nuclei:exposed-panel:http://target/admin"

    for f in findings:
        validate(f)

    print("nuclei adapter self-test passed")
    for f in findings:
        print(f)
