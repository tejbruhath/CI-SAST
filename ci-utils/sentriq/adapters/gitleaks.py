"""gitleaks adapter — secret detection (SAST/static). Parser ported from the
proven ci-utils aggregator; tiers secrets by rule class."""
from __future__ import annotations

import json
from typing import List

from .base import BaseAdapter, register, Finding, STATIC

WORKDIR = "/work"

# gitleaks rule keywords denoting high-value credentials -> critical tier.
_CRITICAL_KEYWORDS = (
    "aws", "gcp", "azure", "private-key", "privatekey", "rsa",
    "stripe", "paypal", "square", "github", "gitlab", "slack",
    "twilio", "sendgrid", "npm", "pypi", "digitalocean",
)


def _rel(path: str) -> str:
    if not path:
        return "unknown"
    p = path
    if p.startswith(WORKDIR + "/"):
        p = p[len(WORKDIR) + 1:]
    return p.lstrip("/") or "unknown"


@register
class GitleaksAdapter(BaseAdapter):
    NAME = "gitleaks"
    IMAGE = "zricethezav/gitleaks:latest"
    PIPELINE = STATIC
    OUTPUT_FILE = "output.json"

    def command(self, target: str, workdir: str) -> List[str]:
        # --no-git: scan the working tree as files (works on shallow clones and
        # non-repo dirs alike). --exit-code 0: findings are not a run failure.
        return [
            "detect",
            f"--source={workdir}",
            "--no-git",
            "--report-format=json",
            f"--report-path={workdir}/{self.OUTPUT_FILE}",
            "--exit-code=0",
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output) if raw_output.strip() else []
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        out: List[Finding] = []
        for f in data:
            if not isinstance(f, dict):
                continue
            rule = f.get("RuleID", "unknown")
            crit = any(k in rule.lower() for k in _CRITICAL_KEYWORDS)
            file = _rel(f.get("File", "unknown"))
            line = f.get("StartLine")
            out.append(Finding(
                tool=self.NAME, pipeline=STATIC, type="secret",
                severity="critical" if crit else "high",
                rule_id=rule,
                message=f"Secret detected: {rule} in {file}:{line}",
                file=file, line=line, url=None,
                details={"secret_type": rule, "entropy": f.get("Entropy"),
                         "match": f.get("Match", "")[:80]},
                # rule+file+line is stable across scans (gitleaks' own
                # Fingerprint embeds the scan-time path and is not).
                fingerprint=f"gitleaks:{rule}:{file}:{line}",
            ))
        return out


if __name__ == "__main__":
    import json as _j
    raw = _j.dumps([
        {"RuleID": "aws-access-key", "File": "/work/app/config.py",
         "StartLine": 12, "Entropy": 4.5, "Match": "AKIA..."},
        {"RuleID": "generic-token", "File": "/work/util.py", "StartLine": 5},
    ])
    fs = GitleaksAdapter().parse(raw, "")
    assert len(fs) == 2
    assert fs[0].severity == "critical" and fs[0].file == "app/config.py"
    assert fs[1].severity == "high"  # non-cloud rule -> high tier
    assert GitleaksAdapter().parse("not json", "") == []
    print("gitleaks adapter self-test passed:", fs[0].to_dict())
