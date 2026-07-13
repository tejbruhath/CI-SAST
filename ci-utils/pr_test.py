"""
PR-automation test WITHOUT touching a real repo or GitHub.

Mocks executor.apply_fix_and_push (the git clone/apply/push) and scm.open_pr /
default_branch (the GitHub API), then drives the real create_pr task and the
real /pr endpoint guards. Run: USE_SQLITE=1 python pr_test.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")
os.environ.setdefault("USE_SQLITE", "1")
django.setup()

from django.test import Client  # noqa: E402
from sentriq import executor, scm, tasks  # noqa: E402
from sentriq.schema import STATIC  # noqa: E402
from sentriq.models import Scan, Finding, FixSuggestion, ProvenanceEvent  # noqa: E402

# ---- mocks (no real git / no real GitHub) ----
executor.apply_fix_and_push = lambda *a, **k: None
executor.make_scratch = lambda x: "/tmp/pr-test-noop"
executor.cleanup = lambda x: None
tasks.executor.apply_fix_and_push = executor.apply_fix_and_push
tasks.executor.make_scratch = executor.make_scratch
tasks.executor.cleanup = executor.cleanup
scm.default_branch = lambda repo: "main"
scm.open_pr = lambda repo, head, base, title, body: "https://github.com/tejbruhath/VaulS.ai/pull/7"
import sys  # noqa: E402
sys.modules["sentriq.scm"].default_branch = scm.default_branch
sys.modules["sentriq.scm"].open_pr = scm.open_pr


def make_fixture(target="https://github.com/tejbruhath/VaulS.ai", approved=True):
    Scan.objects.all().delete()
    scan = Scan.objects.create(pipeline=STATIC, target=target, status=Scan.COMPLETE)
    f = Finding.objects.create(scan=scan, tool="semgrep", pipeline=STATIC,
        type="sast", severity="high", severity_score=3, rule_id="sqli",
        message="SQL injection", file="app/s.py", line=3, fingerprint="fp1")
    fix = FixSuggestion.objects.create(finding=f, diff="--- a/app/s.py\n+++ b/app/s.py\n@@ -3 +3 @@\n-bad\n+good\n",
        explanation="use params", model="deepseek-v4-flash",
        status=FixSuggestion.APPROVED if approved else FixSuggestion.PROPOSED)
    return scan, f, fix


def main():
    # 1) happy path: approved fix -> create_pr task -> PR open
    scan, f, fix = make_fixture()
    res = tasks.create_pr(str(fix.id))
    fix.refresh_from_db()
    assert res["pr_status"] == "open", res
    assert fix.pr_status == FixSuggestion.PR_OPEN
    assert fix.pr_url.endswith("/pull/7")
    assert fix.branch == f"sentriq/fix-{str(f.id)[:8]}"
    assert ProvenanceEvent.objects.filter(event="PR opened").exists()

    # 2) unsupported repo URL -> failed, not crash
    scan2, f2, fix2 = make_fixture(target="https://gitlab.com/o/r.git")
    tasks.create_pr(str(fix2.id))
    fix2.refresh_from_db()
    assert fix2.pr_status == FixSuggestion.PR_FAILED and "unsupported" in fix2.pr_error

    # 3) endpoint guard: not-approved fix -> 409
    scan3, f3, fix3 = make_fixture(approved=False)
    c = Client()
    tasks.create_pr.delay = lambda *a, **k: None  # don't need a real broker
    r = c.post(f"/api/v1/findings/{f3.id}/pr")
    assert r.status_code == 409, r.status_code

    # 4) endpoint: approved fix -> 202 accepted
    fix3.status = FixSuggestion.APPROVED
    fix3.save()
    r = c.post(f"/api/v1/findings/{f3.id}/pr")
    assert r.status_code == 202, (r.status_code, r.content)

    print("PR-AUTOMATION TEST PASSED")
    print("  happy path pr_url:", fix.pr_url, "| branch:", fix.branch)
    print("  unsupported-repo ->", fix2.pr_status, "| guard 409 + accept 202 OK")


if __name__ == "__main__":
    main()
