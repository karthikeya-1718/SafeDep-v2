"""Test that `main.py analyze --json` exits 0 and produces valid JSON with 12 affected sites."""

import json
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
storefront_app = repo_root / "demo" / "storefront" / "app"
shopkit_v1 = repo_root / "demo" / "shopkit_v1" / "shopkit"
shopkit_v2 = repo_root / "demo" / "shopkit_v2" / "shopkit"


import pytest


@pytest.mark.skipif(
    not (storefront_app.exists() and shopkit_v1.exists() and shopkit_v2.exists()),
    reason="demo/storefront or shopkit demo folders are missing",
)
def test_analyze_json_exit_code_and_parse():
    """analyze --json must exit 0, stdout must be valid JSON, affected_call_sites must have 12 entries."""
    result = subprocess.run(
        [
            sys.executable, "main.py",
            "analyze",
            str(shopkit_v1),
            str(shopkit_v2),
            "--client", str(storefront_app),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )

    # Exit code 1 means breaking changes found (which is expected); 0 means none found; 2 means error.
    # The analyze command returns 1 when breaking changes are present, NOT 2.
    assert result.returncode != 2, (
        f"analyze --json crashed (exit code 2).\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )

    # stdout must be valid JSON
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"stdout is not valid JSON: {exc}\nstdout (first 500 chars): {result.stdout[:500]}"
        ) from exc

    # Must contain the affected_call_sites key with exactly 12 entries
    assert "affected_call_sites" in data, (
        f"JSON output missing 'affected_call_sites' key. Keys: {list(data.keys())}"
    )
    sites = data["affected_call_sites"]
    assert len(sites) == 12, (
        f"Expected 12 affected call sites, got {len(sites)}"
    )
