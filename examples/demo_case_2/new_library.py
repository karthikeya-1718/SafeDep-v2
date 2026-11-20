"""Billing & Pricing Library - Version 2.0.0

Notice: `legacy_discount` has been completely removed in Version 2.0.0.
A new promotion engine is introduced instead.
"""

def calculate_tax(amount: float, tax_rate: float = 0.05) -> float:
    """Calculate tax on an amount."""
    return amount * tax_rate


def get_receipt(order_id: int, total: float) -> dict:
    """Generate a receipt dictionary."""
    return {"order_id": order_id, "total": total, "status": "paid"}


def apply_promotional_code(amount: float, promo_code: str) -> float:
    """New promotion engine introduced in Version 2.0.0."""
    if promo_code == "WELCOME20":
        return amount * 0.80
    return amount
