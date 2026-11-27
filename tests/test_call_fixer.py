"""Tests for safedep.call_fixer (R2 rules).

Tests cover:
- removed keyword parameter: drop that keyword argument
- parameter lost default, call omits it: restore old default as keyword argument
- new required parameter without default: resolve via R3 or manual
- reordered positional parameters: reorder positional args
- call uses *args or **kwargs: review
- double and single quote preservation
- multi-line calls
- nested calls
- two calls on one line
- non-ASCII characters earlier on line (UTF-8 byte offset handling)
- untouched arguments preserved byte-for-byte
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from safedep.call_fixer import apply_span_edit, fix_call, patch_file


def _make_site(callee: str, line: int = 1, col: int = 0, end_line: int = 1, end_col: int = 20,
               caller: str = "<module>", file_path: str = "app.py",
               kw_args: list[str] | None = None, pos_count: int = 0,
               has_varargs: bool = False, has_varkwargs: bool = False,
               is_removal: bool = False) -> dict:
    return {
        "callee_name": callee,
        "caller_name": caller,
        "file_path": file_path,
        "line_number": line,
        "col_offset": col,
        "end_line": end_line,
        "end_col_offset": end_col,
        "keyword_args": kw_args or [],
        "positional_args_count": pos_count,
        "has_varargs": has_varargs,
        "has_varkwargs": has_varkwargs,
        "is_removal": is_removal,
    }


def test_removed_keyword_parameter_double_quotes():
    """R2: Drop removed keyword parameter, preserve double quotes in untouched string argument."""
    src = b'result = execute_query("SELECT 1", timeout=10)\n'
    # execute_query: timeout removed
    site = _make_site("execute_query", line=1, col=9, end_line=1, end_col=46,
                      kw_args=["timeout"], pos_count=1)
    bc = {
        "old_signature": "def execute_query(sql: str, timeout: int = 10) -> list:",
        "new_signature": "def execute_query(sql: str) -> list:",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b'execute_query("SELECT 1")'


def test_removed_keyword_parameter_single_quotes():
    """R2: Drop removed keyword parameter, preserve single quotes in untouched string argument."""
    src = b"result = execute_query('SELECT 1', timeout=10)\n"
    site = _make_site("execute_query", line=1, col=9, end_line=1, end_col=46,
                      kw_args=["timeout"], pos_count=1)
    bc = {
        "old_signature": "def execute_query(sql: str, timeout: int = 10) -> list:",
        "new_signature": "def execute_query(sql: str) -> list:",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b"execute_query('SELECT 1')"


def test_parameter_lost_default_call_omits():
    """R2: Parameter lost its default and call omits it -> add keyword with old default text."""
    src = b"msg = set_notification_channel()\n"
    site = _make_site("set_notification_channel", line=1, col=6, end_line=1, end_col=32,
                      kw_args=[], pos_count=0)
    bc = {
        "old_signature": "def set_notification_channel(channel: str = 'email') -> str:",
        "new_signature": "def set_notification_channel(channel: str) -> str:",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b"set_notification_channel(channel='email')"


def test_new_required_parameter_resolved():
    """R2: New required parameter resolved via R3 -> add as keyword."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = root / "config.py"
        cfg.write_text('AUTH_TOKEN = "xyz123"\n', encoding="utf-8")

        app_file = root / "app.py"
        app_file.write_text("from config import AUTH_TOKEN\nprofile = fetch_user_profile(user_id)\n", encoding="utf-8")
        src = app_file.read_bytes()

        site = _make_site("fetch_user_profile", line=2, col=10, end_line=2, end_col=38,
                          file_path=str(app_file), caller="<module>",
                          kw_args=[], pos_count=1)
        bc = {
            "old_signature": "def fetch_user_profile(user_id: int) -> dict:",
            "new_signature": "def fetch_user_profile(user_id: int, auth_token: str) -> dict:",
        }
        res = fix_call(site, bc, src)
        assert res.status == "applied"
        assert b"auth_token=" in res.new_call_bytes
        assert b"AUTH_TOKEN" in res.new_call_bytes


def test_new_required_parameter_unresolved_is_manual():
    """R2: New required parameter cannot be resolved -> status manual, no edit."""
    src = b"profile = fetch_user_profile(user_id)\n"
    site = _make_site("fetch_user_profile", line=1, col=10, end_line=1, end_col=38,
                      file_path="/tmp/fake_nonexistent.py", caller="<module>",
                      kw_args=[], pos_count=1)
    bc = {
        "old_signature": "def fetch_user_profile(user_id: int) -> dict:",
        "new_signature": "def fetch_user_profile(user_id: int, auth_token: str) -> dict:",
    }
    res = fix_call(site, bc, src)
    assert res.status == "manual"
    assert res.new_call_bytes is None


