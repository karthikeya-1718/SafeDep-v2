"""Integration analysis test for demo/storefront against shopkit v1 and v2."""

import pytest
from pathlib import Path
from safedep.api_diff import get_breaking_changes
from safedep.call_graph import get_affected_call_sites
from safedep.risk_ranker import rank_affected_call_sites

repo_root = Path(__file__).resolve().parent.parent
storefront_app = repo_root / "demo" / "storefront" / "app"
shopkit_v1 = repo_root / "demo" / "shopkit_v1" / "shopkit"
shopkit_v2 = repo_root / "demo" / "shopkit_v2" / "shopkit"


@pytest.mark.skipif(
    not (storefront_app.exists() and shopkit_v1.exists() and shopkit_v2.exists()),
    reason="demo/storefront or shopkit demo folders are missing",
)
def test_storefront_analysis_exact_breaking_call_sites():
    """Verify that analysis on storefront against shopkit v1 -> v2 reports exactly the 12 breaking call sites."""
    diff = get_breaking_changes(shopkit_v1, shopkit_v2)
    sites = get_affected_call_sites(storefront_app, diff, library_name="shopkit")
    ranked = rank_affected_call_sites(sites, project_path=storefront_app, tier_ordering=True, library_name="shopkit")

    # Assert count is exactly 12
    assert len(ranked) == 12

    # Map each site to tuple: (callee, file_basename, caller_name)
    tuples = [
        (
            s.get("callee_name") or s.get("callee") or str(s.get("function_name")),
            Path(s.get("file_path", "")).name,
            s.get("caller_name") or s.get("caller") or "<module>",
        )
        for s in ranked
    ]

    expected_12 = [
        # fetch_user_profile x6
        ("fetch_user_profile", "user_helpers.py", "load_user_record"),
        ("fetch_user_profile", "user_service.py", "get_display_name"),
        ("fetch_user_profile", "user_service.py", "update_preferences"),
        ("fetch_user_profile", "order_service.py", "place_order"),
        ("fetch_user_profile", "order_service.py", "get_order_history"),
        ("fetch_user_profile", "notification_service.py", "send_order_confirmation"),
        # execute_query x3
        ("execute_query", "catalog.py", "<module>"),
        ("execute_query", "db_helpers.py", "fetch_order_history"),
        ("execute_query", "db_helpers.py", "fetch_stock_levels"),
        # format_invoice x1
        ("format_invoice", "order_service.py", "create_invoice"),
        # set_notification_channel x1
        ("set_notification_channel", "notification_service.py", "send_order_confirmation"),
        # legacy_discount x1
        ("legacy_discount", "pricing_service.py", "apply_promo"),
    ]

    for item in expected_12:
        assert item in tuples, f"Expected breaking site {item} not found in {tuples}"

    # Assert these 3 are NOT reported:
    assert ("execute_query", "db_helpers.py", "fetch_featured_products") not in tuples
    assert ("execute_query", "search_service.py", "search_products") not in tuples
    assert ("set_notification_channel", "user_service.py", "update_preferences") not in tuples

    # Assert the first ranked site is the execute_query call in catalog.py with when_fails == "startup"
    first_site = ranked[0]
    assert first_site.get("callee_name") == "execute_query"
    assert Path(first_site.get("file_path", "")).name == "catalog.py"
    assert first_site.get("when_fails") == "startup"

    # Assert that legacy_discount has fixability "manual"
    legacy_site = next(s for s in ranked if s.get("callee_name") == "legacy_discount")
    assert legacy_site.get("fixability") == "manual"
