"""Search service module."""

from app import config
from app.data import PRODUCTS
from shopkit import execute_query


def search_products(query: str) -> list[dict]:
    """Search products by query term."""
    _currency = config.CURRENCY
    sql = f"SELECT * FROM products WHERE name LIKE '%{query}%'"
    _db_res = execute_query(sql)

    q = query.lower().strip()
    if not q:
        return list(PRODUCTS)
    return [p for p in PRODUCTS if q in p["name"].lower()]
