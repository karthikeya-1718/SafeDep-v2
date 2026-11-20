"""ShopKit E-Commerce Library - Version 2.0.0

Breaking changes introduced:
1. `calculate_shipping`: Positional parameters reordered and base calculation changed.
2. `apply_discount`: 'discount_code' renamed/changed to keyword-only parameter.
3. `process_payment`: Requires 'api_key' parameter without default value.
4. `legacy_tax_calc`: Function removed completely in v2.0.0.
"""

__version__ = "2.0.0"


def calculate_shipping(weight: float, express: bool = False, region: str = "US") -> float:
    """Calculate shipping cost in v2.0.0 (updated regional rates)."""
    rate = 2.0 if region == "US" else 3.5
    base = 20.0 if express else 8.0
    return round(base + (weight * rate), 2)


def apply_discount(subtotal: float, *, promo_code: str) -> float:
    """Apply discount in v2.0.0.

    Breaking changes:
    - `discount_code` renamed to `promo_code`
    - parameter is keyword-only
    - no default value
    """
    discounts = {
        "SAVE10": 0.10,
        "SAVE20": 0.20,
        "DEFAULT": 0.05,
    }
    rate = discounts.get(promo_code, 0.0)
    return round(subtotal * (1.0 - rate), 2)


def process_payment(amount: float, card_number: str, api_key: str, currency: str = "USD") -> dict:
    """Process a customer payment transaction.

    Breaking change: 'api_key' is now required.
    """
    return {
        "status": "APPROVED",
        "amount": amount,
        "currency": currency,
        "transaction_id": f"v2_txn_{int(amount * 100)}",
    }
