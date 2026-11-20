"""Order Billing Library - Version 1.0.0

In Version 1.0.0, calculate_total(...) uses tax-INCLUSIVE calculation:
the returned total already includes 10% sales tax by default.
"""


def calculate_total(subtotal: float, discount: float = 0.0) -> float:
    """Calculate the final order total.

    Version 1.0 (tax-inclusive):
    Applies discount, then includes 10% tax automatically:
    total = (subtotal - discount) * 1.10
    """
    net_amount = max(0.0, subtotal - discount)
    tax_rate = 0.10
    total = net_amount * (1.0 + tax_rate)
    return round(total, 2)
