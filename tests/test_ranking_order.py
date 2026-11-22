"""Tests that ranking order and labels match for storefront analysis."""

import pytest
from pathlib import Path
from safedep.api_diff import get_breaking_changes
from safedep.call_graph import get_affected_call_sites
from safedep.risk_ranker import rank_affected_call_sites

repo_root = Path(__file__).resolve().parent.parent
storefront_app = repo_root / "demo" / "storefront" / "app"
shopkit_v1 = repo_root / "demo" / "shopkit_v1" / "shopkit"
shopkit_v2 = repo_root / "demo" / "shopkit_v2" / "shopkit"

RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


@pytest.fixture(scope="module")
def ranked():
    diff = get_breaking_changes(shopkit_v1, shopkit_v2)
    sites = get_affected_call_sites(storefront_app, diff, library_name="shopkit")
    return rank_affected_call_sites(
        sites, project_path=storefront_app, tier_ordering=True, library_name="shopkit"
    )


@pytest.mark.skipif(
    not (storefront_app.exists() and shopkit_v1.exists() and shopkit_v2.exists()),
    reason="demo/storefront or shopkit demo folders are missing",
)
def test_first_site_is_catalog_startup_critical(ranked):
    """(a) The first site must be execute_query in catalog.py, startup tier, CRITICAL."""
    first = ranked[0]
    callee = first.get("callee_name") or first.get("callee") or str(first.get("function_name"))
    file_name = Path(first.get("file_path", "")).name
    when = first.get("when_fails")
    level = first.get("risk_level")

    assert callee == "execute_query", f"Expected execute_query as first site, got {callee}"
    assert file_name == "catalog.py", f"Expected catalog.py as first file, got {file_name}"
    assert when == "startup", f"Expected when_fails=startup for first site, got {when}"
    assert level == "CRITICAL", f"Expected CRITICAL for startup first site, got {level}"


@pytest.mark.skipif(
    not (storefront_app.exists() and shopkit_v1.exists() and shopkit_v2.exists()),
    reason="demo/storefront or shopkit demo folders are missing",
)
def test_on_call_rows_risk_score_non_increasing(ranked):
    """(b) Within the on_call rows, risk_score must be non-increasing."""
    on_call_rows = [s for s in ranked if s.get("when_fails") == "on_call"]
    assert on_call_rows, "No on_call rows found"
    scores = [s.get("risk_score", 0) for s in on_call_rows]
    for i in range(1, len(scores)):
        assert scores[i] <= scores[i - 1], (
            f"on_call risk_score increased at index {i}: {scores[i-1]} -> {scores[i]}"
        )


@pytest.mark.skipif(
    not (storefront_app.exists() and shopkit_v1.exists() and shopkit_v2.exists()),
    reason="demo/storefront or shopkit demo folders are missing",
)
def test_on_call_rows_risk_level_non_increasing_severity(ranked):
    """(c) Within the on_call rows, risk_level must never increase in severity (CRIT >= HIGH >= MED >= LOW)."""
    on_call_rows = [s for s in ranked if s.get("when_fails") == "on_call"]
    assert on_call_rows, "No on_call rows found"
    levels = [s.get("risk_level", "LOW") for s in on_call_rows]
    for i in range(1, len(levels)):
        prev_order = RISK_ORDER.get(levels[i - 1], 3)
        curr_order = RISK_ORDER.get(levels[i], 3)
        assert curr_order >= prev_order, (
            f"risk_level severity increased at index {i}: {levels[i-1]} -> {levels[i]}"
        )
