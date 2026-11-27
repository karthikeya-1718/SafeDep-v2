"""Integration tests for storefront pre-repair on a temporary copy."""

from __future__ import annotations

import ast
import shutil
import tempfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
demo_storefront = repo_root / "demo" / "storefront"
demo_v1 = repo_root / "demo" / "shopkit_v1" / "shopkit"
demo_v2 = repo_root / "demo" / "shopkit_v2" / "shopkit"


@pytest.mark.skipif(
    not (demo_storefront.exists() and demo_v1.exists() and demo_v2.exists()),
    reason="demo/storefront or shopkit versions not present",
)
def test_storefront_prerepair_full_application():
    """Run apply on a temporary copy of demo/storefront and assert all fixes via AST."""
    from safedep.pre_install_repair import run_pre_install_repair
    from safedep.api_diff import get_breaking_changes
    from safedep.call_graph import get_affected_call_sites

    with tempfile.TemporaryDirectory() as td:
        tmp_storefront = Path(td) / "storefront"
        shutil.copytree(demo_storefront, tmp_storefront)

        client_app = tmp_storefront / "app"

        # Run pre-repair apply_only
        report = run_pre_install_repair(
            old_path=demo_v1,
            new_path=demo_v2,
            client_path=client_app,
            action="apply_only",
            library_name="shopkit",
        )

        assert report.applied is True

        # 1. Assert via AST: all 6 fetch_user_profile calls pass keyword auth_token=config.AUTH_TOKEN
        fup_files = [
            client_app / "helpers" / "user_helpers.py",
            client_app / "services" / "user_service.py",
            client_app / "services" / "order_service.py",
            client_app / "services" / "notification_service.py",
        ]
        fup_calls = []
        for fp in fup_files:
            tree = ast.parse(fp.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn_name = ""
                    if isinstance(node.func, ast.Name):
                        fn_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        fn_name = node.func.attr
                    if fn_name == "fetch_user_profile":
                        fup_calls.append((fp.name, node))

        assert len(fup_calls) == 6, f"Expected 6 fetch_user_profile calls, found {len(fup_calls)}"
        for fname, call in fup_calls:
            kw_names = [kw.arg for kw in call.keywords]
            assert "auth_token" in kw_names, f"{fname}: fetch_user_profile missing auth_token keyword"
            auth_kw = next(kw for kw in call.keywords if kw.arg == "auth_token")
            unparsed = ast.unparse(auth_kw.value)
            assert unparsed == "config.AUTH_TOKEN", f"{fname}: expected config.AUTH_TOKEN, got {unparsed}"

        # 2. Assert: the 3 execute_query calls that had timeout lost it
        eq_with_timeout_files = [
            client_app / "helpers" / "db_helpers.py",
            client_app / "catalog.py",
        ]
        for fp in eq_with_timeout_files:
            tree = ast.parse(fp.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                    if fn_name == "execute_query":
                        kw_names = [kw.arg for kw in node.keywords]
                        assert "timeout" not in kw_names, f"{fp.name}: timeout was not removed from execute_query"

        # 3. Assert: 2 other execute_query calls unchanged byte-for-byte
        # fetch_featured_products in db_helpers.py, search_products in search_service.py
        orig_search = (demo_storefront / "app" / "services" / "search_service.py").read_bytes()
        new_search = (client_app / "services" / "search_service.py").read_bytes()
        assert orig_search == new_search, "search_service.py was modified unexpectedly"

        # 4. set_notification_channel in send_order_confirmation passes channel='email'
        notif_file = client_app / "services" / "notification_service.py"
        tree_notif = ast.parse(notif_file.read_text(encoding="utf-8"))
        snc_calls = []
        for node in ast.walk(tree_notif):
            if isinstance(node, ast.Call):
                fn_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if fn_name == "set_notification_channel":
                    snc_calls.append(node)
        assert len(snc_calls) == 1
        snc_call = snc_calls[0]
        assert any(kw.arg == "channel" and ast.unparse(kw.value) == "'email'" for kw in snc_call.keywords)

        # 5. format_invoice arguments are swapped
        order_file = client_app / "services" / "order_service.py"
        tree_order = ast.parse(order_file.read_text(encoding="utf-8"))
        fi_calls = []
        for node in ast.walk(tree_order):
            if isinstance(node, ast.Call):
                fn_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if fn_name == "format_invoice":
                    fi_calls.append(node)
        assert len(fi_calls) == 1
        fi = fi_calls[0]
        assert ast.unparse(fi.args[0]) == "total"
        assert ast.unparse(fi.args[1]) == "customer_name"

        # 6. legacy_discount line is unchanged
        pricing_file = client_app / "services" / "pricing_service.py"
        assert "shopkit.legacy_discount(amount, code)" in pricing_file.read_text(encoding="utf-8")

        # 7. catalog.py is fixed (execute_query without timeout)
        cat_file = client_app / "catalog.py"
        cat_src = cat_file.read_text(encoding="utf-8")
        assert "timeout" not in cat_src
        assert 'execute_query("SELECT id, stock FROM inventory")' in cat_src

        # 8. Re-scan reports 0 auto-fixable and exactly 1 manual
        diff_res = get_breaking_changes(demo_v1, demo_v2)
        remaining_sites = get_affected_call_sites(client_app, diff_res, library_name="shopkit")
        assert len(remaining_sites) == 1
        assert remaining_sites[0].get("is_removal") is True or remaining_sites[0].get("callee_name") == "legacy_discount"

        # 9. No placeholder strings anywhere
        for py_file in client_app.rglob("*.py"):
            txt = py_file.read_text(encoding="utf-8")
            assert "<AUTH_TOKEN>" not in txt
            assert "<REQUIRED_VALUE>" not in txt
