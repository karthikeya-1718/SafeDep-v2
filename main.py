"""SafeDep - Automated API Breaking Change Detector & Repair Tool.

Professional CLI providing:
1. `analyze`: Detect breaking changes between API versions and analyze client call-site risk.
2. `pre-repair`: Generate signature-level patches before library installation.
3. `post-repair`: Run test-gated repair for behavioral/runtime issues using pytest.
4. `demo`: Run the complete 6-scenario automated demonstration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Load .env file early — before any os.environ reads
# ---------------------------------------------------------------------------

def _load_dotenv_early() -> None:
    """Load the nearest .env file into the environment.

    Searches SafeDep/ then d:\\AIML_Project\\ so that GROQ_API_KEY /
    DEEPSEEK_API_KEY are visible to the CLI and all sub-modules.
    """
    try:
        from dotenv import load_dotenv  # type: ignore[import]
    except ImportError:
        return  # python-dotenv not installed — skip silently

    search_dirs = [
        Path(__file__).resolve().parent,         # SafeDep/
        Path(__file__).resolve().parent.parent,  # d:\AIML_Project\
    ]
    for directory in search_dirs:
        env_file = directory / ".env"
        if env_file.is_file():
            load_dotenv(dotenv_path=env_file, override=False)
            break


_load_dotenv_early()

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from safedep import __version__
from safedep.api_diff import get_breaking_changes
from safedep.call_graph import format_call_sites_report, get_affected_call_sites
from safedep.post_install_repair import format_post_install_report, run_post_install_repair
from safedep.pre_install_repair import format_pre_install_report, run_pre_install_repair
from safedep.risk_ranker import format_risk_report, rank_affected_call_sites
from safedep.utils import format_diff_report


# ===========================================================================
# Sample API Definitions for Built-In Demonstration
# ===========================================================================

SAMPLE_V1_CODE = '''"""Sample Library API Version 1.0.0"""

API_VERSION = "1.0.0"

def calculate_tax(amount: float, rate: float = 0.2) -> float:
    """Calculate tax for an amount."""
    return amount * rate

def fetch_user(user_id: int) -> dict:
    """Fetch user by id."""
    return {"id": user_id, "name": "Alice"}

def query(sql: str, timeout: int = 10) -> list:
    """Execute SQL query."""
    return []

def greet(name: str = "Guest") -> str:
    """Greet user."""
    return f"Hello, {name}!"

def render_template(name: str, context: dict) -> str:
    """Render template with context."""
    return f"Template {name}"

def _internal_helper(data: str) -> str:
    """Internal helper, not part of public API."""
    return data.strip()

class LegacyAuthHandler:
    """Legacy authentication handler."""
    def authenticate(self, token: str) -> bool:
        return True

class ApiClient:
    """API client."""
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def connect(self) -> bool:
        return True

    def disconnect(self, force: bool = False) -> None:
        pass

    def _cache_token(self, token: str) -> None:
        pass
'''

SAMPLE_V2_CODE = '''"""Sample Library API Version 2.0.0 (Has Breaking Changes)"""

API_VERSION = "2.0.0"

# BREAKING: calculate_tax function was removed!

# BREAKING: Added required parameter 'api_token' without default value!
def fetch_user(user_id: int, api_token: str) -> dict:
    """Fetch user by id with required token."""
    return {"id": user_id, "name": "Alice"}

# BREAKING: Removed parameter 'timeout'!
def query(sql: str) -> list:
    """Execute SQL query."""
    return []

# BREAKING: Removed default value from 'name', making it required!
def greet(name: str) -> str:
    """Greet user."""
    return f"Hello, {name}!"

# BREAKING: Positional parameters reordered!
def render_template(context: dict, name: str) -> str:
    """Render template with reordered parameters."""
    return f"Template {name}"

class ApiClient:
    """API client with changes."""
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def connect(self) -> bool:
        return True
    # BREAKING: disconnect method was removed!
'''

SAMPLE_V1_1_CODE = '''"""Sample Library API Version 1.1.0 (Backward-Compatible)"""

API_VERSION = "1.1.0"

def calculate_tax(amount: float, rate: float = 0.2) -> float:
    return amount * rate

def fetch_user(user_id: int, include_profile: bool = False) -> dict:
    return {"id": user_id, "name": "Alice"}

def query(sql: str, timeout: int = 10, retry: int = 3) -> list:
    return []

def greet(name: str = "Guest", uppercase: bool = False) -> str:
    res = f"Hello, {name}!"
    return res.upper() if uppercase else res

def render_template(name: str, context: dict, engine: str = "default") -> str:
    return f"Template {name}"

class LegacyAuthHandler:
    def authenticate(self, token: str) -> bool:
        return True

class ApiClient:
    def __init__(self, endpoint: str, timeout: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout

    def connect(self) -> bool:
        return True

    def disconnect(self, force: bool = False) -> None:
        pass
'''

CLIENT_APP_CODE = '''"""Client Application using Sample Library API"""

from sample_lib import calculate_tax, fetch_user, query, greet, ApiClient

def process_order(amount: float) -> float:
    tax = calculate_tax(amount, rate=0.15)
    return amount + tax

def get_user_profile(user_id: int) -> dict:
    return fetch_user(user_id)

def execute_search(term: str):
    return query(f"SELECT * FROM items WHERE name LIKE '{term}'", timeout=5)

def run_client():
    client = ApiClient("https://api.example.com")
    client.connect()
    client.disconnect(force=True)

if __name__ == "__main__":
    greet()
    process_order(100.0)
'''


# ===========================================================================
# Validation & Path Helpers
# ===========================================================================


def _validate_path(path_str: str, label: str) -> Path:
    """Ensure path exists; print clear error and raise SystemExit on failure."""
    p = Path(path_str)
    if not p.exists():
        print(f"\n[ERROR] {label} not found: '{path_str}'", file=sys.stderr)
        print("Please verify the path and try again.\n", file=sys.stderr)
        sys.exit(2)
    return p


def _check_api_key_notice() -> None:
    """Print an informative notice showing the active LLM provider or AST fallback."""
    if os.environ.get("GROQ_API_KEY"):
        print("[INFO] GROQ_API_KEY detected. Using Groq LLM (llama-3.3-70b-versatile).\n")
    elif os.environ.get("DEEPSEEK_API_KEY"):
        print("[INFO] DEEPSEEK_API_KEY detected. Using DeepSeek LLM (deepseek-chat).\n")
    else:
        print("[INFO] No remote LLM API key detected (GROQ_API_KEY or DEEPSEEK_API_KEY).")
        print("       SafeDep will use its offline deterministic AST refactoring engine.\n")


# ===========================================================================
# Command Handlers
# ===========================================================================


def handle_analyze(args: argparse.Namespace) -> int:
    """Execute `safedep analyze`: Detect breaking changes & optional call graph ranking."""
    old_p = _validate_path(args.old_path, "Original library path")
    new_p = _validate_path(args.new_path, "New library path")

    client_p: Optional[Path] = None
    if getattr(args, "client_path", None):
        client_p = _validate_path(args.client_path, "Client project path")

    try:
        diff_result = get_breaking_changes(old_p, new_p)
    except SyntaxError as syn_err:
        print(f"\n[ERROR] Python syntax error in library files: {syn_err}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n[ERROR] Analysis failed: {exc}", file=sys.stderr)
        return 2

    ranked_sites: Optional[list[dict[str, Any]]] = None
    call_sites: Optional[list[dict[str, Any]]] = None
    if client_p:
        try:
            call_sites = get_affected_call_sites(client_p, diff_result)
            ranked_sites = rank_affected_call_sites(call_sites, project_path=client_p)
        except Exception as exc:
            print(f"\n[ERROR] Call graph analysis on client codebase failed: {exc}", file=sys.stderr)
            return 2

    if args.json:
        payload: dict[str, Any] = {"diff": diff_result}
        if ranked_sites is not None:
            payload["affected_call_sites"] = ranked_sites
        elif call_sites is not None:
            payload["affected_call_sites"] = call_sites
        print(json.dumps(payload, indent=2))
    else:
        print(format_diff_report(diff_result, title=f"API Diff: {old_p.name} -> {new_p.name}"))
        if ranked_sites is not None:
            print()
            print(format_risk_report(ranked_sites, title=f"Risk-Ranked Call Sites in {client_p}"))

    return 1 if diff_result.get("breaking_changes_found") else 0


def handle_pre_repair(args: argparse.Namespace) -> int:
    """Execute `safedep pre-repair`: Generate signature-level patches before installation."""
    old_p = _validate_path(args.old_path, "Original library path")
    new_p = _validate_path(args.new_path, "New library path")
    client_p = _validate_path(args.client_path, "Client codebase path")

    _check_api_key_notice()

    action = getattr(args, "action", "report_only")
    is_interactive = (action == "interactive")
    chosen_action = None if is_interactive else action

    try:
        report = run_pre_install_repair(
            old_path=old_p,
            new_path=new_p,
            client_path=client_p,
            action=chosen_action,
            interactive=is_interactive,
        )
    except Exception as exc:
        print(f"\n[ERROR] Pre-install repair failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0


def handle_post_repair(args: argparse.Namespace) -> int:
    """Execute `safedep post-repair`: Test-gated behavioral repair using pytest."""
    test_target_str = args.test_target or getattr(args, "client_path", None) or "tests"
    test_p = _validate_path(test_target_str, "Test target path")

    client_p: Optional[Path] = None
    if getattr(args, "client_path", None):
        client_p = _validate_path(args.client_path, "Client codebase path")

    _check_api_key_notice()

    max_retries = getattr(args, "max_retries", 2)

    try:
        report = run_post_install_repair(
            test_target=test_p,
            client_path=client_p,
            max_retries=max_retries,
        )
    except Exception as exc:
        print(f"\n[ERROR] Post-install repair failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_post_install_report(report))

    return 0 if report.final_tests_passed else 1


# ===========================================================================
# Built-In Automated Demonstration (6 Scenarios)
# ===========================================================================


def run_demo() -> int:
    """Run the comprehensive built-in demonstration showcasing all 6 scenarios."""
    border = "=" * 70
    print(border)
    print("  SAFEDEP - COMPREHENSIVE AUTOMATED DEMONSTRATION")
    print(f"  Version: {__version__}")
    print(border)
    print("Demonstrating SafeDep's end-to-end upgrade safety pipeline...\n")

    with tempfile.TemporaryDirectory() as td:
        dir_p = Path(td)
        v1_file = dir_p / "sample_v1.py"
        v2_file = dir_p / "sample_v2.py"
        v1_1_file = dir_p / "sample_v1_1.py"
        client_file = dir_p / "client_app.py"

        v1_file.write_text(SAMPLE_V1_CODE, encoding="utf-8")
        v2_file.write_text(SAMPLE_V2_CODE, encoding="utf-8")
        v1_1_file.write_text(SAMPLE_V1_1_CODE, encoding="utf-8")
        client_file.write_text(CLIENT_APP_CODE, encoding="utf-8")

        # SCENARIO 1: Breaking changes detection
        print("-" * 70)
        print("SCENARIO 1: Comparing v1.0.0 vs v2.0.0 (Breaking Changes Expected)")
        print("-" * 70)
        diff_v2 = get_breaking_changes(v1_file, v2_file)
        print(format_diff_report(diff_v2, title="DIFF: SAMPLE_V1.PY VS SAMPLE_V2.PY"))

        # SCENARIO 2: Backward-compatible update
        print("\n" + "-" * 70)
        print("SCENARIO 2: Comparing v1.0.0 vs v1.1.0 (Backward-Compatible Update)")
        print("-" * 70)
        diff_v1_1 = get_breaking_changes(v1_file, v1_1_file)
        print(format_diff_report(diff_v1_1, title="DIFF: SAMPLE_V1.PY VS SAMPLE_V1_1.PY"))

        # SCENARIO 3: Call Graph Impact Analysis
        print("\n" + "-" * 70)
        print("SCENARIO 3: Call Graph Impact Analysis on Client Project (AST)")
        print("-" * 70)
        call_sites = get_affected_call_sites(client_file, diff_v2)
        print(format_call_sites_report(call_sites, title="AFFECTED CALL SITES: CLIENT_APP.PY"))

        # SCENARIO 4: Risk Scoring and Prioritization
        print("\n" + "-" * 70)
        print("SCENARIO 4: Risk Scoring & Call-Site Prioritization")
        print("-" * 70)
        ranked_sites = rank_affected_call_sites(call_sites, project_path=client_file)
        print(format_risk_report(ranked_sites, title="RISK RANKING REPORT: CLIENT_APP.PY"))

        # SCENARIO 5: Pre-Install Repair Mode
        print("\n" + "-" * 70)
        print("SCENARIO 5: Pre-Install Repair Mode (Syntactical / Signature-Level)")
        print("-" * 70)
        run_pre_install_repair(
            old_path=v1_file,
            new_path=v2_file,
            client_path=client_file,
            action="report_only",
        )

        # SCENARIO 6: Post-Install Repair Mode
        print("\n" + "-" * 70)
        print("SCENARIO 6: Post-Install Repair Mode (Test-Gated Behavioral Repair)")
        print("-" * 70)
        print("Assumes v2.0 library is installed. Running client project's test suite...")

        post_app_file = dir_p / "order_service.py"
        post_app_file.write_text(
            '''def calculate_shipping(weight: float) -> float:
    # Behavioral change: v2.0 base rate changed from 10.0 to 15.0
    return weight * 1.5 + 10.0
''',
            encoding="utf-8",
        )

        post_test_file = dir_p / "test_orders.py"
        post_test_file.write_text(
            '''from order_service import calculate_shipping

def test_shipping_rate():
    assert calculate_shipping(10.0) == 30.0  # 10*1.5 + 15.0 = 30.0
''',
            encoding="utf-8",
        )

        post_report = run_post_install_repair(
            test_target=post_test_file,
            client_path=post_app_file,
            cwd=dir_p,
        )
        print(format_post_install_report(post_report))

    print("\n" + border)
    print("SAFEDEP CLI QUICK REFERENCE:")
    print("  1. Analyze breaking changes:")
    print("       safedep analyze <old.py> <new.py> [--client <client_app.py>]")
    print("  2. Pre-Install Repair (Syntactical / Signature changes):")
    print("       safedep pre-repair <old.py> <new.py> --client <client_app.py> [--action apply_only]")
    print("  3. Post-Install Repair (Behavioral / Test-Gated changes):")
    print("       safedep post-repair --test-target <tests/> [--client <src/>]")
    print("  4. Run built-in demo:")
    print("       safedep demo")
    print(border)
    return 0


# ===========================================================================
# Argument Parser Construction
# ===========================================================================


def build_parser() -> argparse.ArgumentParser:
    """Construct the professional SafeDep CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="safedep",
        description="SafeDep: Automated API Breaking Change Detection & Test-Gated Repair.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  safedep analyze v1.py v2.py
  safedep analyze v1.py v2.py --client src/app.py
  safedep pre-repair v1.py v2.py --client src/app.py --action apply_only
  safedep post-repair --test-target tests/ --client src/
  safedep demo
