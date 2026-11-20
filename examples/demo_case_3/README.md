# Demo Case 3: Behavioral Breaking Change (Tax-Inclusive vs Tax-Exclusive)

This demo demonstrates how SafeDep handles **purely behavioral breaking changes** where function signatures remain 100% identical between library versions, but runtime calculation semantics change.

---

## The Scenario

- **`old_library.py` (v1.0.0)**:
  ```python
  def calculate_total(subtotal: float, discount: float = 0.0) -> float:
      # Tax-INCLUSIVE: adds 10% tax automatically
      return round((subtotal - discount) * 1.10, 2)
  ```
- **`new_library.py` (v2.0.0)**:
  ```python
  def calculate_total(subtotal: float, discount: float = 0.0) -> float:
      # Tax-EXCLUSIVE: returns net total without adding tax (SAME signature!)
      return round(subtotal - discount, 2)
  ```
- **`client_app.py`**:
  Calls `calculate_total(subtotal, discount)` expecting the final tax-inclusive customer total.
- **`tests/test_calculate_total.py`**:
  Unit tests expecting tax-inclusive totals ($100 $\rightarrow$ $110).
  - Passes with `old_library` behavior.
  - Fails with `new_library` behavior due to numerical value mismatch ($100.0 \neq 110.0$).

---

## Key Observation: Pre-Install vs Post-Install

1. **Pre-Install Analysis**:
   - Because `calculate_total(subtotal: float, discount: float = 0.0)` has the exact same signature and is neither removed nor reordered, `safedep analyze` reports **0 breaking changes** and backward compatibility.
   - Static AST inspection cannot detect this change without executing code.

2. **Post-Install Repair**:
   - Running the test suite immediately catches the regression via `pytest`.
   - `safedep post-repair` detects the failing assertion, evaluates the behavioral divergence, and proposes a test-gated fix.

---

## How to Run the Demo

### 1. Pre-Install Analysis (Verifies no signature break)
From the project root:
```bash
python main.py analyze examples/demo_case_3/old_library.py examples/demo_case_3/new_library.py --client examples/demo_case_3/client_app.py
```
*Output: All public APIs are backward-compatible! (Zero signature breaks).*

### 2. Run Test Suite Directly (Demonstrates behavioral failure)
```bash
python -m pytest examples/demo_case_3/tests/ -v
```
*Output: Fails with `AssertionError: Expected tax-inclusive total of $110.0, got $100.0`.*

### 3. Run Post-Install Repair
```bash
python main.py post-repair --test-target examples/demo_case_3/tests/ --client examples/demo_case_3/client_app.py
```
SafeDep will capture the runtime failure from `pytest` and apply a test-gated fix.
