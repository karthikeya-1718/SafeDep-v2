"""SafeDep Environment Layer.

Manages library resolution, virtual environment inspection, installation,
and upgrade guarding without altering runtime client projects unexpectedly.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


@dataclass(frozen=True)
class LibrarySource:
    """Resolved metadata about a library distribution source."""

    name: str
    version: str
    project_dir: Path
    package_dir: Path
    origin: str = "local"


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an installation attempt."""

    success: bool
    stdout_tail: str
    stderr_tail: str
    method: str = "failed"


def _read_pyproject_metadata(pyproject_path: Path) -> tuple[str, str]:
    """Parse name and version from a pyproject.toml file."""
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")

    content = pyproject_path.read_text(encoding="utf-8")
    if tomllib is not None:
        data = tomllib.loads(content)
        project = data.get("project", {})
        name = project.get("name")
        version = project.get("version")
        if name and version:
            return str(name), str(version)

    # Fallback basic TOML regex parser if tomllib is unavailable or metadata is custom
    name_match = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    version_match = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if name_match and version_match:
        return name_match.group(1), version_match.group(1)

    raise ValueError(f"Could not parse [project] name and version from {pyproject_path}")


def _find_package_dir(project_dir: Path, dist_name: str) -> Path:
    """Find the package source directory (with __init__.py) for a given project."""
    # Common conventions:
    # 1. <project_dir>/<name>/__init__.py
    normalized_name = dist_name.replace("-", "_")
    candidates = [
        project_dir / dist_name,
        project_dir / normalized_name,
        project_dir / "src" / dist_name,
        project_dir / "src" / normalized_name,
    ]
    for c in candidates:
        if c.is_dir() and (c / "__init__.py").exists():
            return c.resolve()

    # Any top-level folder with __init__.py
    for sub in project_dir.iterdir():
        if sub.is_dir() and sub.name not in ("tests", "test", "build", "dist", ".git", ".safedep") and (sub / "__init__.py").exists():
            return sub.resolve()

    # Fallback: if project_dir itself contains __init__.py
    if (project_dir / "__init__.py").exists():
        return project_dir.resolve()

    # Default to direct folder
    return (project_dir / normalized_name).resolve()


def resolve_library_source(spec: Union[str, Path]) -> LibrarySource:
    """Resolve library metadata from a project directory or package directory.

    Args:
        spec: Path to project directory (with pyproject.toml) or package folder.

    Returns:
        LibrarySource with name, version, project_dir, package_dir, and origin.

    Raises:
        NotImplementedError: If spec is not an existing path on disk.
        ValueError: If metadata cannot be resolved.
    """
    path_obj = Path(spec)
    if not path_obj.exists():
        raise NotImplementedError("PyPI download is planned for a later phase")

    path_obj = path_obj.resolve()

    if path_obj.is_dir():
        pyproject_direct = path_obj / "pyproject.toml"
        if pyproject_direct.is_file():
            # Project folder
            name, version = _read_pyproject_metadata(pyproject_direct)
            package_dir = _find_package_dir(path_obj, name)
            return LibrarySource(
                name=name,
                version=version,
                project_dir=path_obj,
                package_dir=package_dir,
                origin="local",
            )

        # Might be a package folder inside a project: look upwards for pyproject.toml
        curr = path_obj.parent
        while curr != curr.parent:
            candidate_pyproject = curr / "pyproject.toml"
            if candidate_pyproject.is_file():
                name, version = _read_pyproject_metadata(candidate_pyproject)
                return LibrarySource(
                    name=name,
                    version=version,
                    project_dir=curr.resolve(),
                    package_dir=path_obj,
                    origin="local",
                )
            curr = curr.parent

    raise ValueError(f"Cannot resolve library source from: {spec}")


