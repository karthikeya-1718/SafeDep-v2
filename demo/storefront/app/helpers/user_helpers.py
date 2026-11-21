"""User helpers module."""

from app import config
from shopkit import fetch_user_profile


def load_user_record(user_id: int) -> dict:
    """Load the raw user record from ShopKit."""
    _store = config.STORE_NAME
    return fetch_user_profile(user_id)
