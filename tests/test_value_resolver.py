"""Tests for R3 Value Resolver in safedep.call_fixer.

Strategy:
  (a) parameter or local variable of the enclosing function with the same name (case-insensitive)
  (b) a module-level name in the same file with the same name (case-insensitive)
  (c) an attribute MOD.NAME where MOD is imported in the file from a project module
      (e.g. from app import config) and that module defines a module-level assignment
      with the same name (case-insensitive)
  Unresolved -> None (which triggers manual)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from safedep.call_fixer import resolve_value


def test_resolve_case_a_enclosing_function_parameter():
    """Case (a): parameter of the enclosing function matches (case-insensitive)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "service.py"
        f.write_text(
            "def process_user(user_id: int, auth_token: str):\n"
            "    return fetch_user_profile(user_id)\n",
            encoding="utf-8",
        )
        resolved = resolve_value("auth_token", "process_user", str(f), str(root))
        assert resolved == "auth_token"


def test_resolve_case_a_case_insensitive():
    """Case (a): match is case-insensitive."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "service.py"
        f.write_text(
            "def process_user(user_id: int, Auth_Token: str):\n"
            "    return fetch_user_profile(user_id)\n",
            encoding="utf-8",
        )
        resolved = resolve_value("auth_token", "process_user", str(f), str(root))
        assert resolved == "Auth_Token"


def test_resolve_case_b_module_level_variable():
    """Case (b): module-level name in the same file matches (case-insensitive)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "service.py"
        f.write_text(
            'AUTH_TOKEN = "secret_abc"\n\n'
            "def get_user(user_id: int):\n"
            "    return fetch_user_profile(user_id)\n",
            encoding="utf-8",
        )
        resolved = resolve_value("auth_token", "get_user", str(f), str(root))
        assert resolved == "AUTH_TOKEN"


def test_resolve_case_c_imported_attribute():
    """Case (c): imported module attribute e.g. from app import config -> config.AUTH_TOKEN."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        app_pkg = root / "app"
        app_pkg.mkdir()
        (app_pkg / "__init__.py").write_text("", encoding="utf-8")
        (app_pkg / "config.py").write_text(
            'STORE_NAME = "MyStore"\n'
            'AUTH_TOKEN = "bearer_demo_token_xyz"\n',
            encoding="utf-8",
        )
        service_file = app_pkg / "service.py"
        service_file.write_text(
            "from app import config\n\n"
            "def get_user(user_id: int):\n"
            "    return fetch_user_profile(user_id)\n",
            encoding="utf-8",
        )
        resolved = resolve_value("auth_token", "get_user", str(service_file), str(root))
        assert resolved == "config.AUTH_TOKEN"


def test_resolve_case_c_direct_import_alias():
    """Case (c) with alias: import app.config as cfg -> cfg.AUTH_TOKEN."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        app_pkg = root / "app"
        app_pkg.mkdir()
        (app_pkg / "__init__.py").write_text("", encoding="utf-8")
        (app_pkg / "config.py").write_text(
            'AUTH_TOKEN = "bearer_123"\n',
            encoding="utf-8",
        )
        service_file = app_pkg / "service.py"
        service_file.write_text(
            "import app.config as cfg\n\n"
            "def get_user(user_id: int):\n"
            "    return fetch_user_profile(user_id)\n",
            encoding="utf-8",
        )
        resolved = resolve_value("auth_token", "get_user", str(service_file), str(root))
        assert resolved == "cfg.AUTH_TOKEN"


def test_unresolved_returns_none():
    """When no matching name exists, returns None (never invent placeholders)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "empty.py"
        f.write_text("def do_something(): pass\n", encoding="utf-8")
        resolved = resolve_value("nonexistent_param", "do_something", str(f), str(root))
        assert resolved is None
