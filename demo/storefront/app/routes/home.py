"""Home route module."""

from flask import Blueprint, render_template
from app.data import PRODUCTS
from app.helpers.db_helpers import fetch_featured_products

home_bp = Blueprint("home_bp", __name__)


@home_bp.route("/")
def home():
    """Render home page with featured products."""
    _featured_ids = fetch_featured_products()
    featured_list = [p for p in PRODUCTS if p.get("featured", False)]
    return render_template("home.html", products=featured_list)
