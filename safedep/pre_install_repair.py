"""SafeDep Pre-Install Repair Module.

Implements the Pre-Install Repair mode:
1. Combines `api_diff`, `call_graph`, and `risk_ranker` to identify and prioritize affected call sites.
2. Generates patches for syntactical/signature-level breaking changes using the shared
   `patcher` module (DeepSeek API with an intelligent AST-based fallback).
3. Produces a clear pre-installation report:
   - Total issues found
   - How many syntactical issues can be fixed now
   - Explanatory note that behavioral issues can only be detected after installation
4. Offers the user 3 explicit execution options:
   - [1] Apply fixes and install the new library
   - [2] Apply fixes only
   - [3] Only show report

Behavioral issues are explicitly deferred to post-installation testing.
"""

from __future__ import annotations

import ast
import difflib
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from .api_diff import get_breaking_changes
from .call_graph import get_affected_call_sites
from .patcher import propose_patch
from .risk_ranker import rank_affected_call_sites


def _is_valid_replacement_code(replacement: str) -> bool:
    """Check if proposed replacement string is valid executable Python code and not text."""
    if not replacement or not replacement.strip():
        return False
    text = replacement.strip()
    # Check for manual intervention markers or explanatory guidance text
    if any(marker in text.lower() for marker in (
        "manual intervention", "no longer exists", "was removed", "remove this call", "replace with"
    )):
        return False
    try:
        parsed = ast.parse(text)
        if not parsed.body:
            return False
        # Reject lone string literals (docstrings or English explanations in quotes)
        if (
            len(parsed.body) == 1
            and isinstance(parsed.body[0], ast.Expr)
            and isinstance(parsed.body[0].value, ast.Constant)
            and isinstance(parsed.body[0].value.value, str)
        ):
            return False
        return True
    except SyntaxError:
        return False


@dataclass
class RepairIssue:
    """Represents an identified issue with repair details."""

    file_path: str
    line_number: int
    function_name: str
    caller_name: str
    breaking_change: str
    issue_type: str  # 'syntactical' or 'behavioral'
    risk_score: float
    risk_level: str
    call_expression: str = ""
    old_signature: Optional[str] = None
    new_signature: Optional[str] = None
    proposed_fix: Optional[str] = None
    patch_diff: Optional[str] = None
    explanation: str = ""
    is_removal: bool = False
    manual_intervention_required: bool = False


