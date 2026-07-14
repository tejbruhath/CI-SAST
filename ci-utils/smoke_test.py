"""
End-to-end pipeline smoke test WITHOUT Docker or live LLM.

Mocks executor.run_tool (fake tool findings) and deepseek (canned triage/fix),
then drives the real run_scan orchestration and the real DRF API, asserting the
whole chain persists + serves correctly. Run: USE_SQLITE=1 python smoke_test.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")
os.environ.setdefault("USE_SQLITE", "1")
os.environ.setdefault("LLM_ENABLED", "true")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from sentriq import executor, deepseek, config  # noqa: E402
from sentriq.executor import ToolRun  # noqa: E402
from sentriq.schema import Finding as F, STATIC  # noqa: E402
from sentriq.models import (Scan, Finding, Triage, FixSuggestion,  # noqa: E402
                            ProvenanceEvent, HitlAction)
from sentriq import tasks  # noqa: E402


# ---- mocks -------------------------------------------------------------------
def fake_run_tool(adapter, target, work_dir, timeout):
    if adapter.NAME == "gitleaks":
        fs = [F(tool="gitleaks", pipeline=STATIC, type="secret", severity="critical",
                rule_id="aws-key", message="AWS key leaked", file="app/s.py", line=3)]
    elif adapter.NAME == "semgrep":
        fs = [F(tool="semgrep", pipeline=STATIC, type="sast", severity="high",
                rule_id="sqli", message="SQL injection", file="app/s.py", line=3)]
    elif adapter.NAME == "trivy":
        fs = [F(tool="trivy", pipeline=STATIC, type="vulnerability", severity="medium",
                rule_id="CVE-2024-1", message="lib bug", file="requirements.txt")]
    else:
        fs = []
    return ToolRun(adapter.NAME, fs, True, 0, 1.2)


def fake_triage(finding, snippet=""):
    return deepseek.TriageResult("real", 0.9, "exploitable", {"rule": finding["rule_id"]})


def fake_fix(finding, file_text=""):
    return deepseek.FixResult("--- a/app/s.py\n+++ b/app/s.py\n@@ -3 +3 @@\n-bad\n+good\n",
                              "use parameterized query", True)


executor.run_tool = fake_run_tool
tasks.executor.run_tool = fake_run_tool
tasks.executor.git_clone = lambda *a, **k: None
deepseek.triage = fake_triage
deepseek.generate_fix = fake_fix
import sys  # noqa: E402
sys.modules["sentriq.deepseek"].triage = fake_triage
sys.modules["sentriq.deepseek"].generate_fix = fake_fix


# ---- drive -------------------------------------------------------------------
def main():
    Scan.objects.all().delete()
    # The API is IsAuthenticated and scopes every read to scan.requested_by, so
    # the smoke user must own the scan it then reads back over HTTP.
    User = get_user_model()
    User.objects.filter(username="smoke").delete()
    user = User.objects.create_user(username="smoke", password="smoke")
    scan = Scan.objects.create(pipeline=STATIC, target="https://example.com/repo.git",
                               requested_by=user)
    result = tasks.run_scan(str(scan.id))
    scan.refresh_from_db()

    print("scan result:", result)
    assert scan.status == Scan.COMPLETE, scan.status
    # 3 distinct findings: gitleaks(secret), semgrep(sast), trivy(vuln). The
    # secret + sast share app/s.py:3 but are DIFFERENT types, so they correctly
    # do NOT merge (cross-tool same-type dedup is covered by aggregator's test).
    fcount = Finding.objects.filter(scan=scan).count()
    assert fcount == 3, f"expected 3 findings, got {fcount}"
    assert Triage.objects.count() == 3, Triage.objects.count()
    # only critical/high real findings get a fix (medium trivy does not) ->
    # gitleaks(critical) + semgrep(high) = 2 fixes
    assert FixSuggestion.objects.count() == 2, FixSuggestion.objects.count()
    assert ProvenanceEvent.objects.filter(scan=scan).count() >= 5
    # Policy: non-critical fixes are auto-approved; critical always waits for a
    # human. So semgrep(high) is already approved, gitleaks(critical) is not.
    assert FixSuggestion.objects.get(
        finding__tool="semgrep").status == FixSuggestion.APPROVED
    assert FixSuggestion.objects.get(
        finding__tool="gitleaks").status == FixSuggestion.PROPOSED
    assert HitlAction.objects.filter(actor="sentriq-auto").count() == 1

    # ---- API ----
    c = Client()
    c.force_login(user)
    r = c.get("/api/v1/findings")
    assert r.status_code == 200 and len(r.json()) == 3, r.content
    fid = r.json()[0]["id"]
    r = c.get(f"/api/v1/findings/{fid}")
    assert r.status_code == 200 and r.json()["triage"]["verdict"] == "real"

    # HITL approve
    r = c.post(f"/api/v1/findings/{fid}/hitl",
               data={"action": "approve", "actor": "tej"},
               content_type="application/json")
    assert r.status_code == 201, r.content
    # 2 approves now: the human one above + the auto-approve from scan policy.
    assert HitlAction.objects.filter(action="approve", actor="tej").count() == 1
    assert HitlAction.objects.filter(action="approve").count() == 2

    r = c.get("/api/v1/metrics")
    m = r.json()
    # both fixes approved: semgrep(high) by policy, gitleaks(critical) by human.
    assert m["totals"]["findings"] == 3 and m["totals"]["fixes_approved"] == 2, m

    r = c.get(f"/api/v1/provenance?scan={scan.id}")
    assert r.status_code == 200 and len(r.json()) >= 5

    print("SMOKE TEST PASSED")
    print("  findings:", fcount, "| triage:", Triage.objects.count(),
          "| fixes:", FixSuggestion.objects.count(),
          "| provenance:", ProvenanceEvent.objects.filter(scan=scan).count())
    print("  metrics:", m["totals"])


if __name__ == "__main__":
    main()
