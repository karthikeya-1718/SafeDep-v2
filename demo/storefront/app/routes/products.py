"""Products route module."""

from flask import Blueprint, abort, render_template, request
from app.data import PRODUCTS
from app.services.search_service import search_products

products_bp = Blueprint("products_bp", __name__)


@products_bp.route("/products")
def product_list():
    """List or search products."""
    query = request.args.get("q", "")
    items = search_products(query)
    return render_template("products.html", products=items, query=query)


@products_bp.route("/product/<int:pid>")
def product_detail(pid: int):
    """View details for a single product without calling shopkit."""
    prod = next((p for p in PRODUCTS if p["id"] == pid), None)
    if prod is None:
        abort(404)
    return render_template("product_detail.html", product=prod)
