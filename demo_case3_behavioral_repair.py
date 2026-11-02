#!/usr/bin/env python3
"""
SafeDep Demo Case 3 – Post-Install Test-Gated Behavioral Repair
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safedep.post_install_repair import (
    format_post_install_report,
    run_post_install_repair,
)


def _write(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def _banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_success_scenario(base: Path) -> None:
    _banner("SCENARIO A – Successful Test-Gated Repair")

    client = _write(
        base,
        "calculator.py",
        """
def compute_discount(price: float) -> float:
    return price * 0.20
""",
    )
    test_file = _write(
        base,
        "test_calc.py",
        """
from calculator import compute_discount

def test_discount():
    assert compute_discount(100.0) == 15.0
""",
    )

    print("\n[1] Client source (before):")
    print(client.read_text())
    print("[2] Client test expects compute_discount(100.0) == 15.0")
    print("    → Initial pytest will FAIL (got 20.0).")

    def correct_patch(code_snippet, breaking_change_info, **kwargs):
        if "0.20" in code_snippet:
            return "return price * 0.15"
        return code_snippet

    print("\n[3] Running SafeDep post-install repair (mocked correct patch)...")
    with patch("safedep.post_install_repair.propose_patch", side_effect=correct_patch):
        report = run_post_install_repair(
            test_target=test_file,
            client_path=client,
            cwd=base,
        )

    print("\n[4] Repair report:")
    print(format_post_install_report(report))
    print("\n[5] Client source (after):")
    print(client.read_text())

    assert report.initial_tests_passed is False
    assert report.final_tests_passed is True
    assert report.fixed_count == 1
    assert "0.15" in client.read_text()
    print("✓ Patch retained – final tests PASSED.")


def run_rollback_scenario(base: Path) -> None:
    _banner("SCENARIO B – Failed Patch + Automatic Rollback")

    client = _write(
        base,
        "service.py",
        """
def get_status() -> str:
    return "DOWN"
""",
    )
    test_file = _write(
        base,
        "test_service.py",
        """
from service import get_status

def test_status():
    assert get_status() == "UP"
""",
    )
    original = client.read_text()

    print("\n[1] Client source (before):")
    print(original)
    print("[2] Client test expects get_status() == 'UP'")
    print("    → Initial pytest will FAIL.")

    def bad_patch(code_snippet, breaking_change_info, **kwargs):
        return 'return "STILL_WRONG"'

    print("\n[3] Running SafeDep post-install repair (mocked incorrect patch)...")
    with patch("safedep.post_install_repair.propose_patch", side_effect=bad_patch):
        report = run_post_install_repair(
            test_target=test_file,
            client_path=client,
            max_retries=2,
            cwd=base,
        )

    print("\n[4] Repair report:")
    print(format_post_install_report(report))
    print("\n[5] Client source (after – should be restored):")
    print(client.read_text())

    assert report.initial_tests_passed is False
    assert report.final_tests_passed is False
    assert report.fixed_count == 0
    assert report.failed_count == 1
    assert client.read_text() == original
    print("✓ Incorrect patch rejected – original source RESTORED.")


def main() -> None:
    parser = argparse.ArgumentParser(description="SafeDep Demo Case 3")
    parser.add_argument(
        "--scenario",
        choices=("success", "rollback", "both"),
        default="both",
        help="Which scenario to run (default: both)",
    )
    args = parser.parse_args()

    _banner("SafeDep – Demo Case 3: Post-Install Test-Gated Behavioral Repair")
    print(
        "Function signature unchanged; behaviour changed.\n"
        "SafeDep uses pytest as the oracle and only keeps a patch when tests pass."
    )

    with tempfile.TemporaryDirectory(prefix="safedep_demo3_") as td:
        base = Path(td)
        if args.scenario in ("success", "both"):
            success_dir = base / "success"
            success_dir.mkdir()
            run_success_scenario(success_dir)

        if args.scenario in ("rollback", "both"):
            rollback_dir = base / "rollback"
            rollback_dir.mkdir()
            run_rollback_scenario(rollback_dir)

    print("\n" + "=" * 70)
    print("  Demo Case 3 complete.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
