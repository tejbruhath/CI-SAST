"""
Aggregation + cross-pipeline deduplication (Tasks B2 + B3).

Merges every tool's Findings for a scan into one deduplicated list. Dedup is
fingerprint-keyed, with a secondary semantic key (type + file + line) so the
same issue reported by two tools (e.g. semgrep + zap both flagging one SQLi)
collapses to a single finding that records every tool that saw it.
"""
from __future__ import annotations  # modern typing without quoted forwards

from typing import Dict, List, Tuple  # type hints for dedup maps

from .schema import Finding  # normalized finding value objects


def _semantic_key(f: Finding) -> Tuple:
    """A location-based identity independent of which tool reported it.
    Falls back to the tool-specific fingerprint when there's no usable location
    (so unrelated findings never collapse together)."""
    if f.file and f.line is not None:
        return ("loc", f.type, f.file, f.line)  # same place + type = same issue
    if f.file and f.type in ("vulnerability", "secret"):
        # SCA/secret findings often have no line; rule+file is enough.
        return ("rulefile", f.type, f.rule_id, f.file)  # package/secret without line
    return ("fp", f.fingerprint)  # last resort: tool-specific fingerprint only


def deduplicate(findings: List[Finding]) -> List[Finding]:
    """Collapse duplicates, keeping the highest-severity representative and
    annotating it with all contributing tools."""
    best: Dict[Tuple, Finding] = {}  # key → highest-severity representative
    seen_tools: Dict[Tuple, set] = {}  # key → set of tools that reported it
    for f in findings:  # walk every raw finding from all tools
        key = _semantic_key(f)  # compute cross-tool identity
        seen_tools.setdefault(key, set()).add(f.tool)  # record this tool
        cur = best.get(key)  # current winner for this key, if any
        if cur is None or f.severity_score > cur.severity_score:
            best[key] = f  # keep the more severe report as the face of the group
    out = []  # final deduped list
    for key, f in best.items():  # one representative per key
        tools = sorted(seen_tools[key])  # stable tool list for UI
        if len(tools) > 1:
            f.details = {**f.details, "also_reported_by": tools}  # multi-tool annotation
        out.append(f)  # include representative finding
    # stable, worst-first ordering for the UI
    out.sort(key=lambda x: (-x.severity_score, x.tool, x.file or ""))  # severity then name
    return out


if __name__ == "__main__":
    from .schema import STATIC, DYNAMIC  # pipeline constants for self-test
    a = Finding(tool="semgrep", pipeline=STATIC, type="sast", severity="high",
                rule_id="sql", message="sqli", file="a.py", line=5)  # SAST SQLi
    b = Finding(tool="zap", pipeline=DYNAMIC, type="sast", severity="critical",
                rule_id="40018", message="sqli", file="a.py", line=5)  # same loc, worse sev
    c = Finding(tool="trivy", pipeline=STATIC, type="vulnerability",
                severity="medium", rule_id="CVE-1", message="cve", file="r.txt")  # unrelated CVE
    out = deduplicate([a, b, c])  # should collapse a+b, keep c
    assert len(out) == 2, [x.to_dict() for x in out]  # two unique issues
    top = out[0]  # worst-first: critical zap wins over high semgrep
    assert top.severity == "critical" and "also_reported_by" in top.details  # multi-tool tag
    assert set(top.details["also_reported_by"]) == {"semgrep", "zap"}  # both tools recorded
    print("dedup self-check passed:", [(x.tool, x.severity, x.details.get('also_reported_by')) for x in out])
