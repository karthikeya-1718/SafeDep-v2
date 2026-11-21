"""Profile route module."""

from flask import Blueprint, redirect, render_template, request, url_for
from app.services.user_service import get_profile_data, update_preferences

profile_bp = Blueprint("profile_bp", __name__)


@profile_bp.route("/profile", methods=["GET"])
def profile_page():
    """Display user profile details."""
    user_id = 42
    profile = get_profile_data(user_id)
    return render_template("profile.html", profile=profile)


@profile_bp.route("/profile", methods=["POST"])
def save_preferences():
    """Save customer notification preference."""
    user_id = 42
    channel = request.form.get("channel", "email")
    update_preferences(user_id, channel)
    return redirect(url_for("profile_bp.profile_page"))
