# Demo Case 1: Pre-Install Signature Fixes

This demonstration case illustrates SafeDep's **Pre-Install Repair** capability on a client application upgrading between two versions of a dependency with **purely signature-level breaking changes**.

---

## Scenario Overview

| Function | Old Signature (`v1.0.0`) | New Signature (`v2.0.0`) | Breaking Change Type |
| :--- | :--- | :--- | :--- |
| `execute_query` | `def execute_query(query_str: str, timeout: int = 30)` | `def execute_query(query_str: str)` | **Parameter removed** (`timeout`) |
| `format_invoice` | `def format_invoice(customer_name: str, total_amount: float)` | `def format_invoice(total_amount: float, customer_name: str)` | **Positional parameters reordered** |
| `set_notification_channel` | `def set_notification_channel(channel: str = "email")` | `def set_notification_channel(channel: str)` | **Default value removed** (now required) |
| `fetch_user_profile` | `def fetch_user_profile(user_id: int)` | `def fetch_user_profile(user_id: int, auth_token: str)` | **New required parameter added** (`auth_token`) |

---

## File Structure

```
examples/demo_case_1/
├── old_library.py   # v1.0.0 reference implementation
├── new_library.py   # v2.0.0 with 4 signature-level breaking changes
├── client_app.py    # Client code calling all 4 functions with v1.0.0 signatures
└── README.md        # This guide
```

---

## How to Run with SafeDep

### 1. Analyze Breaking Changes & Impact
Inspect the API differences and view affected call sites in `client_app.py`:
```bash
python main.py analyze examples/demo_case_1/old_library.py examples/demo_case_1/new_library.py --client examples/demo_case_1/client_app.py
```

### 2. Preview Pre-Install Repairs (Report Only)
Preview the auto-generated patches without touching your files:
```bash
python main.py pre-repair examples/demo_case_1/old_library.py examples/demo_case_1/new_library.py --client examples/demo_case_1/client_app.py --action report_only
```

### 3. Apply Patches
Apply the proposed fixes to `client_app.py` (with automated `.bak` backup creation):
```bash
python main.py pre-repair examples/demo_case_1/old_library.py examples/demo_case_1/new_library.py --client examples/demo_case_1/client_app.py --action apply_only
```

