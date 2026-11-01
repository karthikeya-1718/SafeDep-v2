"""Unit tests for SafeDep pre_install_repair module."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.pre_install_repair import (
    analyze_pre_install_issues,
    apply_fixes,
    classify_issue,
    format_pre_install_report,
    generate_fallback_patch,
    run_pre_install_repair,
)


class TestPreInstallRepair(unittest.TestCase):
    """Test suite for Pre-Install Repair mode."""

    def _write_file(self, directory: Path, filename: str, content: str) -> Path:
        """Helper to create a temporary source file."""
        file_path = directory / filename
        file_path.write_text(content.strip(), encoding="utf-8")
        return file_path

    def test_classify_syntactical_vs_behavioral(self):
        """Test classifying signature changes and removals as syntactical; only runtime-only changes as behavioral."""
        diff_result = {
            "changed_signatures": [{"name": "fetch_user"}, {"name": "query"}],
            "removed_functions": [{"name": "calculate_tax"}],
            "removed_methods": [{"class_name": "ApiClient", "method_name": "disconnect"}],
        }

        # Changed signature → syntactical
        issue_type_1, _ = classify_issue({"callee_name": "query"}, diff_result)
        self.assertEqual(issue_type_1, "syntactical")

        # Keyword in breaking_change text → syntactical
        issue_type_2, _ = classify_issue(
            {"callee_name": "unknown_fn", "breaking_change": "[CHANGED SIGNATURE] param removed"},
            diff_result,
        )
        self.assertEqual(issue_type_2, "syntactical")

        # Removed function → syntactical (detectable from diff, can be flagged pre-install)
        issue_type_3, _ = classify_issue(
            {"callee_name": "calculate_tax", "breaking_change": "Public function 'calculate_tax' was removed"},
            diff_result,
        )
        self.assertEqual(issue_type_3, "syntactical")

        # Removed method → syntactical (detectable from diff, can be flagged pre-install)
        issue_type_4, _ = classify_issue(
            {"callee_name": "disconnect", "breaking_change": "Public method 'ApiClient.disconnect' was removed"},
            diff_result,
        )
        self.assertEqual(issue_type_4, "syntactical")

    def test_fallback_patch_parameter_removal(self):
        """Test rule-based patch generator removing an unsupported keyword parameter."""
        call_expr = "query(sql, timeout=5)"
        breaking = "query: Parameter 'timeout' was removed"
        fixed = generate_fallback_patch(call_expr, breaking)
        self.assertEqual(fixed, "query(sql)")

    def test_fallback_patch_parameter_reordering(self):
        """Test rule-based patch generator reordering positional parameters."""
        call_expr = "render_template(my_name, my_ctx)"
        breaking = "render_template: Positional parameters were reordered: ['name', 'context'] -> ['context', 'name']"
        fixed = generate_fallback_patch(call_expr, breaking)
        self.assertEqual(fixed, "render_template(my_ctx, my_name)")

    def test_fallback_patch_added_required_parameter(self):
        """Test rule-based patch generator adding a required keyword parameter placeholder."""
        call_expr = "fetch_user(user_id)"
        breaking = "fetch_user: New required parameter 'api_token' added without a default value"
        fixed = generate_fallback_patch(call_expr, breaking)
        self.assertIn("api_token=", fixed)

    def test_analyze_pre_install_issues_end_to_end(self):
        """Test full analysis classifying syntactical and behavioral issues."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_file = self._write_file(
                dir_path,
                "v1.py",
                """
def calculate_tax(amount: float) -> float:
    return amount * 0.2

def query(sql: str, timeout: int = 10) -> list:
    return []
""",
            )
            new_file = self._write_file(
                dir_path,
                "v2.py",
                """
# calculate_tax removed
def query(sql: str) -> list:  # timeout removed (syntactical)
    return []
""",
            )
            client_file = self._write_file(
                dir_path,
                "app.py",
                """
def run_app():
    tax = calculate_tax(100.0)
    data = query("SELECT 1", timeout=5)
    return tax, data
""",
            )

            report = analyze_pre_install_issues(old_file, new_file, client_file)

            self.assertEqual(report.total_issues, 2)
            self.assertEqual(report.syntactical_count, 2)
            self.assertEqual(report.behavioral_count, 0)

            # Both should be syntactical: query (changed signature) and calculate_tax (removed)
            fn_names = {iss.function_name for iss in report.syntactical_issues}
            self.assertIn("query", fn_names)
            self.assertIn("calculate_tax", fn_names)

            # query should have a real code patch that removes the timeout argument
            query_issue = next(i for i in report.syntactical_issues if i.function_name == "query")
            self.assertEqual(query_issue.proposed_fix, "query('SELECT 1')")
            self.assertFalse(query_issue.is_removal)

            # calculate_tax is removed — proposed_fix must be None (no invalid code patch)
            tax_issue = next(i for i in report.syntactical_issues if i.function_name == "calculate_tax")
            self.assertIsNone(tax_issue.proposed_fix)
            self.assertTrue(tax_issue.is_removal)
            # patch_diff should contain a safe commented-out suggestion, not an English sentence
            self.assertIn("calculate_tax", tax_issue.patch_diff)
            self.assertTrue(tax_issue.patch_diff.startswith("#"))

    def test_format_pre_install_report_content(self):
        """Test that the report contains all required headers and explanatory notes."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_file = self._write_file(dir_path, "v1.py", "def query(sql, timeout=10): pass\ndef old_fn(): pass")
            new_file = self._write_file(dir_path, "v2.py", "def query(sql): pass")
            client_file = self._write_file(
                dir_path, "app.py", "def run():\n    old_fn()\n    query('SELECT', timeout=5)"
            )

            report = analyze_pre_install_issues(old_file, new_file, client_file)
            formatted = format_pre_install_report(report)

            # Verify required reporting elements
            self.assertIn("Total issues found:", formatted)
            self.assertIn("Auto-fixable signature changes:", formatted)
            self.assertIn("Removed functions/methods (manual intervention):", formatted)
            self.assertIn("Behavioral / structural issues (deferred):", formatted)
            self.assertIn("IMPORTANT NOTE ON BEHAVIORAL ISSUES:", formatted)
            self.assertIn("CAN ONLY BE DETECTED AND VERIFIED AFTER INSTALLATION", formatted)
            # Removal section should say manual intervention
            self.assertIn("MANUAL INTERVENTION REQUIRED", formatted)
            # Auto-fix section should be present for query's timeout removal
            self.assertIn("AUTO-FIXABLE SIGNATURE CHANGES", formatted)

    def test_apply_fixes_skips_removals(self):
        """Verify apply_fixes never writes English text (or any patch) for removed functions."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_file = self._write_file(dir_path, "v1.py", "def old_fn(): pass\ndef query(sql, timeout=10): pass")
            new_file = self._write_file(dir_path, "v2.py", "def query(sql): pass")
            client_file = self._write_file(
                dir_path, "app.py", "def run():\n    old_fn()\n    query('SELECT *', timeout=5)"
            )

            report = run_pre_install_repair(old_file, new_file, client_file, action="apply_only")
            content = client_file.read_text(encoding="utf-8")

            # old_fn is removed — the original call line must NOT be replaced with English text
            self.assertIn("old_fn()", content, "removed call should remain in file (not replaced with English)")
            self.assertNotIn("no longer exists", content)
            self.assertNotIn("Remove this call", content)
            self.assertNotIn("manual replacement required", content)

            # query's timeout arg should have been removed (it's an auto-fixable change)
            self.assertNotIn("timeout=5", content)
            self.assertIn("query('SELECT *')", content)

    def test_apply_fixes_only(self):
        """Test Option 2: Apply fixes only without installing the new library."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_file = self._write_file(dir_path, "v1.py", "def query(sql, timeout=10): pass")
            new_file = self._write_file(dir_path, "v2.py", "def query(sql): pass")
            client_file = self._write_file(dir_path, "app.py", "def run():\n    query('SELECT *', timeout=5)")

            report = run_pre_install_repair(old_file, new_file, client_file, action="apply_only")

            self.assertTrue(report.applied)
            self.assertFalse(report.installed)

            # Verify file was updated on disk
            updated_content = client_file.read_text(encoding="utf-8")
            self.assertNotIn("timeout=5", updated_content)
            self.assertIn("query('SELECT *')", updated_content)

            # Verify .bak backup file was created
            backup_file = client_file.with_suffix(".py.bak")
            self.assertTrue(backup_file.exists())
            self.assertIn("timeout=5", backup_file.read_text(encoding="utf-8"))

    def test_report_only_mode(self):
        """Test Option 3: Only show report without modifying any files."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_file = self._write_file(dir_path, "v1.py", "def query(sql, timeout=10): pass")
            new_file = self._write_file(dir_path, "v2.py", "def query(sql): pass")
            client_file = self._write_file(dir_path, "app.py", "def run():\n    query('SELECT *', timeout=5)")

            initial_content = client_file.read_text(encoding="utf-8")

            report = run_pre_install_repair(old_file, new_file, client_file, action="report_only")

            self.assertFalse(report.applied)
            self.assertFalse(report.installed)

            # Verify file was NOT modified
            self.assertEqual(client_file.read_text(encoding="utf-8"), initial_content)

            # Verify no backup file was created
            backup_file = client_file.with_suffix(".py.bak")
            self.assertFalse(backup_file.exists())


if __name__ == "__main__":
    unittest.main()

