"""Unit tests for the Storefront checkout application."""

import sys
from pathlib import Path

# Add demo directory to sys.path so demo modules import cleanly
demo_dir = str(Path(__file__).resolve().parent.parent.parent)
if demo_dir not in sys.path:
    sys.path.insert(0, demo_dir)

import pytest
from demo.storefront.app import checkout_cart


def test_checkout_cart_basic():
    """Verify basic storefront cart calculation."""
    items = [
        {"name": "Item A", "price": 50.0, "quantity": 2, "weight": 2.0},
    ]
    result = checkout_cart(items, card_number="4111-1111-1111-1234", discount_code="SAVE10")
    assert result["order_id"] == 9001
    assert result["subtotal"] == 100.0
    assert result["payment"]["status"] == "APPROVED"
