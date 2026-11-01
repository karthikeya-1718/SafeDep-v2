"""Client E-Commerce Application utilizing Payment & Discount Service (client_app.py)."""

# Import payment and discount service functions
try:
    from new_library import calculate_discount, process_payment
except ImportError:
    from old_library import calculate_discount, process_payment


def checkout(amount: float, currency: str = "USD") -> dict:
    """Execute customer checkout.

    SYNTACTICAL ISSUE:
    Passes 'timeout=30', which was supported in old_library but removed in new_library.
    Pre-Install Repair detects this breaking change and automatically patches
    this call site to: process_payment(amount, currency=currency).
    """
    payment = process_payment(amount, currency=currency, timeout=30)
    discount = apply_order_discount(amount)

    return {
        "payment": payment,
        "discount": discount,
        "final_price": round(amount - discount, 2),
    }


def apply_order_discount(price: float) -> float:
    """Compute promotional discount for order.

    BEHAVIORAL ISSUE:
    Client application expects 20% discount (0.20 * price) from v1.0.0.
    In v2.0.0, the library discount policy updated to 15% (0.15 * price).
    The test suite will fail (assert 20.0 == 15.0) until Post-Install Repair
    adapts this calculation to return round(price * 0.15, 2).
    """
    # Fix: return round(price * 0.15, 2)
    return round(price * 0.20, 2)
