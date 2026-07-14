"""Fix generation: fixes generated during a scan stay proposed.

Run:
  USE_SQLITE=1 python manage.py test sentriq.test_fix_pipeline
"""
from unittest.mock import patch

from django.test import TestCase

from . import config, deepseek
from .deepseek import TriageResult, FixResult
from .models import Scan, Finding, FixSuggestion, HitlAction, Triage
from .tasks import _triage_and_fix


class FixPipelineTests(TestCase):
    def setUp(self):
        self.scan = Scan.objects.create(
            pipeline="static", target="git@x/repo", auto_fix_severity="low")
        self.finding = Finding.objects.create(
            scan=self.scan, tool="semgrep", pipeline="static", type="sast",
            severity="high", severity_score=100, rule_id="R1", message="m",
            fingerprint="fp1")

    @patch.object(deepseek, "generate_fix",
                  return_value=FixResult(diff="--- a\n+++ b\n", explanation="x", ok=True))
    @patch.object(deepseek, "triage",
                  return_value=TriageResult("real", 0.9, "why", {}))
    def test_real_noncritical_finding_gets_proposed_fix(self, *_mocks):
        with patch.object(config, "LLM_ENABLED", True):
            _triage_and_fix(self.scan, [self.finding], work_dir="/nonexistent")

        self.assertEqual(Triage.objects.filter(finding=self.finding).count(), 1)
        fix = FixSuggestion.objects.get(finding=self.finding)
        self.assertEqual(fix.status, FixSuggestion.PROPOSED)
        self.assertFalse(
            HitlAction.objects.filter(
                finding=self.finding, action=HitlAction.APPROVE).exists())

    @patch.object(deepseek, "generate_fix",
                  return_value=FixResult(diff="--- a\n+++ b\n", explanation="x", ok=True))
    @patch.object(deepseek, "triage",
                  return_value=TriageResult("real", 0.9, "why", {}))
    def test_autofix_none_still_triages(self, _triage_mock, fix_mock):
        """auto_fix_severity='none' means "don't write patches", not "don't think"."""
        self.scan.auto_fix_severity = "none"
        self.scan.save(update_fields=["auto_fix_severity"])

        with patch.object(config, "LLM_ENABLED", True):
            _triage_and_fix(self.scan, [self.finding], work_dir="/nonexistent")

        self.assertEqual(Triage.objects.filter(finding=self.finding).count(), 1)
        self.assertFalse(FixSuggestion.objects.filter(finding=self.finding).exists())
        fix_mock.assert_not_called()
