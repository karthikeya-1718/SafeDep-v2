"""Smoke tests for ShopKit v1.0.0."""

import pytest
import sys
from pathlib import Path

# Add package root to sys.path
package_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(package_root))

from shopkit import (
    __version__,
    fetch_user_profile,
    execute_query,
    format_invoice,
    set_notification_channel,
    legacy_discount,
    calculate_total,
)


def test_v1_version():
    assert __version__ == "1.0.0"


def test_v1_fetch_user_profile():
    profile = fetch_user_profile(42)
    assert isinstance(profile, dict)
    assert profile["name"] == "User_42"
    assert profile["user_id"] == 42


def test_v1_execute_query():
    rows = execute_query("SELECT * FROM products")
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["timeout_applied"] == 10

    # Custom timeout
    rows_custom = execute_query("SELECT * FROM products", timeout=30)
    assert rows_custom[0]["timeout_applied"] == 30


def test_v1_format_invoice():
    result = format_invoice("Alex", 149.99)
    assert isinstance(result, str)
    assert result == "Invoice for Alex: $149.99"


def test_v1_set_notification_channel():
    # Default value works in v1
    res_default = set_notification_channel()
    assert res_default == "Notification channel set to email"

    res_custom = set_notification_channel("sms")
    assert res_custom == "Notification channel set to sms"


def test_v1_legacy_discount():
    # Exists in v1
    discounted = legacy_discount(100.0, "SAVE10")
    assert discounted == 90.0


def test_v1_calculate_total():
    cart = [{"price": 100.0, "qty": 1}]
    # 100 * 1.18 = 118.0
    total = calculate_total(cart)
    assert total == 118.0
