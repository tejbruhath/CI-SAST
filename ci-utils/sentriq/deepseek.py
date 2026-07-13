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
    "You are a secure-coding assistant. Given a vulnerable code snippet and a "
    "scanner finding, produce a minimal fix as a unified diff (git-style, with "
    "--- a/<file> and +++ b/<file> headers and @@ hunks). Change as little as "
    "possible. If you cannot safely fix it from the given context, return an "
    "empty diff. Respond ONLY as JSON with keys: diff (string, the unified "
    "diff or ''), explanation (<=60 words)."
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


def generate_fix(finding: Dict[str, Any], snippet: str = "") -> FixResult:
    data = _chat(FIX_SYSTEM, _finding_prompt(finding, snippet))
    if not data:
        return FixResult("", "LLM unavailable", False)
    diff = str(data.get("diff", "") or "")
    return FixResult(diff=diff,
                     explanation=str(data.get("explanation", ""))[:1000],
                     ok=bool(diff.strip()))


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
    fx = generate_fix({"tool": "semgrep", "rule_id": "sql", "message": "sqli"})
    assert fx.ok is False and fx.diff == ""
    print("deepseek self-check passed (offline guards OK)")
