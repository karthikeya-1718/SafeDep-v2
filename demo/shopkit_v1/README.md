# ShopKit v1.0.0

ShopKit E-Commerce Library version 1.0.0.

## Layout
- `pyproject.toml`: Package configuration.
- `shopkit/`: Source code package containing functions:
  - `fetch_user_profile(user_id)`
  - `execute_query(sql, timeout=10)`
  - `format_invoice(customer_name, amount)`
  - `set_notification_channel(channel="email")`
  - `legacy_discount(amount, code)`
  - `calculate_total(cart)` (18% tax-inclusive)
- `tests/`: Smoke test suite.

## Installation
```bash
pip install --no-build-isolation ./demo/shopkit_v1
```
