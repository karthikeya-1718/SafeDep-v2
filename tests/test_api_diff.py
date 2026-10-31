"""Unit tests for SafeDep breaking change detection."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.api_diff import get_breaking_changes


class TestApiDiff(unittest.TestCase):
    """Test suite for get_breaking_changes."""

    def _write_file(self, temp_dir: Path, filename: str, content: str) -> Path:
        file_path = temp_dir / filename
        file_path.write_text(content.strip(), encoding="utf-8")
        return file_path

    def test_removed_function(self):
        """Test that removing a public function is identified as a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def calculate_tax(amount: float, rate: float = 0.2) -> float:
    return amount * rate

def get_user_id() -> int:
    return 42
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def get_user_id() -> int:
    return 42
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["removed_functions"], 1)
            self.assertEqual(diff["removed_functions"][0]["name"], "calculate_tax")
            self.assertEqual(len(diff["breaking_changes"]), 1)

    def test_removed_class(self):
        """Test that removing a public class is identified as a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
class OldClient:
    def connect(self): pass

class NewClient:
    def connect(self): pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
class NewClient:
    def connect(self): pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["removed_classes"], 1)
            self.assertEqual(diff["removed_classes"][0]["name"], "OldClient")

    def test_removed_method(self):
        """Test that removing a public method from a class is identified as a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
class Database:
    def connect(self): pass
    def disconnect(self): pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
class Database:
    def connect(self): pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["removed_methods"], 1)
            self.assertEqual(diff["removed_methods"][0]["class_name"], "Database")
            self.assertEqual(diff["removed_methods"][0]["method_name"], "disconnect")

    def test_added_required_parameter(self):
        """Test that adding a parameter without a default value is a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def fetch_data(endpoint: str):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def fetch_data(endpoint: str, api_token: str):
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["changed_signatures"], 1)
            reasons = diff["changed_signatures"][0]["reasons"]
            self.assertTrue(any("api_token" in r and "without a default value" in r for r in reasons))

    def test_added_optional_parameter_is_safe(self):
        """Test that adding an optional parameter with a default is backward-compatible."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def fetch_data(endpoint: str):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def fetch_data(endpoint: str, timeout: int = 30):
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertFalse(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["total"], 0)

    def test_removed_parameter(self):
        """Test that removing an existing parameter is a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def search(query: str, page: int = 1, page_size: int = 20):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def search(query: str, page: int = 1):
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["changed_signatures"], 1)
            reasons = diff["changed_signatures"][0]["reasons"]
            self.assertTrue(any("page_size" in r and "removed" in r for r in reasons))

    def test_default_value_removed(self):
        """Test that removing a default value makes parameter required (breaking)."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def greet(name: str = "World"):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def greet(name: str):
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["changed_signatures"], 1)
            reasons = diff["changed_signatures"][0]["reasons"]
            self.assertTrue(any("Default value removed" in r for r in reasons))

    def test_positional_to_keyword_only(self):
        """Test that changing a positional-or-keyword param to keyword-only breaks positional callers."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def calculate(a: int, b: int):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def calculate(a: int, *, b: int):
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            reasons = diff["changed_signatures"][0]["reasons"]
            self.assertTrue(any("keyword-only" in r for r in reasons))

    def test_positional_parameter_reordering(self):
        """Test that swapping the order of positional parameters is a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def divide(dividend: float, divisor: float):
    return dividend / divisor
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def divide(divisor: float, dividend: float):
    return dividend / divisor
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            reasons = diff["changed_signatures"][0]["reasons"]
            self.assertTrue(any("reordered" in r for r in reasons))

    def test_removed_varargs_and_kwargs(self):
        """Test that removing *args or **kwargs is detected as breaking."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def log(msg: str, *args, **kwargs):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
def log(msg: str):
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            reasons = diff["changed_signatures"][0]["reasons"]
            self.assertTrue(any("*args" in r for r in reasons))
            self.assertTrue(any("**kwargs" in r for r in reasons))

    def test_private_symbols_ignored(self):
        """Test that private functions and classes (starting with _) are not flagged when removed."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
def _internal_helper(): pass
class _InternalStorage: pass

class Client:
    def _private_method(self): pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
class Client:
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertFalse(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["total"], 0)

    def test_class_init_signature_change(self):
        """Test that changing __init__ signature in an incompatible way is reported."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
class Config:
    def __init__(self, host: str):
        self.host = host
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
class Config:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["changed_signatures"], 1)
            sig_change = diff["changed_signatures"][0]
            self.assertEqual(sig_change["name"], "Config.__init__")

    def test_removed_base_class(self):
        """Test that removing a base class is identified as a breaking change."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
class CustomDict(dict):
    pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
class CustomDict:
    pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["removed_base_classes"], 1)
            self.assertEqual(diff["removed_base_classes"][0]["removed_base"], "dict")

    def test_dunder_all_exports(self):
        """Test that __all__ defines what is public; symbols not in __all__ are ignored."""
        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            old_f = self._write_file(
                dir_path,
                "old.py",
                """
__all__ = ["exported_fn"]

def exported_fn(): pass
def unexported_fn(): pass
""",
            )
            new_f = self._write_file(
                dir_path,
                "new.py",
                """
__all__ = ["exported_fn"]

def exported_fn(): pass
""",
            )

            diff = get_breaking_changes(old_f, new_f)
            self.assertFalse(diff["breaking_changes_found"])

    def test_directory_comparison(self):
        """Test comparing two packages/directories."""
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            v1_dir = base_dir / "v1"
            v2_dir = base_dir / "v2"
            v1_dir.mkdir()
            v2_dir.mkdir()

            self._write_file(v1_dir, "auth.py", "def login(user, password): pass\ndef logout(): pass")
            self._write_file(v2_dir, "auth.py", "def login(user, password): pass")  # logout removed

            self._write_file(v1_dir, "removed_mod.py", "def old_tool(): pass")
            # removed_mod.py omitted in v2

            diff = get_breaking_changes(v1_dir, v2_dir)
            self.assertTrue(diff["breaking_changes_found"])
            self.assertEqual(diff["summary"]["removed_modules"], 1)
            # logout removed from auth.py + old_tool removed from removed_mod.py
            self.assertTrue(diff["summary"]["removed_functions"] >= 2)

    def test_error_handling(self):
        """Test FileNotFoundError for non-existent paths and ValueError for mismatched types."""
        with self.assertRaises(FileNotFoundError):
            get_breaking_changes("non_existent_file_a.py", "non_existent_file_b.py")

        with tempfile.TemporaryDirectory() as td:
            dir_path = Path(td)
            f = self._write_file(dir_path, "sample.py", "def x(): pass")
            with self.assertRaises(ValueError):
                get_breaking_changes(f, dir_path)


if __name__ == "__main__":
    unittest.main()
