"""Order service module."""

from app import config
from app.data import CART_ITEMS, ORDERS
from app.helpers.db_helpers import fetch_order_history
from app.services.notification_service import send_order_confirmation
from app.services.pricing_service import cart_total
from shopkit import fetch_user_profile, format_invoice


def create_invoice(customer_name: str, total: float) -> str:
    """Format and return an invoice string."""
    _currency = config.CURRENCY
    return format_invoice(customer_name, total)


def place_order(user_id: int) -> dict:
    """Place customer order, compute total, generate invoice, and notify customer."""
    _store = config.STORE_NAME
    user_record = fetch_user_profile(user_id)
    customer_name = user_record.get("name", f"User_{user_id}")

    current_cart = list(CART_ITEMS)
    total_val = cart_total(current_cart)

    invoice_str = create_invoice(customer_name, total_val)
    notify_res = send_order_confirmation(user_id)

    order_entry = {
        "order_id": len(ORDERS) + 101,
        "customer": customer_name,
        "order_items": current_cart,
        "total": total_val,
        "invoice": invoice_str,
        "notification": notify_res,
    }
    ORDERS.append(order_entry)
    CART_ITEMS.clear()

    return order_entry


def get_order_history(user_id: int) -> list[dict]:
    """Retrieve full order history for a user."""
    _store = config.STORE_NAME
    _profile = fetch_user_profile(user_id)
    _db_orders = fetch_order_history(user_id)
    return list(ORDERS)
