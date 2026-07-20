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
from __future__ import annotations  # modern annotations without runtime cost

import difflib  # build real unified diffs from before/after text
import json  # parse model JSON and serialize finding details
import logging  # log API failures and rejected fix anchors
from dataclasses import dataclass  # result types for triage and fix
from typing import Any, Dict, Optional  # flexible finding dicts and JSON

import httpx  # HTTP client for DeepSeek chat completions

from . import config  # API key, model name, base URL, timeouts

logger = logging.getLogger("sentriq.deepseek")  # namespaced logger


@dataclass
class TriageResult:
    verdict: str            # real | false_positive | noise | error
    confidence: float       # 0..1  # model confidence, clamped later
    rationale: str  # short human-readable explanation
    citation: Dict[str, Any]  # rule/file/line/why for audit trail


@dataclass
class FixResult:
    diff: str               # unified diff, or "" if none
    explanation: str  # why the change fixes the issue
    ok: bool  # True only when a usable non-empty diff exists


_VALID_VERDICTS = {"real", "false_positive", "noise"}  # allowed triage labels

# Files bigger than this are windowed around the finding before being sent.
_MAX_FILE_CHARS = 12000  # soft budget so prompts fit the context window

TRIAGE_SYSTEM = (  # system prompt steers the model as a strict security reviewer
    "You are a senior application-security engineer triaging a static/dynamic "
    "scanner finding. Decide if it is a real exploitable issue, a false "
    "positive, or noise (low-value/informational). Be strict: prefer 'real' "
    "only when the evidence supports exploitability. Respond ONLY as JSON with "
    "keys: verdict (one of 'real','false_positive','noise'), confidence "
    "(0.0-1.0), rationale (<=60 words), citation (object with keys rule, file, "
    "line, why)."
)

FIX_SYSTEM = (  # system prompt: ask for text swap, not a hand-written diff
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
    if not config.DEEPSEEK_API_KEY:  # missing key → soft skip, not crash
        logger.warning("DEEPSEEK_API_KEY unset; skipping LLM call")
        return None
    payload = {
        "model": config.DEEPSEEK_MODEL,  # configured chat model id
        "messages": [
            {"role": "system", "content": system},  # role instructions
            {"role": "user", "content": user},  # finding + code context
        ],
        "response_format": {"type": "json_object"},  # force valid JSON object
        "temperature": 0.0,  # deterministic outputs for triage/fix
        "stream": False,  # single complete response body
    }
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",  # API auth
               "Content-Type": "application/json"}
    url = config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"  # OpenAI-style path
    try:
        resp = httpx.post(url, json=payload, headers=headers,
                          timeout=config.DEEPSEEK_TIMEOUT_SECONDS)  # bounded wait
        resp.raise_for_status()  # non-2xx raises
        content = resp.json()["choices"][0]["message"]["content"]  # model text
        return json.loads(content)  # parse JSON mode body into a dict
    except Exception as exc:  # network, HTTP, or JSON parse failure
        logger.error("deepseek call failed: %s", exc)
        return None  # callers turn None into safe error results


def _finding_prompt(finding: Dict[str, Any], snippet: str) -> str:
    return (  # compact, structured user message for triage
        f"Tool: {finding.get('tool')}\n"
        f"Type: {finding.get('type')}\n"
        f"Severity: {finding.get('severity')}\n"
        f"Rule: {finding.get('rule_id')}\n"
        f"Message: {finding.get('message')}\n"
        f"File: {finding.get('file')}  Line: {finding.get('line')}\n"
        f"Details: {json.dumps(finding.get('details', {}))[:800]}\n\n"  # cap noise
        f"Code context:\n```\n{snippet[:2000]}\n```"  # short snippet for triage
    )


