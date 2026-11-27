"""Integration roundtrip test for storefront repair."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent.parent
demo_storefront = repo_root / "demo" / "storefront"
demo_v1 = repo_root / "demo" / "shopkit_v1"
demo_v2 = repo_root / "demo" / "shopkit_v2"
health_check_script = repo_root / "demo" / "tools" / "health_check.py"
manual_fix_script = repo_root / "demo" / "manual_fixes" / "apply_legacy_discount_fix.py"
venv_python = repo_root / ".safedep_envs" / "test-roundtrip" / "Scripts" / "python.exe"


@pytest.mark.integration
@pytest.mark.skipif(
    not (demo_storefront.exists() and demo_v2.exists() and venv_python.exists()),
    reason="storefront, shopkit_v2 or .safedep_envs/test-roundtrip venv missing",
)
def test_storefront_repair_roundtrip():
    """Roundtrip: install v2 into venv, pre-repair storefront, verify checkout is only failure, apply manual fix -> healthy."""
    from safedep.environment import install_library

    # 1. Install shopkit v2 into test-roundtrip venv
    res = install_library(str(venv_python), str(demo_v2))
    assert res.success, f"Failed to install shopkit v2: {res.stderr_tail}"

    with tempfile.TemporaryDirectory() as td:
        tmp_storefront = Path(td) / "storefront"
        shutil.copytree(demo_storefront, tmp_storefront)

        # 2. Run pre-repair apply_only on tmp copy
        run_res = subprocess.run(
            [
                sys.executable, "main.py",
                "pre-repair",
                str(demo_v1 / "shopkit"),
                str(demo_v2 / "shopkit"),
                "--client", str(tmp_storefront / "app"),
                "--action", "apply_only",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert run_res.returncode == 0, f"pre-repair failed: {run_res.stderr}\n{run_res.stdout}"

        # 3. Run health check: startup OK and only failing route is GET /checkout
        hc_res = subprocess.run(
            [sys.executable, str(health_check_script), "--python", str(venv_python), "--project", str(tmp_storefront)],
            capture_output=True,
            text=True,
        )
        # returncode is 1 because /checkout fails
        assert hc_res.returncode == 1
        assert "APPLICATION STARTUP OK" in hc_res.stdout
        assert "GET      /checkout            500 ERR" in hc_res.stdout
        assert "GET      /                    200 OK" in hc_res.stdout

        # 4. Apply manual fix kit
        fix_res = subprocess.run(
            [sys.executable, str(manual_fix_script), "--project", str(tmp_storefront)],
            capture_output=True,
            text=True,
        )
        assert fix_res.returncode == 0

        # 5. Run health check again: all routes healthy!
        hc_res2 = subprocess.run(
            [sys.executable, str(health_check_script), "--python", str(venv_python), "--project", str(tmp_storefront)],
            capture_output=True,
            text=True,
        )
        assert hc_res2.returncode == 0, f"Health check failed after manual fix:\n{hc_res2.stdout}"
        assert "RESULT: HEALTHY" in hc_res2.stdout
