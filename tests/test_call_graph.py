"""Unit tests for SafeDep call graph and affected call site detection."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.call_graph import (
    build_call_graph,
    extract_breaking_symbols,
    find_affected_call_sites,
    format_call_sites_report,
    get_affected_call_sites,
)


class TestCallGraph(unittest.TestCase):
    """Test suite for AST call graph building and affected call site detection."""

    def _write_file(self, directory: Path, filename: str, content: str) -> Path:
        """Helper to create a temporary source file."""
        file_path = directory / filename
        file_path.write_text(content.strip(), encoding="utf-8")
        return file_path

    def test_direct_function_call_affected(self):
        """Test detecting a call site that calls a removed or broken function."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app_file = self._write_file(
                project_dir,
                "app.py",
                """
def process_order(amount: float) -> float:
    tax = calculate_tax(amount)
    return amount + tax
""",
            )

            breaking_changes = {
                "removed_functions": [
                    {
                        "name": "calculate_tax",
                        "line": 5,
                        "signature": "def calculate_tax(amount: float) -> float",
                    }
                ]
            }

            sites = get_affected_call_sites(app_file, breaking_changes)
            self.assertEqual(len(sites), 1)

            site = sites[0]
            self.assertEqual(site["file_path"], str(app_file))
            self.assertEqual(site["line_number"], 2)
            # function_name matches the breaking function callee
            self.assertEqual(site["function_name"], "calculate_tax")
            # And also equals caller function via DualFunctionName
            self.assertEqual(site["function_name"], "process_order")
            self.assertEqual(site["caller_name"], "process_order")

    def test_method_call_affected(self):
        """Test detecting a method call when a class method was removed."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            client_file = self._write_file(
                project_dir,
                "client_app.py",
                """
class App:
    def shutdown(self, client):
        client.disconnect()
""",
            )

            breaking_changes = {
                "removed_methods": [
                    {
                        "class_name": "ApiClient",
                        "method_name": "disconnect",
                        "line": 10,
                    }
                ]
            }

            sites = get_affected_call_sites(client_file, breaking_changes)
            self.assertEqual(len(sites), 1)
            site = sites[0]
            self.assertEqual(site["function_name"], "disconnect")
            self.assertEqual(site["line_number"], 3)
            self.assertEqual(site["caller_name"], "App.shutdown")

    def test_class_instantiation_affected(self):
        """Test detecting class instantiation when class is removed or __init__ signature changed."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            main_file = self._write_file(
                project_dir,
                "main.py",
                """
def initialize():
    auth = LegacyAuthHandler()
    config = Config("localhost")
    return auth, config
""",
            )

            breaking_changes = {
                "removed_classes": [{"name": "LegacyAuthHandler"}],
                "changed_signatures": [
                    {
                        "symbol_type": "method",
                        "name": "Config.__init__",
                        "reasons": ["New required parameter 'port' added"],
                    }
                ],
            }

            sites = get_affected_call_sites(main_file, breaking_changes)
            self.assertEqual(len(sites), 2)
            callees = [s["callee_name"] for s in sites]
            self.assertIn("LegacyAuthHandler", callees)
            self.assertIn("Config", callees)

    def test_aliased_import_affected(self):
        """Test detecting a broken call site when the function was imported under an alias."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            script_file = self._write_file(
                project_dir,
                "script.py",
                """
from mylib import calculate_tax as my_tax

def compute(x):
    return my_tax(x)
""",
            )

            breaking_changes = ["calculate_tax"]
            sites = get_affected_call_sites(script_file, breaking_changes)
            self.assertEqual(len(sites), 1)
            site = sites[0]
            self.assertEqual(site["callee_name"], "calculate_tax")
            self.assertEqual(site["line_number"], 4)

    def test_nested_calls_affected(self):
        """Test that nested calls inside arguments are detected."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            nested_file = self._write_file(
                project_dir,
                "nested.py",
                """
def report():
    print(format_currency(calculate_tax(100.0)))
""",
            )

            breaking_changes = ["calculate_tax"]
            sites = get_affected_call_sites(nested_file, breaking_changes)
            self.assertEqual(len(sites), 1)
            self.assertEqual(sites[0]["function_name"], "calculate_tax")
            self.assertEqual(sites[0]["line_number"], 2)

    def test_top_level_module_call_affected(self):
        """Test that top-level calls outside any function are detected with caller '<module>'."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            run_file = self._write_file(
                project_dir,
                "run.py",
                """
