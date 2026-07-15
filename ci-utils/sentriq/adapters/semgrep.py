"""Semgrep SAST scanner adapter."""
from __future__ import annotations  # allow postponed evaluation of annotations

import json  # parse Semgrep's JSON report
from typing import Any, Dict, List, Optional  # flexible types for nested JSON

from .base import BaseAdapter, register, Finding, STATIC  # adapter base + Finding


@register  # register under NAME when this module is imported
class SemgrepAdapter(BaseAdapter):
    NAME = "semgrep"  # tool identifier in findings and UI
    IMAGE = "semgrep/semgrep:latest"  # official Semgrep container image
    PIPELINE = STATIC  # source code analysis, not live DAST
    OUTPUT_FILE = "output.json"  # report path relative to workdir

    def command(self, target: str, workdir: str) -> List[str]:
        return [
            "semgrep",  # entrypoint binary inside the image
            "scan",  # run a scan (not other subcommands)
            "--config",
            "auto",  # Semgrep picks relevant rule packs
            "--json",  # structured output mode
            "--output",
            f"{workdir}/{self.OUTPUT_FILE}",  # write report under mount
            workdir,  # scan the mounted repo tree
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output)  # full report object
        except Exception:
            return []  # any parse failure -> empty list

        if not isinstance(data, dict):
            return []  # Semgrep always emits an object at top level

        results = data.get("results", [])  # list of match objects
        if not isinstance(results, list):
            return []  # non-list results block is unexpected; bail

        findings: List[Finding] = []
        for result in results:  # iterate each raw result object
            finding = self._parse_result(result)  # normalize one match
            if finding is not None:
                findings.append(finding)  # drop invalid entries
        return findings  # fully normalized list

    def _parse_result(self, result: Any) -> Optional[Finding]:
        if not isinstance(result, dict):
            return None  # skip non-objects

        check_id = result.get("check_id")  # Semgrep rule id
        if not check_id:
            return None  # cannot fingerprint without a rule

        path = result.get("path", "")  # absolute path inside container
        rel_path = self._strip_work_prefix(path)  # repo-relative for display

        start = result.get("start") or {}  # start position object
        line = start.get("line") if isinstance(start, dict) else None

        extra = result.get("extra") or {}  # message, severity, metadata
        metadata = extra.get("metadata") or {} if isinstance(extra, dict) else {}

        severity = self._map_severity(extra.get("severity") if isinstance(extra, dict) else None)
        message = self._truncate(extra.get("message", "") if isinstance(extra, dict) else "", 200)
        references = metadata.get("references") if isinstance(metadata, dict) else None
        url = references[0] if isinstance(references, list) and references else None

        details: Dict[str, Any] = {
            "cwe": metadata.get("cwe") if isinstance(metadata, dict) else None,
            "owasp": metadata.get("owasp") if isinstance(metadata, dict) else None,
            "category": metadata.get("category") if isinstance(metadata, dict) else None,
            "code": self._truncate(extra.get("lines", "") if isinstance(extra, dict) else "", 200),
        }  # keep classification + code snippet for triage

        fingerprint = f"semgrep:{check_id}:{rel_path}:{line}"  # stable dedup key

        return Finding(
            tool="semgrep",
            pipeline=STATIC,
            type="sast",  # static application security testing
            severity=severity,
            rule_id=check_id,
            message=message,
            file=rel_path,
            line=line,
            url=url,
            details=details,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _strip_work_prefix(path: Any) -> str:
        if not isinstance(path, str):
            return ""  # non-string path is unusable
        prefix = "/work/"  # container mount prefix
        if path.startswith(prefix):
            return path[len(prefix):]  # repo-relative remainder
        return path  # already relative or different layout

    @staticmethod
    def _map_severity(raw: Any) -> str:
        if not isinstance(raw, str):
            return "low"  # default when severity missing
        mapping = {
            "ERROR": "high",  # Semgrep ERROR ~ high risk
            "WARNING": "medium",  # Semgrep WARNING ~ medium risk
            "INFO": "low",  # Semgrep INFO ~ low risk
        }
        return mapping.get(raw, "low")  # unknown labels fall to low

    @staticmethod
    def _truncate(value: Any, max_len: int) -> str:
        if not isinstance(value, str):
            return ""  # non-string values become empty
        if len(value) <= max_len:
            return value  # fits as-is
        return value[:max_len]  # hard cut; messages stay bounded


if __name__ == "__main__":  # developer self-test
    sample = json.dumps({
        "results": [
            {
                "check_id": "python.django.security.injection.sql.sql-injection",
                "path": "/work/app/views.py",
                "start": {"line": 42, "col": 5},
                "end": {"line": 42, "col": 60},
                "extra": {
                    "message": "User input flows into a raw SQL query.",
                    "severity": "ERROR",
                    "metadata": {
                        "cwe": ["CWE-89: SQL Injection"],
                        "owasp": ["A03:2021 - Injection"],
                        "references": ["https://semgrep.dev/r/python.django.security.injection.sql.sql-injection"],
                        "category": "security",
                    },
                    "lines": "cursor.execute(...)",
                },
            }
        ],
        "errors": [],
    })  # minimal Semgrep-shaped JSON

    adapter = SemgrepAdapter()
    findings = adapter.parse(sample, "/work")
    assert len(findings) == 1, f"expected 1 finding, got {len(findings)}"

    finding = findings[0]
    assert finding.type == "sast", f"expected type 'sast', got {finding.type!r}"
    assert finding.severity == "high", f"expected severity 'high', got {finding.severity!r}"
    assert finding.file == "app/views.py", f"expected file 'app/views.py', got {finding.file!r}"
    assert finding.rule_id == "python.django.security.injection.sql.sql-injection"
    assert finding.line == 42
    assert finding.fingerprint == "semgrep:python.django.security.injection.sql.sql-injection:app/views.py:42"

    print("semgrep adapter self-test passed:", finding.to_dict())
