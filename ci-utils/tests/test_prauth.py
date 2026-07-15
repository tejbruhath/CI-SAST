"""Tests for PR auth (per-user OAuth token) and fix-request throttling.

Run:
  USE_SQLITE=1 python manage.py test tests.test_prauth
"""
import os
import tempfile
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from sentriq import crypto, executor, tasks
from sentriq.deepseek import FixResult
from sentriq.models import Finding, FixSuggestion, Scan, UserProfile


User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PrAuthTests(TestCase):
    def setUp(self):
        if not crypto._token_key:
            crypto._token_key = Fernet.generate_key().decode()
        cache.clear()
        self.user = User.objects.create_user(username="pruser", password="pruser")
        self.client.force_login(self.user)

    def tearDown(self):
        cache.clear()

    def _github_scan(self):
        return Scan.objects.create(
            pipeline="static",
            target="https://github.com/owner/repo.git",
            status=Scan.COMPLETE,
            requested_by=self.user,
            finished_at=timezone.now())

    def _finding(self, scan, **kwargs):
        defaults = {
            "scan": scan, "tool": "semgrep", "pipeline": "static", "type": "sast",
            "severity": "high", "severity_score": 100, "rule_id": "sqli",
            "message": "SQL injection", "file": "app/s.py", "line": 3,
            "fingerprint": str(uuid.uuid4()),
        }
        defaults.update(kwargs)
        return Finding.objects.create(**defaults)

    def _approved_fix(self, finding):
        return FixSuggestion.objects.create(
            finding=finding,
            diff="--- a/app/s.py\n+++ b/app/s.py\n@@ -1 +1 @@\n-bad\n+good\n",
            explanation="use parameterized query",
            status=FixSuggestion.APPROVED)

    def _make_scratch(self):
        work_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(work_dir, "app"), exist_ok=True)
        with open(os.path.join(work_dir, "app", "s.py"), "w") as f:
            f.write("bad\n")
        return work_dir

    @patch.object(executor, "cleanup")
    @patch.object(executor, "make_scratch")
    @patch("sentriq.scm.open_pr")
    @patch("sentriq.scm.default_branch")
    @patch.object(executor, "apply_fix_and_push")
    def test_create_pr_uses_user_oauth_token(
            self, push_mock, branch_mock, open_pr_mock, scratch_mock, cleanup_mock):
        """When user_id is passed, GitHub API calls use the decrypted OAuth token."""
        UserProfile.objects.create(
            user=self.user,
            github_id="42",
            github_login="pruser",
            github_access_token=crypto.encrypt_token("gho_user_token"))

        scan = self._github_scan()
        finding = self._finding(scan)
        fix = self._approved_fix(finding)

        scratch_mock.return_value = self._make_scratch()
        branch_mock.return_value = "main"
        open_pr_mock.return_value = "https://github.com/owner/repo/pull/1"

        result = tasks.create_pr(str(fix.id), user_id=self.user.id)

        self.assertEqual(result["pr_status"], "open")
        branch_mock.assert_called_once()
        open_pr_mock.assert_called_once()
        _, kwargs_branch = branch_mock.call_args
        _, kwargs_open = open_pr_mock.call_args
        self.assertEqual(kwargs_branch.get("token"), "gho_user_token")
        self.assertEqual(kwargs_open.get("token"), "gho_user_token")

    @patch.object(executor, "cleanup")
    @patch.object(executor, "make_scratch")
    @patch("sentriq.scm.open_pr")
    @patch("sentriq.scm.default_branch")
    @patch.object(executor, "apply_fix_and_push")
    def test_create_pr_without_user_falls_back_to_shared_token(
            self, push_mock, branch_mock, open_pr_mock, scratch_mock, cleanup_mock):
        """Calling create_pr without a user_id still works via the shared PAT."""
        scan = self._github_scan()
        finding = self._finding(scan)
        fix = self._approved_fix(finding)

        scratch_mock.return_value = self._make_scratch()
        branch_mock.return_value = "main"
        open_pr_mock.return_value = "https://github.com/owner/repo/pull/1"

        result = tasks.create_pr(str(fix.id))

        self.assertEqual(result["pr_status"], "open")
        open_pr_mock.assert_called_once()
        _, kwargs_open = open_pr_mock.call_args
        # No per-user token was supplied; scm falls back to config.GIT_TOKEN.
        self.assertIsNone(kwargs_open.get("token"))

    def test_finding_fix_throttled_returns_429(self):
        """Excessive POSTs to /findings/<id>/fix are rejected with 429."""
        from sentriq import views
        original_rate = views.FixRequestThrottle.rate
        views.FixRequestThrottle.rate = "1/minute"
        self.addCleanup(setattr, views.FixRequestThrottle, "rate", original_rate)

        scan = self._github_scan()
        finding = self._finding(scan)

        work_dir = self._make_scratch()
        with patch.object(executor, "make_scratch", return_value=work_dir), \
             patch.object(executor, "git_clone", return_value=None), \
             patch.object(executor, "cleanup", return_value=None), \
             patch("sentriq.deepseek.generate_fix", return_value=FixResult(
                 diff="--- a/app/s.py\n+++ b/app/s.py\n@@ -1 +1 @@\n-bad\n+good\n",
                 explanation="use parameterized query", ok=True)):
            r1 = self.client.post(f"/api/v1/findings/{finding.id}/fix",
                                  content_type="application/json")
            self.assertEqual(r1.status_code, 202)

            r2 = self.client.post(f"/api/v1/findings/{finding.id}/fix",
                                  content_type="application/json")
            self.assertEqual(r2.status_code, 429)