def installed_version(python: Union[str, Path], dist_name: str) -> Optional[str]:
    """Query the installed version of a package in the target Python environment.

    Args:
        python: Path to target python executable.
        dist_name: Distribution package name (e.g. 'shopkit', 'flask').

    Returns:
        Version string if installed, None otherwise.
    """
    cmd = [
        str(python),
        "-c",
        f"import importlib.metadata as m; print(m.version({dist_name!r}))",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            ver = res.stdout.strip()
            return ver if ver else None
        return None
    except Exception:
        return None


def install_library(python: Union[str, Path], project_dir: Union[str, Path]) -> InstallResult:
    """Install a library into the target Python environment using pip.

    Args:
        python: Path to target python executable.
        project_dir: Path to project directory containing pyproject.toml.

    Returns:
        InstallResult indicating success, output tails, and the installation method used.
    """
    proj_path = Path(project_dir).resolve()

    # 1. First attempt: standard pip install with build isolation
    cmd_standard = [str(python), "-m", "pip", "install", str(proj_path)]
    res = subprocess.run(cmd_standard, capture_output=True, text=True, check=False)

    if res.returncode == 0:
        stdout_lines = res.stdout.strip().splitlines()
        stderr_lines = res.stderr.strip().splitlines()
        return InstallResult(
            success=True,
            stdout_tail="\n".join(stdout_lines[-10:]) if stdout_lines else "",
            stderr_tail="\n".join(stderr_lines[-10:]) if stderr_lines else "",
            method="standard",
        )

    # 2. Second attempt: retry with --no-build-isolation as fallback for offline or restricted environments
    cmd_fallback = [str(python), "-m", "pip", "install", str(proj_path), "--no-build-isolation"]
    res_fallback = subprocess.run(cmd_fallback, capture_output=True, text=True, check=False)

    stdout_lines = res_fallback.stdout.strip().splitlines()
    stderr_lines = res_fallback.stderr.strip().splitlines()
    last_stdout_tail = "\n".join(stdout_lines[-10:]) if stdout_lines else ""
    last_stderr_tail = "\n".join(stderr_lines[-10:]) if stderr_lines else ""

    if res_fallback.returncode == 0:
        return InstallResult(
            success=True,
            stdout_tail=last_stdout_tail,
            stderr_tail=last_stderr_tail,
            method="no-build-isolation",
        )

    # Both attempts failed; tails come from the last attempt with clear notice that two attempts were made
    combined_stderr = f"[SafeDep] Two install attempts made (standard and --no-build-isolation fallback failed).\n{last_stderr_tail}".strip()
    return InstallResult(
        success=False,
        stdout_tail=last_stdout_tail,
        stderr_tail=combined_stderr,
        method="failed",
    )


class UpgradeGuard:
    """Guards library upgrades by recording baseline versions and providing verified rollbacks."""

    def __init__(self, python: Union[str, Path], dist_name: str, old_source: LibrarySource) -> None:
        self.python = str(python)
        self.dist_name = dist_name
        self.old_source = old_source
        self.baseline_version = installed_version(self.python, self.dist_name)
        self.new_source: Optional[LibrarySource] = None

    def install(self, new_source: LibrarySource) -> InstallResult:
        """Record target new source and install it."""
        self.new_source = new_source
        self.baseline_version = installed_version(self.python, self.dist_name)
        result = install_library(self.python, new_source.project_dir)
        if not result.success:
            raise RuntimeError(
                f"Failed to install {new_source.name} {new_source.version}:\n{result.stderr_tail}"
            )
        return result

    def rollback(self) -> InstallResult:
        """Reinstall the old library source and verify that the installed version matches."""
        result = install_library(self.python, self.old_source.project_dir)
        if not result.success:
            raise RuntimeError(
                f"Rollback failed during pip install of {self.old_source.name} {self.old_source.version}:\n{result.stderr_tail}"
            )

        current_ver = installed_version(self.python, self.dist_name)
        if current_ver != self.old_source.version:
            raise RuntimeError(
                f"Rollback verification failed: expected {self.old_source.version}, got {current_ver}"
            )
        return result
