"""Storefront Health Check Tool.

Runs demo/tools/probe_site.py in the target Python environment and formats a
clean plain-text table of routes, HTTP statuses, and errors.
Exits with 0 only if startup succeeded and all routes returned < 400.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_health_check(python_exe: str, project_dir: str) -> tuple[int, str]:
    """Execute probe_site.py with target python and format output."""
    tools_dir = Path(__file__).resolve().parent
    probe_script = tools_dir / "probe_site.py"

    cmd = [python_exe, str(probe_script), "--project", str(Path(project_dir).resolve())]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        output = f"[FAIL] Could not run probe_site with {python_exe}: {exc}\n"
        return 1, output

    raw_stdout = proc.stdout.strip()

    # Attempt to locate the JSON line in probe output
    data = None
    for line in raw_stdout.splitlines():
        line_s = line.strip()
        if line_s.startswith("{") and line_s.endswith("}"):
            try:
                data = json.loads(line_s)
                break
            except Exception:
                continue

    if data is None:
        lines = [
            "=" * 70,
            "STOREFRONT HEALTH CHECK: FAILED (NO PROBE RESPONSE)",
            "=" * 70,
            f"Process returncode: {proc.returncode}",
            f"STDOUT: {proc.stdout}",
            f"STDERR: {proc.stderr}",
        ]
        return 1, "\n".join(lines)

    lines = []
    lines.append("=" * 70)
    lines.append("STOREFRONT HEALTH CHECK")
    lines.append("=" * 70)

    if not data.get("startup_ok"):
        lines.append("[STATUS] STARTUP FAILED")
        lines.append(f"Error:   {data.get('error')}")
        lines.append("=" * 70)
        return 1, "\n".join(lines)

    lines.append("[STATUS] APPLICATION STARTUP OK")
    lines.append(f"{'METHOD':<8} {'PATH':<20} {'STATUS':<10} {'ERROR'}")
    lines.append("-" * 70)

    routes = data.get("routes", [])
    all_healthy = True

    for r in routes:
        m = r.get("method", "GET")
        p = r.get("path", "")
        s = r.get("status", 0)
        e = r.get("error") or "-"
        if s >= 400:
            all_healthy = False
        status_str = f"{s} OK" if s < 400 else f"{s} ERR"
        lines.append(f"{m:<8} {p:<20} {status_str:<10} {e}")

    lines.append("=" * 70)
    if all_healthy:
        lines.append("RESULT: HEALTHY (All routes operational)")
        exit_code = 0
    else:
        lines.append("RESULT: UNHEALTHY (One or more routes failed)")
        exit_code = 1

    return exit_code, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run storefront health check via target Python")
    parser.add_argument("--python", required=True, help="Path to target python executable")
    parser.add_argument("--project", default="demo/storefront", help="Path to storefront project root")

    args = parser.parse_args()
    code, report = run_health_check(args.python, args.project)
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