""",
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"SafeDep {__version__}",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the built-in automated 6-scenario demonstration",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="Commands",
        description="Run 'safedep <command> --help' for detailed option summaries.",
    )

    # Command: analyze
    p_analyze = subparsers.add_parser(
        "analyze",
        help="Compare API versions and analyze client call-site risk",
        description="Detect backward-incompatible API changes between two library versions and map affected client call sites.",
    )
    p_analyze.add_argument("old_path", help="Path to original (older) library file or directory")
    p_analyze.add_argument("new_path", help="Path to new (updated) library file or directory")
    p_analyze.add_argument("--client", dest="client_path", default=None, help="Path to client project/file to analyze via AST call graph")
    p_analyze.add_argument("--json", action="store_true", help="Output results in JSON format")

    # Command: pre-repair
    p_pre = subparsers.add_parser(
        "pre-repair",
        help="Generate signature-level patches before installing the library",
        description="Identify syntactical/signature breaking changes and generate refactored call-site patches before installation.",
    )
    p_pre.add_argument("old_path", help="Path to original (older) library file or directory")
    p_pre.add_argument("new_path", help="Path to new (updated) library file or directory")
    p_pre.add_argument("--client", dest="client_path", required=True, help="Path to client project/file to repair")
    p_pre.add_argument(
        "--action",
        choices=["apply_and_install", "apply_only", "report_only", "interactive"],
        default="report_only",
        help="Action to execute (default: report_only)",
    )
    p_pre.add_argument("--json", action="store_true", help="Output report in JSON format")

    # Command: post-repair
    p_post = subparsers.add_parser(
        "post-repair",
        help="Run test-gated repair for behavioral/runtime issues using pytest",
        description="Execute client test suite after installation, identify runtime/behavioral failures, and apply strictly test-gated patches.",
    )
    p_post.add_argument(
        "--test-target",
        dest="test_target",
        default="tests",
        help="Path to pytest test directory or test file (default: 'tests')",
    )
    p_post.add_argument("--client", dest="client_path", default=None, help="Path to client project/file to pinpoint issues")
    p_post.add_argument("--max-retries", dest="max_retries", type=int, default=2, help="Maximum patch retries per failing issue (default: 2)")
    p_post.add_argument("--json", action="store_true", help="Output report in JSON format")

    # Command: demo
    subparsers.add_parser(
        "demo",
        help="Run the built-in 6-scenario demonstration",
        description="Run an end-to-end demonstration comparing APIs, computing call graphs, ranking risk, and executing pre/post repair.",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()

    raw_args = argv if argv is not None else sys.argv[1:]

    # Backwards compatibility: if invoked with two file paths directly without a subcommand
    # e.g.: `python main.py old.py new.py` -> rewrite as `analyze old.py new.py`
    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in ("analyze", "pre-repair", "post-repair", "demo"):
        raw_args = ["analyze"] + raw_args

    args = parser.parse_args(raw_args)

    # Demo trigger: explicit flag or 'demo' subcommand
    if getattr(args, "demo", False) or getattr(args, "command", None) == "demo":
        return run_demo()

    # If no subcommand provided at all, show demo
    if not getattr(args, "command", None):
        return run_demo()

    if args.command == "analyze":
        return handle_analyze(args)
    elif args.command == "pre-repair":
        return handle_pre_repair(args)
    elif args.command == "post-repair":
        return handle_post_repair(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
