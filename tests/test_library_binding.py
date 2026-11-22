"""Unit tests for library-aware call graph binding in safedep.call_graph."""

import pytest
from pathlib import Path
from safedep.call_graph import get_affected_call_sites


def test_aliased_import_matching(tmp_path: Path):
    """from mylib import calculate_tax as my_tax -> matches calculate_tax when library_name='mylib'."""
    src = tmp_path / "app.py"
    src.write_text(
        """from mylib import calculate_tax as my_tax

def process():
    return my_tax(100.0)
""",
        encoding="utf-8",
    )

    diff = {"removed_functions": [{"name": "calculate_tax"}]}
    sites = get_affected_call_sites(src, diff, library_name="mylib")
    assert len(sites) == 1
    assert sites[0]["callee_name"] == "calculate_tax"


def test_import_lib_attribute_call(tmp_path: Path):
    """import mylib; mylib.calculate_tax(10) -> matches calculate_tax when library_name='mylib'."""
    src = tmp_path / "app.py"
    src.write_text(
        """import mylib

def process():
    return mylib.calculate_tax(100.0)
""",
        encoding="utf-8",
    )

    diff = {"removed_functions": [{"name": "calculate_tax"}]}
    sites = get_affected_call_sites(src, diff, library_name="mylib")
    assert len(sites) == 1
    assert sites[0]["callee_name"] == "calculate_tax"


def test_locally_defined_function_does_not_match(tmp_path: Path):
    """Locally defined function with same name as library function must NOT match."""
    src = tmp_path / "app.py"
    src.write_text(
        """def calculate_tax(amount):
    return amount * 0.15

def process():
    return calculate_tax(100.0)
""",
        encoding="utf-8",
    )

    diff = {"removed_functions": [{"name": "calculate_tax"}]}
    sites = get_affected_call_sites(src, diff, library_name="mylib")
    assert len(sites) == 0


def test_per_file_import_tracking(tmp_path: Path):
    """Same name imported from lib in file1, defined locally in file2: only file1 matches."""
    file1 = tmp_path / "file1.py"
    file1.write_text(
        """from mylib import calculate_tax

def run():
    return calculate_tax(50)
""",
        encoding="utf-8",
    )

    file2 = tmp_path / "file2.py"
    file2.write_text(
        """def calculate_tax(x):
    return x * 2

def run2():
    return calculate_tax(50)
""",
        encoding="utf-8",
    )

    diff = {"removed_functions": [{"name": "calculate_tax"}]}
    sites = get_affected_call_sites(tmp_path, diff, library_name="mylib")
    assert len(sites) == 1
    assert Path(sites[0]["file_path"]).name == "file1.py"
