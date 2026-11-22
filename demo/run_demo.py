"""Interactive / Automated Demonstration Script for Phase 3 Environment Safety.

Demonstrates:
  Step 1: ShopKit v1 installed -> Storefront is healthy
  Step 2: UpgradeGuard installs ShopKit v2 -> Storefront breaks with 'timeout' error
  Step 3: UpgradeGuard rolls back to ShopKit v1 -> Storefront is restored and healthy

Usage:
  python demo/run_demo.py --python <PATH> --steps 1-3 [--auto]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add repo root to sys.path so safedep can be imported
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from safedep.environment import (
    UpgradeGuard,
    install_library,
    installed_version,
    resolve_library_source,
)
from demo.tools.health_check import run_health_check


def prompt_step(step_num: int, title: str, auto: bool) -> None:
    """Print step header and optionally pause."""
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"STEP {step_num}: {title}")
    print(f"{sep}")
    if not auto:
        input("Press Enter to continue...")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 3 Environment Safety Demo")
    parser.add_argument("--python", required=True, help="Path to target environment python executable")
    parser.add_argument("--steps", default="1-3", help="Steps to execute (e.g. 1-3)")
    parser.add_argument("--auto", action="store_true", help="Run without pausing for user input")
    parser.add_argument("--project", default=str(repo_root / "demo" / "storefront"), help="Storefront project directory")
    args = parser.parse_args()

    python_exe = str(Path(args.python).resolve())
    project_dir = str(Path(args.project).resolve())
    v1_dir = repo_root / "demo" / "shopkit_v1"
    v2_dir = repo_root / "demo" / "shopkit_v2"

    print("=" * 70)
    print("SAFEDEP PHASE 3: SAFE ENVIRONMENT UPGRADE & ROLLBACK DEMO")
    print(f"Target Python: {python_exe}")
    print(f"Storefront:    {project_dir}")
    print("=" * 70)

    # Resolve sources (never modifies or installs anything)
    v1_source = resolve_library_source(str(v1_dir))
    v2_source = resolve_library_source(str(v2_dir))

    checklist = {
        "step1": False,
        "step2": False,
        "step3": False,
    }

    guard = UpgradeGuard(python_exe, "shopkit", v1_source)

    # ------------------------------------------------------------------
    # Step 1: Baseline with ShopKit v1
    # ------------------------------------------------------------------
    prompt_step(1, "Baseline — Ensure ShopKit v1 Installed & Health Check", args.auto)
    current_ver = installed_version(python_exe, "shopkit")
    if current_ver != v1_source.version:
        print(f"Installing baseline {v1_source.name} {v1_source.version}...")
        res = install_library(python_exe, v1_source.project_dir)
        if not res.success:
            print(f"[FAIL] Could not install v1:\n{res.stderr_tail}")
            return 1

    ver1 = installed_version(python_exe, "shopkit")
    print(f"Current installed version: shopkit=={ver1}")

    code1, report1 = run_health_check(python_exe, project_dir)
    print(report1)
    if code1 == 0 and ver1 == "1.0.0":
        checklist["step1"] = True

    # ------------------------------------------------------------------
    # Step 2: Upgrade to ShopKit v2 (Breaking Change)
    # ------------------------------------------------------------------
    prompt_step(2, "Upgrade — UpgradeGuard Installs ShopKit v2 (Failure Expected)", args.auto)
    print(f"Upgrading to {v2_source.name} {v2_source.version} via UpgradeGuard...")
    guard.install(v2_source)
    ver2 = installed_version(python_exe, "shopkit")
    print(f"Current installed version: shopkit=={ver2}")

    code2, report2 = run_health_check(python_exe, project_dir)
    print(report2)
    # Expect failure mentioning 'timeout'
    if code2 != 0 and "timeout" in report2.lower():
        checklist["step2"] = True

    # ------------------------------------------------------------------
    # Step 3: Rollback to ShopKit v1
    # ------------------------------------------------------------------
    prompt_step(3, "Rollback — UpgradeGuard Restores ShopKit v1", args.auto)
    print("Initiating verified rollback via UpgradeGuard...")
    guard.rollback()
    ver3 = installed_version(python_exe, "shopkit")
    print(f"Current installed version: shopkit=={ver3}")

    code3, report3 = run_health_check(python_exe, project_dir)
    print(report3)
    if code3 == 0 and ver3 == "1.0.0":
        checklist["step3"] = True

    # ------------------------------------------------------------------
    # Final Checklist Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("FINAL VERIFICATION CHECKLIST")
    print("=" * 70)
    s1_status = "PASS" if checklist["step1"] else "FAIL"
    s2_status = "PASS" if checklist["step2"] else "FAIL"
    s3_status = "PASS" if checklist["step3"] else "FAIL"

    print(f"  [{s1_status}] Step 1: ShopKit v1 healthy (storefront operational)")
    print(f"  [{s2_status}] Step 2: ShopKit v2 broke storefront (startup error with 'timeout')")
    print(f"  [{s3_status}] Step 3: Rollback restored ShopKit v1 (storefront operational)")
    print("=" * 70)

    all_passed = all(checklist.values())
    if all_passed:
        print("OVERALL DEMO STATUS: ALL EXPECTATIONS PASSED\n")
        return 0
    else:
        print("OVERALL DEMO STATUS: ONE OR MORE EXPECTATIONS FAILED\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
