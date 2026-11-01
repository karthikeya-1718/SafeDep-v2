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
from safedep.pre_install_repair import run_pre_install_repair


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
        self.assertIn("WHAT WAS FIXED", formatted)
        self.assertIn("Retries Used: Attempt 1 of 2", formatted)
        self.assertIn("get_rate(0.15)", formatted)

    def test_symbol_mapping_with_variable_assignment(self):
        """Test mapping test failure when variable assignment precedes assertion."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            client_file = self._write_file(
                dir_path,
                "billing.py",
                """
def calculate_charge(amount: float) -> float:
    rate = 0.20  # Fix: rate = 0.15
    return amount * rate
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_billing.py",
                """
from billing import calculate_charge

def test_charge():
    charge = calculate_charge(100.0)
    assert charge == 15.0
""",
            )

            def fake_propose_patch(code_snippet, breaking_change_info, **kwargs):
                if "0.20" in code_snippet:
                    return "rate = 0.15"
                return code_snippet

            with patch("safedep.post_install_repair.propose_patch", side_effect=fake_propose_patch):
                report = run_post_install_repair(
                    test_target=test_file,
                    client_path=client_file,
                    cwd=dir_path,
                )

            self.assertTrue(report.final_tests_passed)
            self.assertEqual(report.fixed_count, 1)
            self.assertIn("rate = 0.15", client_file.read_text(encoding="utf-8"))

    def test_retry_capped_at_two_and_full_reversion(self):
        """Test that retries are strictly capped at 2 and file is bit-for-bit reverted on failure."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            client_file = self._write_file(
                dir_path,
                "handler.py",
                """
def handle_event():
    return "INITIAL_STATE"
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_handler.py",
                """
from handler import handle_event

def test_event():
    assert handle_event() == "CORRECT_VALUE"
""",
            )
            original_code = client_file.read_text(encoding="utf-8")

            call_count = 0

            def failing_patch(code_snippet, breaking_change_info, **kwargs):
                nonlocal call_count
                call_count += 1
                return f'return "WRONG_ATTEMPT_{call_count}"'

            with patch("safedep.post_install_repair.propose_patch", side_effect=failing_patch):
                # Pass max_retries=10 -> must be capped at 2!
                report = run_post_install_repair(
                    test_target=test_file,
                    client_path=client_file,
                    max_retries=10,
                    cwd=dir_path,
                )

            self.assertFalse(report.final_tests_passed)
            self.assertEqual(report.fixed_count, 0)
            self.assertEqual(report.failed_count, 1)
            self.assertEqual(report.max_retries, 2)
            self.assertEqual(call_count, 2)
            self.assertEqual(report.failed_issues[0].attempt_count, 2)
            self.assertTrue(report.failed_issues[0].reverted)
            # Bit-for-bit exact match to original code
            self.assertEqual(client_file.read_text(encoding="utf-8"), original_code)

    def test_format_post_install_report_shows_both_fixed_and_failed_with_retries(self):
        """Test report clearly displays What was fixed, What failed, and Retries used."""
        report = PostInstallRepairReport(
            initial_tests_passed=False,
            final_tests_passed=False,
            total_issues_detected=2,
            fixed_count=1,
            failed_count=1,
            max_retries=2,
            fixed_issues=[
                PostInstallIssue(
                    test_name="test_ok",
                    file_path="app.py",
                    line_number=5,
                    call_expression="val = 20",
                    error_type="AssertionError",
                    error_message="assert 20 == 15",
                    attempt_count=1,
                    fixed=True,
                    proposed_fix="val = 15",
                    patch_diff="- val = 20\n+ val = 15",
                )
            ],
            failed_issues=[
                PostInstallIssue(
                    test_name="test_bad",
                    file_path="service.py",
                    line_number=20,
                    call_expression="raise_err()",
                    error_type="RuntimeError",
                    error_message="unhandled failure",
                    attempt_count=2,
                    fixed=False,
                    reverted=True,
                    error_output="RuntimeError: unhandled failure",
                )
            ],
        )

        formatted = format_post_install_report(report)
        self.assertIn("WHAT WAS FIXED", formatted)
        self.assertIn("WHAT FAILED", formatted)
        self.assertIn("Attempt 1 of 2 (Fixed on first try)", formatted)
        self.assertIn("2 of 2 retries exhausted", formatted)
        self.assertIn("REVERTED", formatted)

    def test_full_integrated_repair_pipeline(self):
        """End-to-end test of the complete pipeline: Pre-Repair -> Install -> Post-Repair."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_lib = self._write_file(
                dir_path,
                "my_lib_v1.py",
                """
def calculate_tax(amount: float, rate: float = 0.20) -> float:
    return amount * rate

def process_order(item_id: int, timeout: int = 30) -> str:
    return f"Processed {item_id}"
""",
            )
            # v2: signature change on process_order (timeout removed), behavioral change on calculate_tax (rate=0.15)
            new_lib = self._write_file(
                dir_path,
                "my_lib.py",
                """
def calculate_tax(amount: float, rate: float = 0.15) -> float:
    return amount * rate

def process_order(item_id: int) -> str:
    return f"Processed {item_id}"
""",
            )
            client_file = self._write_file(
                dir_path,
                "app.py",
                """
from my_lib import calculate_tax, process_order

def run_app():
    res = process_order(101, timeout=30)
    tax = compute_tax(100.0)
    return {"order": res, "tax": tax}

def compute_tax(amount: float) -> float:
    # Fix: return calculate_tax(amount, rate=0.15)
    return calculate_tax(amount, rate=0.20)
""",
            )
            test_file = self._write_file(
                dir_path,
                "test_app.py",
                """
from app import compute_tax, run_app

def test_order():
    assert run_app()["order"] == "Processed 101"

def test_tax():
    assert compute_tax(100.0) == 15.0
""",
            )

            # Step 1: Pre-Install Repair (signature fix)
            pre_report = run_pre_install_repair(
                old_path=old_lib,
                new_path=new_lib,
                client_path=client_file,
                action="apply_only",
            )
            self.assertEqual(pre_report.syntactical_count, 1)
            self.assertIn("process_order(101)", client_file.read_text(encoding="utf-8"))

            # Step 2: Test fails initially due to behavioral rate mismatch
            init_test = run_pytest(test_file, cwd=dir_path)
            self.assertFalse(init_test.passed)

            # Step 3: Post-Install Repair (test-gated)
            def behavioral_patch(code_snippet, breaking_change_info, **kwargs):
                if "0.20" in code_snippet:
                    return "return calculate_tax(amount, rate=0.15)"
                return code_snippet

            with patch("safedep.post_install_repair.propose_patch", side_effect=behavioral_patch):
                post_report = run_post_install_repair(
                    test_target=test_file,
                    client_path=client_file,
                    cwd=dir_path,
                )

            self.assertTrue(post_report.final_tests_passed)
            self.assertEqual(post_report.fixed_count, 1)
            self.assertIn("return calculate_tax(amount, rate=0.15)", client_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()



