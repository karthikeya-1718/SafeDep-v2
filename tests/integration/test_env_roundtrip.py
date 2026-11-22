"""Integration test for environment roundtrip with shopkit and storefront."""

import os
import subprocess
import sys
from pathlib import Path
import pytest

from safedep.environment import (
    resolve_library_source,
    installed_version,
    UpgradeGuard,
    install_library,
)


@pytest.mark.integration
def test_environment_roundtrip_and_health_check():
    """Verify venv creation, shopkit v1 install, guard upgrade to v2, rollback, and health checks."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    envs_dir = repo_root / ".safedep_envs"
    envs_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = envs_dir / "test-roundtrip"

    # Create venv if not already created
    if not venv_dir.exists():
        res = subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"venv creation failed: {res.stderr}"

    venv_python = venv_dir / "Scripts" / "python.exe" if sys.platform == "win32" else venv_dir / "bin" / "python"
    assert venv_python.exists(), f"Python binary not found at {venv_python}"

    # Install flask into the venv (needed for storefront health check)
    # Use --no-build-isolation if needed or standard install
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "flask", "--no-build-isolation", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )

    shopkit_v1_dir = repo_root / "demo" / "shopkit_v1"
    shopkit_v2_dir = repo_root / "demo" / "shopkit_v2"

    # Step 1: Install shopkit v1
    v1_source = resolve_library_source(str(shopkit_v1_dir))
    install_res = install_library(str(venv_python), str(shopkit_v1_dir))
    assert install_res.success, f"Failed to install shopkit v1: {install_res.stderr_tail}"
    assert installed_version(str(venv_python), "shopkit") == "1.0.0"

    # Step 2: resolve_library_source on shopkit v2 does not change installed version
    v2_source = resolve_library_source(str(shopkit_v2_dir))
    assert v2_source.version == "2.0.0"
    assert installed_version(str(venv_python), "shopkit") == "1.0.0"

    # Step 3: Run health check on v1 (healthy)
    health_check_script = repo_root / "demo" / "tools" / "health_check.py"
    res_hc_v1 = subprocess.run(
        [sys.executable, str(health_check_script), "--python", str(venv_python), "--project", str(repo_root / "demo" / "storefront")],
        capture_output=True,
        text=True,
    )
    assert res_hc_v1.returncode == 0, f"Expected health check to pass on v1: {res_hc_v1.stdout} {res_hc_v1.stderr}"

    # Step 4: Upgrade to v2 via UpgradeGuard
    guard = UpgradeGuard(str(venv_python), "shopkit", v1_source)
    guard.install(v2_source)
    assert installed_version(str(venv_python), "shopkit") == "2.0.0"

    # Step 5: Run health check on v2 (expected startup failure mentioning 'timeout')
    res_hc_v2 = subprocess.run(
        [sys.executable, str(health_check_script), "--python", str(venv_python), "--project", str(repo_root / "demo" / "storefront")],
        capture_output=True,
        text=True,
    )
    assert res_hc_v2.returncode != 0
    assert "timeout" in (res_hc_v2.stdout + res_hc_v2.stderr).lower()

    # Step 6: Rollback via guard
    guard.rollback()
    assert installed_version(str(venv_python), "shopkit") == "1.0.0"

    # Step 7: Run health check again (expected healthy)
    res_hc_v1_post = subprocess.run(
        [sys.executable, str(health_check_script), "--python", str(venv_python), "--project", str(repo_root / "demo" / "storefront")],
        capture_output=True,
        text=True,
    )
    assert res_hc_v1_post.returncode == 0, f"Expected health check to pass after rollback: {res_hc_v1_post.stdout}"
