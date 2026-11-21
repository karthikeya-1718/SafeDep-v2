"""Smoke tests for ShopKit v2.0.0 and verification of breaking changes against v1 style."""

import pytest
import sys
from pathlib import Path

# Add package root to sys.path
package_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(package_root))

import shopkit
from shopkit import (
    __version__,
    fetch_user_profile,
    execute_query,
    format_invoice,
    set_notification_channel,
    calculate_total,
)


def test_v2_version():
    assert __version__ == "2.0.0"


def test_v2_fetch_user_profile():
    profile = fetch_user_profile(42, auth_token="bearer_xyz")
    assert isinstance(profile, dict)
    assert profile["name"] == "User_42"
    assert profile["status"] == "authenticated"


def test_v2_execute_query():
    rows = execute_query("SELECT * FROM users")
    assert isinstance(rows, list)
    assert rows[0]["query"] == "SELECT * FROM users"


def test_v2_format_invoice():
    # v2 accepts (amount, customer_name)
    result = format_invoice(149.99, "Alex")
    assert isinstance(result, str)
    assert result == "Invoice for Alex: $149.99"


def test_v2_set_notification_channel():
    # v2 requires channel argument
    res = set_notification_channel("push")
    assert res == "Notification channel set to push"


def test_v2_calculate_total():
    cart = [{"price": 100.0, "qty": 1}]
    # v2 returns 100.0 (tax-exclusive)
    total = calculate_total(cart)
    assert total == 100.0


# ----------------------------------------------------------------------
# Tests proving v1-style calls fail on v2
# ----------------------------------------------------------------------

def test_v1_call_fetch_user_profile_fails_on_v2():
    """fetch_user_profile(42) fails with TypeError on v2 because auth_token is required."""
    with pytest.raises(TypeError) as excinfo:
        fetch_user_profile(42)  # type: ignore[call-arg]
    assert "auth_token" in str(excinfo.value) or "missing" in str(excinfo.value)


def test_v1_call_execute_query_with_timeout_fails_on_v2():
    """execute_query(sql, timeout=10) fails with TypeError on v2 because timeout kwarg was removed."""
    with pytest.raises(TypeError) as excinfo:
        execute_query("SELECT 1", timeout=10)  # type: ignore[call-arg]
    assert "timeout" in str(excinfo.value) or "unexpected keyword" in str(excinfo.value)


def test_v1_call_set_notification_channel_no_args_fails_on_v2():
    """set_notification_channel() fails with TypeError on v2 because default value was removed."""
    with pytest.raises(TypeError) as excinfo:
        set_notification_channel()  # type: ignore[call-arg]
    assert "channel" in str(excinfo.value) or "missing" in str(excinfo.value)


def test_v1_legacy_discount_removed_in_v2():
    """legacy_discount does not exist in v2, triggering AttributeError / ImportError."""
    assert not hasattr(shopkit, "legacy_discount")


def test_v1_call_format_invoice_on_v2():
    """Demonstrate what happens when calling format_invoice('Alex', 149.99) on v2.

    In v2, signature is format_invoice(amount, customer_name).
    Calling format_invoice('Alex', 149.99) passes amount='Alex' (str) and customer_name=149.99 (float).
    Inside format_invoice: f'Invoice for {customer_name}: ${amount:.2f}'
    Attempting to format 'Alex' (str) with float specifier ':.2f' raises:
        ValueError: Unknown format code 'f' for object of type 'str'
    """
    with pytest.raises(ValueError) as excinfo:
        format_invoice("Alex", 149.99)  # type: ignore[arg-type]
    assert "Unknown format code 'f'" in str(excinfo.value)
