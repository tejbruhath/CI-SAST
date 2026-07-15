"""Fix diffs must actually apply to the real file.

Every diff the LLM authored by hand failed `git apply` (wrong hunk headers,
invented context), so the diff is now computed from the file with difflib and
the LLM only chooses the text to swap. This test guards that: the diff must
apply cleanly to a real git repo.

  USE_SQLITE=1 python manage.py test tests.test_fix_diff
"""
import os
import subprocess
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from sentriq import deepseek

REQUIREMENTS = (
    "Django==4.2.13\n"
    "djangorestframework==3.14.0\n"
    "celery==5.3.4\n"
    "gunicorn==21.2.0\n"
    "numpy==1.24.3\n"
)

FINDING = {"tool": "trivy", "type": "vulnerability", "severity": "high",
           "rule_id": "CVE-2024-6827", "message": "gunicorn TE smuggling",
           "file": "requirements.txt", "line": None}


class FixDiffTests(SimpleTestCase):
    def _apply(self, diff: str, content: str = REQUIREMENTS) -> subprocess.CompletedProcess:
        """Write content into a real git repo and try to apply diff to it."""
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "requirements.txt"), "w") as f:
            f.write(content)
        for args in (["init", "-q"], ["add", "-A"]):
            subprocess.run(["git", *args], cwd=d, check=True, capture_output=True)
        with open(os.path.join(d, "p.patch"), "w") as f:
            f.write(diff if diff.endswith("\n") else diff + "\n")
        return subprocess.run(["git", "apply", "--check", "p.patch"],
                              cwd=d, capture_output=True, text=True)

    @patch.object(deepseek, "_chat")
    def test_diff_applies_to_real_file(self, chat):
        chat.return_value = {"old_str": "gunicorn==21.2.0",
                             "new_str": "gunicorn==22.0.0",
                             "explanation": "bump"}
        fx = deepseek.generate_fix(FINDING, file_text=REQUIREMENTS)
        self.assertTrue(fx.ok, fx.explanation)
        res = self._apply(fx.diff)
        self.assertEqual(res.returncode, 0, f"diff did not apply:\n{fx.diff}\n{res.stderr}")
        self.assertIn("-gunicorn==21.2.0", fx.diff)
        self.assertIn("+gunicorn==22.0.0", fx.diff)

    @patch.object(deepseek, "_chat")
    def test_hallucinated_anchor_is_rejected(self, chat):
        """An old_str not present in the file must fail loudly, not ship a bad diff."""
        chat.return_value = {"old_str": "flask==2.3.2", "new_str": "flask==3.0.0",
                             "explanation": "bump"}
        fx = deepseek.generate_fix(FINDING, file_text=REQUIREMENTS)
        self.assertFalse(fx.ok)
        self.assertEqual(fx.diff, "")

    @patch.object(deepseek, "_chat")
    def test_ambiguous_anchor_is_rejected(self, chat):
        """old_str matching multiple places is unsafe to swap blind."""
        chat.return_value = {"old_str": "x==1\n", "new_str": "x==2\n", "explanation": ""}
        fx = deepseek.generate_fix(FINDING, file_text="x==1\nx==1\n")
        self.assertFalse(fx.ok)

    @patch.object(deepseek, "_chat")
    def test_no_fix_available(self, chat):
        chat.return_value = {"old_str": "", "new_str": "", "explanation": "cannot fix"}
        fx = deepseek.generate_fix(FINDING, file_text=REQUIREMENTS)
        self.assertFalse(fx.ok)
        self.assertEqual(fx.diff, "")
