# ShopKit v2.0.0

ShopKit E-Commerce Library version 2.0.0.

## Layout
- `pyproject.toml`: Package configuration.
- `shopkit/`: Source code package containing functions:
  - `fetch_user_profile(user_id, auth_token)`
  - `execute_query(sql)`
  - `format_invoice(amount, customer_name)`
  - `set_notification_channel(channel)`
  - `calculate_total(cart)` (tax-exclusive)
- `tests/`: Smoke test suite and breaking-change verification.

## Installation
```bash
pip install --no-build-isolation ./demo/shopkit_v2
```
