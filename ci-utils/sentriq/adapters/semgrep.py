"""Semgrep SAST scanner adapter."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseAdapter, register, Finding, STATIC


@register
class SemgrepAdapter(BaseAdapter):
    NAME = "semgrep"
    IMAGE = "semgrep/semgrep:latest"
    PIPELINE = STATIC
    OUTPUT_FILE = "output.json"

    def command(self, target: str, workdir: str) -> List[str]:
        return [
            "semgrep",
            "scan",
            "--config",
            "auto",
            "--json",
            "--output",
            f"{workdir}/{self.OUTPUT_FILE}",
            workdir,
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output)
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        results = data.get("results", [])
        if not isinstance(results, list):
            return []

        findings: List[Finding] = []
        for result in results:
            finding = self._parse_result(result)
            if finding is not None:
                findings.append(finding)
        return findings

    def _parse_result(self, result: Any) -> Optional[Finding]:
        if not isinstance(result, dict):
            return None

        check_id = result.get("check_id")
        if not check_id:
            return None

        path = result.get("path", "")
        rel_path = self._strip_work_prefix(path)

        start = result.get("start") or {}
        line = start.get("line") if isinstance(start, dict) else None

        extra = result.get("extra") or {}
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
        }

        fingerprint = f"semgrep:{check_id}:{rel_path}:{line}"

        return Finding(
            tool="semgrep",
            pipeline=STATIC,
            type="sast",
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
            return ""
        prefix = "/work/"
        if path.startswith(prefix):
            return path[len(prefix):]
        return path

    @staticmethod
    def _map_severity(raw: Any) -> str:
        if not isinstance(raw, str):
            return "low"
        mapping = {
            "ERROR": "high",
            "WARNING": "medium",
            "INFO": "low",
        }
        return mapping.get(raw, "low")

    @staticmethod
    def _truncate(value: Any, max_len: int) -> str:
        if not isinstance(value, str):
            return ""
        if len(value) <= max_len:
            return value
        return value[:max_len]


if __name__ == "__main__":
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
    })

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
