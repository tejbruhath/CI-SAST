"""
DeepSeek LLM layer — triage + fix generation (Sentriq's Triage + Fix Generator).

Uses DeepSeek's OpenAI-compatible /chat/completions endpoint (model
deepseek-v4-flash) via plain httpx — no SDK dependency. Two capabilities:

  triage(finding, snippet) -> verdict {real | false_positive | noise} + citation
  generate_fix(finding, snippet) -> unified-diff patch + explanation

Both use JSON-mode (response_format json_object) so parsing is reliable. All
calls are defensive: on any network/parse error they return a safe "error"
result rather than raising, so one bad LLM call never fails a whole scan.
"""
from __future__ import annotations

import difflib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from . import config

logger = logging.getLogger("sentriq.deepseek")


@dataclass
class TriageResult:
    verdict: str            # real | false_positive | noise | error
    confidence: float       # 0..1
    rationale: str
    citation: Dict[str, Any]


@dataclass
class FixResult:
    diff: str               # unified diff, or "" if none
    explanation: str
    ok: bool


_VALID_VERDICTS = {"real", "false_positive", "noise"}

# Files bigger than this are windowed around the finding before being sent.
_MAX_FILE_CHARS = 12000

TRIAGE_SYSTEM = (
    "You are a senior application-security engineer triaging a static/dynamic "
    "scanner finding. Decide if it is a real exploitable issue, a false "
    "positive, or noise (low-value/informational). Be strict: prefer 'real' "
    "only when the evidence supports exploitability. Respond ONLY as JSON with "
    "keys: verdict (one of 'real','false_positive','noise'), confidence "
    "(0.0-1.0), rationale (<=60 words), citation (object with keys rule, file, "
    "line, why)."
)

FIX_SYSTEM = (
    "You are a secure-coding assistant. Given the contents of a vulnerable file "
    "and a scanner finding, propose the minimal edit that fixes it. Do NOT write "
    "a diff — instead identify the exact text to replace. Respond ONLY as JSON "
    "with keys: old_str (the text to replace, copied VERBATIM from the file "
    "including exact indentation and whitespace; it must appear EXACTLY ONCE in "
    "the file; keep it as short as possible while still unique), new_str (the "
    "replacement text), explanation (<=60 words). If you cannot safely fix it "
    "from the given context, set old_str and new_str to empty strings."
)


def _chat(system: str, user: str) -> Optional[Dict[str, Any]]:
    if not config.DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY unset; skipping LLM call")
        return None
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
               "Content-Type": "application/json"}
    url = config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        resp = httpx.post(url, json=payload, headers=headers,
                          timeout=config.DEEPSEEK_TIMEOUT_SECONDS)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:
        logger.error("deepseek call failed: %s", exc)
        return None


def _finding_prompt(finding: Dict[str, Any], snippet: str) -> str:
    return (
        f"Tool: {finding.get('tool')}\n"
        f"Type: {finding.get('type')}\n"
        f"Severity: {finding.get('severity')}\n"
        f"Rule: {finding.get('rule_id')}\n"
        f"Message: {finding.get('message')}\n"
        f"File: {finding.get('file')}  Line: {finding.get('line')}\n"
        f"Details: {json.dumps(finding.get('details', {}))[:800]}\n\n"
        f"Code context:\n```\n{snippet[:2000]}\n```"
    )


def _fix_prompt(finding: Dict[str, Any], file_text: str) -> str:
    """Fix prompt carries the real file text — old_str must be copied from it.

    Large files are windowed around the finding so the anchor stays in view;
    the uniqueness check still runs against the full text.
    """
    path = finding.get("file")
    body = file_text
    if len(file_text) > _MAX_FILE_CHARS:
        body = _window(file_text, finding.get("line"))
        header = f"Excerpt of {path} (the file is large; edit only what you see here):"
    else:
        header = f"Full contents of {path}:"
    return (
        f"Tool: {finding.get('tool')}\n"
        f"Type: {finding.get('type')}\n"
        f"Severity: {finding.get('severity')}\n"
        f"Rule: {finding.get('rule_id')}\n"
        f"Message: {finding.get('message')}\n"
        f"File: {path}  Line: {finding.get('line')}\n"
        f"Details: {json.dumps(finding.get('details', {}))[:800]}\n\n"
        f"{header}\n```\n{body}\n```\n\n"
        "Copy old_str verbatim from the text above."
    )


