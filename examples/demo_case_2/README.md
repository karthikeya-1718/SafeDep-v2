# Demo Case 2: Removed-Function Handling

This demo illustrates how **SafeDep** handles **removed public functions and methods** during dependency upgrades.

---

## The Scenario

- **`old_library.py` (v1.0.0)** contains a public function:
  ```python
  def legacy_discount(amount: float, discount_percent: float = 10.0) -> float:
      ...
  ```
- **`new_library.py` (v2.0.0)** has completely removed `legacy_discount` in favor of a new promotional model.
- **`client_app.py`** calls `legacy_discount`:
  ```python
  discounted_price = legacy_discount(original_price, discount_percent=15.0)
  ```

---

## SafeDep Safety Principle: No Executable Junk

When a function or method is completely removed from a library:
1. SafeDep **does not** invent fake code or insert explanatory English sentences into the source code (which would produce invalid Python syntax).
2. SafeDep marks the issue as **"Manual intervention required"** (`Cannot auto-fix safely -- function was removed`).
3. In pre-repair reports, SafeDep provides an informative suggestion (e.g. commented-out line) while leaving the source file safe and uncorrupted.

---

## Running the Demo

### 1. Analyze breaking changes
```bash
python main.py analyze examples/demo_case_2/old_library.py examples/demo_case_2/new_library.py --client examples/demo_case_2/client_app.py
```

### 2. Run Pre-Install Repair (Report-only)
```bash
python main.py pre-repair examples/demo_case_2/old_library.py examples/demo_case_2/new_library.py --client examples/demo_case_2/client_app.py --action report_only
```

You will see:
- `Total issues found: 1`
- `Auto-fixable signature changes: 0`
- `Removed functions/methods (manual intervention): 1`
- Status clearly reported: `Cannot auto-fix safely -- manual replacement or removal required.`
