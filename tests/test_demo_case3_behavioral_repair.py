"""Mocked regression test for post-install behavioral repair.

NOTE: This is a mocked regression test suite moved from demo_case3_behavioral_repair.py,
testing that SafeDep's post-install repair workflow handles behavioral incompatibilities
with mock test suites and mock propose_patch responses.
It is NOT an interactive user-facing demo (real demos live in examples/ and demo/).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.post_install_repair import (
    PostInstallIssue,
    PostInstallRepairReport,
    run_post_install_repair,
    run_pytest,
)


class TestDemoCase3BehavioralRepairRegression(unittest.TestCase):
    """Mocked regression test: behavioral repair on client application."""

    def _write_file(self, directory: Path, filename: str, content: str) -> Path:
        """Helper to create a temporary source file."""
        file_path = directory / filename
        file_path.write_text(content.strip(), encoding="utf-8")
        return file_path

    def test_behavioral_repair_repaired_successfully(self):
        """Test mocked behavioral regression: calculation rate mismatch auto-repaired."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            client_file = self._write_file(
                dir_path,
                "order_service.py",
                """
def calculate_shipping(weight: float) -> float:
    # Behavioral regression: rate multiplier was 1.5 in v1, now requires 2.0
    return weight * 1.5 + 10.0
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_orders.py",
                """
from order_service import calculate_shipping

def test_shipping_rate():
    # v2 expects 30.0 for 10kg (10.0 * 2.0 + 10.0)
    assert calculate_shipping(10.0) == 30.0
""",
            )

            def fake_patch(code_snippet, breaking_change_info, **kwargs):
                if "1.5" in code_snippet:
                    return "return weight * 2.0 + 10.0"
                return code_snippet

            with patch("safedep.post_install_repair.propose_patch", side_effect=fake_patch):
                report = run_post_install_repair(
                    test_target=test_file,
                    client_path=client_file,
                    cwd=dir_path,
                )

            self.assertFalse(report.initial_tests_passed)
            self.assertTrue(report.final_tests_passed)
            self.assertEqual(report.fixed_count, 1)
            self.assertEqual(report.failed_count, 0)
            self.assertIn("2.0", client_file.read_text(encoding="utf-8"))

    def test_behavioral_repair_reverts_on_unsuccessful_patch(self):
        """Test mocked behavioral regression: bad patch rejected and reverted."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            client_file = self._write_file(
                dir_path,
                "tax_service.py",
                """
def get_tax(amount: float) -> float:
    return amount * 0.10
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_tax.py",
                """
from tax_service import get_tax

def test_tax_rate():
    assert get_tax(100.0) == 20.0
""",
            )
            original_text = client_file.read_text(encoding="utf-8")

            def bad_patch(code_snippet, breaking_change_info, **kwargs):
                return "return amount * 0.99"

            with patch("safedep.post_install_repair.propose_patch", side_effect=bad_patch):
                report = run_post_install_repair(
                    test_target=test_file,
                    client_path=client_file,
                    max_retries=2,
                    cwd=dir_path,
                )

            self.assertFalse(report.initial_tests_passed)
            self.assertFalse(report.final_tests_passed)
            self.assertEqual(report.fixed_count, 0)
            self.assertEqual(report.failed_count, 1)
            self.assertEqual(client_file.read_text(encoding="utf-8"), original_text)


if __name__ == "__main__":
    unittest.main()
