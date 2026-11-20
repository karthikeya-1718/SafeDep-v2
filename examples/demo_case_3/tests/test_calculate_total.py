"""Tests verifying customer billing calculations.

Expectation: Customer total must reflect tax-inclusive billing
(e.g., $100 subtotal with 10% tax = $110.00; $200 with $20 discount = $198.00).

These tests:
- Pass on old_library behavior (tax-inclusive: $100 -> $110.0)
- Fail on new_library behavior (tax-exclusive: returns $100.0 != $110.0)
"""

import sys
from pathlib import Path

# Add demo_case_3 to sys.path
demo_dir = str(Path(__file__).resolve().parent.parent)
if demo_dir not in sys.path:
    sys.path.insert(0, demo_dir)

import pytest
from client_app import compute_final_bill


def test_standard_checkout_includes_tax():
    """Verify that a standard $100 purchase results in $110 (10% tax included)."""
    total = compute_final_bill(100.0, 0.0)
    assert total == 110.0, f"Expected tax-inclusive total of $110.0, got ${total}"


def test_discounted_checkout_includes_tax():
    """Verify that a $200 purchase with $20 discount results in $198 ($180 + 10% tax)."""
    total = compute_final_bill(200.0, 20.0)
    assert total == 198.0, f"Expected tax-inclusive total of $198.0, got ${total}"
