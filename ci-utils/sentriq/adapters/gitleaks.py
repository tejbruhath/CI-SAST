"""gitleaks adapter — secret detection (SAST/static). Parser ported from the
proven ci-utils aggregator; tiers secrets by rule class."""
from __future__ import annotations  # modern type annotations without quotes

import json  # parse gitleaks JSON report
from typing import List  # type hint for command and parse returns

from .base import BaseAdapter, register, Finding, STATIC  # adapter contract + types

WORKDIR = "/work"  # path prefix inside the container mount

# gitleaks rule keywords denoting high-value credentials -> critical tier.
_CRITICAL_KEYWORDS = (
    "aws", "gcp", "azure", "private-key", "privatekey", "rsa",
    "stripe", "paypal", "square", "github", "gitlab", "slack",
    "twilio", "sendgrid", "npm", "pypi", "digitalocean",
)  # cloud/payment keys treated as highest severity


def _rel(path: str) -> str:
    if not path:
        return "unknown"  # empty path becomes a safe placeholder
    p = path
    if p.startswith(WORKDIR + "/"):
        p = p[len(WORKDIR) + 1:]  # strip container mount prefix for repo-relative path
    return p.lstrip("/") or "unknown"  # never return empty string


@register  # add this adapter to REGISTRY under NAME
class GitleaksAdapter(BaseAdapter):
    NAME = "gitleaks"  # tool id used in findings and selection
    IMAGE = "zricethezav/gitleaks:latest"  # Docker image the executor pulls/runs
    PIPELINE = STATIC  # scans source code, not a live URL
    OUTPUT_FILE = "output.json"  # where the container writes the report

    def command(self, target: str, workdir: str) -> List[str]:
        # --no-git: scan the working tree as files (works on shallow clones and
        # non-repo dirs alike). --exit-code 0: findings are not a run failure.
        return [
            "detect",  # gitleaks subcommand for secret scanning
            f"--source={workdir}",  # directory inside the container to scan
            "--no-git",  # treat as files, not full git history
            "--report-format=json",  # machine-readable findings
            f"--report-path={workdir}/{self.OUTPUT_FILE}",  # write report here
            "--exit-code=0",  # secrets found still counts as success for us
        ]

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        try:
            data = json.loads(raw_output) if raw_output.strip() else []  # empty -> list
        except json.JSONDecodeError:
            return []  # corrupt report yields no findings
        if not isinstance(data, list):
            return []  # unexpected shape: refuse to parse
        out: List[Finding] = []  # accumulate normalized findings
        for f in data:
            if not isinstance(f, dict):
                continue  # skip non-object entries
            rule = f.get("RuleID", "unknown")  # which secret rule matched
            crit = any(k in rule.lower() for k in _CRITICAL_KEYWORDS)  # tier up?
            file = _rel(f.get("File", "unknown"))  # repo-relative path
            line = f.get("StartLine")  # optional line number
            out.append(Finding(
                tool=self.NAME, pipeline=STATIC, type="secret",  # domain labels
                severity="critical" if crit else "high",  # cloud keys are critical
                rule_id=rule,
                message=f"Secret detected: {rule} in {file}:{line}",
                file=file, line=line, url=None,  # secrets rarely have external URLs
                details={"secret_type": rule, "entropy": f.get("Entropy"),
                         "match": f.get("Match", "")[:80]},  # truncate leaked snippet
                # rule+file+line is stable across scans (gitleaks' own
                # Fingerprint embeds the scan-time path and is not).
                fingerprint=f"gitleaks:{rule}:{file}:{line}",
            ))
        return out


if __name__ == "__main__":  # manual self-test when run as a script
    import json as _j
    raw = _j.dumps([
        {"RuleID": "aws-access-key", "File": "/work/app/config.py",
         "StartLine": 12, "Entropy": 4.5, "Match": "AKIA..."},
        {"RuleID": "generic-token", "File": "/work/util.py", "StartLine": 5},
    ])  # synthetic gitleaks-like report
    fs = GitleaksAdapter().parse(raw, "")
    assert len(fs) == 2  # both secrets become findings
    assert fs[0].severity == "critical" and fs[0].file == "app/config.py"
    assert fs[1].severity == "high"  # non-cloud rule -> high tier
    assert GitleaksAdapter().parse("not json", "") == []  # bad input is safe
    print("gitleaks adapter self-test passed:", fs[0].to_dict())
