"""On-demand AI fix API + orphan reaper tests.

Run:
  USE_SQLITE=1 python manage.py test tests.test_fixapi
"""
import os
import tempfile
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from sentriq import deepseek, executor, tasks
from sentriq.deepseek import FixResult
from sentriq.models import Finding, FixSuggestion, Scan, ProvenanceEvent


User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class FixApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testfix", password="testfix")
        self.client.force_login(self.user)

    def _complete_scan(self):
        return Scan.objects.create(
            pipeline=Scan.QUEUED, target="https://example.com/repo.git",
            status=Scan.COMPLETE, requested_by=self.user, finished_at=timezone.now())

    def _finding(self, scan, **kwargs):
        defaults = {
            "scan": scan, "tool": "semgrep", "pipeline": "static", "type": "sast",
            "severity": "high", "severity_score": 100, "rule_id": "sqli",
            "message": "SQL injection", "file": "app/s.py", "line": 3,
            "fingerprint": str(uuid.uuid4()),
        }
        defaults.update(kwargs)
        return Finding.objects.create(**defaults)

    @patch.object(executor, "cleanup")
    @patch.object(executor, "git_clone")
    @patch.object(executor, "make_scratch")
    @patch("sentriq.deepseek.generate_fix")
    def test_post_fix_returns_202_and_creates_proposed_suggestion(
            self, gen_mock, scratch_mock, clone_mock, cleanup_mock):
        """Clicking 'Fix with AI' queues generation and stores a PROPOSED fix."""
        scan = self._complete_scan()
        finding = self._finding(scan)

        work_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(work_dir, "app"), exist_ok=True)
        with open(os.path.join(work_dir, "app", "s.py"), "w") as f:
            f.write("bad\n")
        scratch_mock.return_value = work_dir
        clone_mock.return_value = None
        cleanup_mock.return_value = None
        gen_mock.return_value = FixResult(
            diff="--- a/app/s.py\n+++ b/app/s.py\n@@ -1 +1 @@\n-bad\n+good\n",
            explanation="use parameterized query", ok=True)

        r = self.client.post(f"/api/v1/findings/{finding.id}/fix",
                             content_type="application/json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["status"], "queued")

        fix = FixSuggestion.objects.get(finding=finding)
        self.assertEqual(fix.status, FixSuggestion.PROPOSED)
        self.assertTrue(fix.diff)
        gen_mock.assert_called_once()
        self.assertTrue(
            ProvenanceEvent.objects.filter(
                finding=finding, stage=ProvenanceEvent.FIX,
                event="on-demand fix generated").exists())
        cleanup_mock.assert_called_once_with(work_dir)

    @patch.object(executor, "cleanup")
    @patch.object(executor, "git_clone")
    @patch.object(executor, "make_scratch")
    @patch("sentriq.deepseek.generate_fix")
    def test_post_fix_is_idempotent(
            self, gen_mock, scratch_mock, clone_mock, cleanup_mock):
        """A second click reuses the existing fix instead of creating a duplicate."""
        scan = self._complete_scan()
        finding = self._finding(scan)

        work_dir = tempfile.mkdtemp()
        scratch_mock.return_value = work_dir
        clone_mock.return_value = None
        cleanup_mock.return_value = None
        gen_mock.return_value = FixResult(
            diff="--- a/app/s.py\n+++ b/app/s.py\n@@ -1 +1 @@\n-bad\n+good\n",
            explanation="use parameterized query", ok=True)

        self.client.post(f"/api/v1/findings/{finding.id}/fix",
                         content_type="application/json")
        first = FixSuggestion.objects.get(finding=finding)

        self.client.post(f"/api/v1/findings/{finding.id}/fix",
                         content_type="application/json")
        self.assertEqual(FixSuggestion.objects.filter(finding=finding).count(), 1)
        self.assertEqual(FixSuggestion.objects.get(finding=finding).id, first.id)
        gen_mock.assert_called_once()

    def test_findings_filtered_to_finished_scans(self):
        """Findings from running/queued scans are hidden until triage completes."""
        running_scan = Scan.objects.create(
            pipeline=Scan.QUEUED, target="https://example.com/running.git",
            status=Scan.RUNNING, requested_by=self.user)
        complete_scan = Scan.objects.create(
            pipeline=Scan.QUEUED, target="https://example.com/done.git",
            status=Scan.COMPLETE, requested_by=self.user,
            finished_at=timezone.now())

        running_finding = self._finding(running_scan, fingerprint="running")
        complete_finding = self._finding(complete_scan, fingerprint="done")

        r = self.client.get("/api/v1/findings")
        self.assertEqual(r.status_code, 200)
        ids = {f["id"] for f in r.json()}
        self.assertNotIn(str(running_finding.id), ids)
        self.assertIn(str(complete_finding.id), ids)

    @patch("django.conf.settings.CELERY_TASK_TIME_LIMIT", 3600)
    def test_reap_orphaned_scans(self):
        """Stale RUNNING scans become FAILED; fresh ones are left alone."""
        now = timezone.now()
        stale = Scan.objects.create(
            pipeline=Scan.QUEUED, target="https://example.com/stale.git",
            status=Scan.RUNNING, requested_by=self.user, created_at=now)
        # Override created_at after create (auto_now_add would set it to now).
        Scan.objects.filter(id=stale.id).update(
            created_at=now - timezone.timedelta(seconds=7200))

        fresh = Scan.objects.create(
            pipeline=Scan.QUEUED, target="https://example.com/fresh.git",
            status=Scan.RUNNING, requested_by=self.user)

        result = tasks.reap_orphaned_scans()
        self.assertEqual(result["reaped"], 1)

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.status, Scan.FAILED)
        self.assertEqual(stale.error, "orphaned: worker died mid-scan")
        self.assertIsNotNone(stale.finished_at)
        self.assertEqual(fresh.status, Scan.RUNNING)
        self.assertTrue(
            ProvenanceEvent.objects.filter(
                scan=stale, stage=ProvenanceEvent.SCAN,
                event="orphaned scan reaped").exists())

    @patch.object(executor, "cleanup")
    @patch.object(executor, "git_clone")
    @patch.object(executor, "make_scratch")
    @patch("sentriq.deepseek.generate_fix")
    def test_post_fix_persists_failed_suggestion(
            self, gen_mock, scratch_mock, clone_mock, cleanup_mock):
        """Failed generation still creates a FAILED fix so the UI can clear FIXING."""
        scan = self._complete_scan()
        finding = self._finding(scan)
        work_dir = tempfile.mkdtemp()
        scratch_mock.return_value = work_dir
        clone_mock.return_value = None
        cleanup_mock.return_value = None
        gen_mock.return_value = FixResult(diff="", explanation="no match", ok=False)

        r = self.client.post(f"/api/v1/findings/{finding.id}/fix",
                             content_type="application/json")
        self.assertEqual(r.status_code, 202)
        fix = FixSuggestion.objects.get(finding=finding)
        self.assertEqual(fix.status, FixSuggestion.FAILED)
        self.assertEqual(fix.explanation, "no match")

    @patch.object(executor, "cleanup")
    @patch.object(executor, "git_clone")
    @patch.object(executor, "make_scratch")
    @patch("sentriq.deepseek.generate_fix")
    def test_post_fix_retries_after_failed(
            self, gen_mock, scratch_mock, clone_mock, cleanup_mock):
        """RETRY after FAILED deletes the failed row and stores a new proposal."""
        scan = self._complete_scan()
        finding = self._finding(scan)
        work_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(work_dir, "app"), exist_ok=True)
        with open(os.path.join(work_dir, "app", "s.py"), "w") as f:
            f.write("bad\n")
        scratch_mock.return_value = work_dir
        clone_mock.return_value = None
        cleanup_mock.return_value = None
        gen_mock.side_effect = [
            FixResult(diff="", explanation="no match", ok=False),
            FixResult(diff="--- a/app/s.py\n+++ b/app/s.py\n@@ -1 +1 @@\n-bad\n+good\n",
                      explanation="fixed", ok=True),
        ]
        self.client.post(f"/api/v1/findings/{finding.id}/fix",
                         content_type="application/json")
        self.assertEqual(FixSuggestion.objects.get(finding=finding).status,
                         FixSuggestion.FAILED)
        self.client.post(f"/api/v1/findings/{finding.id}/fix",
                         content_type="application/json")
        fix = FixSuggestion.objects.get(finding=finding)
        self.assertEqual(fix.status, FixSuggestion.PROPOSED)
        self.assertTrue(fix.diff)
        self.assertEqual(gen_mock.call_count, 2)
