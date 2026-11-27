"""Tests for R4 safety: snapshot before applying, rollback on syntax error."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from safedep.call_fixer import FixResult, patch_file
from safedep.snapshot import list_snapshots


def test_invalid_replacement_triggers_restore():
    """R4: A deliberately invalid replacement triggers rollback and original bytes come back exactly."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        app_file = root / "app.py"
        original_content = b'res = execute_query("SELECT 1", timeout=10)\n'
        app_file.write_bytes(original_content)

        site = {
            "callee_name": "execute_query",
            "caller_name": "<module>",
            "file_path": str(app_file),
            "line_number": 1,
            "col_offset": 6,
            "end_line": 1,
            "end_col_offset": 43,
            "keyword_args": ["timeout"],
            "positional_args_count": 1,
        }

        # Deliberately invalid replacement (syntax error)
        bad_fix = FixResult(status="applied", new_call_bytes=b'execute_query("SELECT 1", invalid syntax (((', reason="bad")

        with patch("safedep.call_fixer.fix_call", return_value=bad_fix):
            results = patch_file(str(app_file), [site], {}, str(root))

        # Must report failed
        assert results[0].status == "failed"
        # Original bytes must be restored exactly
        assert app_file.read_bytes() == original_content
