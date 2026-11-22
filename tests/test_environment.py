"""Unit tests for safedep.environment."""

import sys
import pytest
from pathlib import Path

from unittest.mock import MagicMock, patch

from safedep.environment import (
    resolve_library_source,
    installed_version,
    LibrarySource,
    install_library,
)


def test_resolve_library_source_project_folder(tmp_path: Path):
    """resolve_library_source reads name/version from a project folder containing pyproject.toml."""
    proj = tmp_path / "fakepkg_proj"
    proj.mkdir()
    pyproject = proj / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "fakepkg"
version = "3.2.1"
""",
        encoding="utf-8",
    )
    pkg_dir = proj / "fakepkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("# init\n", encoding="utf-8")

    src = resolve_library_source(str(proj))
    assert isinstance(src, LibrarySource)
    assert src.name == "fakepkg"
    assert src.version == "3.2.1"
    assert src.project_dir == proj.resolve()
    assert src.package_dir == pkg_dir.resolve()
    assert src.origin == "local"


def test_resolve_library_source_package_folder(tmp_path: Path):
    """resolve_library_source reads name/version from the package folder by finding nearest pyproject.toml."""
    proj = tmp_path / "my_project"
    proj.mkdir()
    pyproject = proj / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "cooltool"
version = "0.9.5"
""",
        encoding="utf-8",
    )
    pkg_dir = proj / "cooltool"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("# cooltool\n", encoding="utf-8")

    src = resolve_library_source(str(pkg_dir))
    assert isinstance(src, LibrarySource)
    assert src.name == "cooltool"
    assert src.version == "0.9.5"
    assert src.project_dir == proj.resolve()
    assert src.package_dir == pkg_dir.resolve()


def test_resolve_library_source_pypi_spec_raises_not_implemented():
    """resolve_library_source('somepkg==1.0') raises NotImplementedError with expected message."""
    with pytest.raises(NotImplementedError, match="PyPI download is planned for a later phase"):
        resolve_library_source("somepkg==1.0")

    with pytest.raises(NotImplementedError, match="PyPI download is planned for a later phase"):
        resolve_library_source("requests>=2.28")


def test_resolve_library_source_does_not_change_installed_version():
    """resolve_library_source does not install or modify anything; installed_version remains identical."""
    repo_root = Path(__file__).resolve().parent.parent
    shopkit_v1_path = repo_root / "demo" / "shopkit_v1"
    shopkit_v2_path = repo_root / "demo" / "shopkit_v2"

    before_v1 = installed_version(sys.executable, "shopkit")

    # Call resolve_library_source on both projects
    src1 = resolve_library_source(str(shopkit_v1_path))
    assert src1.name == "shopkit"
    assert src1.version == "1.0.0"

    src2 = resolve_library_source(str(shopkit_v2_path))
    assert src2.name == "shopkit"
    assert src2.version == "2.0.0"

    after_v1 = installed_version(sys.executable, "shopkit")
    assert before_v1 == after_v1


def test_install_library_first_attempt_succeeds(tmp_path: Path):
    """First attempt succeeds -> exactly one subprocess call, no --no-build-isolation flag, method == 'standard'."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "Successfully installed pkg-1.0.0"
    mock_res.stderr = ""

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        res = install_library(sys.executable, tmp_path)
        assert res.success is True
        assert res.method == "standard"
        assert mock_run.call_count == 1
        cmd = mock_run.call_args[0][0]
        assert "--no-build-isolation" not in cmd


def test_install_library_first_attempt_fails_second_succeeds(tmp_path: Path):
    """First attempt fails, second succeeds -> exactly two calls, the second includes --no-build-isolation, method == 'no-build-isolation'."""
    mock_fail = MagicMock()
    mock_fail.returncode = 1
    mock_fail.stdout = ""
    mock_fail.stderr = "Build isolation error: could not connect to PyPI"

    mock_success = MagicMock()
    mock_success.returncode = 0
    mock_success.stdout = "Successfully installed without build isolation"
    mock_success.stderr = ""

    with patch("subprocess.run", side_effect=[mock_fail, mock_success]) as mock_run:
        res = install_library(sys.executable, tmp_path)
        assert res.success is True
        assert res.method == "no-build-isolation"
        assert mock_run.call_count == 2
        first_cmd = mock_run.call_args_list[0][0][0]
        second_cmd = mock_run.call_args_list[1][0][0]
        assert "--no-build-isolation" not in first_cmd
        assert "--no-build-isolation" in second_cmd
