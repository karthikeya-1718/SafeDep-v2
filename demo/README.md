# ShopKit & Storefront Demo

This folder provides a complete, realistic e-commerce demonstration of SafeDep.

---

## Structure

```
demo/
├── shopkit_v1/          # Original library (v1.0.0)
│   └── __init__.py
├── shopkit_v2/          # Upgraded library with breaking changes (v2.0.0)
│   └── __init__.py
└── storefront/          # Client project using shopkit
    ├── app.py           # Client application
    └── tests/           # Client test suite
        └── test_checkout.py
```

---

## Breaking Changes in ShopKit v2.0.0

1. **`apply_discount`**: Parameter renamed to `promo_code` (keyword-only, no default).
2. **`calculate_shipping`**: Internal rate changes and new parameter `region`.
3. **`process_payment`**: New required parameter `api_key`.
4. **`legacy_tax_calc`**: Function removed completely.

---

## SafeDep Commands for this Demo

### 1. Analyze breaking changes
```bash
python main.py analyze demo/shopkit_v1/__init__.py demo/shopkit_v2/__init__.py --client demo/storefront/app.py
```

### 2. Run Pre-Install Repair
```bash
python main.py pre-repair demo/shopkit_v1/__init__.py demo/shopkit_v2/__init__.py --client demo/storefront/app.py --action report_only
```
