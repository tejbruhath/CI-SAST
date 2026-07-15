"""One PR, containing exactly what the user approved — and nothing else.

The whole point of the approval gate is that unapproved AI output can never
reach a pull request. That is the property these tests pin.

  USE_SQLITE=1 python manage.py test tests.test_batch_pr
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from sentriq import executor, scm as scm_mod, tasks
from sentriq.models import Finding, FixSuggestion, Scan


def _fix(scan, tool, sev, score, status):
    f = Finding.objects.create(
        scan=scan, tool=tool, pipeline="static", type="vulnerability",
        severity=sev, severity_score=score, rule_id=f"CVE-{tool}",
        message="m", file="requirements.txt", fingerprint=f"fp-{tool}")
    return FixSuggestion.objects.create(
        finding=f, diff=f"--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1 +1 @@\n-{tool}\n+{tool}2\n",
        explanation="bump", status=status)


class BatchPrTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tej")
        self.scan = Scan.objects.create(
            pipeline="static", target="https://github.com/o/r",
            status=Scan.COMPLETE, requested_by=self.user)
        self.approved = _fix(self.scan, "trivy", "high", 3, FixSuggestion.APPROVED)
        self.proposed = _fix(self.scan, "semgrep", "critical", 4, FixSuggestion.PROPOSED)

    def _run(self):
        with patch.object(scm_mod, "parse_repo") as parse_repo, \
             patch.object(scm_mod, "default_branch", return_value="main"), \
             patch.object(scm_mod, "open_pr", return_value="https://github.com/o/r/pull/1") as open_pr, \
             patch.object(executor, "apply_fix_and_push") as push, \
             patch.object(executor, "make_scratch", return_value="/tmp/x"), \
             patch.object(executor, "cleanup"):
            parse_repo.return_value = object()
            push.side_effect = lambda *a, **k: [lbl for lbl, _ in a[3]]
            res = tasks.create_batch_pr("o/r", user_id=self.user.id)
            return res, push, open_pr

    def test_only_approved_fixes_are_included(self):
        res, push, _ = self._run()
        self.assertEqual(res["status"], "open")
        self.assertEqual(res["count"], 1)
        # the patches handed to git: approved only, never the proposed one
        patches = push.call_args[0][3]
        labels = " ".join(lbl for lbl, _ in patches)
        self.assertIn("trivy", labels)
        self.assertNotIn("semgrep", labels, "an UNAPPROVED fix reached the PR")

        self.approved.refresh_from_db()
        self.proposed.refresh_from_db()
        self.assertEqual(self.approved.pr_status, FixSuggestion.PR_OPEN)
        self.assertEqual(self.proposed.pr_status, FixSuggestion.PR_NONE)

    def test_all_approved_fixes_share_one_branch_and_pr(self):
        second = _fix(self.scan, "gitleaks", "critical", 4, FixSuggestion.APPROVED)
        res, push, open_pr = self._run()
        self.assertEqual(res["count"], 2)
        self.assertEqual(open_pr.call_count, 1, "should be ONE PR, not one per fix")
        second.refresh_from_db()
        self.approved.refresh_from_db()
        self.assertEqual(second.branch, self.approved.branch)
        self.assertEqual(second.pr_url, res["pr_url"])

    def test_nothing_approved_is_a_noop(self):
        self.approved.status = FixSuggestion.PROPOSED
        self.approved.save(update_fields=["status"])
        with patch.object(scm_mod, "open_pr") as open_pr:
            res = tasks.create_batch_pr("o/r", user_id=self.user.id)
        self.assertEqual(res["status"], "empty")
        open_pr.assert_not_called()

    def test_already_shipped_fixes_are_not_reopened(self):
        self.approved.pr_status = FixSuggestion.PR_OPEN
        self.approved.save(update_fields=["pr_status"])
        self.proposed.delete()
        res = tasks.create_batch_pr("o/r", user_id=self.user.id)
        self.assertEqual(res["status"], "empty")

    def test_endpoint_returns_pr_url_and_branch(self):
        self.client.force_login(self.user)
        with patch.object(tasks, "create_batch_pr",
                          return_value={"status": "open", "pr_url": "u",
                                        "branch": "b", "count": 1}):
            r = self.client.post("/api/v1/pr", data={"repo": "o/r"},
                                 content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["branch"], "b")

    def test_endpoint_409s_when_nothing_approved(self):
        self.client.force_login(self.user)
        with patch.object(tasks, "create_batch_pr",
                          return_value={"status": "empty", "count": 0}):
            r = self.client.post("/api/v1/pr", data={"repo": "o/r"},
                                 content_type="application/json")
        self.assertEqual(r.status_code, 409)
