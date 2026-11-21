"""Notification service module."""

from app import config
from shopkit import fetch_user_profile, set_notification_channel


def send_order_confirmation(user_id: int) -> dict:
    """Send an order confirmation alert using the default notification channel."""
    _store = config.STORE_NAME
    profile = fetch_user_profile(user_id)
    status_msg = set_notification_channel()
    return {
        "recipient": profile.get("name", f"User_{user_id}"),
        "status": status_msg,
    }
