"""ShopKit E-Commerce Library - Version 2.0.0

A modernized e-commerce toolkit with updated security and accounting semantics.
Breaking changes introduced relative to v1.0.0:
1. fetch_user_profile requires 'auth_token'.
2. execute_query removed 'timeout' parameter.
3. format_invoice parameters reordered to (amount, customer_name).
4. set_notification_channel removed default value (channel is now required).
5. legacy_discount removed entirely.
6. calculate_total is now tax-exclusive.
"""

from __future__ import annotations

from typing import Any, Dict, List

__version__ = "2.0.0"


def fetch_user_profile(user_id: int, auth_token: str) -> dict[str, Any]:
    """Fetch profile information for an authenticated user.

    Breaking change: Added required parameter 'auth_token'.

    Args:
        user_id: Unique integer identifier of the user.
        auth_token: Authentication bearer or session token.

    Returns:
        dict: User profile data containing 'user_id', 'name', 'status', and 'email'.
    """
    return {
        "user_id": user_id,
        "name": f"User_{user_id}",
        "status": "authenticated",
        "email": f"user_{user_id}@example.com",
    }


def execute_query(sql: str) -> list[dict[str, Any]]:
    """Execute a read-only database query.

    Breaking change: Removed 'timeout' parameter.

    Args:
        sql: SQL query statement string.

    Returns:
        list[dict]: Query result rows as list of column-value mappings.
    """
    return [
        {
            "row_id": 1,
            "query": sql,
            "status": "executed",
        }
    ]


def format_invoice(amount: float, customer_name: str) -> str:
    """Format a customer invoice string.

    Breaking change: Positional parameters reordered to (amount, customer_name).

    Args:
        amount: Total billed invoice amount.
        customer_name: Name of the customer.

    Returns:
        str: Formatted invoice line.
    """
    return f"Invoice for {customer_name}: ${amount:.2f}"


def set_notification_channel(channel: str) -> str:
    """Configure customer notification channel.

    Breaking change: Default value removed; 'channel' parameter is now required.

    Args:
        channel: Notification medium ('email', 'sms', 'push').

    Returns:
        str: Confirmation message.
    """
    return f"Notification channel set to {channel}"


def calculate_total(cart: list[dict[str, Any]]) -> float:
    """Calculate the total for a cart with tax-exclusive behavior.

    Breaking change: Same signature as v1, but returns the raw subtotal without
    adding tax (tax must be handled separately by caller).

    Args:
        cart: List of item dictionaries with keys 'price' (float) and 'qty' (int).

    Returns:
        float: Tax-exclusive total rounded to 2 decimal places.
    """
    subtotal = sum(float(item["price"]) * int(item["qty"]) for item in cart)
    # v2 behavior: tax-exclusive (subtotal only)
    return round(subtotal, 2)


__all__ = [
    "__version__",
    "fetch_user_profile",
    "execute_query",
    "format_invoice",
    "set_notification_channel",
    "calculate_total",
]
