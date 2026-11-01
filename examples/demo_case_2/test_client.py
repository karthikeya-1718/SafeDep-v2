"""Test Suite for Client Application (test_client.py)."""

import sys
from pathlib import Path

# Ensure demo directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from client_app import apply_order_discount, checkout


def test_checkout_payment():
    """Verify payment execution during checkout.

    Before Pre-Install Repair: Fails with TypeError ('timeout' unexpected keyword argument).
    After Pre-Install Repair: Passes because 'timeout=30' was automatically removed.
    """
    res = checkout(100.0)
    assert res["payment"]["status"] == "success"


def test_order_discount():
    """Verify promotional discount under Library v2.0.0 policy.

    BEHAVIORAL FAILURE:
    Under v2.0.0, promotional discount is 15% ($15.00 on $100.00).
    client_app's apply_order_discount still calculates 20% ($20.00).
    Fails with: AssertionError: assert 20.0 == 15.0.
    Post-Install Repair detects this failure and updates the rate to 0.15.
    """
    assert apply_order_discount(100.0) == 15.0
