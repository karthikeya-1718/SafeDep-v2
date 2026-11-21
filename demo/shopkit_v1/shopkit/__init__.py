"""ShopKit E-Commerce Library - Version 1.0.0

A lightweight e-commerce toolkit providing user profile management,
query execution, invoice formatting, notifications, discounts, and cart totals.
"""

from __future__ import annotations

from typing import Any, Dict, List

__version__ = "1.0.0"


def fetch_user_profile(user_id: int) -> dict[str, Any]:
    """Fetch profile information for a user.

    Args:
        user_id: Unique integer identifier of the user.

    Returns:
        dict: User profile data containing 'user_id', 'name', 'status', and 'email'.
    """
    return {
        "user_id": user_id,
        "name": f"User_{user_id}",
        "status": "active",
        "email": f"user_{user_id}@example.com",
    }


def execute_query(sql: str, timeout: int = 10) -> list[dict[str, Any]]:
    """Execute a read-only database query with an optional timeout.

    Args:
        sql: SQL query statement string.
        timeout: Query timeout in seconds (default: 10).

    Returns:
        list[dict]: Query result rows as list of column-value mappings.
    """
    return [
        {
            "row_id": 1,
            "query": sql,
            "status": "executed",
            "timeout_applied": timeout,
        }
    ]


def format_invoice(customer_name: str, amount: float) -> str:
    """Format a customer invoice string.

    Args:
        customer_name: Name of the customer.
        amount: Total billed invoice amount.

    Returns:
        str: Formatted invoice line.
    """
    return f"Invoice for {customer_name}: ${amount:.2f}"


def set_notification_channel(channel: str = "email") -> str:
    """Configure customer notification channel.

    Args:
        channel: Notification medium ('email', 'sms', 'push'). Defaults to 'email'.

    Returns:
        str: Confirmation message.
    """
    return f"Notification channel set to {channel}"


def legacy_discount(amount: float, code: str) -> float:
    """Apply promotional discount code to an amount using legacy calculation rules.

    Args:
        amount: Pre-discount amount.
        code: Discount voucher or coupon code.

    Returns:
        float: Discounted amount after applying promo code.
    """
    discount_rates: dict[str, float] = {
        "SAVE10": 0.10,
        "SAVE20": 0.20,
        "HALF": 0.50,
    }
    rate = discount_rates.get(code.upper(), 0.05)
    return round(amount * (1.0 - rate), 2)


def calculate_total(cart: list[dict[str, Any]]) -> float:
    """Calculate the grand total for a cart with tax-inclusive behavior (18% tax).

    Args:
        cart: List of item dictionaries with keys 'price' (float) and 'qty' (int).

    Returns:
        float: Tax-inclusive total rounded to 2 decimal places.
    """
    subtotal = sum(float(item["price"]) * int(item["qty"]) for item in cart)
    # v1 behavior: tax-inclusive (18% tax rate)
    tax_rate = 0.18
    return round(subtotal * (1.0 + tax_rate), 2)


__all__ = [
    "__version__",
    "fetch_user_profile",
    "execute_query",
    "format_invoice",
    "set_notification_channel",
    "legacy_discount",
    "calculate_total",
]
