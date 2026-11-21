"""Cart route module."""

from flask import Blueprint, redirect, render_template, request, url_for
from app.data import APPLIED_PROMO
from app.services.cart_service import add_to_cart, retrieve_cart_items
from app.services.pricing_service import apply_promo, cart_total

cart_bp = Blueprint("cart_bp", __name__)


@cart_bp.route("/cart")
def view_cart():
    """View shopping cart contents and calculated total."""
    items = retrieve_cart_items()
    subtotal = cart_total(items)
    promo_code = APPLIED_PROMO.get("code", "")
    final_amount = subtotal
    if promo_code:
        final_amount = apply_promo(subtotal, promo_code)

    return render_template(
        "cart.html",
        items=items,
        total_str=f"{final_amount:.2f}",
        promo_code=promo_code,
    )


@cart_bp.route("/cart/add", methods=["POST"])
def add_item():
    """Add product item to cart."""
    product_id = int(request.form.get("product_id", 1))
    quantity = int(request.form.get("quantity", 1))
    add_to_cart(product_id, quantity)
    return redirect(url_for("cart_bp.view_cart"))


@cart_bp.route("/cart/promo", methods=["POST"])
def apply_promo_code():
    """Apply discount voucher code to cart."""
    code = request.form.get("promo_code", "").strip()
    if code:
        APPLIED_PROMO["code"] = code
    return redirect(url_for("cart_bp.view_cart"))
