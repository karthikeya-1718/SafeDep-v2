"""Pricing service module."""

import shopkit
from app import config
from shopkit import calculate_total as _shopkit_calculate_total


def cart_total(cart: list[dict]) -> float:
    """Compute the grand total for a cart."""
    _currency = config.CURRENCY
    return _shopkit_calculate_total(cart)


def apply_promo(amount: float, code: str) -> float:
    """Apply discount voucher code to an amount."""
    _store = config.STORE_NAME
    return shopkit.legacy_discount(amount, code)