@dataclass
class PreInstallRepairReport:
    """Encapsulates the complete findings and generated patches of Pre-Install Repair."""

    total_issues: int
    syntactical_count: int
    behavioral_count: int
    syntactical_issues: list[RepairIssue] = field(default_factory=list)
    behavioral_issues: list[RepairIssue] = field(default_factory=list)
    patched_files: dict[str, str] = field(default_factory=dict)  # file_path -> new_content
    unified_diffs: dict[str, str] = field(default_factory=dict)  # file_path -> unified diff text
    applied: bool = False
    installed: bool = False
    manual_intervention_count: int = 0

    @property
    def auto_fixable_issues(self) -> list[RepairIssue]:
        """Syntactical signature issues that can be automatically patched safely."""
        return [i for i in self.syntactical_issues if not i.is_removal and not i.manual_intervention_required]

    @property
    def manual_intervention_issues(self) -> list[RepairIssue]:
        """Issues involving removed symbols or breaking changes requiring manual intervention."""
        return [i for i in self.syntactical_issues if i.is_removal or i.manual_intervention_required]

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary format."""
        return {
            "total_issues": self.total_issues,
            "syntactical_issues_fixable_now": len(self.auto_fixable_issues),
            "manual_intervention_required": len(self.manual_intervention_issues),
            "behavioral_issues_deferred": self.behavioral_count,
            "syntactical_issues": [
                {
                    "file_path": i.file_path,
                    "line_number": i.line_number,
                    "function_name": i.function_name,
                    "caller_name": i.caller_name,
                    "breaking_change": i.breaking_change,
                    "risk_score": i.risk_score,
                    "risk_level": i.risk_level,
                    "call_expression": i.call_expression,
                    "proposed_fix": i.proposed_fix,
                    "patch_diff": i.patch_diff,
                    "is_removal": i.is_removal,
                    "manual_intervention_required": i.manual_intervention_required,
                }
                for i in self.syntactical_issues
            ],
            "behavioral_issues": [
                {
                    "file_path": i.file_path,
                    "line_number": i.line_number,
                    "function_name": i.function_name,
                    "caller_name": i.caller_name,
                    "breaking_change": i.breaking_change,
                    "risk_score": i.risk_score,
                    "risk_level": i.risk_level,
                    "explanation": i.explanation,
                }
                for i in self.behavioral_issues
            ],
            "applied": self.applied,
            "installed": self.installed,
        }


def classify_issue(call_site: dict[str, Any], diff_result: dict[str, Any]) -> tuple[str, Optional[dict[str, Any]]]:
    """Classify a call site issue as either 'syntactical' or 'behavioral'.

    Syntactical / signature-level issues are detectable purely from the API diff:
    - Removed functions, classes, or methods (call site can be flagged and removed/stubbed pre-install)
    - Changed signatures (parameter added, removed, renamed, reordered, default value removed)

    Behavioral issues are ONLY those where a function still exists but its runtime
    behavior, return values, or side effects may have changed in ways not visible
    from the signature/API diff alone — not detectable pre-installation.
    """
    callee = str(call_site.get("callee_name") or call_site.get("function_name", ""))
    breaking_text = str(call_site.get("breaking_change", ""))

    # 1. Explicitly removed functions — detectable and flaggable pre-install
    for fn in diff_result.get("removed_functions", []):
        if fn.get("name") == callee:
            return "syntactical", None

    # 2. Explicitly removed classes (constructor/instantiation calls)
    for cls in diff_result.get("removed_classes", []):
        if cls.get("name") == callee:
            return "syntactical", None

    # 3. Explicitly removed methods
    for m in diff_result.get("removed_methods", []):
        method_name = m.get("method_name", "")
        full_name = f"{m.get('class_name', '')}.{method_name}"
        if callee == method_name or callee == full_name:
            return "syntactical", None

    # 4. Match against changed signatures in api_diff
    for sig in diff_result.get("changed_signatures", []):
        sig_name = sig.get("name", "")
        if sig_name == callee or sig_name.endswith("." + callee) or callee.endswith("." + sig_name):
            return "syntactical", sig

    # 5. Check for signature/parameter keywords in description
    if "[CHANGED SIGNATURE]" in breaking_text or any(
        kw in breaking_text.lower() for kw in ("parameter", "signature", "reordered", "default value", "keyword-only", "removed")
    ):
        return "syntactical", None

    # 6. Only defer to behavioral if no structural evidence found in the diff —
    #    i.e., the function still exists but may behave differently at runtime.
    return "behavioral", None


# ---------------------------------------------------------------------------
# Backwards-compatibility shims
# ---------------------------------------------------------------------------
# The patch generation logic now lives in safedep.patcher.  The two names
# below are kept so that any code (or tests) that imported them directly
# from pre_install_repair continue to work without changes.


def generate_patch_with_deepseek(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
    code_context: str = "",
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
) -> str:
    """Thin shim — delegates to :func:`safedep.patcher.propose_patch`.

    .. deprecated::
        Import :func:`safedep.patcher.propose_patch` directly instead.
    """
    return propose_patch(
        code_snippet=call_expression,
        breaking_change_info={
            "breaking_change": breaking_change,
            "old_signature": old_signature,
            "new_signature": new_signature,
            "code_context": code_context,
        },
        api_key=api_key,
        model=model,
    )


def generate_fallback_patch(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
) -> str:
    """Thin shim — delegates to the AST fallback inside :mod:`safedep.patcher`.

    .. deprecated::
        Import :func:`safedep.patcher.propose_patch` directly instead.
    """
    # Call propose_patch with no API key so it always takes the AST path
    return propose_patch(
        code_snippet=call_expression,
        breaking_change_info={
            "breaking_change": breaking_change,
            "old_signature": old_signature,
            "new_signature": new_signature,
        },
        api_key="",  # empty string → skip DeepSeek, go straight to AST engine
    )


def analyze_pre_install_issues(
    old_path: Union[str, Path],
    new_path: Union[str, Path],
    client_path: Union[str, Path],
    api_key: Optional[str] = None,
    deepseek_model: str = "deepseek-chat",
) -> PreInstallRepairReport:
    """Analyze a client project against a proposed library upgrade.

    Combines:
      - `api_diff` to detect breaking API changes
      - `call_graph` to locate affected call sites
      - `risk_ranker` to prioritize call sites by impact

    Separates issues into:
      - Fixable syntactical/signature changes (generates patches via DeepSeek)
      - Deferred behavioral issues (noted for post-installation runtime verification)
    """
    # 0. Validate input paths
    old_p = Path(old_path)
    new_p = Path(new_path)
    client_p = Path(client_path)
    if not old_p.exists():
        raise FileNotFoundError(f"Original library path does not exist: '{old_path}'")
    if not new_p.exists():
        raise FileNotFoundError(f"New library path does not exist: '{new_path}'")
    if not client_p.exists():
        raise FileNotFoundError(f"Client codebase path does not exist: '{client_path}'")

    # 1. Run api_diff to find breaking changes in the library
    diff_result = get_breaking_changes(old_p, new_p)

    # 2. Run call_graph to find affected call sites in the client project
    raw_call_sites = get_affected_call_sites(client_p, diff_result)

    # 3. Run risk_ranker to assign risk scores and sort by impact
    ranked_call_sites = rank_affected_call_sites(raw_call_sites, project_path=client_p)

    syntactical_issues: list[RepairIssue] = []
    behavioral_issues: list[RepairIssue] = []

    # Map file_path -> file content lines for patch extraction
    file_lines_cache: dict[str, list[str]] = {}

    def get_lines(fp: str) -> list[str]:
        if fp not in file_lines_cache:
            p = Path(fp)
            if p.is_file():
                file_lines_cache[fp] = p.read_text(encoding="utf-8").splitlines(keepends=True)
            else:
                file_lines_cache[fp] = []
        return file_lines_cache[fp]

    # 4. Classify issues and generate patches for syntactical/signature changes
    for site in ranked_call_sites:
        issue_type, sig_meta = classify_issue(site, diff_result)

        fp = site.get("file_path", "")
        line_no = int(site.get("line_number", 0))
        callee = str(site.get("callee_name") or site.get("function_name", "unknown"))
        caller = str(site.get("caller_name") or site.get("caller", "<module>"))
        expr = str(site.get("call_expression", ""))
        breaking = str(site.get("breaking_change", ""))
        score = float(site.get("risk_score", 1.0))
        level = str(site.get("risk_level", "MEDIUM"))

        old_sig = sig_meta.get("old_signature") if sig_meta else None
        new_sig = sig_meta.get("new_signature") if sig_meta else None

        if sig_meta and sig_meta.get("reasons"):
            reasons_str = "; ".join(sig_meta["reasons"])
            if not breaking or breaking == callee:
                breaking = reasons_str
            elif reasons_str not in breaking:
                breaking = f"{breaking} ({reasons_str})"

        if issue_type == "syntactical":
            # Determine whether this is a removed symbol vs. an auto-fixable signature change.
            # Removed symbols (functions, classes, methods) CANNOT be safely auto-patched;
            # they must be flagged as "Manual Intervention Required".
            is_removal = (
                any(fn.get("name") == callee or callee.endswith("." + str(fn.get("name", ""))) for fn in diff_result.get("removed_functions", []))
                or any(cls.get("name") == callee or callee.endswith("." + str(cls.get("name", ""))) for cls in diff_result.get("removed_classes", []))
                or any(
                    callee in (m.get("method_name", ""), f"{m.get('class_name','')}.{m.get('method_name','')}")
                    or callee.endswith("." + str(m.get("method_name", "")))
                    for m in diff_result.get("removed_methods", [])
                )
                or (
                    any(phrase in breaking.lower() for phrase in ("function was removed", "method was removed", "class was removed", "was removed"))
                    and not any(param_kw in breaking.lower() for param_kw in ("parameter", "argument", "default value", "param"))
                )
            )

            if is_removal:
                proposed_fix = (
                    f"Manual Intervention Required (`{callee}` was removed and no longer exists in new version)"
                )
                patch_diff = ""
            else:
                # Extract surrounding context if file exists
                lines = get_lines(fp)
                ctx = ""
                if lines and 1 <= line_no <= len(lines):
                    start = max(0, line_no - 4)
                    end = min(len(lines), line_no + 3)
                    ctx = "".join(lines[start:end])

                # Generate fix via patcher (Groq/DeepSeek API with AST fallback)
                proposed_fix = propose_patch(
                    code_snippet=expr,
                    breaking_change_info={
                        "breaking_change": breaking,
                        "old_signature": old_sig,
                        "new_signature": new_sig,
                        "code_context": ctx,
                    },
                    api_key=api_key,
                    model=deepseek_model,
                )

                # Generate unified diff preview
                patch_diff = ""
                if expr and proposed_fix and expr != proposed_fix and _is_valid_replacement_code(proposed_fix):
                    patch_diff = f"- {expr}\n+ {proposed_fix}"
                elif proposed_fix and not _is_valid_replacement_code(proposed_fix):
                    # If invalid or explanation returned, revert to expr (no patch)
                    proposed_fix = expr

            syntactical_issues.append(
                RepairIssue(
                    file_path=fp,
                    line_number=line_no,
                    function_name=callee,
                    caller_name=caller,
                    breaking_change=breaking,
                    issue_type="syntactical",
                    risk_score=score,
                    risk_level=level,
                    call_expression=expr,
                    old_signature=old_sig,
                    new_signature=new_sig,
                    proposed_fix=proposed_fix,
                    patch_diff=patch_diff,
                    is_removal=is_removal,
                    manual_intervention_required=is_removal,
                )
            )
        else:
            explanation = (
                f"Behavioral or structural breaking change ({breaking}). "
                f"Runtime behavior, algorithms, or removed symbols cannot be patched "
                f"pre-installation; verify after installation via test suite."
            )
            behavioral_issues.append(
                RepairIssue(
                    file_path=fp,
                    line_number=line_no,
                    function_name=callee,
                    caller_name=caller,
                    breaking_change=breaking,
                    issue_type="behavioral",
                    risk_score=score,
                    risk_level=level,
                    call_expression=expr,
                    explanation=explanation,
                )
            )

    # 5. Build file-level patched content and unified diffs
    patched_files: dict[str, str] = {}
    unified_diffs: dict[str, str] = {}

    # Group syntactical issues by file
    by_file: dict[str, list[RepairIssue]] = {}
    for iss in syntactical_issues:
        by_file.setdefault(iss.file_path, []).append(iss)

    for file_path, issues in by_file.items():
        p = Path(file_path)
        if not p.is_file():
            continue
        original_text = p.read_text(encoding="utf-8")
        file_lines = original_text.splitlines(keepends=True)

        modified = False
        # Sort issues by line number in reverse order to avoid line shifting
        sorted_issues = sorted(issues, key=lambda x: x.line_number, reverse=True)
        for iss in sorted_issues:
            # Exclude removed symbols or issues requiring manual intervention
            if iss.is_removal or iss.manual_intervention_required:
                continue
            if not iss.proposed_fix or not iss.call_expression:
                continue
            # Ensure proposed fix is valid code, not English or unchanged
            if not _is_valid_replacement_code(iss.proposed_fix):
                continue
            if iss.proposed_fix == iss.call_expression:
                continue

            idx = iss.line_number - 1
            if 0 <= idx < len(file_lines):
                old_line = file_lines[idx]
                if iss.call_expression in old_line:
                    new_line = old_line.replace(iss.call_expression, iss.proposed_fix)
                    file_lines[idx] = new_line
                    modified = True

        if modified:
            new_text = "".join(file_lines)
            # Verify that patched content parses as valid Python
            try:
                ast.parse(new_text)
                patched_files[file_path] = new_text

                # Compute unified diff
                diff = difflib.unified_diff(
                    original_text.splitlines(),
                    new_text.splitlines(),
                    fromfile=f"a/{Path(file_path).name}",
                    tofile=f"b/{Path(file_path).name}",
                    lineterm="",
                )
                unified_diffs[file_path] = "\n".join(diff)
            except SyntaxError:
                # Patch generated invalid syntax - safely discard to prevent breaking code
                pass

    total_issues = len(syntactical_issues) + len(behavioral_issues)
    manual_count = sum(1 for iss in syntactical_issues if iss.is_removal or iss.manual_intervention_required)

    return PreInstallRepairReport(
        total_issues=total_issues,
        syntactical_count=len(syntactical_issues),
        behavioral_count=len(behavioral_issues),
        syntactical_issues=syntactical_issues,
        behavioral_issues=behavioral_issues,
        patched_files=patched_files,
        unified_diffs=unified_diffs,
        manual_intervention_count=manual_count,
    )


def format_pre_install_report(report: PreInstallRepairReport) -> str:
    """Produce the clear terminal Pre-Install Repair report.

    Clearly separates:
    1. Auto-fixable signature changes (applied pre-installation)
    2. Removed functions / symbols (manual intervention required)
    3. Behavioral / structural issues (deferred to post-installation test verification)
    """
    border = "=" * 70
    sub_border = "-" * 70

    auto_fixable = report.auto_fixable_issues
    removals = report.manual_intervention_issues
    behavioral = report.behavioral_issues

    lines = [
        border,
        "  SAFEDEP - PRE-INSTALL REPAIR REPORT",
        border,
        "SUMMARY:",
        f"  * Total issues found:                                 {report.total_issues}",
        f"  * Syntactical / signature issues (fixable now):       {len(auto_fixable)}",
        f"  * Removed functions (manual intervention):            {len(removals)}",
        f"  * Behavioral / structural issues (deferred):          {report.behavioral_count}",
        sub_border,
        "IMPORTANT NOTE ON BEHAVIORAL ISSUES:",
        "  [!] Behavioral and semantic issues (e.g., altered return value ranges,",
        "      internal algorithm modifications, runtime exceptions, removed functions)",
        "      cannot be safely fixed pre-installation without running the software.",
        "      These issues CAN ONLY BE DETECTED AND VERIFIED AFTER INSTALLATION",
        "      by running the client project's unit and integration test suite.",
        sub_border,
    ]

    # Section 1: Auto-Fixable Signature Changes
    if auto_fixable:
        lines.append(f"\n[+] AUTO-FIXABLE SIGNATURE CHANGES ({len(auto_fixable)}):")
        lines.append("    (Patches generated via Groq / DeepSeek / AST Refactoring Engine)\n")
        for idx, iss in enumerate(auto_fixable, 1):
            fname = Path(iss.file_path).name
            lines.append(f"  {idx}. [{iss.risk_level}] `{iss.function_name}` in {fname}:{iss.line_number}")
            lines.append(f"     Caller:       `{iss.caller_name}()`")
            lines.append(f"     Issue:        {iss.breaking_change}")
            lines.append(f"     Old Call:     {iss.call_expression}")
            if iss.proposed_fix:
                lines.append(f"     Proposed Fix: {iss.proposed_fix}")
            if iss.patch_diff:
                lines.append(f"     Patch Diff:   {iss.patch_diff.replace(chr(10), ' | ')}")
            lines.append("")

    # Section 2: Removed Functions / Methods (Manual Intervention Required)
    if removals:
        lines.append(f"\n[!] REMOVED FUNCTIONS / SYMBOLS (MANUAL INTERVENTION REQUIRED) ({len(removals)}):")
        lines.append("    (Removed symbols cannot be safely auto-patched; manual review required)\n")
        for idx, iss in enumerate(removals, 1):
            fname = Path(iss.file_path).name
            lines.append(f"  {idx}. [{iss.risk_level}] `{iss.function_name}` in {fname}:{iss.line_number}")
            lines.append(f"     Caller:       `{iss.caller_name}()`")
            lines.append(f"     Issue:        {iss.breaking_change}")
            lines.append(f"     Old Call:     {iss.call_expression}")
            lines.append(f"     Status:       MANUAL INTERVENTION REQUIRED")
            lines.append(f"     Guidance:     {iss.proposed_fix or 'Symbol removed in new version.'}")
            lines.append("")

    # Section 3: Behavioral / Deferred Issues
    if behavioral:
        lines.append(f"\n[?] BEHAVIORAL / STRUCTURAL ISSUES (DEFERRED) ({len(behavioral)}):")
        lines.append("    (Must be verified post-installation via test suite)\n")
        for idx, iss in enumerate(behavioral, 1):
            fname = Path(iss.file_path).name
            lines.append(f"  {idx}. [{iss.risk_level}] `{iss.function_name}` in {fname}:{iss.line_number}")
            lines.append(f"     Caller:   `{iss.caller_name}()`")
            lines.append(f"     Issue:    {iss.breaking_change}")
            lines.append(f"     Status:   DEFERRED -> Post-install test verification required.")
            lines.append("")

    # Section 4: File Diffs (Only for valid auto-fixable patches)
    if report.unified_diffs:
        lines.append(sub_border)
        lines.append("GENERATED UNIFIED DIFFS:")
        for fp, diff in report.unified_diffs.items():
            lines.append(f"\n--- {fp} ---")
            lines.append(diff.strip())

    lines.append(border)
    return "\n".join(lines)


def apply_fixes(report: PreInstallRepairReport, create_backup: bool = True) -> list[str]:
    """Apply generated patches to files on disk.

    Only applies valid Python code patches. Any invalid patches or manual
    intervention items are strictly excluded.

    Args:
        report: The PreInstallRepairReport containing patched file contents.
        create_backup: Whether to create a `.bak` copy of files before modifying.

    Returns:
        list[str]: Paths of modified files.
    """
    modified_files: list[str] = []

    for file_path, new_content in report.patched_files.items():
        p = Path(file_path)
        if not p.is_file():
            continue

        # Strictly verify that new_content is syntactically valid Python before writing
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            print(f"[!] Warning: Skipping candidate patch for {file_path} because it produced a syntax error: {e}", file=sys.stderr)
            continue

        if create_backup:
            backup_path = p.with_suffix(p.suffix + ".bak")
            shutil.copy2(p, backup_path)

        p.write_text(new_content, encoding="utf-8")
        modified_files.append(str(p))

    report.applied = True
    return modified_files


def install_new_library(new_library_spec: str) -> bool:
    """Execute installation of the new library using pip or local module installation.

    Args:
        new_library_spec: Package specification, wheel path, package directory, or python file.

    Returns:
        bool: True if installation succeeded (exit code 0), False otherwise.
    """
    p = Path(new_library_spec)
    # If the spec points directly to a single standalone .py file (e.g. in file-based demos)
    if p.is_file() and p.suffix == ".py":
        try:
            import site
            site_dirs = site.getsitepackages() if hasattr(site, "getsitepackages") else []
            if not site_dirs:
                site_dirs = [site.getusersitepackages()]
            for sdir in site_dirs:
                sp = Path(sdir)
                if sp.is_dir() and os.access(sp, os.W_OK):
                    dest = sp / p.name
                    shutil.copy2(p, dest)
                    return True
        except Exception:
            pass

    cmd = [sys.executable, "-m", "pip", "install", new_library_spec]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


def run_pre_install_repair(
    old_path: Union[str, Path],
    new_path: Union[str, Path],
    client_path: Union[str, Path],
    action: Optional[str] = None,
    api_key: Optional[str] = None,
    deepseek_model: str = "deepseek-chat",
    install_target: Optional[str] = None,
    interactive: bool = False,
) -> PreInstallRepairReport:
    """Orchestrate the complete Pre-Install Repair workflow.

    1. Analyzes issues using api_diff, call_graph, and risk_ranker.
    2. Generates patches for syntactical/signature changes with DeepSeek API.
    3. Prints the comprehensive Pre-Install Repair Report.
    4. Handles user options:
       - 'apply_and_install' / '1': Apply fixes and install the new library
       - 'apply_only' / '2': Apply fixes only
       - 'report_only' / '3': Only show report

    Args:
        old_path: Path to old library version.
        new_path: Path to new library version.
        client_path: Path to client application codebase.
        action: 'apply_and_install', 'apply_only', 'report_only', or None.
        api_key: Optional Groq / DeepSeek API key.
        deepseek_model: LLM model identifier (default: "deepseek-chat").
        install_target: Library spec or path to pass to pip install (defaults to str(new_path)).
        interactive: If True and action is None, prompt user via stdin.

    Returns:
        PreInstallRepairReport: Completed repair report.
    """
    # 1. Run analysis and patch generation
    report = analyze_pre_install_issues(
        old_path=old_path,
        new_path=new_path,
        client_path=client_path,
        api_key=api_key,
        deepseek_model=deepseek_model,
    )

    # 2. Display the clear report
    print(format_pre_install_report(report))

    # 3. Determine action
    chosen_action = action
    if chosen_action is None and interactive:
        print("\nPre-Install Repair Actions:")
        print("  [1] Apply fixes and install the new library")
        print("  [2] Apply fixes only")
        print("  [3] Only show report")
        try:
            choice = input("\nEnter choice [1-3] (default: 3): ").strip()
            if choice == "1":
                chosen_action = "apply_and_install"
            elif choice == "2":
                chosen_action = "apply_only"
            else:
                chosen_action = "report_only"
        except (EOFError, KeyboardInterrupt):
            chosen_action = "report_only"

    # Default to report_only if no action specified
    if not chosen_action:
        chosen_action = "report_only"

    # 4. Execute selected option
    target_spec = install_target or str(new_path)

    if chosen_action in ("apply_and_install", "1"):
        print("\n[>>] Applying fixes to client codebase...")
        applied = apply_fixes(report)
        print(f"Applied fixes to {len(applied)} file(s):")
        for f in applied:
            print(f"  * {f} (backup created)")

        print(f"\n[>>] Installing new library: {target_spec} ...")
        success = install_new_library(target_spec)
        report.installed = success
        if success:
            print("[OK] Library installed successfully!")
        else:
            print(f"[!] Warning: Library installation failed for '{target_spec}'. Please verify the package specification and network connection.", file=sys.stderr)

    elif chosen_action in ("apply_only", "2"):
        print("\n[>>] Applying fixes only (skipping library installation)...")
        applied = apply_fixes(report)
        print(f"Applied fixes to {len(applied)} file(s):")
        for f in applied:
            print(f"  * {f} (backup created)")

    else:
        print("\n[OK] Report only mode completed. No files were modified.")

    return report