def _window(text: str, line: Optional[int], radius: int = 60) -> str:
    """Lines around `line` (or the head of the file when the tool gave no line)."""
    lines = text.splitlines(keepends=True)
    if not line:
        return "".join(lines[:2 * radius])
    lo = max(0, line - 1 - radius)
    return "".join(lines[lo:line - 1 + radius + 1])


def triage(finding: Dict[str, Any], snippet: str = "") -> TriageResult:
    data = _chat(TRIAGE_SYSTEM, _finding_prompt(finding, snippet))
    if not data:
        return TriageResult("error", 0.0, "LLM unavailable", {})
    verdict = str(data.get("verdict", "")).lower().strip()
    if verdict not in _VALID_VERDICTS:
        verdict = "real"  # fail safe: never silently drop a finding
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return TriageResult(
        verdict=verdict,
        confidence=max(0.0, min(1.0, conf)),
        rationale=str(data.get("rationale", ""))[:1000],
        citation=data.get("citation") if isinstance(data.get("citation"), dict) else {},
    )


def _unified_diff(path: str, before: str, after: str) -> str:
    """Build a git-applyable unified diff from the real before/after text."""
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}"))
    return diff if diff.endswith("\n") else diff + "\n"


def generate_fix(finding: Dict[str, Any], file_text: str = "") -> FixResult:
    """Ask the LLM which text to swap, then compute the diff ourselves.

    LLM-authored unified diffs were unusable: the model invents hunk headers and
    context lines it cannot verify, so every patch failed `git apply`. Here the
    model only chooses old_str/new_str, and difflib produces the real diff
    against the real file — headers and offsets are correct by construction.

    Takes the raw file text, never the line-numbered triage snippet: `12: code`
    prefixes are exactly what the model cannot turn back into a valid patch.
    """
    path = finding.get("file") or ""
    if not file_text or not path:
        return FixResult("", "no file context available to fix against", False)

    data = _chat(FIX_SYSTEM, _fix_prompt(finding, file_text))
    if not data:
        return FixResult("", "LLM unavailable", False)

    old = str(data.get("old_str") or "")
    new = str(data.get("new_str") or "")
    explanation = str(data.get("explanation", ""))[:1000]

    if not old.strip():
        return FixResult("", explanation or "no fix proposed", False)
    # The anchor must exist verbatim and be unambiguous, else the swap is a
    # guess. Reject rather than emit a patch that corrupts the file.
    occurrences = file_text.count(old)
    if occurrences == 0:
        logger.warning("fix rejected: old_str not found in %s (%s)",
                       path, finding.get("rule_id"))
        return FixResult("", "proposed fix did not match the file", False)
    if occurrences > 1:
        logger.warning("fix rejected: old_str matches %d places in %s",
                       occurrences, path)
        return FixResult("", "proposed fix was ambiguous", False)
    if old == new:
        return FixResult("", explanation or "no change proposed", False)

    diff = _unified_diff(path, file_text, file_text.replace(old, new, 1))
    return FixResult(diff=diff, explanation=explanation, ok=bool(diff.strip()))


if __name__ == "__main__":
    # Offline self-check: with no API key, both paths return safe error results
    # (never raise). Exercises the parsing/guard logic without a network call.
    assert not config.DEEPSEEK_API_KEY or True
    import os
    os.environ.pop("DEEPSEEK_API_KEY", None)
    config.DEEPSEEK_API_KEY = ""
    t = triage({"tool": "semgrep", "type": "sast", "severity": "high",
                "rule_id": "sql", "message": "sqli", "file": "a.py", "line": 5})
    assert t.verdict == "error" and t.confidence == 0.0
    fx = generate_fix({"tool": "semgrep", "rule_id": "sql", "message": "sqli",
                       "file": "a.py"}, file_text="x = 1\n")
    assert fx.ok is False and fx.diff == ""
    # No file text -> nothing to anchor a diff against, so never call the LLM.
    assert generate_fix({"file": "a.py"}).ok is False

    # difflib produces correct headers/offsets regardless of where the edit lands.
    before = "".join(f"line{i}\n" for i in range(1, 21))
    diff = _unified_diff("f.txt", before, before.replace("line14", "patched"))
    assert diff.startswith("--- a/f.txt\n+++ b/f.txt\n"), diff
    assert "@@ -11,7 +11,7 @@" in diff, diff
    assert "-line14\n+patched\n" in diff, diff
    print("deepseek self-check passed (offline guards + diff builder OK)")
