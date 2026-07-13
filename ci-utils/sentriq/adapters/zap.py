"""OWASP ZAP baseline scan adapter.

Parses the JSON report produced by `zap-baseline.py -J output.json` into
normalized Finding objects.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseAdapter, register, Finding, DYNAMIC


RISKCODE_TO_SEVERITY = {
    "3": "high",
    "2": "medium",
    "1": "low",
    "0": "info",
}


def _truncate(value: Optional[str], limit: int = 300) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


@register
class ZapAdapter(BaseAdapter):
    NAME = "zap"
    IMAGE = "ghcr.io/zaproxy/zaproxy:stable"
    PIPELINE = DYNAMIC
    OUTPUT_FILE = "output.json"
    MOUNT = "/zap/wrk"  # zap-baseline.py always writes its -J report here

    def command(self, target: str, workdir: str) -> List[str]:
        return ["zap-baseline.py", "-t", target, "-J", self.OUTPUT_FILE, "-I"]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

        if not isinstance(data, dict):
            return []

        findings: List[Finding] = []
        for site in data.get("site", []) or []:
            if not isinstance(site, dict):
                continue

            host = site.get("@host") or site.get("@name") or target
            site_name = site.get("@name") or host

            for alert in site.get("alerts", []) or []:
                if not isinstance(alert, dict):
                    continue

                pluginid = alert.get("pluginid") or alert.get("alertRef") or alert.get("alert") or ""
                message = alert.get("alert") or alert.get("name") or ""

                instances = alert.get("instances", []) or []
                instance_uris: List[str] = []
                first_uri: Optional[str] = None
                if isinstance(instances, list):
                    for i, inst in enumerate(instances):
                        if i >= 10:
                            break
                        if isinstance(inst, dict) and inst.get("uri"):
                            uri = str(inst["uri"])
                            instance_uris.append(uri)
                            if first_uri is None:
                                first_uri = uri

                file_url = first_uri or site_name

                details: Dict[str, Any] = {
                    "cweid": alert.get("cweid") or "",
                    "wascid": alert.get("wascid") or "",
                    "confidence": alert.get("confidence") or "",
                    "solution": _truncate(alert.get("solution")),
                    "description": _truncate(alert.get("desc")),
                    "instances": instance_uris,
                }

                findings.append(
                    Finding(
                        tool="zap",
                        pipeline=DYNAMIC,
                        type="dast",
                        severity=RISKCODE_TO_SEVERITY.get(str(alert.get("riskcode", "")), "low"),
                        rule_id=str(pluginid),
                        message=str(message),
                        file=str(file_url) if file_url else None,
                        line=None,
                        url=None,
                        details=details,
                        fingerprint=f"zap:{pluginid}:{host}",
                    )
                )

        return findings


if __name__ == "__main__":
    sample_report = json.dumps(
        {
            "@version": "2.15.0",
            "site": [
                {
                    "@name": "http://target",
                    "@host": "target",
                    "alerts": [
                        {
                            "pluginid": "40018",
                            "alertRef": "40018",
                            "alert": "SQL Injection",
                            "name": "SQL Injection",
                            "riskcode": "3",
                            "confidence": "2",
                            "riskdesc": "High (Medium)",
                            "desc": "<p>SQL injection may be possible.</p>",
                            "solution": "<p>Use parameterized queries.</p>",
                            "cweid": "89",
                            "wascid": "19",
                            "instances": [
                                {
                                    "uri": "http://target/search?q=1",
                                    "method": "GET",
                                    "param": "q",
                                    "evidence": "syntax error",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    adapter = ZapAdapter()
    results = adapter.parse(sample_report, target="http://target")
    assert len(results) == 1, f"expected exactly 1 finding, got {len(results)}"
    finding = results[0]
    assert finding.type == "dast"
    assert finding.severity == "high"
    assert finding.rule_id == "40018"
    assert "http://target/search?q=1" in finding.details.get("instances", [])
    assert finding.fingerprint == "zap:40018:target"
    print(finding.to_dict())
    print("zap adapter self-test passed")
