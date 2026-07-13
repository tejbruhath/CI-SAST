"""
Unified Findings Schema — THE contract the whole system normalizes to (Task A1).

Every scanner adapter converts its native output into a list of `Finding`
dataclasses. Everything downstream (aggregator, dedup, triage, fix generation,
API, frontend) speaks only this shape, never a tool-native one.

Kept as a plain dataclass (not the Django model) so adapters — including ones
built in isolation/subprocesses — depend on nothing but this file. `Finding.to_dict`
is the serialization boundary; the Django `Finding` model mirrors these fields.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ---- controlled vocabularies -------------------------------------------------
# Severity, normalized across every tool. Ordinal score for sorting/filtering.
SEVERITIES = ("critical", "high", "medium", "low", "info")
SEV_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# Finding type taxonomy. Adapters map their native categories onto these.
TYPES = (
    "secret",          # gitleaks
    "vulnerability",   # trivy (CVE), nuclei (CVE templates)
    "sast",            # semgrep static code finding
    "dast",            # zap / nuclei dynamic web finding
    "misconfiguration",
    "code_smell",
    "bug",
)

# Which pipeline a finding belongs to (mirrors the Sentriq CI/CD split).
STATIC = "static"    # SAST + SCA, runs on source
DYNAMIC = "dynamic"  # DAST, runs on a deployed target
PIPELINES = (STATIC, DYNAMIC)


def normalize_severity(raw: Optional[str], default: str = "low") -> str:
    """Best-effort map any tool's severity string onto SEVERITIES."""
    if not raw:
        return default
    s = str(raw).strip().lower()
    aliases = {
        "blocker": "critical", "crit": "critical",
        "error": "high", "warning": "medium", "warn": "medium",
        "moderate": "medium", "note": "low", "unknown": "low",
        "informational": "info", "information": "info", "none": "info",
    }
    if s in SEVERITIES:
        return s
    return aliases.get(s, default)


@dataclass
class Finding:
    """One normalized security finding."""
    tool: str                       # "gitleaks" | "semgrep" | "trivy" | "zap" | "nuclei"
    pipeline: str                   # STATIC | DYNAMIC
    type: str                       # one of TYPES
    severity: str                   # one of SEVERITIES
    rule_id: str                    # tool-native rule/CVE id
    message: str                    # human-readable one-liner
    file: Optional[str] = None      # repo-relative path (static) or URL (dynamic)
    line: Optional[int] = None
    url: Optional[str] = None       # deep link to the tool's own UI / advisory
    # Free-form per-tool extras (cvss, package, fixed_version, entropy, cwe...).
    details: Dict[str, Any] = field(default_factory=dict)
    # Stable cross-scan identity. Auto-derived if not supplied by the adapter.
    fingerprint: Optional[str] = None

    def __post_init__(self):
        self.severity = normalize_severity(self.severity)
        if self.fingerprint is None:
            self.fingerprint = self.compute_fingerprint()

    @property
    def severity_score(self) -> int:
        return SEV_SCORE.get(self.severity, 0)

    def compute_fingerprint(self) -> str:
        """Deterministic identity: tool + rule + location.

        Deliberately excludes any scan-time path prefix (e.g. /repos/{job}/) so
        the same issue matches across scans — the property that makes dedup and
        cross-scan resolution work. Adapters that already have a stable native
        fingerprint should pass it explicitly instead.
        """
        basis = f"{self.tool}:{self.rule_id}:{self.file or ''}:{self.line or ''}"
        return hashlib.sha1(basis.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity_score"] = self.severity_score
        return d


def validate(f: Finding) -> None:
    """Raise ValueError if a Finding violates the contract. Cheap guard adapters
    (and delegated code) can call so a bad mapping fails loud, not silently."""
    if f.tool not in ("gitleaks", "semgrep", "trivy", "zap", "nuclei"):
        raise ValueError(f"unknown tool: {f.tool!r}")
    if f.pipeline not in PIPELINES:
        raise ValueError(f"bad pipeline: {f.pipeline!r}")
    if f.type not in TYPES:
        raise ValueError(f"bad type: {f.type!r}")
    if f.severity not in SEVERITIES:
        raise ValueError(f"bad severity: {f.severity!r}")
    if not f.rule_id:
        raise ValueError("rule_id required")


def summarize(findings: List[Finding]) -> Dict[str, Any]:
    """ASPM-style rollup over a list of findings."""
    by_sev = {s: 0 for s in SEVERITIES}
    by_tool: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    files = set()
    for f in findings:
        by_sev[f.severity] += 1
        by_tool[f.tool] = by_tool.get(f.tool, 0) + 1
        by_type[f.type] = by_type.get(f.type, 0) + 1
        if f.file:
            files.add(f.file)
    return {
        "total": len(findings),
        "files_affected": len(files),
        "by_severity": by_sev,
        "by_tool": by_tool,
        "by_type": by_type,
    }


if __name__ == "__main__":
    # Self-check: fingerprint stability + validation + summary.
    a = Finding(tool="gitleaks", pipeline=STATIC, type="secret", severity="high",
                rule_id="aws-key", message="AWS key", file="app/s.py", line=3)
    b = Finding(tool="gitleaks", pipeline=STATIC, type="secret", severity="high",
                rule_id="aws-key", message="AWS key", file="app/s.py", line=3)
    assert a.fingerprint == b.fingerprint, "same location must fingerprint equal"
    c = Finding(tool="gitleaks", pipeline=STATIC, type="secret", severity="high",
                rule_id="aws-key", message="AWS key", file="app/s.py", line=99)
    assert a.fingerprint != c.fingerprint, "different line must differ"
    assert a.severity_score == 3
    validate(a)
    try:
        validate(Finding(tool="bogus", pipeline=STATIC, type="secret",
                         severity="high", rule_id="x", message="m"))
        raise AssertionError("should have rejected bad tool")
    except ValueError:
        pass
    s = summarize([a, c])
    assert s["total"] == 2 and s["by_severity"]["high"] == 2
    print("schema self-check passed:", s)
