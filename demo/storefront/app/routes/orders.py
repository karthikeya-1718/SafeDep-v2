"""Orders route module."""

from flask import Blueprint, render_template
from app.services.order_service import get_order_history

orders_bp = Blueprint("orders_bp", __name__)


@orders_bp.route("/orders")
def order_list():
    """Display order history with totals."""
    user_id = 42
    orders = get_order_history(user_id)
    return render_template("orders.html", orders=orders)