def _fix_prompt(finding: Dict[str, Any], file_text: str) -> str:
    """Fix prompt carries the real file text — old_str must be copied from it.

    Large files are windowed around the finding so the anchor stays in view;
    the uniqueness check still runs against the full text.
    """
    path = finding.get("file")  # relative path used in the prompt header
    body = file_text  # default: send whole file
    if len(file_text) > _MAX_FILE_CHARS:  # large file → window around line
        body = _window(file_text, finding.get("line"))
        header = f"Excerpt of {path} (the file is large; edit only what you see here):"
    else:
        header = f"Full contents of {path}:"  # small files fit entirely
    prompt = (
        f"Tool: {finding.get('tool')}\n"
        f"Type: {finding.get('type')}\n"
        f"Severity: {finding.get('severity')}\n"
        f"Rule: {finding.get('rule_id')}\n"
        f"Message: {finding.get('message')}\n"
        f"File: {path}  Line: {finding.get('line')}\n"
        f"Details: {json.dumps(finding.get('details', {}))[:800]}\n\n"
        f"{header}\n```\n{body}\n```\n\n"
        "Copy old_str verbatim from the text above."  # critical instruction
    )
    fixed_version = finding.get("details", {}).get("fixed_version")
    if fixed_version:
        prompt += (
            f"\nAuthoritative fixed version (from the scanner's CVE database, "
            f"NOT your training knowledge): {fixed_version}. The new_str MUST "
            f"upgrade to exactly this version — do not substitute a different "
            f"version number from memory, even if you believe another version "
            f"is more current."
        )
    return prompt


def _window(text: str, line: Optional[int], radius: int = 60) -> str:
    """Lines around `line` (or the head of the file when the tool gave no line)."""
    lines = text.splitlines(keepends=True)  # preserve original newlines
    if not line:  # scanners sometimes omit line numbers
        return "".join(lines[:2 * radius])  # take file head as context
    lo = max(0, line - 1 - radius)  # convert 1-based line to index, clamp
    return "".join(lines[lo:line - 1 + radius + 1])  # inclusive window slice


def triage(finding: Dict[str, Any], snippet: str = "") -> TriageResult:
    data = _chat(TRIAGE_SYSTEM, _finding_prompt(finding, snippet))  # call LLM
    if not data:  # missing key or API failure
        return TriageResult("error", 0.0, "LLM unavailable", {})
    verdict = str(data.get("verdict", "")).lower().strip()  # normalize label
    if verdict not in _VALID_VERDICTS:  # unknown label from model
        verdict = "real"  # fail safe: never silently drop a finding
    try:
        conf = float(data.get("confidence", 0.0))  # may be string or missing
    except (TypeError, ValueError):
        conf = 0.0  # unparseable confidence becomes zero
    return TriageResult(
        verdict=verdict,
        confidence=max(0.0, min(1.0, conf)),  # clamp into [0, 1]
        rationale=str(data.get("rationale", ""))[:1000],  # bound stored text
        citation=data.get("citation") if isinstance(data.get("citation"), dict) else {},
    )


