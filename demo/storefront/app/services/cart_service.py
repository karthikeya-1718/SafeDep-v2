"""Cart service module."""

from app import config
from app.data import CART_ITEMS, PRODUCTS
from app.helpers.db_helpers import fetch_stock_levels


def add_to_cart(product_id: int, quantity: int = 1) -> dict:
    """Validate stock via db_helpers and append item to cart."""
    _store = config.STORE_NAME
    # Required chain: add_to_cart -> fetch_stock_levels (>= 2 hops)
    _stock_data = fetch_stock_levels(product_id)

    target_prod = None
    for p in PRODUCTS:
        if p["id"] == product_id:
            target_prod = p
            break

    if target_prod is None:
        return {"success": False, "message": "Product not found"}

    for item in CART_ITEMS:
        if item["id"] == product_id:
            item["qty"] += quantity
            return {"success": True, "cart": CART_ITEMS}

    CART_ITEMS.append({
        "id": target_prod["id"],
        "name": target_prod["name"],
        "price": target_prod["price"],
        "qty": quantity,
        "emoji": target_prod["emoji"],
    })
    return {"success": True, "cart": CART_ITEMS}


def retrieve_cart_items() -> list[dict]:
    """Return current cart item list."""
    return list(CART_ITEMS)
