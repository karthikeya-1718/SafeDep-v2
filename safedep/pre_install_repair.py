"""SafeDep Pre-Install Repair Module.

Implements the Pre-Install Repair mode:
1. Combines `api_diff`, `call_graph`, and `risk_ranker` to identify and prioritize affected call sites.
2. Generates patches for syntactical/signature-level breaking changes using deterministic
   `call_fixer` (R2/R3 rules) with strict fallback/AI guard (R5).
3. Produces a clear pre-installation report with summary counts, diffs, and a NEEDS YOU box.
4. Offers execution options:
   - apply_and_install: Apply fixes and install the new library into specified python
   - apply_only: Apply fixes only
   - report_only: Only show report
   - dry_run: Preview diffs without modifying files
5. R4 Safety: Snapshots taken before edits, AST verification after edits with automatic rollback.
"""

from __future__ import annotations

import ast
import difflib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from .api_diff import get_breaking_changes
from .call_compat import check_call_compatibility
from .call_fixer import (
    FixResult,
    _abs_range,
    _build_breaking_change_map,
    apply_span_edit,
    fix_call,
    patch_file,
)
from .call_graph import get_affected_call_sites
from .environment import install_library
from .patcher import propose_patch
from .risk_ranker import rank_affected_call_sites
from .snapshot import create_snapshot, restore_snapshot


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
    is_removal: bool = False  # True when the function/method no longer exists at all
    fix_status: str = "applied"  # "applied", "manual", "review", "failed"
    col_offset: int = 0
    end_line: int = 0
    end_col_offset: int = 0


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
    applied_count: int = 0
    manual_count: int = 0
    review_count: int = 0
    failed_count: int = 0
    snapshot_id: Optional[str] = None
    project_root: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary format."""
        auto_fixable = [i for i in self.syntactical_issues if i.fix_status == "applied"]
        manual_required = [i for i in self.syntactical_issues if i.fix_status == "manual"]
        review_required = [i for i in self.syntactical_issues if i.fix_status == "review"]
        return {
            "total_issues": self.total_issues,
            "auto_fixable_signature_changes": len(auto_fixable),
            "manual_intervention_required": len(manual_required),
            "review_required": len(review_required),
            "syntactical_issues_fixable_now": self.syntactical_count,
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
                    "fix_status": i.fix_status,
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
            "snapshot_id": self.snapshot_id,
        }


def classify_issue(call_site: dict[str, Any], diff_result: dict[str, Any]) -> tuple[str, Optional[dict[str, Any]]]:
    """Classify a call site issue as either 'syntactical' or 'behavioral'."""
    callee = str(call_site.get("callee_name") or call_site.get("function_name", ""))
    breaking_text = str(call_site.get("breaking_change", ""))

    # 1. Explicitly removed functions
    for fn in diff_result.get("removed_functions", []):
        if fn.get("name") == callee:
            return "syntactical", None

    # 2. Explicitly removed classes
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

    # 6. Behavioral if no structural evidence found in diff
    return "behavioral", None


# ---------------------------------------------------------------------------
# Backwards-compatibility shims
# ---------------------------------------------------------------------------


def generate_patch_with_deepseek(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
    code_context: str = "",
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
) -> str:
    """Thin shim -- delegates to safedep.patcher.propose_patch."""
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
    """Thin shim -- delegates to AST fallback inside safedep.patcher."""
    return propose_patch(
        code_snippet=call_expression,
        breaking_change_info={
            "breaking_change": breaking_change,
            "old_signature": old_signature,
            "new_signature": new_signature,
        },
        api_key="",
    )


def _determine_project_root(client_path: Union[str, Path]) -> Path:
    """Determine snapshot project root: parent of client if client has __init__.py, else client."""
    cp = Path(client_path).resolve()
    if cp.is_file():
        cp = cp.parent
    if (cp / "__init__.py").is_file():
        return cp.parent
    return cp


def analyze_pre_install_issues(
    old_path: Union[str, Path],
    new_path: Union[str, Path],
    client_path: Union[str, Path],
    api_key: Optional[str] = None,
    deepseek_model: str = "deepseek-chat",
    library_name: Optional[str] = None,
    project_root: Optional[Union[str, Path]] = None,
) -> PreInstallRepairReport:
    """Analyze a client project against a proposed library upgrade.

    Uses deterministic R2/R3 call_fixer for patch generation.
    """
    if library_name is None:
        try:
            from .environment import resolve_library_source
            lib_src = resolve_library_source(new_path)
            library_name = lib_src.name
        except Exception:
            library_name = None

    resolved_proj_root = Path(project_root).resolve() if project_root else _determine_project_root(client_path)

    # 1. Run api_diff to find breaking changes in the library
    diff_result = get_breaking_changes(old_path, new_path)
    bc_map = _build_breaking_change_map(diff_result)

    # 2. Run call_graph to find affected call sites in the client project
    raw_call_sites = get_affected_call_sites(client_path, diff_result, library_name=library_name)

    # 3. Run risk_ranker to assign risk scores and sort by impact
    ranked_call_sites = rank_affected_call_sites(
        raw_call_sites, project_path=client_path, tier_ordering=True, library_name=library_name
    )

    syntactical_issues: list[RepairIssue] = []
    behavioral_issues: list[RepairIssue] = []

    # Cache file bytes
    file_bytes_cache: dict[str, bytes] = {}

    def get_source_bytes(fp: str) -> bytes:
        if fp not in file_bytes_cache:
            p = Path(fp)
            if p.is_file():
                file_bytes_cache[fp] = p.read_bytes()
            else:
                file_bytes_cache[fp] = b""
        return file_bytes_cache[fp]

    # 4. Generate fixes for each call site
    for site in ranked_call_sites:
        issue_type, sig_meta = classify_issue(site, diff_result)

        fp = site.get("file_path", "")
        line_no = int(site.get("line_number", 0))
        col_no = int(site.get("col_offset", 0))
        end_line_no = int(site.get("end_line") or line_no)
        end_col_no = int(site.get("end_col_offset", 0))

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
            is_removal = (
                bool(site.get("is_removal"))
                or any(fn.get("name") == callee for fn in diff_result.get("removed_functions", []))
                or any(cls.get("name") == callee for cls in diff_result.get("removed_classes", []))
                or any(
                    callee in (m.get("method_name", ""), f"{m.get('class_name','')}.{m.get('method_name','')}")
                    for m in diff_result.get("removed_methods", [])
                )
            )

            # Get matching breaking change entry
            bc_entry = bc_map.get(callee, sig_meta or {})
            if is_removal:
                bc_entry = {"is_removal": True, **bc_entry}

            src_bytes = get_source_bytes(fp)
            # Invoke deterministic call_fixer
            fix_res = fix_call(site, bc_entry, src_bytes)

            status = fix_res.status
            proposed_fix: Optional[str] = None
            patch_diff: Optional[str] = None

            if status == "review" and (api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")):
                # R5: Call remote provider ONLY for review sites if key configured
                try:
                    ai_answer = propose_patch(
                        code_snippet=expr,
                        breaking_change_info={
                            "breaking_change": breaking,
                            "old_signature": old_sig,
                            "new_signature": new_sig,
                        },
                        api_key=api_key,
                        model=deepseek_model,
                    )
                    # Validate AI answer: parseable, calls same function, call_compat fits
                    ai_tree = ast.parse(ai_answer)
                    if len(ai_tree.body) == 1 and isinstance(ai_tree.body[0], ast.Expr) and isinstance(ai_tree.body[0].value, ast.Call):
                        ai_call = ai_tree.body[0].value
                        ai_callee = ai_call.func.id if isinstance(ai_call.func, ast.Name) else (ai_call.func.attr if isinstance(ai_call.func, ast.Attribute) else "")
                        if ai_callee == callee:
                            compat = check_call_compatibility(bc_entry.get("old_fn") or old_sig, bc_entry.get("new_fn") or new_sig, ai_call)
                            if compat == "fits":
                                status = "applied"
                                fix_res = FixResult(status="applied", new_call_bytes=ai_answer.encode("utf-8"), reason="AI patch validated")
                except Exception:
                    pass

            if status == "applied" and fix_res.new_call_bytes is not None:
                proposed_fix = fix_res.new_call_bytes.decode("utf-8", errors="replace")
                if expr and proposed_fix and expr != proposed_fix:
                    patch_diff = f"- {expr}\n+ {proposed_fix}"
            elif status == "manual":
                proposed_fix = None
                patch_diff = f"# {expr}  # TODO: `{callee}` was removed or requires manual fix"
            elif status == "review":
                proposed_fix = None
                patch_diff = f"# {expr}  # REVIEW: requires human confirmation"

            syntactical_issues.append(
                RepairIssue(
                    file_path=fp,
                    line_number=line_no,
                    col_offset=col_no,
                    end_line=end_line_no,
                    end_col_offset=end_col_no,
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
                    fix_status=status,
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
                    col_offset=col_no,
                    end_line=end_line_no,
                    end_col_offset=end_col_no,
                    function_name=callee,
                    caller_name=caller,
                    breaking_change=breaking,
                    issue_type="behavioral",
                    risk_score=score,
                    risk_level=level,
                    call_expression=expr,
                    explanation=explanation,
                    fix_status="review",
                )
            )

    # 5. Build file-level patched content and unified diffs using bottom-up span edits (in memory)
    patched_files: dict[str, str] = {}
    unified_diffs: dict[str, str] = {}

    by_file: dict[str, list[RepairIssue]] = {}
    for iss in syntactical_issues:
        by_file.setdefault(iss.file_path, []).append(iss)

    for file_path, issues in by_file.items():
        p = Path(file_path)
        if not p.is_file():
            continue
        original_bytes = p.read_bytes()
        src_bytes = original_bytes

        # Sort issues bottom-up by line and col
        sorted_issues = sorted(
            [iss for iss in issues if iss.fix_status == "applied" and iss.proposed_fix],
            key=lambda x: (-x.line_number, -x.col_offset),
        )

        for iss in sorted_issues:
            if iss.proposed_fix:
                start_abs, end_abs = _abs_range(
                    src_bytes, iss.line_number, iss.col_offset, iss.end_line, iss.end_col_offset
                )
                orig_call = src_bytes[start_abs:end_abs]
                new_call = iss.proposed_fix.encode("utf-8")
                if orig_call != new_call:
                    src_bytes = apply_span_edit(
                        src_bytes, iss.line_number, iss.col_offset, iss.end_line, iss.end_col_offset, new_call
                    )

        if src_bytes != original_bytes:
            new_text = src_bytes.decode("utf-8", errors="replace")
            orig_text = original_bytes.decode("utf-8", errors="replace")
            patched_files[file_path] = new_text

            diff = difflib.unified_diff(
                orig_text.splitlines(),
                new_text.splitlines(),
                fromfile=f"a/{Path(file_path).name}",
                tofile=f"b/{Path(file_path).name}",
                lineterm="",
            )
            unified_diffs[file_path] = "\n".join(diff)

    applied_count = sum(1 for i in syntactical_issues if i.fix_status == "applied")
    manual_count = sum(1 for i in syntactical_issues if i.fix_status == "manual")
    review_count = sum(1 for i in syntactical_issues if i.fix_status == "review") + len(behavioral_issues)
    failed_count = sum(1 for i in syntactical_issues if i.fix_status == "failed")
    total_issues = len(syntactical_issues) + len(behavioral_issues)

    return PreInstallRepairReport(
        total_issues=total_issues,
        syntactical_count=len(syntactical_issues),
        behavioral_count=len(behavioral_issues),
        syntactical_issues=syntactical_issues,
        behavioral_issues=behavioral_issues,
        patched_files=patched_files,
        unified_diffs=unified_diffs,
        applied_count=applied_count,
        manual_count=manual_count,
        review_count=review_count,
        failed_count=failed_count,
        project_root=str(resolved_proj_root),
    )


def format_pre_install_report(report: PreInstallRepairReport) -> str:
    """Produce the clear terminal Pre-Install Repair report."""
    border = "=" * 70
    sub_border = "-" * 70

    auto_fixable = [i for i in report.syntactical_issues if i.fix_status == "applied"]
    manual_required = [i for i in report.syntactical_issues if i.fix_status == "manual"]
    review_required = [i for i in report.syntactical_issues if i.fix_status == "review"]

    lines = [
        border,
        "  SAFEDEP - PRE-INSTALL REPAIR REPORT",
        border,
        "SUMMARY:",
        f"  * Total issues found:                                 {report.total_issues}",
        f"  * Auto-fixable signature changes:                     {len(auto_fixable)}",
        f"  * Removed functions/methods (manual intervention):    {len(manual_required)}",
        f"  * Behavioral / structural issues (deferred):          {report.behavioral_count}",
        f"  * Summary: {len(auto_fixable)} edits to apply, {len(manual_required)} manual, {len(review_required) + report.behavioral_count} review",
        sub_border,
        "IMPORTANT NOTE ON BEHAVIORAL ISSUES:",
        "  [!] Behavioral and semantic issues (e.g., altered return value ranges,",
        "      internal algorithm modifications, runtime exceptions)",
        "      cannot be safely fixed pre-installation without running the software.",
        "      These issues CAN ONLY BE DETECTED AND VERIFIED AFTER INSTALLATION",
        "      by running the client project's unit and integration test suite.",
        sub_border,
    ]

    # Section 1a: Auto-fixable signature changes
    if auto_fixable:
        lines.append(f"\n[+] AUTO-FIXABLE SIGNATURE CHANGES ({len(auto_fixable)}):")
        lines.append("    (Patches generated via Deterministic Call Fixer / R2 Rules)\n")
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

    # Section 1b: Removed functions/methods -- cannot be auto-fixed
    if manual_required:
        lines.append(f"\n[x] REMOVED FUNCTIONS / METHODS -- MANUAL INTERVENTION REQUIRED ({len(manual_required)}):")
        lines.append("    (Cannot auto-fix safely: the function no longer exists in the new version.")
        lines.append("     The original call is shown below. Replace or remove it manually.)\n")
        for idx, iss in enumerate(manual_required, 1):
            fname = Path(iss.file_path).name
            lines.append(f"  {idx}. [{iss.risk_level}] `{iss.function_name}` in {fname}:{iss.line_number}")
            lines.append(f"     Caller:   `{iss.caller_name}()`")
            lines.append(f"     Issue:    `{iss.function_name}` was removed -- no replacement call can be generated.")
            lines.append(f"     Old Call: {iss.call_expression}")
            lines.append(f"     Status:   Cannot auto-fix safely -- manual replacement or removal required.")
            if iss.patch_diff:
                lines.append(f"     Safe Suggestion: Comment out the line -->")
                lines.append(f"       {iss.patch_diff}")
            lines.append("")

    # Section 2: Behavioral / Deferred Issues
    if report.behavioral_issues:
        lines.append(f"\n[!] BEHAVIORAL / STRUCTURAL ISSUES ({report.behavioral_count}):")
        lines.append("    (Must be verified post-installation via test suite)\n")
        for idx, iss in enumerate(report.behavioral_issues, 1):
            fname = Path(iss.file_path).name
            lines.append(f"  {idx}. [{iss.risk_level}] `{iss.function_name}` in {fname}:{iss.line_number}")
            lines.append(f"     Caller:   `{iss.caller_name}()`")
            lines.append(f"     Issue:    {iss.breaking_change}")
            lines.append(f"     Status:   DEFERRED -> Post-install test verification required.")
            lines.append("")

    # Section 3: File Diffs (only for auto-fixable changes)
    auto_fix_diffs = {
        fp: diff for fp, diff in report.unified_diffs.items() if diff.strip()
    }
    if auto_fix_diffs:
        lines.append(sub_border)
        lines.append("GENERATED UNIFIED DIFFS (auto-fixable changes only):")
        for fp, diff in auto_fix_diffs.items():
            lines.append(f"\n--- {fp} ---")
            lines.append(diff.strip())

    # Section 4: NEEDS YOU box (R6)
    needs_you_items = manual_required + review_required
    if needs_you_items:
        lines.append("\n" + "=" * 70)
        lines.append("  NEEDS YOU: SITES REQUIRING HUMAN ACTION OR CONFIRMATION")
        lines.append("=" * 70)
        for idx, iss in enumerate(needs_you_items, 1):
            fname = Path(iss.file_path).name
            loc = f"{fname}:{iss.line_number}"
            lines.append(f"  {idx}. [{iss.fix_status.upper()}] `{iss.function_name}` at {loc}")
            lines.append(f"     Expression: {iss.call_expression}")
            if iss.fix_status == "manual":
                lines.append(f"     Suggested replacement: # {iss.call_expression}  # replace with local implementation or remove")
            else:
                lines.append(f"     Action: Review dynamic call or parameter structure")
            lines.append("")
        lines.append("=" * 70)

    lines.append(border)
    return "\n".join(lines)


def apply_fixes(
    report: PreInstallRepairReport,
    create_backup: bool = True,
    project_root: Optional[Union[str, Path]] = None,
) -> list[str]:
    """Apply generated patches to files on disk with R4 safety guarantees.

    Creates snapshot before editing, validates via ast.parse, and rolls back on failure.
    """
    if not report.patched_files:
        report.applied = True
        return []

    files_to_edit = [Path(fp).resolve() for fp in report.patched_files.keys()]
    proj_root = Path(project_root).resolve() if project_root else (Path(report.project_root).resolve() if report.project_root else _determine_project_root(files_to_edit[0]))

    # R4: Snapshot before applying
    snap = create_snapshot(proj_root, files_to_edit, label="pre-repair")
    report.snapshot_id = snap.snapshot_id
    report.project_root = str(proj_root)

    modified_files: list[str] = []
    syntax_error_occurred = False

    try:
        for file_path, new_content in report.patched_files.items():
            p = Path(file_path)
            if not p.is_file():
                continue
            if create_backup:
                backup_path = p.with_suffix(p.suffix + ".bak")
                shutil.copy2(p, backup_path)

            p.write_text(new_content, encoding="utf-8")
            modified_files.append(str(p))

            # Verify with ast.parse
            try:
                ast.parse(new_content)
            except SyntaxError as syn_err:
                syntax_error_occurred = True
                print(f"\n[ERROR] SyntaxError in patched file {file_path}: {syn_err}", file=sys.stderr)
                break

        if syntax_error_occurred:
            print(f"[RECOVERY] Rolling back all changes using snapshot '{snap.snapshot_id}'...", file=sys.stderr)
            restore_snapshot(proj_root, snap.snapshot_id)
            report.applied = False
            return []

    except Exception as exc:
        print(f"[RECOVERY] Exception during apply, rolling back: {exc}", file=sys.stderr)
        restore_snapshot(proj_root, snap.snapshot_id)
        report.applied = False
        return []

    report.applied = True
    return modified_files


def install_new_library(new_library_spec: str, python: Optional[str] = None) -> bool:
    """Execute library installation into the target python environment."""
    py_exe = python or sys.executable
    res = install_library(py_exe, new_library_spec)
    return res.success


def run_pre_install_repair(
    old_path: Union[str, Path],
    new_path: Union[str, Path],
    client_path: Union[str, Path],
    action: Optional[str] = None,
    api_key: Optional[str] = None,
    install_target: Optional[str] = None,
    interactive: bool = False,
    is_demo_case_1: bool = False,
    library_name: Optional[str] = None,
    project_root: Optional[Union[str, Path]] = None,
    dry_run: bool = False,
    python: Optional[str] = None,
) -> PreInstallRepairReport:
    """Orchestrate the complete Pre-Install Repair workflow."""
    # 1. Run analysis and patch generation
    report = analyze_pre_install_issues(
        old_path=old_path,
        new_path=new_path,
        client_path=client_path,
        api_key=api_key,
        library_name=library_name,
        project_root=project_root,
    )

    # 2. Display the clear report
    if is_demo_case_1:
        from .utils import format_demo_case_1_report
        diff_res = get_breaking_changes(old_path, new_path)
        print(format_demo_case_1_report(diff_res))
    else:
        print(format_pre_install_report(report))

    # 3. Determine action
    chosen_action = action
    if dry_run:
        chosen_action = "preview"
    elif chosen_action is None and interactive:
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

    if not chosen_action:
        chosen_action = "report_only"

    target_spec = install_target or str(new_path)

    if chosen_action == "preview":
        if report.unified_diffs:
            print("\n" + "=" * 70)
            print("PREVIEW GENERATED PATCHES (DRY RUN):")
            print("=" * 70)
            for fp, diff in report.unified_diffs.items():
                print(f"--- {fp} ---")
                print(diff.strip())
            print("=" * 70)
        else:
            print("\n[OK] No patch diffs to preview.")
        return report

    if chosen_action in ("apply_and_install", "1"):
        print("\n[>>] Applying fixes to client codebase...")
        applied = apply_fixes(report, create_backup=create_bak, project_root=project_root)
        print(f"Applied fixes to {len(applied)} file(s).")
        if report.snapshot_id and report.project_root:
            print(f"Snapshot ID: {report.snapshot_id}")
            print(f"Restore command: python main.py snapshots restore --project {report.project_root} --id {report.snapshot_id}")

        # Post-apply re-scan
        _run_post_apply_rescan(client_path, old_path, new_path, library_name)

        target_python = python or sys.executable
        print(f"\n[>>] Installing new library: {target_spec} using {target_python} ...")
        success = install_new_library(target_spec, python=target_python)
        report.installed = success
        if success:
            print("[OK] Library installed successfully!")
        else:
            print(f"[!] Warning: Library installation exited with error. Check package spec: {target_spec}")

    elif chosen_action in ("apply_only", "2"):
        print("\n[>>] Applying fixes only (skipping library installation)...")
        # For CLI usage, create_backup=False as snapshots supersede .bak; for programmatic callers create_backup is controlled by argument
        create_bak = False if project_root or getattr(report, "snapshot_id", None) else True
        applied = apply_fixes(report, create_backup=create_bak, project_root=project_root)
        print(f"Applied fixes to {len(applied)} file(s).")
        if report.snapshot_id and report.project_root:
            print(f"Snapshot ID: {report.snapshot_id}")
            print(f"Restore command: python main.py snapshots restore --project {report.project_root} --id {report.snapshot_id}")

        # Post-apply re-scan
        _run_post_apply_rescan(client_path, old_path, new_path, library_name)

    else:
        print("\n[OK] Report only mode completed. No files were modified.")

    return report


def _run_post_apply_rescan(
    client_path: Union[str, Path],
    old_path: Union[str, Path],
    new_path: Union[str, Path],
    library_name: Optional[str],
) -> None:
    """Run Phase 4 analysis on the patched client and print summary of remaining sites."""
    try:
        diff_res = get_breaking_changes(old_path, new_path)
        remaining = get_affected_call_sites(client_path, diff_res, library_name=library_name)
        print(f"\n[RE-SCAN AFTER PATCHING]")
        print(f"  * Call sites still breaking: {len(remaining)}")
        for idx, site in enumerate(remaining, 1):
            fn = site.get("callee_name") or site.get("function_name", "unknown")
            fp = Path(site.get("file_path", "")).name
            ln = site.get("line_number", 0)
            compat = site.get("compatibility", "breaks")
            is_rem = site.get("is_removal", False)
            cat = "manual" if is_rem else ("review" if compat == "uncertain" else "auto")
            print(f"    {idx}. {fn} in {fp}:{ln} [{cat}]")
    except Exception as exc:
        print(f"[RE-SCAN] Notice: Could not run post-apply re-scan: {exc}")
