"""Storefront E-Commerce Client Application."""

import shopkit_v1 as shopkit


def checkout_cart(cart_items: list[dict], card_number: str, discount_code: str = "SAVE10") -> dict:
    """Process an order checkout using ShopKit APIs."""
    subtotal = sum(item["price"] * item["quantity"] for item in cart_items)
    total_weight = sum(item.get("weight", 1.0) * item["quantity"] for item in cart_items)

    # 1. Signature change in v2 (promo_code is keyword-only):
    discounted = shopkit.apply_discount(subtotal, discount_code)

    # 2. Shipping calculation:
    shipping = shopkit.calculate_shipping(total_weight, express=True)

    # 3. Removed function in v2:
    tax = shopkit.legacy_tax_calc(discounted)

    final_amount = round(discounted + shipping + tax, 2)

    # 4. Added required parameter in v2 (api_key):
    payment = shopkit.process_payment(final_amount, card_number)

    return {
        "order_id": 9001,
        "subtotal": subtotal,
        "final_amount": final_amount,
        "payment": payment,
    }


if __name__ == "__main__":
    items = [
        {"name": "Sneakers", "price": 80.0, "quantity": 1, "weight": 1.5},
        {"name": "Socks", "price": 10.0, "quantity": 2, "weight": 0.2},
    ]
    receipt = checkout_cart(items, card_number="4111-1111-1111-1234")
    print("Storefront checkout completed:", receipt)
