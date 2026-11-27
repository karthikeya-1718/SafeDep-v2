"""Tests for demo/manual_fixes/apply_legacy_discount_fix.py."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
demo_storefront = repo_root / "demo" / "storefront"
fix_script = repo_root / "demo" / "manual_fixes" / "apply_legacy_discount_fix.py"


@pytest.mark.skipif(
    not (demo_storefront.exists() and fix_script.exists()),
    reason="demo/storefront or manual fix script missing",
)
def test_manual_kit_applies_and_is_idempotent():
    """Manual fix kit replaces legacy_discount with local function and is idempotent."""
    with tempfile.TemporaryDirectory() as td:
        tmp_storefront = Path(td) / "storefront"
        shutil.copytree(demo_storefront, tmp_storefront)

        pricing_file = tmp_storefront / "app" / "services" / "pricing_service.py"

        # Verify initial state
        initial_text = pricing_file.read_text(encoding="utf-8")
        assert "shopkit.legacy_discount(amount, code)" in initial_text

        # Run the fix script
        res = subprocess.run(
            [sys.executable, str(fix_script), "--project", str(tmp_storefront)],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"

        # Verify modifications
        modified_text = pricing_file.read_text(encoding="utf-8")
        assert "apply_discount_code(amount, code)" in modified_text
        assert "shopkit.legacy_discount" not in modified_text
        assert "def apply_discount_code(amount: float, code: str)" in modified_text
        # import shopkit should be removed since nothing else in pricing_service uses it
        assert "import shopkit" not in modified_text

        # Valid Python syntax
        ast.parse(modified_text)

        # Idempotence: running it a second time makes no change
        res2 = subprocess.run(
            [sys.executable, str(fix_script), "--project", str(tmp_storefront)],
            capture_output=True,
            text=True,
        )
        assert res2.returncode == 0
        assert pricing_file.read_text(encoding="utf-8") == modified_text
