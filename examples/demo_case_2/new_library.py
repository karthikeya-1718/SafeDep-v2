"""New Library (Version 2.0.0) - Payment & Discount Service.

This represents the upgraded third-party library containing:
1. Syntactical breaking change: Parameter 'timeout' was removed from process_payment.
2. Behavioral breaking change: calculate_discount signature is unchanged, but
   the promotional discount rate was updated from 20% (0.20) to 15% (0.15).
"""

API_VERSION = "2.0.0"


# 1. SYNTACTICAL BREAKING CHANGE:
# Parameter 'timeout' was removed!
def process_payment(amount: float, currency: str = "USD") -> dict:
    """Process a customer payment.

    In Version 2.0.0, timeout is managed globally and parameter 'timeout' was removed.
    """
    return {
        "status": "success",
        "amount": amount,
        "currency": currency,
    }


# 2. BEHAVIORAL BREAKING CHANGE:
# Signature is IDENTICAL to v1.0.0 (AST diff cannot detect any signature change),
# but internal algorithm/rate changed from 20% to 15%!
def calculate_discount(price: float) -> float:
    """Calculate promotional discount on purchases.

    In Version 2.0.0, standard promotional discount rate was updated to 15% (0.15).
    """
    return round(price * 0.15, 2)
