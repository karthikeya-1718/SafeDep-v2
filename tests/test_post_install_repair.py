"""Unit tests for SafeDep post_install_repair module."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.post_install_repair import (
    PostInstallIssue,
    PostInstallRepairReport,
    TestSuiteResult,
    apply_line_patch,
    format_post_install_report,
    identify_test_failures,
    run_post_install_repair,
    run_pytest,
)


class TestPostInstallRepair(unittest.TestCase):
    """Test suite for Post-Install Repair mode."""

    def _write_file(self, directory: Path, filename: str, content: str) -> Path:
        """Helper to create a temporary source file."""
        file_path = directory / filename
        file_path.write_text(content.strip(), encoding="utf-8")
        return file_path

    def test_run_pytest_passing(self):
        """Test running a passing pytest suite."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            test_file = self._write_file(
                dir_path,
                "test_example.py",
                """
def test_ok():
    assert 1 + 1 == 2
""",
            )
            result = run_pytest(test_file)
            self.assertTrue(result.passed)
            self.assertEqual(result.failed_count, 0)
            self.assertEqual(len(result.failed_test_names), 0)

    def test_run_pytest_failing(self):
        """Test running a failing pytest suite."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            test_file = self._write_file(
                dir_path,
                "test_fail.py",
                """
def test_bad():
    assert 1 == 2
""",
            )
            result = run_pytest(test_file)
            self.assertFalse(result.passed)
            self.assertGreaterEqual(result.failed_count, 1)
            self.assertTrue(any("test_bad" in name for name in result.failed_test_names))

    def test_identify_test_failures_parsing(self):
        """Test parsing pytest detailed failure blocks and summary."""
        sample_output = """
=================================== FAILURES ===================================
___________________________________ test_tax ___________________________________

    def test_tax():
>       assert calculate_tax(100.0) == 15.0
E       AssertionError: assert 20.0 == 15.0
E        +  where 20.0 = calculate_tax(100.0)

test_client.py:6: AssertionError
=========================== short test summary info ============================
FAILED test_client.py::test_tax - AssertionError: assert 20.0 == 15.0
============================== 1 failed in 0.05s ===============================
"""
        issues = identify_test_failures(sample_output)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.test_name, "test_tax")
        self.assertEqual(issue.error_type, "AssertionError")
        self.assertIn("20.0 == 15.0", issue.error_message)
        self.assertEqual(issue.line_number, 6)
        self.assertIn("calculate_tax(100.0) == 15.0", issue.call_expression)

    def test_apply_line_patch_success_and_revert(self):
        """Test applying a patch to a line and reverting it."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            app_file = self._write_file(
                dir_path,
                "app.py",
                """
def get_rate():
    return 0.20
""",
            )
            initial_content = app_file.read_text(encoding="utf-8")

            # Apply patch
            ok, original, modified = apply_line_patch(
                app_file,
                line_number=2,
                old_code="return 0.20",
                new_code="return 0.15",
            )
            self.assertTrue(ok)
            self.assertIn("return 0.15", app_file.read_text(encoding="utf-8"))

            # Revert to original
            app_file.write_text(original, encoding="utf-8")
            self.assertEqual(app_file.read_text(encoding="utf-8"), initial_content)

    def test_run_post_install_repair_all_passing_initially(self):
        """Test Post-Install Repair when all tests already pass."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            test_file = self._write_file(
                dir_path,
                "test_pass.py",
                """
def test_success():
    assert True
""",
            )
            report = run_post_install_repair(test_target=test_file)
            self.assertTrue(report.initial_tests_passed)
            self.assertTrue(report.final_tests_passed)
            self.assertEqual(report.total_issues_detected, 0)
            self.assertEqual(report.fixed_count, 0)
            self.assertEqual(report.failed_count, 0)

    def test_run_post_install_repair_successful_gated_fix(self):
        """Test test-gated fix: behavioral incompatibility repaired and tests pass."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            client_file = self._write_file(
                dir_path,
                "calculator.py",
                """
def compute_discount(price: float) -> float:
    return price * 0.20
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_calc.py",
                f"""
from calculator import compute_discount

def test_discount():
    # In v2.0 library, expected discount rate changed to 0.15
    assert compute_discount(100.0) == 15.0
""",
            )

            # Mock propose_patch to return the fix
            def fake_propose_patch(code_snippet, breaking_change_info, **kwargs):
                if "0.20" in code_snippet:
                    return "return price * 0.15"
                return code_snippet

            with patch("safedep.post_install_repair.propose_patch", side_effect=fake_propose_patch):
                report = run_post_install_repair(
                    test_target=test_file,
                    client_path=client_file,
                    cwd=dir_path,
                )

            self.assertFalse(report.initial_tests_passed)
            self.assertTrue(report.final_tests_passed)
            self.assertEqual(report.fixed_count, 1)
            self.assertEqual(report.failed_count, 0)
            self.assertIn("return price * 0.15", client_file.read_text(encoding="utf-8"))

            # Backup should exist
            bak_file = client_file.with_suffix(".py.bak")
            self.assertTrue(bak_file.exists())

    def test_run_post_install_repair_reverts_on_failing_patch(self):
        """Test test-gated rollback: bad patch is rejected and file reverted."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            client_file = self._write_file(
                dir_path,
                "service.py",
                """
def get_status():
    return "DOWN"
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_service.py",
                """
from service import get_status

def test_status():
    assert get_status() == "UP"
""",
            )
            original_code = client_file.read_text(encoding="utf-8")

            # Mock propose_patch to return a patch that still fails
            def bad_patch(code_snippet, breaking_change_info, **kwargs):
                return 'return "STILL_WRONG"'

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

            # Ensure file was reverted!
            self.assertEqual(client_file.read_text(encoding="utf-8"), original_code)
            self.assertEqual(report.failed_issues[0].attempt_count, 2)

    def test_format_post_install_report_content(self):
        """Test report formatting contains all required sections and notes."""
        report = PostInstallRepairReport(
            initial_tests_passed=False,
            final_tests_passed=True,
            total_issues_detected=1,
            fixed_count=1,
            failed_count=0,
            fixed_issues=[
                PostInstallIssue(
                    test_name="tests/test_api.py::test_rate",
                    file_path="app.py",
                    line_number=10,
                    call_expression="get_rate(0.20)",
                    error_type="AssertionError",
                    error_message="assert 0.20 == 0.15",
                    attempt_count=1,
                    fixed=True,
                    proposed_fix="get_rate(0.15)",
                    patch_diff="- get_rate(0.20)\n+ get_rate(0.15)",
                )
            ],
            failed_issues=[],
        )

        formatted = format_post_install_report(report)
        self.assertIn("SAFEDEP - POST-INSTALL REPAIR REPORT (TEST-GATED)", formatted)
        self.assertIn("IMPORTANT NOTE ON POST-INSTALL REPAIR:", formatted)
        self.assertIn("BEHAVIORAL and runtime incompatibilities", formatted)
        self.assertIn("TEST-GATED", formatted)
        self.assertIn("Maximum 2 retries per issue", formatted)
        self.assertIn("[+] RESOLVED BEHAVIORAL ISSUES (1):", formatted)
        self.assertIn("get_rate(0.15)", formatted)


if __name__ == "__main__":
    unittest.main()

