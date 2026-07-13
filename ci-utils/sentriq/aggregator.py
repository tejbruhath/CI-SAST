"""
Aggregation + cross-pipeline deduplication (Tasks B2 + B3).

Merges every tool's Findings for a scan into one deduplicated list. Dedup is
fingerprint-keyed, with a secondary semantic key (type + file + line) so the
same issue reported by two tools (e.g. semgrep + zap both flagging one SQLi)
collapses to a single finding that records every tool that saw it.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .schema import Finding


def _semantic_key(f: Finding) -> Tuple:
    """A location-based identity independent of which tool reported it.
    Falls back to the tool-specific fingerprint when there's no usable location
    (so unrelated findings never collapse together)."""
    if f.file and f.line is not None:
        return ("loc", f.type, f.file, f.line)
    if f.file and f.type in ("vulnerability", "secret"):
        # SCA/secret findings often have no line; rule+file is enough.
        return ("rulefile", f.type, f.rule_id, f.file)
    return ("fp", f.fingerprint)


def deduplicate(findings: List[Finding]) -> List[Finding]:
    """Collapse duplicates, keeping the highest-severity representative and
    annotating it with all contributing tools."""
    best: Dict[Tuple, Finding] = {}
    seen_tools: Dict[Tuple, set] = {}
    for f in findings:
        key = _semantic_key(f)
        seen_tools.setdefault(key, set()).add(f.tool)
        cur = best.get(key)
        if cur is None or f.severity_score > cur.severity_score:
            best[key] = f
    out = []
    for key, f in best.items():
        tools = sorted(seen_tools[key])
        if len(tools) > 1:
            f.details = {**f.details, "also_reported_by": tools}
        out.append(f)
    # stable, worst-first ordering for the UI
    out.sort(key=lambda x: (-x.severity_score, x.tool, x.file or ""))
    return out


if __name__ == "__main__":
    from .schema import STATIC, DYNAMIC
    a = Finding(tool="semgrep", pipeline=STATIC, type="sast", severity="high",
                rule_id="sql", message="sqli", file="a.py", line=5)
    b = Finding(tool="zap", pipeline=DYNAMIC, type="sast", severity="critical",
                rule_id="40018", message="sqli", file="a.py", line=5)
    c = Finding(tool="trivy", pipeline=STATIC, type="vulnerability",
                severity="medium", rule_id="CVE-1", message="cve", file="r.txt")
    out = deduplicate([a, b, c])
    assert len(out) == 2, [x.to_dict() for x in out]
    top = out[0]
    assert top.severity == "critical" and "also_reported_by" in top.details
    assert set(top.details["also_reported_by"]) == {"semgrep", "zap"}
    print("dedup self-check passed:", [(x.tool, x.severity, x.details.get('also_reported_by')) for x in out])
