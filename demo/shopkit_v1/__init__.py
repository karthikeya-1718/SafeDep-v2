"""ShopKit E-Commerce Library - Version 1.0.0"""

__version__ = "1.0.0"


def calculate_shipping(weight: float, express: bool = False) -> float:
    """Calculate shipping cost based on package weight."""
    base = 15.0 if express else 5.0
    return round(base + (weight * 1.5), 2)


def apply_discount(subtotal: float, discount_code: str = "DEFAULT") -> float:
    """Apply discount code to order subtotal."""
    discounts = {
        "SAVE10": 0.10,
        "SAVE20": 0.20,
        "DEFAULT": 0.05,
    }
    rate = discounts.get(discount_code, 0.0)
    return round(subtotal * (1.0 - rate), 2)


def process_payment(amount: float, card_number: str, currency: str = "USD") -> dict:
    """Process a customer payment transaction."""
    return {
        "status": "APPROVED",
        "amount": amount,
        "currency": currency,
        "transaction_id": f"txn_{int(amount * 100)}",
    }


def legacy_tax_calc(amount: float) -> float:
    """Legacy tax calculation formula."""
    return round(amount * 0.08, 2)
