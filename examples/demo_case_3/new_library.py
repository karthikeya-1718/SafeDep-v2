"""Order Billing Library - Version 2.0.0

In Version 2.0.0, calculate_total(...) has the EXACT SAME signature,
but uses tax-EXCLUSIVE calculation: tax is no longer added automatically,
returning strictly the net amount.
"""


def calculate_total(subtotal: float, discount: float = 0.0) -> float:
    """Calculate the final order total.

    Version 2.0 (tax-exclusive):
    Returns purely net total without adding tax.
    total = subtotal - discount
    Tax calculation is now separated or caller-managed.
    """
    net_amount = max(0.0, subtotal - discount)
    return round(net_amount, 2)
