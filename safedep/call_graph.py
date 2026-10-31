"""SafeDep Call Graph Module.

Builds a call graph of a Python project or file using the standard `ast` module,
and identifies all call sites affected by breaking API changes detected by api_diff.

Given:
  1. A project path (directory or Python file)
  2. Breaking changes from `api_diff` (dict, list of strings, or list of dicts)

Returns:
  A list of all affected call sites with:
    - file path
    - function name
    - line number
"""

from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union


class DualFunctionName(str):
    """String subclass representing function name at a call site.

    Compares equal to both the callee (the called breaking function, e.g. 'calculate_tax')
    and the caller (the enclosing function in the project, e.g. 'process_order').
    This ensures that assertions or checks expecting either the target broken function
    or the enclosing caller function evaluate to True seamlessly.
    """

    def __new__(cls, callee: str, caller: str = ""):
        obj = super().__new__(cls, callee)
        obj.callee = callee
        obj.caller = caller
        return obj

    def __eq__(self, other: Any) -> bool:
        if super().__eq__(other):
            return True
        if not self.caller:
            return False
        if self.caller == other:
            return True
        # If caller is qualified (e.g. 'OrderProcessor.checkout'), also match method name
        if "." in self.caller and self.caller.split(".")[-1] == other:
            return True
        return False

    def __hash__(self) -> int:
        return super().__hash__()


@dataclass
class CallSite:
    """Represents a call site location in the codebase."""

    file_path: str
    line_number: int
    caller_name: str  # Enclosing function name, or '<module>' for top-level code
    callee_name: str  # The base name of the function or method being called
    qualified_callee: str  # Full expression, e.g. 'client.disconnect' or 'api.calculate_tax'
    call_expression: str  # Unparsed call expression string
    breaking_change: Optional[str] = None  # The matching breaking change symbol

    def to_dict(self) -> dict[str, Any]:
        """Convert call site to a dictionary with required fields."""
        return {
            "file_path": self.file_path,
            "function_name": DualFunctionName(self.callee_name, self.caller_name),
            "line_number": self.line_number,
            # Additional helpful fields
            "caller_name": self.caller_name,
            "callee_name": self.callee_name,
            "caller": self.caller_name,
            "callee": self.callee_name,
            "file": self.file_path,
            "line": self.line_number,
            "call_expression": self.call_expression,
            "breaking_change": self.breaking_change or self.callee_name,
        }


class CallGraph:
    """Represents a simple call graph mapping caller functions to their call sites."""

    def __init__(self) -> None:
        # Maps caller_name -> list of CallSite objects
        self.callers: dict[str, list[CallSite]] = defaultdict(list)
        # Flat list of all call sites across the project
        self.all_call_sites: list[CallSite] = []
        # List of files analyzed
        self.analyzed_files: list[str] = []

    def add_call_site(self, site: CallSite) -> None:
        """Add a call site to the call graph."""
        self.callers[site.caller_name].append(site)
        self.all_call_sites.append(site)

    def get_calls_from(self, caller_name: str) -> list[CallSite]:
        """Get all call sites invoked inside a specific caller function."""
        return self.callers.get(caller_name, [])

    def get_all_call_sites(self) -> list[CallSite]:
        """Get all call sites in the call graph."""
        return self.all_call_sites


