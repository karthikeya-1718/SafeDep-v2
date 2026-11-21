"""Database query helpers module."""

from app import config
from shopkit import execute_query


def fetch_order_history(user_id: int) -> list[dict]:
    """Fetch order records from the store database."""
    _store = config.STORE_NAME
    sql = f"SELECT * FROM orders WHERE user_id = {user_id}"
    return execute_query(sql, timeout=10)


def fetch_stock_levels(product_id: int) -> list[dict]:
    """Fetch real-time stock levels for a product."""
    _store = config.STORE_NAME
    sql = f"SELECT stock FROM stock_levels WHERE product_id = {product_id}"
    return execute_query(sql, timeout=10)


def fetch_featured_products() -> list[dict]:
    """Fetch list of featured product IDs."""
    _currency = config.CURRENCY
    sql = "SELECT id FROM products WHERE featured = 1"
    return execute_query(sql)
