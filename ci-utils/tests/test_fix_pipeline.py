"""Fix generation: fixes generated during a scan stay proposed.

Run:
  USE_SQLITE=1 python manage.py test tests.test_fix_pipeline
"""
from unittest.mock import patch  # mock LLM calls

from django.test import TestCase  # Django TestCase with DB

from sentriq import config, deepseek  # config flag + LLM module
from sentriq.deepseek import TriageResult, FixResult  # fake LLM return types
from sentriq.models import Scan, Finding, FixSuggestion, HitlAction, Triage
from sentriq.tasks import _triage_and_fix  # function under test


class FixPipelineTests(TestCase):
    """Triage + optional fix creation paths for a single finding."""

    def setUp(self):
        self.scan = Scan.objects.create(
            pipeline="static", target="git@x/repo", auto_fix_severity="low")  # allow low+
        self.finding = Finding.objects.create(
            scan=self.scan, tool="semgrep", pipeline="static", type="sast",
            severity="high", severity_score=100, rule_id="R1", message="m",
            fingerprint="fp1")  # eligible for fix

    @patch.object(deepseek, "generate_fix",
                  return_value=FixResult(diff="--- a\n+++ b\n", explanation="x", ok=True))  # fake patch
    @patch.object(deepseek, "triage",
                  return_value=TriageResult("real", 0.9, "why", {}))  # real verdict
    def test_real_noncritical_finding_gets_proposed_fix(self, *_mocks):
        with patch.object(config, "LLM_ENABLED", True):  # AI on
            _triage_and_fix(self.scan, [self.finding], work_dir="/nonexistent")  # no source needed

        self.assertEqual(Triage.objects.filter(finding=self.finding).count(), 1)  # triage row
        fix = FixSuggestion.objects.get(finding=self.finding)  # one fix created
        self.assertEqual(fix.status, FixSuggestion.PROPOSED)  # not auto-approved
        self.assertFalse(
            HitlAction.objects.filter(
                finding=self.finding, action=HitlAction.APPROVE).exists())  # no silent approve

    @patch.object(deepseek, "generate_fix",
                  return_value=FixResult(diff="--- a\n+++ b\n", explanation="x", ok=True))
    @patch.object(deepseek, "triage",
                  return_value=TriageResult("real", 0.9, "why", {}))
    def test_autofix_none_still_triages(self, _triage_mock, fix_mock):
        """auto_fix_severity='none' means "don't write patches", not "don't think"."""
        self.scan.auto_fix_severity = "none"  # disable fix generation
        self.scan.save(update_fields=["auto_fix_severity"])

        with patch.object(config, "LLM_ENABLED", True):
            _triage_and_fix(self.scan, [self.finding], work_dir="/nonexistent")

        self.assertEqual(Triage.objects.filter(finding=self.finding).count(), 1)  # triage still runs
        self.assertFalse(FixSuggestion.objects.filter(finding=self.finding).exists())  # no fix
        fix_mock.assert_not_called()  # generate_fix skipped
