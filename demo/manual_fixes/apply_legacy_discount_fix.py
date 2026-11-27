"""Manual fix kit for legacy_discount in demo/storefront.

Replaces the call `shopkit.legacy_discount(amount, code)` in
`<project>/app/services/pricing_service.py` with a local implementation
`apply_discount_code(amount, code)` based on ShopKit v1's discount logic,
and removes `import shopkit` if nothing else in the file uses it.

Usage:
    python demo/manual_fixes/apply_legacy_discount_fix.py --project <storefront folder>
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Local implementation of v1 discount rules to inject
LOCAL_DISCOUNT_FUNCTION = """

def apply_discount_code(amount: float, code: str) -> float:
    \"\"\"Apply promotional discount code to an amount using legacy calculation rules.\"\"\"
    discount_rates: dict[str, float] = {
        "SAVE10": 0.10,
        "SAVE20": 0.20,
        "HALF": 0.50,
    }
    rate = discount_rates.get(code.upper(), 0.05)
    return round(amount * (1.0 - rate), 2)
"""


def apply_fix(project_dir: Path) -> bool:
    """Apply the legacy discount manual replacement to pricing_service.py.

    Returns True if changes were made, False if already applied (idempotent).
    """
    target = project_dir / "app" / "services" / "pricing_service.py"
    if not target.is_file():
        # Maybe project_dir is already the app folder?
        alt = project_dir / "services" / "pricing_service.py"
        if alt.is_file():
            target = alt
        else:
            raise FileNotFoundError(f"Could not locate pricing_service.py under {project_dir}")

    content = target.read_text(encoding="utf-8")

    # Idempotence check: if already defines apply_discount_code, nothing to do
    if "def apply_discount_code(" in content:
        return False

    # 1. Replace the call: shopkit.legacy_discount(amount, code) -> apply_discount_code(amount, code)
    if "shopkit.legacy_discount(amount, code)" not in content:
        # Check if legacy_discount is present in any other form
        if "legacy_discount" not in content:
            return False

    new_content = content.replace("shopkit.legacy_discount(amount, code)", "apply_discount_code(amount, code)")
    # Fallback regex in case of slight spacing differences
    if new_content == content:
        new_content = re.sub(r"shopkit\.legacy_discount\s*\(\s*amount\s*,\s*code\s*\)", "apply_discount_code(amount, code)", content)

    # 2. Append the local helper function
    new_content = new_content.rstrip() + "\n" + LOCAL_DISCOUNT_FUNCTION

    # 3. Check if 'shopkit' is used anywhere else in the file
    # Parse to see if 'shopkit' appears other than in 'import shopkit'
    try:
        tree = ast.parse(new_content)
        shopkit_used = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "shopkit":
                shopkit_used = True
                break
        if not shopkit_used:
            # Remove 'import shopkit\n'
            new_content = re.sub(r"^import\s+shopkit\s*\n", "", new_content, flags=re.MULTILINE)
    except Exception:
        pass

    target.write_text(new_content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply legacy_discount manual fix to storefront")
    parser.add_argument("--project", default="demo/storefront", help="Storefront project directory")
    args = parser.parse_args()

    proj = Path(args.project).resolve()
    changed = apply_fix(proj)
    if changed:
        print(f"[OK] Applied manual fix for legacy_discount in {proj}")
    else:
        print(f"[OK] No changes needed (already up to date): {proj}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
