"""OWASP ZAP baseline scan adapter.

Parses the JSON report produced by `zap-baseline.py -J output.json` into
normalized Finding objects.
"""
from __future__ import annotations  # postpone annotation evaluation

import json  # parse ZAP JSON report
from typing import Any, Dict, List, Optional  # typing for nested report fields

from .base import BaseAdapter, register, Finding, DYNAMIC  # DAST adapter base


RISKCODE_TO_SEVERITY = {
    "3": "high",  # ZAP riskcode 3 = High
    "2": "medium",
    "1": "low",
    "0": "info",
}  # map ZAP numeric risk codes to our labels


def _truncate(value: Optional[str], limit: int = 300) -> str:
    if not value:
        return ""  # missing text becomes empty string
    text = str(value)  # ensure string type for len check
    if len(text) <= limit:
        return text  # already short enough
    return text[:limit].rsplit(" ", 1)[0] + "…"  # cut on word boundary + ellipsis


@register  # register zap in REGISTRY on import
class ZapAdapter(BaseAdapter):
    NAME = "zap"  # tool name on findings
    IMAGE = "ghcr.io/zaproxy/zaproxy:stable"  # official ZAP stable image
    PIPELINE = DYNAMIC  # scans a live web target
    OUTPUT_FILE = "output.json"  # baseline -J report name
    MOUNT = "/zap/wrk"  # zap-baseline.py always writes its -J report here

    def command(self, target: str, workdir: str) -> List[str]:
        return ["zap-baseline.py", "-t", target, "-J", self.OUTPUT_FILE, "-I"]
        # TODO: longer note about -I: do not fail container exit on alerts found

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output)  # full ZAP report object
        except (json.JSONDecodeError, TypeError, ValueError):
            return []  # unreadable report -> no findings

        if not isinstance(data, dict):
            return []

        findings: List[Finding] = []
        for site in data.get("site", []) or []:  # multi-site reports possible
            if not isinstance(site, dict):
                continue  # skip non-object site entries

            host = site.get("@host") or site.get("@name") or target  # identity key
            site_name = site.get("@name") or host  # display fallback

            for alert in site.get("alerts", []) or []:  # each vulnerability alert
                if not isinstance(alert, dict):
                    continue  # skip malformed alert entries

                pluginid = alert.get("pluginid") or alert.get("alertRef") or alert.get("alert") or ""
                message = alert.get("alert") or alert.get("name") or ""  # alert title

                instances = alert.get("instances", []) or []  # affected request URIs
                instance_uris: List[str] = []  # collect up to 10 URIs for details
                first_uri: Optional[str] = None  # first match location for file field
                if isinstance(instances, list):  # guard against non-list instances
                    for i, inst in enumerate(instances):
                        if i >= 10:
                            break  # cap stored instances for payload size
                        if isinstance(inst, dict) and inst.get("uri"):
                            uri = str(inst["uri"])  # ensure string type
                            instance_uris.append(uri)  # accumulate for details field
                            if first_uri is None:
                                first_uri = uri  # primary location for file field

                file_url = first_uri or site_name  # prefer concrete request URI

                details: Dict[str, Any] = {
                    "cweid": alert.get("cweid") or "",
                    "wascid": alert.get("wascid") or "",
                    "confidence": alert.get("confidence") or "",
                    "solution": _truncate(alert.get("solution")),  # remediation text
                    "description": _truncate(alert.get("desc")),
                    "instances": instance_uris,  # sample of hit URLs
                }

                findings.append(
                    Finding(
                        tool="zap",
                        pipeline=DYNAMIC,
                        type="dast",  # dynamic application security testing
                        severity=RISKCODE_TO_SEVERITY.get(str(alert.get("riskcode", "")), "low"),
                        rule_id=str(pluginid),  # ZAP plugin / rule id
                        message=str(message),
                        file=str(file_url) if file_url else None,  # URL as location
                        line=None,  # no source line for DAST
                        url=None,  # extra URL not used; location is in file
                        details=details,
                        fingerprint=f"zap:{pluginid}:{host}",  # host-level dedup
                    )
                )

        return findings


if __name__ == "__main__":  # parser self-test
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
    )  # minimal ZAP-shaped report

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
