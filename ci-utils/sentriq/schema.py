"""
Unified Findings Schema — THE contract the whole system normalizes to (Task A1).

Every scanner adapter converts its native output into a list of `Finding`
dataclasses. Everything downstream (aggregator, dedup, triage, fix generation,
API, frontend) speaks only this shape, never a tool-native one.

Kept as a plain dataclass (not the Django model) so adapters — including ones
built in isolation/subprocesses — depend on nothing but this file. `Finding.to_dict`
is the serialization boundary; the Django `Finding` model mirrors these fields.
"""
from __future__ import annotations  # allow forward type refs without quotes

import hashlib  # SHA1 for stable finding fingerprints
from dataclasses import dataclass, field, asdict  # lightweight Finding value object
from typing import Any, Dict, List, Optional  # type hints for schema helpers

# ---- controlled vocabularies -------------------------------------------------
# Severity, normalized across every tool. Ordinal score for sorting/filtering.
SEVERITIES = ("critical", "high", "medium", "low", "info")  # allowed severity strings
SEV_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}  # sort weight

# Finding type taxonomy. Adapters map their native categories onto these.
TYPES = (
    "secret",          # leaked credential (gitleaks)
    "vulnerability",   # CVE-style issue (trivy / nuclei)
    "sast",            # static code analysis hit (semgrep)
    "dast",            # dynamic web finding (zap / nuclei)
    "misconfiguration",  # insecure config / cloud posture
    "code_smell",      # quality issue that may not be a vuln
    "bug",             # correctness bug surfaced by a scanner
)

# Which pipeline a finding belongs to (mirrors the Sentriq CI/CD split).
STATIC = "static"    # SAST + SCA, runs on source checkout
DYNAMIC = "dynamic"  # DAST, runs against a live URL
PIPELINES = (STATIC, DYNAMIC)  # allowed pipeline values for validation


def normalize_severity(raw: Optional[str], default: str = "low") -> str:
    """Best-effort map any tool's severity string onto SEVERITIES."""
    if not raw:  # missing severity → use safe default
        return default
    s = str(raw).strip().lower()  # normalize casing/whitespace from tools
    aliases = {  # map common tool-specific labels onto our vocab
        "blocker": "critical", "crit": "critical",
        "error": "high", "warning": "medium", "warn": "medium",
        "moderate": "medium", "note": "low", "unknown": "low",
        "informational": "info", "information": "info", "none": "info",
    }
    if s in SEVERITIES:  # already one of our canonical values
        return s
    return aliases.get(s, default)  # alias hit or fall back to default


@dataclass
class Finding:
    """One normalized security finding."""
    tool: str                       # scanner name, e.g. gitleaks
    pipeline: str                   # STATIC or DYNAMIC pipeline tag
    type: str                       # one of TYPES taxonomy values
    severity: str                   # one of SEVERITIES
    rule_id: str                    # tool-native rule or CVE identifier
    message: str                    # short human-readable description
    file: Optional[str] = None      # repo path (static) or URL path (dynamic)
    line: Optional[int] = None      # 1-based source line when known
    url: Optional[str] = None       # link to advisory or tool UI
    # Free-form per-tool extras (cvss, package, fixed_version, entropy, cwe...).
    details: Dict[str, Any] = field(default_factory=dict)  # tool-specific extras bag
    # Stable cross-scan identity. Auto-derived if not supplied by the adapter.
    fingerprint: Optional[str] = None  # dedup key across scans

    def __post_init__(self):
        self.severity = normalize_severity(self.severity)  # coerce tool labels
        if self.fingerprint is None:  # adapter did not supply a native fingerprint
            self.fingerprint = self.compute_fingerprint()  # derive stable hash id

    @property
    def severity_score(self) -> int:
        return SEV_SCORE.get(self.severity, 0)  # numeric rank for sort/filter

    def compute_fingerprint(self) -> str:
        """Deterministic identity: tool + rule + location.

        Deliberately excludes any scan-time path prefix (e.g. /repos/{job}/) so
        the same issue matches across scans — the property that makes dedup and
        cross-scan resolution work. Adapters that already have a stable native
        fingerprint should pass it explicitly instead.
        """
        # TODO: path prefixes are stripped by adapters before file is set here.
        basis = f"{self.tool}:{self.rule_id}:{self.file or ''}:{self.line or ''}"  # identity inputs
        return hashlib.sha1(basis.encode()).hexdigest()[:16]  # short stable hex id

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)  # dataclass → plain dict for JSON/DB handoff
        d["severity_score"] = self.severity_score  # include computed sort weight
        return d