result = calculate_tax(500)
""",
            )

            breaking_changes = ["calculate_tax"]
            sites = get_affected_call_sites(run_file, breaking_changes)
            self.assertEqual(len(sites), 1)
            site = sites[0]
            self.assertEqual(site["caller_name"], "<module>")
            self.assertEqual(site["function_name"], "calculate_tax")
            self.assertEqual(site["line_number"], 1)

    def test_unaffected_calls_not_flagged(self):
        """Test that unbroken functions are not reported as affected call sites."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            safe_file = self._write_file(
                project_dir,
                "safe.py",
                """
def compute():
    x = [1, 2, 3]
    return sum(x)
""",
            )

            breaking_changes = ["calculate_tax", "ApiClient.disconnect"]
            sites = get_affected_call_sites(safe_file, breaking_changes)
            self.assertEqual(len(sites), 0)

    def test_various_breaking_changes_input_formats(self):
        """Test passing full api_diff dictionary, list of strings, and list of dicts."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            file_path = self._write_file(
                project_dir,
                "test_formats.py",
                """
def run():
    calculate_tax(10)
    fetch_user(42)
""",
            )

            # Format 1: Full dict from get_breaking_changes
            full_dict = {
                "breaking_changes_found": True,
                "removed_functions": [{"name": "calculate_tax"}],
                "changed_signatures": [{"name": "fetch_user"}],
            }
            sites_1 = get_affected_call_sites(file_path, full_dict)
            self.assertEqual(len(sites_1), 2)

            # Format 2: List of strings from diff["breaking_changes"]
            str_list = [
                "[REMOVED FUNCTION] Public function 'calculate_tax' was removed",
                "[CHANGED SIGNATURE] fetch_user: New required parameter 'api_token'",
            ]
            sites_2 = get_affected_call_sites(file_path, str_list)
            self.assertEqual(len(sites_2), 2)

            # Format 3: Simple list of symbol names
            raw_list = ["calculate_tax", "fetch_user"]
            sites_3 = get_affected_call_sites(file_path, raw_list)
            self.assertEqual(len(sites_3), 2)

    def test_directory_project_scan(self):
        """Test analyzing a whole directory with multiple Python files."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            src_dir = base_dir / "src"
            src_dir.mkdir()

            f1 = self._write_file(src_dir, "module_a.py", "def a(): calculate_tax(10)")
            f2 = self._write_file(src_dir, "module_b.py", "def b(): calculate_tax(20)\ndef safe(): pass")

            breaking_changes = ["calculate_tax"]
            sites = get_affected_call_sites(base_dir, breaking_changes)

            self.assertEqual(len(sites), 2)
            detected_files = {s["file_path"] for s in sites}
            self.assertIn(str(f1), detected_files)
            self.assertIn(str(f2), detected_files)

    def test_build_call_graph_direct(self):
        """Test build_call_graph returns CallGraph with callers and call sites."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            f = self._write_file(
                project_dir,
                "sample.py",
                """
def foo():
    bar()
    baz()
""",
            )
            cg = build_call_graph(f)
            self.assertEqual(len(cg.get_all_call_sites()), 2)
            self.assertEqual(len(cg.get_calls_from("foo")), 2)

    def test_format_call_sites_report(self):
        """Test report formatting utility returns readable string."""
        sample_sites = [
            {
                "file_path": "app.py",
                "function_name": "calculate_tax",
                "line_number": 12,
                "caller_name": "process_order",
                "callee_name": "calculate_tax",
                "call_expression": "calculate_tax(100)",
                "breaking_change": "calculate_tax",
            }
        ]
        report = format_call_sites_report(sample_sites)
        self.assertIn("AFFECTED CALL SITES FOUND", report)
        self.assertIn("app.py", report)
        self.assertIn("calculate_tax", report)
        self.assertIn("Line 12", report)

    def test_error_handling(self):
        """Test that non-existent paths raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            get_affected_call_sites("non_existent_project_path", ["calculate_tax"])

    def test_swapped_arguments(self):
        """Test that get_affected_call_sites handles swapped arguments gracefully."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app_file = self._write_file(project_dir, "app.py", "def run(): calculate_tax(10)")
            # Passing (breaking_changes, project_path) instead of (project_path, breaking_changes)
            sites = get_affected_call_sites(["calculate_tax"], app_file)
            self.assertEqual(len(sites), 1)

    def test_alias_find_affected_call_sites(self):
        """Test find_affected_call_sites is an exact alias for get_affected_call_sites."""
        self.assertIs(find_affected_call_sites, get_affected_call_sites)


if __name__ == "__main__":
    unittest.main()

