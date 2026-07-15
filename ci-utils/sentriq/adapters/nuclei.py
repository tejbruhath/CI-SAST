from .base import BaseAdapter, register, Finding, DYNAMIC  # dynamic pipeline adapter base

import json  # parse JSONL lines from nuclei output
from typing import Any, Dict, List, Optional  # typed intermediate structures


@register  # auto-register when adapters package is imported
class NucleiAdapter(BaseAdapter):
    NAME = "nuclei"  # tool id for findings and selection
    IMAGE = "projectdiscovery/nuclei:latest"  # ProjectDiscovery official image
    PIPELINE = DYNAMIC  # hits a live URL with templates
    OUTPUT_FILE = "output.jsonl"  # one JSON object per line

    def command(self, target: str, workdir: str) -> List[str]:
        return [
            "-u", target,  # URL under test
            "-jsonl",  # JSON lines output format
            "-o", f"{workdir}/{self.OUTPUT_FILE}",  # report path inside mount
            "-silent",  # suppress progress noise in logs
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        findings: List[Finding] = []  # collect all valid lines
        for line in raw_output.splitlines():  # iterate newline-separated JSONL events
            line = line.strip()  # remove surrounding whitespace
            if not line:
                continue  # skip blank lines between events
            try:
                obj = json.loads(line)  # each line is one match event
            except json.JSONDecodeError:
                continue  # ignore garbage lines in the stream

            info = obj.get("info") or {}  # template metadata block
            classification = info.get("classification") or {}  # CVE/CWE/CVSS

            template_id = obj.get("template-id", "")  # which template fired
            host = obj.get("host")  # scanned host
            matched_at = obj.get("matched-at")  # exact URL that matched

            cve_ids = classification.get("cve-id") or []  # may be list or empty
            finding_type = "vulnerability" if cve_ids else "dast"  # CVE vs generic

            references = info.get("reference")  # advisory links from template
            if isinstance(references, list) and references:
                url: Optional[str] = references[0]  # first advisory link
            else:
                url = None  # no reference available

            details: Dict[str, Any] = {
                "tags": info.get("tags") or [],
                "cve": cve_ids,
                "cwe": classification.get("cwe-id") or [],
                "cvss_score": classification.get("cvss-score"),
                "matcher": obj.get("matcher-name"),  # which matcher condition hit
                "host": host,
            }

            findings.append(
                Finding(
                    tool="nuclei",
                    pipeline=DYNAMIC,
                    type=finding_type,
                    severity=info.get("severity"),  # nuclei's own severity string
                    rule_id=template_id,
                    message=info.get("name") or template_id,  # human template name
                    file=matched_at or host,  # store URL in file field for DAST
                    line=None,  # no source line for remote checks
                    url=url,
                    details=details,
                    fingerprint=f"nuclei:{template_id}:{matched_at}",  # dedup key
                )
            )

        return findings


if __name__ == "__main__":  # self-test harness
    from ..schema import validate  # ensure Finding schema compliance

    sample = """
{"template-id":"CVE-2021-44228","type":"http","host":"http://target","matched-at":"http://target/api/login","info":{"name":"Log4j RCE","severity":"critical","tags":["cve","rce","log4j"],"classification":{"cve-id":["CVE-2021-44228"],"cwe-id":["CWE-502"],"cvss-score":10.0},"reference":["https://example.com/cve-2021-44228"]},"matcher-name":"jndi"}

this is not json
{"template-id":"exposed-panel","type":"http","host":"http://target","matched-at":"http://target/admin","info":{"name":"Exposed Admin Panel","severity":"high","tags":["panel","config"],"classification":{"cwe-id":["CWE-200"]},"reference":["https://example.com/exposed-panel"]},"matcher-name":"word"}
"""  # mixed valid + invalid JSONL

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
        validate(f)  # schema validation for each finding

    print("nuclei adapter self-test passed")
    for f in findings:
        print(f)
