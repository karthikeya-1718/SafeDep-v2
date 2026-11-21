"""Flask application factory."""

from flask import Flask


def create_app() -> Flask:
    """Create and configure the Flask storefront application."""
    application = Flask(__name__)
    application.config["SECRET_KEY"] = "demo-secret-key-12345"

    # Startup import of catalog (executes module-level inventory query)
    import app.catalog  # noqa: F401

    # Register all application route blueprints
    from app.routes.cart import cart_bp
    from app.routes.checkout import checkout_bp
    from app.routes.home import home_bp
    from app.routes.orders import orders_bp
    from app.routes.products import products_bp
    from app.routes.profile import profile_bp

    application.register_blueprint(home_bp)
    application.register_blueprint(products_bp)
    application.register_blueprint(cart_bp)
    application.register_blueprint(checkout_bp)
    application.register_blueprint(profile_bp)
    application.register_blueprint(orders_bp)

    @application.context_processor
    def inject_globals():
        from app import config
        from app.catalog import INVENTORY
        return {
            "STORE_NAME": config.STORE_NAME,
            "CURRENCY": config.CURRENCY,
            "TAX_NOTE": config.TAX_NOTE,
            "INVENTORY_COUNT": len(INVENTORY),
        }

    return application