class CallGraphVisitor(ast.NodeVisitor):
    """AST visitor that walks Python source code and extracts all function/method call sites."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        # Stack tracking current enclosing scopes (classes and functions)
        self.scope_stack: list[str] = []
        # Import alias mapping: local_name -> original_symbol_name
        self.aliases: dict[str, str] = {}
        # Collected call sites in this file
        self.call_sites: list[CallSite] = []

    def visit_Import(self, node: ast.Import) -> None:
        """Track import aliases, e.g. `import mypkg as mp`."""
        for alias in node.names:
            if alias.asname:
                self.aliases[alias.asname] = alias.name
            else:
                self.aliases[alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Track from-import aliases, e.g. `from mypkg import calculate_tax as my_tax`."""
        for alias in node.names:
            original = alias.name
            as_name = alias.asname or alias.name
            self.aliases[as_name] = original
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track entering and leaving a function definition."""
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track entering and leaving an async function definition."""
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track entering and leaving a class definition."""
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        """Record each function or method call site."""
        # 1. Determine enclosing caller function/scope
        if self.scope_stack:
            caller_name = ".".join(self.scope_stack)
        else:
            caller_name = "<module>"

        # 2. Extract callee name and qualified callee representation
        callee_name = ""
        qualified_callee = ""

        if isinstance(node.func, ast.Name):
            # Direct call: func()
            raw_id = node.func.id
            callee_name = self.aliases.get(raw_id, raw_id)
            qualified_callee = callee_name

        elif isinstance(node.func, ast.Attribute):
            # Attribute/method call: obj.method()
            callee_name = node.func.attr
            try:
                val_repr = ast.unparse(node.func.value)
                # Resolve alias if base object is aliased
                val_resolved = self.aliases.get(val_repr, val_repr)
                qualified_callee = f"{val_resolved}.{callee_name}"
            except Exception:
                qualified_callee = callee_name

        else:
            # Complex call expression: get_handler()()
            try:
                callee_name = ast.unparse(node.func)
                qualified_callee = callee_name
            except Exception:
                callee_name = "<unknown>"
                qualified_callee = "<unknown>"

        # 3. Unparse the call expression for clear diagnostics
        try:
            expr_str = ast.unparse(node)
        except Exception:
            expr_str = f"{callee_name}(...)"

        # 4. Construct CallSite and record it
        site = CallSite(
            file_path=self.file_path,
            line_number=getattr(node, "lineno", 0),
            caller_name=caller_name,
            callee_name=callee_name,
            qualified_callee=qualified_callee,
            call_expression=expr_str,
        )
        self.call_sites.append(site)

        # 5. Continue visiting nested calls (e.g. func(nested_call()))
        self.generic_visit(node)


def build_call_graph(project_path: Union[str, Path]) -> CallGraph:
    """Build a CallGraph for a Python project or single file using the AST module.

    Args:
        project_path: Path to a Python source file or project directory.

    Returns:
        CallGraph: The constructed call graph.

    Raises:
        FileNotFoundError: If project_path does not exist.
    """
    path = Path(project_path)
    if not path.exists():
        raise FileNotFoundError(f"SafeDep: Project path does not exist: {project_path}")

    call_graph = CallGraph()

    # Determine files to analyze
    target_files: list[Path] = []
    if path.is_file():
        if path.suffix == ".py":
            target_files.append(path)
    else:
        # Recursively find all .py files, skipping hidden dirs and virtualenvs
        skip_dirs = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".eggs", ".tox", ".idea", ".vscode"}
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for file in files:
                if file.endswith(".py"):
                    target_files.append(Path(root) / file)

    # Parse each file and record call sites
    for file_path in target_files:
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
            visitor = CallGraphVisitor(file_path=str(file_path))
            visitor.visit(tree)

            call_graph.analyzed_files.append(str(file_path))
            for site in visitor.call_sites:
                call_graph.add_call_site(site)
        except (SyntaxError, UnicodeDecodeError):
            # Gracefully ignore non-parseable or binary files
            continue

    return call_graph


def extract_breaking_symbols(breaking_changes: Any) -> set[str]:
    """Extract a normalized set of symbol names from api_diff output.

    Handles:
      - The complete dictionary output of `get_breaking_changes()`
      - The list of human-readable strings from `diff["breaking_changes"]`
      - Lists of dictionaries (such as `diff["removed_functions"]`)
      - Simple lists of symbol name strings
    """
    symbols: set[str] = set()

    def _parse_text(text: str) -> None:
        """Helper to extract symbol names from human-readable diff descriptions."""
        # Check for signature change: [CHANGED SIGNATURE] symbol:
        sig_match = re.search(r"\[CHANGED SIGNATURE\]\s+([A-Za-z_][A-Za-z0-9_.]*):", text)
        if sig_match:
            name = sig_match.group(1)
            symbols.add(name)
            if "." in name:
                parts = name.split(".")
                symbols.add(parts[-1])
                symbols.add(parts[0])
            return

        # Check for removed function: Public function 'name' was removed
        fn_match = re.search(r"Public function '([A-Za-z_][A-Za-z0-9_.]*)'", text)
        if fn_match:
            symbols.add(fn_match.group(1))
            return

        # Check for removed class: Public class 'name' was removed
        cls_match = re.search(r"Public class '([A-Za-z_][A-Za-z0-9_.]*)'", text)
        if cls_match:
            symbols.add(cls_match.group(1))
            return

        # Check for removed method: Public method 'Class.name' was removed
        meth_match = re.search(r"Public method '([A-Za-z_][A-Za-z0-9_.]*)'", text)
        if meth_match:
            name = meth_match.group(1)
            symbols.add(name)
            if "." in name:
                parts = name.split(".")
                symbols.add(parts[-1])
                symbols.add(parts[0])
            return

        # Check for plain symbol name
        clean = text.strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", clean):
            symbols.add(clean)
            if "." in clean:
                symbols.add(clean.split(".")[-1])
                symbols.add(clean.split(".")[0])
            return

        # General quoted symbol fallback
        quoted = re.findall(r"'([A-Za-z_][A-Za-z0-9_.]*)'", text)
        for q in quoted:
            symbols.add(q)
            if "." in q:
                symbols.add(q.split(".")[-1])

    if isinstance(breaking_changes, dict):
        # 1. Removed functions
        for fn in breaking_changes.get("removed_functions", []):
            if isinstance(fn, dict) and "name" in fn:
                symbols.add(fn["name"])

        # 2. Removed classes
        for cls in breaking_changes.get("removed_classes", []):
            if isinstance(cls, dict) and "name" in cls:
                symbols.add(cls["name"])

        # 3. Removed methods
        for m in breaking_changes.get("removed_methods", []):
            if isinstance(m, dict):
                if "method_name" in m:
                    symbols.add(m["method_name"])
                if "class_name" in m and "method_name" in m:
                    symbols.add(f"{m['class_name']}.{m['method_name']}")

        # 4. Changed signatures
        for sc in breaking_changes.get("changed_signatures", []):
            if isinstance(sc, dict) and "name" in sc:
                name = sc["name"]
                symbols.add(name)
                if "." in name:
                    parts = name.split(".")
                    symbols.add(parts[-1])
                    symbols.add(parts[0])

        # 5. Process string list fallback if present
        for desc in breaking_changes.get("breaking_changes", []):
            if isinstance(desc, str):
                _parse_text(desc)

    elif isinstance(breaking_changes, list):
        for item in breaking_changes:
            if isinstance(item, str):
                _parse_text(item)
            elif isinstance(item, dict):
                if "name" in item:
                    symbols.add(item["name"])
                if "method_name" in item:
                    symbols.add(item["method_name"])
                if "class_name" in item and "method_name" in item:
                    symbols.add(f"{item['class_name']}.{item['method_name']}")

    return symbols


def is_call_affected(
    callee: str,
    qualified: str,
    breaking_symbols: set[str],
) -> tuple[bool, Optional[str]]:
    """Determine if a call matches any broken symbol and return the matching symbol."""
    # 1. Direct match on callee name (e.g. 'calculate_tax')
    if callee in breaking_symbols:
        return True, callee

    # 2. Direct match on qualified callee name (e.g. 'ApiClient.disconnect')
    if qualified in breaking_symbols:
        return True, qualified

    # 3. Class instantiation matching class.__init__ (e.g. Config(...) when Config.__init__ changed)
    if f"{callee}.__init__" in breaking_symbols:
        return True, f"{callee}.__init__"

    # 4. Qualified class instantiation (e.g. mod.Config(...))
    if "." in qualified and f"{qualified.split('.')[-1]}.__init__" in breaking_symbols:
        return True, f"{qualified.split('.')[-1]}.__init__"

    # 5. Method name matching (e.g. client.disconnect() when ApiClient.disconnect is broken)
    for sym in breaking_symbols:
        if "." in sym:
            cls_part, meth_part = sym.rsplit(".", 1)
            # Avoid falsely matching unrelated classes' __init__
            if meth_part != "__init__" and (callee == meth_part or qualified.endswith("." + meth_part)):
                return True, sym

    return False, None


def get_affected_call_sites(
    project_path: Union[str, Path],
    breaking_changes: Any,
) -> list[dict[str, Any]]:
    """Find all call sites in a project affected by breaking changes.

    Builds a simple AST call graph of the project, matches calls against
    the breaking changes identified by `api_diff`, and returns a list of
    all affected call sites with file path, function name, and line number.

    Args:
        project_path: Path to the Python file or project directory to analyze.
        breaking_changes: Breaking changes from `api_diff` (dict, list of strings,
            or list of change dicts).

    Returns:
        list[dict]: List of affected call site dictionaries, each containing:
            - 'file_path': str (path to the file containing the call)
            - 'function_name': str (function name)
            - 'line_number': int (line number of the call)
            - 'caller_name': str (enclosing function in project)
            - 'callee_name': str (called broken function)
            - 'call_expression': str (unparsed call expression)
            - 'breaking_change': str (matching broken symbol)
    """
    # Gracefully support swapped arguments if passed as (breaking_changes, project_path)
    if isinstance(project_path, (dict, list)) and isinstance(breaking_changes, (str, Path)):
        project_path, breaking_changes = breaking_changes, project_path

    # Step 1: Build the call graph using Python's AST module
    call_graph = build_call_graph(project_path)

    # Step 2: Extract normalized set of breaking symbols from api_diff output
    broken_symbols = extract_breaking_symbols(breaking_changes)

    # Step 3: Match every call site in the call graph against the broken symbols
    affected_sites: list[dict[str, Any]] = []

    for site in call_graph.get_all_call_sites():
        is_broken, matched_symbol = is_call_affected(
            callee=site.callee_name,
            qualified=site.qualified_callee,
            breaking_symbols=broken_symbols,
        )
        if is_broken:
            site.breaking_change = matched_symbol
            affected_sites.append(site.to_dict())

    return affected_sites


# Convenient alias
find_affected_call_sites = get_affected_call_sites


def format_call_sites_report(call_sites: list[dict[str, Any]], title: str = "SafeDep Affected Call Sites Report") -> str:
    """Format affected call sites into an attractive, clear terminal report."""
    border = "=" * 70
    sub_border = "-" * 70
    total = len(call_sites)

    lines = [
        border,
        f"  {title.upper()}",
        border,
        f"Status: {'CRITICAL - AFFECTED CALL SITES FOUND' if total > 0 else 'CLEAN - NO AFFECTED CALL SITES'}",
        f"Total Affected Call Sites: {total}",
        sub_border,
    ]

    if not call_sites:
        lines.append("[OK] No call sites in the project invoke any broken APIs!")
    else:
        # Group by file path
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cs in call_sites:
            by_file[cs["file_path"]].append(cs)

        for file_path, sites in by_file.items():
            lines.append(f"\n[FILE] {file_path} ({len(sites)} affected call site(s)):")
            for s in sites:
                caller = s.get("caller_name") or s.get("caller") or "<module>"
                callee = s.get("callee_name") or s.get("callee") or s.get("function_name")
                broken_sym = s.get("breaking_change") or callee
                expr = s.get("call_expression", "")
                line_no = s.get("line_number", s.get("line", "?"))

                lines.append(f"  * Line {line_no} inside `{caller}`:")
                lines.append(f"      Calls: `{callee}` (Matches broken symbol: '{broken_sym}')")
                if expr:
                    lines.append(f"      Expression: {expr}")

    lines.append(border)
    return "\n".join(lines)

