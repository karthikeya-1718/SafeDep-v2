"""Old Library (Version 1.0.0) - Payment & Discount Service.

This represents the original third-party library before upgrading.
"""

API_VERSION = "1.0.0"


def process_payment(amount: float, currency: str = "USD", timeout: int = 30) -> dict:
    """Process a customer payment with network timeout.

    Syntactical signature in v1.0.0: accepts a 'timeout' parameter.
    """
    return {
        "status": "success",
        "amount": amount,
        "currency": currency,
    }


def calculate_discount(price: float) -> float:
    """Calculate promotional discount on purchases.

    In Version 1.0.0, the standard promotional discount rate is 20% (0.20).
    """
    return round(price * 0.20, 2)
