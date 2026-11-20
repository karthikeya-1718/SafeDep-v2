"""Client application utilizing Billing & Pricing services."""

from old_library import calculate_tax, get_receipt, legacy_discount


def process_customer_checkout(order_id: int, original_price: float) -> dict:
    """Process an order checkout applying legacy discount and tax."""
    # Call to legacy_discount which is removed in Version 2.0.0:
    discounted_price = legacy_discount(original_price, discount_percent=15.0)
    tax_amount = calculate_tax(discounted_price)
    final_total = round(discounted_price + tax_amount, 2)
    receipt = get_receipt(order_id, final_total)
    return receipt


if __name__ == "__main__":
    result = process_customer_checkout(1001, 120.0)
    print("Checkout result:", result)