def _unified_diff(path: str, before: str, after: str) -> str:
    """Build a git-applyable unified diff from the real before/after text."""
    diff = "".join(difflib.unified_diff(  # standard unified format
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}"))  # git apply expects a/ b/
    return diff if diff.endswith("\n") else diff + "\n"  # trailing newline for apply



def _is_secret_finding(finding: Dict[str, Any]) -> bool:
    """True for gitleaks / secret-type findings (no code patch is appropriate)."""
    tool = str(finding.get("tool") or "").lower()
    ftype = str(finding.get("type") or "").lower()
    return tool == "gitleaks" or ftype == "secret"


def _secret_remediation(finding: Dict[str, Any]) -> FixResult:
    """Guidance-only "fix" for leaked secrets — never invent a code patch.

    Secrets should be rotated and moved to env/secrets managers, not rewritten
    in-repo by an LLM. Returns ok=True with empty diff so the UI can show steps.
    """
    rule = finding.get("rule_id") or finding.get("details", {}).get("secret_type") or "credential"
    path = finding.get("file") or "the affected file"
    line = finding.get("line")
    where = f"{path}:{line}" if line else path
    explanation = (
        f"Secret detection ({rule}) at {where}. Do not commit a code patch that "
        f"just deletes or rewrites the leaked value in place.\n\n"
        f"Recommended steps:\n"
        f"1. Rotate/revoke the exposed credential immediately (provider dashboard or CLI).\n"
        f"2. Move the secret out of source into environment variables or a secrets manager.\n"
        f"3. Create a local `.env` (or use your platform secrets) and load it at runtime "
        f"— never commit `.env`; add it to `.gitignore`.\n"
        f"4. Replace hard-coded values with `os.environ[...]` / config lookups.\n"
        f"5. Purge the secret from git history if it was ever committed "
        f"(e.g. git filter-repo / BFG) and force-protect the default branch.\n"
        f"6. Re-scan after rotation to confirm the leak is gone."
    )
    return FixResult(diff="", explanation=explanation, ok=True)


def generate_fix(finding: Dict[str, Any], file_text: str = "") -> FixResult:
    """Ask the LLM which text to swap, then compute the diff ourselves.

    LLM-authored unified diffs were unusable: the model invents hunk headers and
    context lines it cannot verify, so every patch failed `git apply`. Here the
    model only chooses old_str/new_str, and difflib produces the real diff
    against the real file — headers and offsets are correct by construction.

    Takes the raw file text, never the line-numbered triage snippet: `12: code`
    prefixes are exactly what the model cannot turn back into a valid patch.

    Secret findings (gitleaks) skip the LLM and return remediation guidance only
    — rotating credentials / .env is the fix, not an in-repo string rewrite.
    """
    if _is_secret_finding(finding):
        return _secret_remediation(finding)

    path = finding.get("file") or ""  # need a path for diff headers
    if not file_text or not path:  # nothing to anchor against
        return FixResult("", "no file context available to fix against", False)

    data = _chat(FIX_SYSTEM, _fix_prompt(finding, file_text))  # ask for old/new
    if not data:  # API down or key missing
        return FixResult("", "LLM unavailable", False)

    old = str(data.get("old_str") or "")  # text that must match the file once
    new = str(data.get("new_str") or "")  # replacement text
    explanation = str(data.get("explanation", ""))[:1000]  # cap stored length

    if not old.strip():  # model declined to propose a fix
        return FixResult("", explanation or "no fix proposed", False)
    # The anchor must exist verbatim and be unambiguous, else the swap is a
    # guess. Reject rather than emit a patch that corrupts the file.
    occurrences = file_text.count(old)  # uniqueness check on full file
    if occurrences == 0:  # model hallucinated text not in file
        logger.warning("fix rejected: old_str not found in %s (%s)",
                       path, finding.get("rule_id"))
        return FixResult("", "proposed fix did not match the file", False)
    if occurrences > 1:  # replace would be ambiguous/wrong
        logger.warning("fix rejected: old_str matches %d places in %s",
                       occurrences, path)
        return FixResult("", "proposed fix was ambiguous", False)
    if old == new:  # no-op edit
        return FixResult("", explanation or "no change proposed", False)

    diff = _unified_diff(path, file_text, file_text.replace(old, new, 1))  # one swap
    return FixResult(diff=diff, explanation=explanation, ok=bool(diff.strip()))


if __name__ == "__main__":  # offline self-test when run as a script
    # Offline self-check: with no API key, both paths return safe error results
    # (never raise). Exercises the parsing/guard logic without a network call.
    assert not config.DEEPSEEK_API_KEY or True  # always proceed into forced empty key
    import os  # only needed in the self-check block
    os.environ.pop("DEEPSEEK_API_KEY", None)  # clear env for this process
    config.DEEPSEEK_API_KEY = ""  # also clear in-memory config
    t = triage({"tool": "semgrep", "type": "sast", "severity": "high",
                "rule_id": "sql", "message": "sqli", "file": "a.py", "line": 5})
    assert t.verdict == "error" and t.confidence == 0.0  # soft-fail without key
    fx = generate_fix({"tool": "semgrep", "rule_id": "sql", "message": "sqli",
                       "file": "a.py"}, file_text="x = 1\n")
    assert fx.ok is False and fx.diff == ""  # no LLM → no diff
    # No file text -> nothing to anchor a diff against, so never call the LLM.
    assert generate_fix({"file": "a.py"}).ok is False

    # difflib produces correct headers/offsets regardless of where the edit lands.
    before = "".join(f"line{i}\n" for i in range(1, 21))  # 20-line sample file
    diff = _unified_diff("f.txt", before, before.replace("line14", "patched"))
    assert diff.startswith("--- a/f.txt\n+++ b/f.txt\n"), diff  # git-style paths
    assert "@@ -11,7 +11,7 @@" in diff, diff  # expected hunk header
    assert "-line14\n+patched\n" in diff, diff  # expected change lines
    # Secrets never need file text / LLM — always return guidance with empty diff.
    sec = generate_fix({"tool": "gitleaks", "type": "secret", "rule_id": "aws-key",
                         "file": "app.py", "line": 10})
    assert sec.ok and sec.diff == "" and ".env" in sec.explanation, sec
    print("deepseek self-check passed (offline guards + diff builder OK)")
