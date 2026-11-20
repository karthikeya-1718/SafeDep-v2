"""Billing & Pricing Library - Version 1.0.0"""

def legacy_discount(amount: float, discount_percent: float = 10.0) -> float:
    """Calculate discount using the legacy formula."""
    return amount * (1.0 - discount_percent / 100.0)


def calculate_tax(amount: float, tax_rate: float = 0.05) -> float:
    """Calculate tax on an amount."""
    return amount * tax_rate


def get_receipt(order_id: int, total: float) -> dict:
    """Generate a receipt dictionary."""
    return {"order_id": order_id, "total": total, "status": "paid"}