def validate(f: Finding) -> None:
    """Raise ValueError if a Finding violates the contract. Cheap guard adapters
    (and delegated code) can call so a bad mapping fails loud, not silently."""
    if f.tool not in ("gitleaks", "semgrep", "trivy", "zap", "nuclei"):  # known scanners only
        raise ValueError(f"unknown tool: {f.tool!r}")
    if f.pipeline not in PIPELINES:  # must be static or dynamic
        raise ValueError(f"bad pipeline: {f.pipeline!r}")
    if f.type not in TYPES:  # must use taxonomy type
        raise ValueError(f"bad type: {f.type!r}")
    if f.severity not in SEVERITIES:  # must use severity vocab
        raise ValueError(f"bad severity: {f.severity!r}")
    if not f.rule_id:  # every finding needs a rule/CVE id
        raise ValueError("rule_id required")


def summarize(findings: List[Finding]) -> Dict[str, Any]:
    """ASPM-style rollup over a list of findings."""
    by_sev = {s: 0 for s in SEVERITIES}  # counts per severity bucket
    by_tool: Dict[str, int] = {}  # counts per scanner tool
    by_type: Dict[str, int] = {}  # counts per finding type
    files = set()  # unique file paths touched
    for f in findings:  # single pass over all findings
        by_sev[f.severity] += 1  # bump severity histogram
        by_tool[f.tool] = by_tool.get(f.tool, 0) + 1  # bump tool histogram
        by_type[f.type] = by_type.get(f.type, 0) + 1  # bump type histogram
        if f.file:  # only count when location is known
            files.add(f.file)  # unique files for impact surface
    return {
        "total": len(findings),  # overall finding count
        "files_affected": len(files),  # how many distinct files hit
        "by_severity": by_sev,  # severity breakdown for UI charts
        "by_tool": by_tool,  # tool breakdown for UI charts
        "by_type": by_type,  # type breakdown for UI charts
    }


if __name__ == "__main__":
    # Self-check: fingerprint stability + validation + summary.
    a = Finding(tool="gitleaks", pipeline=STATIC, type="secret", severity="high",
                rule_id="aws-key", message="AWS key", file="app/s.py", line=3)  # sample finding A
    b = Finding(tool="gitleaks", pipeline=STATIC, type="secret", severity="high",
                rule_id="aws-key", message="AWS key", file="app/s.py", line=3)  # same location as A
    assert a.fingerprint == b.fingerprint, "same location must fingerprint equal"  # dedup stability
    c = Finding(tool="gitleaks", pipeline=STATIC, type="secret", severity="high",
                rule_id="aws-key", message="AWS key", file="app/s.py", line=99)  # different line
    assert a.fingerprint != c.fingerprint, "different line must differ"  # location matters
    assert a.severity_score == 3  # high → score 3
    validate(a)  # valid finding must pass
    try:
        validate(Finding(tool="bogus", pipeline=STATIC, type="secret",
                         severity="high", rule_id="x", message="m"))  # unknown tool
        raise AssertionError("should have rejected bad tool")  # must not reach here
    except ValueError:
        pass  # expected rejection of invalid tool
    s = summarize([a, c])  # rollup over two findings
    assert s["total"] == 2 and s["by_severity"]["high"] == 2  # counts must match
    print("schema self-check passed:", s)  # manual `python schema.py` smoke test
