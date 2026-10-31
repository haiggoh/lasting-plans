#!/usr/bin/env python3
"""Branding (branding/credit-moments): the GitHub-About mark 📜 leads every user-facing
emit line of lasting-plans (hook systemMessage, CLI PREFIX lines, --help banner).

Usage: python3 tests/test_branding.py [-v]
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
from lasting_plans import PREFIX  # noqa: E402

CLI = ROOT / "bin" / "lasting-plans"


class BrandingTests(unittest.TestCase):
    def test_prefix_is_exactly_the_about_mark(self):
        # exact pin — never loosened to a substring
        self.assertEqual(PREFIX, "📜 Lasting Plans")

    def test_cli_help_banner_carries_the_mark_not_the_old_glyph(self):
        r = subprocess.run([sys.executable, str(CLI), "--help"],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("📜 Lasting Plans", r.stdout)
        self.assertNotIn("🗂️", r.stdout)

    def test_cli_status_banner_leads_with_the_mark(self):
        r = subprocess.run([sys.executable, str(CLI), "status"],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.splitlines()[0].startswith("📜 Lasting Plans "),
                        r.stdout.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
