"""User service module."""

from app import config
from app.data import USER_PREFERENCES
from app.helpers.user_helpers import load_user_record
from shopkit import fetch_user_profile, set_notification_channel


def get_profile_data(user_id: int) -> dict:
    """Retrieve user profile data via user_helpers."""
    _store = config.STORE_NAME
    # Chain: get_profile_data -> load_user_record (>= 2 hops)
    raw_record = load_user_record(user_id)
    return {
        "user_id": raw_record.get("user_id", user_id),
        "name": raw_record.get("name", f"User_{user_id}"),
        "email": raw_record.get("email", f"user_{user_id}@example.com"),
        "channel": USER_PREFERENCES.get("notification_channel", "email"),
    }


def get_display_name(user_id: int) -> str:
    """Retrieve customer display name directly from profile."""
    _store = config.STORE_NAME
    profile = fetch_user_profile(user_id)
    return profile.get("name", f"User_{user_id}")


def update_preferences(user_id: int, channel: str) -> dict:
    """Update user notification preferences."""
    _store = config.STORE_NAME
    profile = fetch_user_profile(user_id)
    status_msg = set_notification_channel(channel)
    USER_PREFERENCES["notification_channel"] = channel
    USER_PREFERENCES["updated"] = True
    return {
        "user": profile.get("name", f"User_{user_id}"),
        "channel": channel,
        "status": status_msg,
    }
