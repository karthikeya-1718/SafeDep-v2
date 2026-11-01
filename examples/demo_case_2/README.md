# Demo Case 2: Behavioral Breaking Change Repair Flow

This demo demonstrates SafeDep's two-stage repair architecture:
1. **Pre-Install Repair**: Detects and fixes syntactical / signature-level breaking changes **before** installing the new library.
2. **Post-Install Repair**: Runs the test suite after upgrading, detects behavioral breaking changes, and generates **test-gated** patches.

---

## Files in this Demo

- `old_library.py`: Version 1.0.0 of the Payment & Discount library.
  - `process_payment(amount, currency="USD", timeout=30)`
  - `calculate_discount(price)`: returns 20% discount (0.20 * price).
- `new_library.py`: Version 2.0.0 of the library.
  - **Syntactical breaking change**: Parameter `timeout` was removed from `process_payment`.
  - **Behavioral breaking change**: `calculate_discount` signature is unchanged, but rate changed from 20% to 15% (0.15 * price).
- `client_app.py`: Client application calling both functions.
- `test_client.py`: Unit test suite testing client functionality under v2.0.0.

---

## Step-by-Step Live Demonstration

### Step 1: Analyze Breaking Changes
Run SafeDep to detect breaking changes between the two library versions and locate affected call sites:

```bash
python main.py analyze examples/demo_case_2/old_library.py examples/demo_case_2/new_library.py --client examples/demo_case_2/client_app.py
```

### Step 2: Pre-Install Repair (Syntactical Issues)
Fix the signature issue (`timeout=30`) in `client_app.py` before installing the library:

```bash
python main.py pre-repair examples/demo_case_2/old_library.py examples/demo_case_2/new_library.py --client examples/demo_case_2/client_app.py --action apply_only
```

*Result:* `process_payment(amount, currency=currency, timeout=30)` is automatically patched to `process_payment(amount, currency=currency)`.

### Step 3: Run the Test Suite (Shows Behavioral Failure)
Execute pytest to verify behavior under the new library:

```bash
pytest examples/demo_case_2/test_client.py -v
```

*Result:*
- `test_checkout_payment` **PASSED** (syntactical issue was resolved by Pre-Install Repair).
- `test_order_discount` **FAILED**: `AssertionError: assert 20.0 == 15.0` (Behavioral breaking change detected!).

### Step 4: Post-Install Repair (Test-Gated Behavioral Repair)
Run SafeDep Post-Install Repair to diagnose the test failure and generate a test-verified patch:

```bash
python main.py post-repair --test-target examples/demo_case_2/test_client.py --client examples/demo_case_2/client_app.py
```

*Result:* SafeDep maps the failure to `client_app.py`, updates `0.20` to `0.15`, verifies with pytest that all tests pass, and commits the patch.
