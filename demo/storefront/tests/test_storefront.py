"""Functional and behavioral test suite for Storefront."""

import pytest
from app.services.pricing_service import cart_total


# ----------------------------------------------------------------------
# Behavioral Tests
# ----------------------------------------------------------------------

@pytest.mark.behavioral
def test_cart_total_single_item():
    """Verify single item total with 18% tax inclusion."""
    total = cart_total([{"price": 100.0, "qty": 1}])
    assert total == 118.0


@pytest.mark.behavioral
def test_cart_total_multiple_items():
    """Verify multiple item total: 100*2 + 50*1 = 250 -> 250*1.18 = 295.0."""
    total = cart_total([{"price": 100.0, "qty": 2}, {"price": 50.0, "qty": 1}])
    assert total == 295.0


@pytest.mark.behavioral
def test_cart_page_shows_total(client):
    """Add backpack (id=1, price=100) and verify GET /cart shows '118.00'."""
    client.post("/cart/add", data={"product_id": 1, "quantity": 1})
    response = client.get("/cart")
    assert response.status_code == 200
    assert "118.00" in response.get_data(as_text=True)


@pytest.mark.behavioral
def test_checkout_page_shows_total(client):
    """Add backpack and verify GET /checkout displays '118.00'."""
    client.post("/cart/add", data={"product_id": 1, "quantity": 1})
    response = client.get("/checkout")
    assert response.status_code == 200
    assert "118.00" in response.get_data(as_text=True)


@pytest.mark.behavioral
def test_order_history_records_total(client):
    """Place order with backpack and verify GET /orders records '118.00'."""
    client.post("/cart/add", data={"product_id": 1, "quantity": 1})
    client.post("/checkout")
    response = client.get("/orders")
    assert response.status_code == 200
    assert "118.00" in response.get_data(as_text=True)


# ----------------------------------------------------------------------
# Smoke Tests
# ----------------------------------------------------------------------

@pytest.mark.smoke
def test_home_loads(client):
    """Verify home page loads successfully with featured products."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Featured Products" in response.get_data(as_text=True)


@pytest.mark.smoke
def test_search_returns_results(client):
    """Verify search returns matching products."""
    response = client.get("/products?q=tent")
    assert response.status_code == 200
    assert "Tent" in response.get_data(as_text=True)


@pytest.mark.smoke
def test_profile_page_shows_name(client):
    """Verify profile page displays customer display name."""
    response = client.get("/profile")
    assert response.status_code == 200
    assert "User_42" in response.get_data(as_text=True)


@pytest.mark.smoke
def test_place_order_creates_invoice(client):
    """Verify order placement creates invoice and order entry."""
    client.post("/cart/add", data={"product_id": 1, "quantity": 1})
    response = client.post("/checkout", follow_redirects=True)
    assert response.status_code == 200
    assert "Invoice for User_42: $118.00" in response.get_data(as_text=True)


@pytest.mark.smoke
def test_promo_code_applies(client):
    """Verify applying promo code recalculates cart amount."""
    client.post("/cart/add", data={"product_id": 1, "quantity": 1})
    # Apply SAVE10 (10% discount on 118.0 -> 106.20)
    response = client.post("/cart/promo", data={"promo_code": "SAVE10"}, follow_redirects=True)
    assert response.status_code == 200
    assert "106.20" in response.get_data(as_text=True)