def test_reordered_positionals():
    """R2: Reordered positional parameters are swapped according to new signature."""
    src = b'inv = format_invoice("Alice", 99.99)\n'
    site = _make_site("format_invoice", line=1, col=6, end_line=1, end_col=37,
                      kw_args=[], pos_count=2)
    bc = {
        "old_signature": "def format_invoice(customer_name: str, amount: float) -> str:",
        "new_signature": "def format_invoice(amount: float, customer_name: str) -> str:",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b'format_invoice(99.99, "Alice")'


def test_reordered_positionals_with_star_arg_is_review():
    """R2: Reordered positionals where call contains *args -> status review."""
    src = b"inv = format_invoice(*args)\n"
    site = _make_site("format_invoice", line=1, col=6, end_line=1, end_col=27,
                      has_varargs=True)
    bc = {
        "old_signature": "def format_invoice(customer_name: str, amount: float) -> str:",
        "new_signature": "def format_invoice(amount: float, customer_name: str) -> str:",
    }
    res = fix_call(site, bc, src)
    assert res.status == "review"
    assert res.new_call_bytes is None


def test_kwargs_spread_is_review():
    """R2: Call uses **kwargs -> status review."""
    src = b"res = execute_query(**kwargs)\n"
    site = _make_site("execute_query", line=1, col=6, end_line=1, end_col=29,
                      has_varkwargs=True)
    bc = {
        "old_signature": "def execute_query(sql: str, timeout: int = 10):",
        "new_signature": "def execute_query(sql: str):",
    }
    res = fix_call(site, bc, src)
    assert res.status == "review"


def test_removal_is_manual():
    """R2: Function removal -> status manual."""
    src = b"discount = legacy_discount(amount, code)\n"
    site = _make_site("legacy_discount", line=1, col=11, end_line=1, end_col=41,
                      is_removal=True)
    bc = {"is_removal": True}
    res = fix_call(site, bc, src)
    assert res.status == "manual"
    assert res.new_call_bytes is None


def test_multi_line_call_preservation():
    """R2: Untouched arguments in multi-line call are preserved byte-for-byte."""
    src = (
        b"res = execute_query(\n"
        b'    "SELECT * FROM items WHERE active = 1",\n'
        b"    timeout=10,\n"
        b")\n"
    )
    # The call node span
    tree = ast.parse(src.decode("utf-8"))
    call = tree.body[0].value
    site = _make_site(
        "execute_query",
        line=call.lineno,
        col=call.col_offset,
        end_line=call.end_lineno,
        end_col=call.end_col_offset,
        kw_args=["timeout"],
        pos_count=1,
    )
    bc = {
        "old_signature": "def execute_query(sql: str, timeout: int = 10):",
        "new_signature": "def execute_query(sql: str):",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert b'"SELECT * FROM items WHERE active = 1"' in res.new_call_bytes
    assert b"timeout" not in res.new_call_bytes


def test_nested_calls():
    """R2: Nested call inside an argument."""
    src = b'inv = format_invoice(get_customer_name(), 49.99)\n'
    site = _make_site("format_invoice", line=1, col=6, end_line=1, end_col=49,
                      kw_args=[], pos_count=2)
    bc = {
        "old_signature": "def format_invoice(customer_name: str, amount: float):",
        "new_signature": "def format_invoice(amount: float, customer_name: str):",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b'format_invoice(49.99, get_customer_name())'


def test_two_calls_on_one_line():
    """R2: Two calls on the same line; span edit modifies only target call."""
    src = b'a = execute_query("Q1", timeout=5); b = execute_query("Q2", timeout=5)\n'
    tree = ast.parse(src.decode("utf-8"))
    first_call = tree.body[0].value
    site1 = _make_site("execute_query", line=first_call.lineno, col=first_call.col_offset,
                       end_line=first_call.end_lineno, end_col=first_call.end_col_offset,
                       kw_args=["timeout"], pos_count=1)
    bc = {
        "old_signature": "def execute_query(sql, timeout=10):",
        "new_signature": "def execute_query(sql):",
    }
    res = fix_call(site1, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b'execute_query("Q1")'
    patched = apply_span_edit(src, site1["line_number"], site1["col_offset"],
                              site1["end_line"], site1["end_col_offset"], res.new_call_bytes)
    assert patched == b'a = execute_query("Q1"); b = execute_query("Q2", timeout=5)\n'


def test_non_ascii_earlier_on_line():
    """R2: Non-ASCII characters earlier on the line (ast byte offsets handled correctly)."""
    # '₹' is 3 bytes in UTF-8
    src = 'currency = "₹"; res = execute_query("SELECT 1", timeout=10)\n'.encode("utf-8")
    tree = ast.parse(src.decode("utf-8"))
    call = tree.body[1].value
    site = _make_site("execute_query", line=call.lineno, col=call.col_offset,
                       end_line=call.end_lineno, end_col=call.end_col_offset,
                       kw_args=["timeout"], pos_count=1)
    bc = {
        "old_signature": "def execute_query(sql, timeout=10):",
        "new_signature": "def execute_query(sql):",
    }
    res = fix_call(site, bc, src)
    assert res.status == "applied"
    assert res.new_call_bytes == b'execute_query("SELECT 1")'
    patched = apply_span_edit(src, site["line_number"], site["col_offset"],
                              site["end_line"], site["end_col_offset"], res.new_call_bytes)
    assert 'currency = "₹"; res = execute_query("SELECT 1")\n'.encode("utf-8") == patched
