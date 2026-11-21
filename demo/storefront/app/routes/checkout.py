"""Checkout route module."""

from flask import Blueprint, redirect, render_template, url_for
from app.data import APPLIED_PROMO
from app.services.cart_service import retrieve_cart_items
from app.services.order_service import place_order
from app.services.pricing_service import apply_promo, cart_total
from app.services.user_service import get_display_name

checkout_bp = Blueprint("checkout_bp", __name__)


@checkout_bp.route("/checkout", methods=["GET"])
def checkout_page():
    """Show checkout overview with total and customer name."""
    user_id = 42
    customer_name = get_display_name(user_id)
    items = retrieve_cart_items()
    subtotal = cart_total(items)
    promo_code = APPLIED_PROMO.get("code", "")
    final_amount = subtotal
    if promo_code:
        final_amount = apply_promo(subtotal, promo_code)

    return render_template(
        "checkout.html",
        customer_name=customer_name,
        items=items,
        total_str=f"{final_amount:.2f}",
    )


@checkout_bp.route("/checkout", methods=["POST"])
def place_order_action():
    """Process customer order and redirect to orders list."""
    user_id = 42
    place_order(user_id)
    return redirect(url_for("orders_bp.order_list"))
