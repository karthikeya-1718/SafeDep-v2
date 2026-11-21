"""Static product data and state store."""

PRODUCTS = [
    {"id": 1, "name": "Backpack", "price": 100.0, "emoji": "🎒", "featured": True},
    {"id": 2, "name": "Bottle", "price": 50.0, "emoji": "🧴", "featured": True},
    {"id": 3, "name": "Stove", "price": 75.0, "emoji": "🍳", "featured": True},
    {"id": 4, "name": "Tent", "price": 200.0, "emoji": "⛺", "featured": True},
    {"id": 5, "name": "Lantern", "price": 40.0, "emoji": "🏮", "featured": False},
    {"id": 6, "name": "Compass", "price": 30.0, "emoji": "🧭", "featured": False},
]

# In-memory session state for demo user (user_id = 42)
CART_ITEMS: list[dict] = []
ORDERS: list[dict] = []
USER_PREFERENCES: dict = {
    "notification_channel": "email",
    "updated": False,
}
APPLIED_PROMO: dict = {
    "code": "",
    "rate": 0.0,
}


def reset_store_state() -> None:
    """Reset all in-memory state for testing isolation."""
    CART_ITEMS.clear()
    ORDERS.clear()
    USER_PREFERENCES["notification_channel"] = "email"
    USER_PREFERENCES["updated"] = False
    APPLIED_PROMO["code"] = ""
    APPLIED_PROMO["rate"] = 0.0
