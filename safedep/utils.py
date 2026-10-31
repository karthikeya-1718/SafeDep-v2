"""SafeDep Utility Module.

Provides AST parsing, parameter extraction, signature formatting,
and report generation utilities for analyzing Python APIs.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union


@dataclass
class ParamInfo:
    """Represents a parameter in a function or method signature."""

    name: str
    kind: str  # POSITIONAL_ONLY, POSITIONAL_OR_KEYWORD, VAR_POSITIONAL, KEYWORD_ONLY, VAR_KEYWORD
    has_default: bool
    default_repr: Optional[str] = None
    annotation: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert parameter to a clean dictionary."""
        return {
            "name": self.name,
            "kind": self.kind,
            "has_default": self.has_default,
            "default": self.default_repr,
            "annotation": self.annotation,
        }

    def format(self) -> str:
        """Format the parameter as valid Python code representation."""
        res = self.name
        if self.annotation:
            res += f": {self.annotation}"
        if self.has_default and self.default_repr is not None:
            res += f" = {self.default_repr}"
        return res


@dataclass
class FunctionInfo:
    """Represents a function or method extracted via AST."""

    name: str
    line: int
    params: list[ParamInfo] = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)
    docstring: Optional[str] = None
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert function info to a clean dictionary."""
        return {
            "name": self.name,
            "line": self.line,
            "signature": self.signature,
            "is_async": self.is_async,
            "decorators": self.decorators,
            "params": [p.to_dict() for p in self.params],
            "return_type": self.return_type,
        }


@dataclass
class ClassInfo:
    """Represents a class extracted via AST."""

    name: str
    line: int
    bases: list[str] = field(default_factory=list)
    methods: dict[str, FunctionInfo] = field(default_factory=dict)
    constants: dict[str, int] = field(default_factory=dict)
    decorators: list[str] = field(default_factory=list)
    docstring: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert class info to a clean dictionary."""
        return {
            "name": self.name,
            "line": self.line,
            "bases": self.bases,
            "decorators": self.decorators,
            "methods": {k: v.to_dict() for k, v in self.methods.items()},
            "constants": self.constants,
        }


@dataclass
class ModuleSnapshot:
    """Represents public API elements of a module or file."""

    file_path: str
    module_name: str
    functions: dict[str, FunctionInfo] = field(default_factory=dict)
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    constants: dict[str, int] = field(default_factory=dict)
    all_exports: Optional[list[str]] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert module snapshot to a clean dictionary."""
        return {
            "file_path": self.file_path,
            "module_name": self.module_name,
            "functions": {k: v.to_dict() for k, v in self.functions.items()},
            "classes": {k: v.to_dict() for k, v in self.classes.items()},
            "constants": self.constants,
            "all_exports": self.all_exports,
        }


def parse_source_to_ast(source_or_path: Union[str, Path]) -> ast.AST:
    """Parse a file path or code string into an AST tree.

    Args:
        source_or_path: A file path or string containing Python source code.

    Returns:
        ast.AST: Parsed module AST.
    """
    path = Path(source_or_path)
    if path.is_file():
        source_code = path.read_text(encoding="utf-8")
        return ast.parse(source_code, filename=str(path))
    
    # Treat as raw Python code string
    return ast.parse(str(source_or_path), filename="<inline>")


def extract_parameters(args_node: ast.arguments) -> list[ParamInfo]:
    """Extract ordered parameter metadata from an ast.arguments node."""
    params: list[ParamInfo] = []

    num_posonly = len(args_node.posonlyargs)
    num_standard = len(args_node.args)
    total_pos = num_posonly + num_standard
    num_defaults = len(args_node.defaults)
    default_start_idx = total_pos - num_defaults

    # 1. Positional-only parameters
    for idx, arg in enumerate(args_node.posonlyargs):
        has_default = idx >= default_start_idx
        default_val = None
        if has_default:
            def_idx = idx - default_start_idx
            default_val = ast.unparse(args_node.defaults[def_idx])
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        params.append(
            ParamInfo(
                name=arg.arg,
                kind="POSITIONAL_ONLY",
                has_default=has_default,
                default_repr=default_val,
                annotation=ann,
            )
        )

    # 2. Standard positional or keyword parameters
    for idx, arg in enumerate(args_node.args):
        overall_idx = num_posonly + idx
        has_default = overall_idx >= default_start_idx
        default_val = None
        if has_default:
            def_idx = overall_idx - default_start_idx
            default_val = ast.unparse(args_node.defaults[def_idx])
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        params.append(
            ParamInfo(
                name=arg.arg,
                kind="POSITIONAL_OR_KEYWORD",
                has_default=has_default,
                default_repr=default_val,
                annotation=ann,
            )
        )

    # 3. Var positional (*args)
    if args_node.vararg:
        ann = ast.unparse(args_node.vararg.annotation) if args_node.vararg.annotation else None
        params.append(
            ParamInfo(
                name=args_node.vararg.arg,
                kind="VAR_POSITIONAL",
                has_default=False,
                default_repr=None,
                annotation=ann,
            )
        )

    # 4. Keyword-only parameters
    for arg, kw_default in zip(args_node.kwonlyargs, args_node.kw_defaults):
        has_default = kw_default is not None
        default_val = ast.unparse(kw_default) if has_default else None
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        params.append(
            ParamInfo(
                name=arg.arg,
                kind="KEYWORD_ONLY",
                has_default=has_default,
                default_repr=default_val,
                annotation=ann,
            )
        )

    # 5. Var keyword (**kwargs)
    if args_node.kwarg:
        ann = ast.unparse(args_node.kwarg.annotation) if args_node.kwarg.annotation else None
        params.append(
            ParamInfo(
                name=args_node.kwarg.arg,
                kind="VAR_KEYWORD",
                has_default=False,
                default_repr=None,
                annotation=ann,
            )
        )

    return params


def format_signature_str(
    name: str,
    params: list[ParamInfo],
    return_type: Optional[str] = None,
    is_async: bool = False,
) -> str:
    """Build a human-readable Python signature string from parameter metadata."""
    posonly = [p.format() for p in params if p.kind == "POSITIONAL_ONLY"]
    standard = [p.format() for p in params if p.kind == "POSITIONAL_OR_KEYWORD"]
    vararg = next((f"*{p.format()}" for p in params if p.kind == "VAR_POSITIONAL"), None)
    kwonly = [p.format() for p in params if p.kind == "KEYWORD_ONLY"]
    kwarg = next((f"**{p.format()}" for p in params if p.kind == "VAR_KEYWORD"), None)

    parts: list[str] = []
    if posonly:
        parts.extend(posonly)
        parts.append("/")
    parts.extend(standard)
    if vararg:
        parts.append(vararg)
    elif kwonly:
        parts.append("*")
    parts.extend(kwonly)
    if kwarg:
        parts.append(kwarg)

    sig = f"{name}({', '.join(parts)})"
    if return_type:
        sig += f" -> {return_type}"
    prefix = "async def " if is_async else "def "
    return f"{prefix}{sig}"


def get_decorator_names(node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]) -> list[str]:
    """Extract decorator names as strings."""
    decorators = []
    for d in node.decorator_list:
        try:
            decorators.append(ast.unparse(d))
        except Exception:
            if isinstance(d, ast.Name):
                decorators.append(d.id)
            elif isinstance(d, ast.Attribute):
                decorators.append(d.attr)
    return decorators


def extract_public_snapshot(tree: ast.AST, file_path: str = "", module_name: str = "") -> ModuleSnapshot:
    """Extract public functions, classes, and constants from an AST tree.

    Respects `__all__` if defined at the top-level. Otherwise, symbols not
    starting with an underscore `_` are considered public.
    """
    snapshot = ModuleSnapshot(file_path=file_path, module_name=module_name)
    defined_all: Optional[set[str]] = None

    # First pass: look for top-level __all__
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(stmt.value, (ast.List, ast.Tuple)):
                        all_items = []
                        for elt in stmt.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_items.append(elt.value)
                        defined_all = set(all_items)
                        snapshot.all_exports = all_items

    def is_public_name(name: str) -> bool:
        if defined_all is not None:
            return name in defined_all
        return not name.startswith("_")

    # Second pass: extract functions, classes, and constants
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if is_public_name(stmt.name):
                params = extract_parameters(stmt.args)
                ret_type = ast.unparse(stmt.returns) if stmt.returns else None
                is_async = isinstance(stmt, ast.AsyncFunctionDef)
                sig = format_signature_str(stmt.name, params, ret_type, is_async)
                docstring = ast.get_docstring(stmt)
                decorators = get_decorator_names(stmt)

                snapshot.functions[stmt.name] = FunctionInfo(
                    name=stmt.name,
                    line=stmt.lineno,
                    params=params,
                    return_type=ret_type,
                    is_async=is_async,
                    decorators=decorators,
                    docstring=docstring,
                    signature=sig,
                )

        elif isinstance(stmt, ast.ClassDef):
            if is_public_name(stmt.name):
                bases = [ast.unparse(b) for b in stmt.bases]
                decorators = get_decorator_names(stmt)
                docstring = ast.get_docstring(stmt)
                cls_info = ClassInfo(
                    name=stmt.name,
                    line=stmt.lineno,
                    bases=bases,
                    decorators=decorators,
                    docstring=docstring,
                )

                # Extract public methods and public class constants
                for item in stmt.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Public method or special dunder like __init__, __call__, __enter__
                        is_dunder = item.name.startswith("__") and item.name.endswith("__")
                        is_method_public = not item.name.startswith("_") or is_dunder
                        if is_method_public:
                            params = extract_parameters(item.args)
                            ret_type = ast.unparse(item.returns) if item.returns else None
                            is_async = isinstance(item, ast.AsyncFunctionDef)
                            sig = format_signature_str(item.name, params, ret_type, is_async)
                            m_decorators = get_decorator_names(item)
                            m_doc = ast.get_docstring(item)

                            cls_info.methods[item.name] = FunctionInfo(
                                name=item.name,
                                line=item.lineno,
                                params=params,
                                return_type=ret_type,
                                is_async=is_async,
                                decorators=m_decorators,
                                docstring=m_doc,
                                signature=sig,
                            )
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and not target.id.startswith("_"):
                                cls_info.constants[target.id] = item.lineno

                snapshot.classes[stmt.name] = cls_info

        elif isinstance(stmt, ast.Assign):
            # Module-level constants / variables
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    if is_public_name(target.id) and target.id.isupper():
                        snapshot.constants[target.id] = stmt.lineno

    return snapshot


def format_diff_report(diff_result: dict[str, Any], title: str = "SafeDep Breaking Changes Report") -> str:
    """Format the breaking changes dictionary into an attractive, clear terminal report."""
    summary = diff_result.get("summary", {})
    total = summary.get("total", 0)
    has_breaking = diff_result.get("breaking_changes_found", False)

    border = "=" * 70
    sub_border = "-" * 70
    lines = [
        border,
        f"  {title.upper()}",
        border,
        f"Status: {'CRITICAL - BREAKING CHANGES DETECTED' if has_breaking else 'CLEAN - NO BREAKING CHANGES FOUND'}",
        f"Total Breaking Changes: {total}",
        sub_border,
        "SUMMARY BREAKDOWN:",
        f"  * Removed Functions:    {summary.get('removed_functions', 0)}",
        f"  * Removed Classes:      {summary.get('removed_classes', 0)}",
        f"  * Removed Methods:      {summary.get('removed_methods', 0)}",
        f"  * Changed Signatures:   {summary.get('changed_signatures', 0)}",
        f"  * Removed Base Classes: {summary.get('removed_base_classes', 0)}",
        f"  * Removed Constants:    {summary.get('removed_constants', 0)}",
        f"  * Removed Modules:      {summary.get('removed_modules', 0)}",
        sub_border,
    ]

    # Removed functions
    removed_funcs = diff_result.get("removed_functions", [])
    if removed_funcs:
        lines.append("\n[x] REMOVED FUNCTIONS:")
        for fn in removed_funcs:
            module_str = f" in {fn['module']}" if "module" in fn else ""
            lines.append(f"  - {fn['name']} (line {fn.get('line', '?')}{module_str})")
            if fn.get("signature"):
                lines.append(f"    Previous: {fn['signature']}")

    # Removed classes
    removed_classes = diff_result.get("removed_classes", [])
    if removed_classes:
        lines.append("\n[x] REMOVED CLASSES:")
        for cls in removed_classes:
            module_str = f" in {cls['module']}" if "module" in cls else ""
            bases_str = f" (bases: {', '.join(cls.get('bases', []))})" if cls.get("bases") else ""
            lines.append(f"  - {cls['name']}{bases_str} (line {cls.get('line', '?')}{module_str})")

    # Removed methods
    removed_methods = diff_result.get("removed_methods", [])
    if removed_methods:
        lines.append("\n[x] REMOVED CLASS METHODS:")
        for m in removed_methods:
            lines.append(f"  - {m['class_name']}.{m['method_name']} (line {m.get('line', '?')})")
            if m.get("signature"):
                lines.append(f"    Previous: {m['signature']}")

    # Changed signatures
    sig_changes = diff_result.get("changed_signatures", [])
    if sig_changes:
        lines.append("\n[!] CHANGED SIGNATURES (INCOMPATIBLE):")
        for sc in sig_changes:
            target_name = sc.get("name", "unknown")
            sym_type = sc.get("symbol_type", "function")
            lines.append(f"  - [{sym_type.upper()}] {target_name}:")
            lines.append(f"      Old: {sc.get('old_signature')}")
            lines.append(f"      New: {sc.get('new_signature')}")
            for r in sc.get("reasons", []):
                lines.append(f"      -> Reason: {r}")

    # Removed base classes
    removed_bases = diff_result.get("removed_base_classes", [])
    if removed_bases:
        lines.append("\n[!] REMOVED BASE CLASSES:")
        for rb in removed_bases:
            lines.append(f"  - Class '{rb['class_name']}' removed base '{rb['removed_base']}'")

    # Removed constants
    removed_consts = diff_result.get("removed_constants", [])
    if removed_consts:
        lines.append("\n[x] REMOVED MODULE CONSTANTS:")
        for rc in removed_consts:
            lines.append(f"  - {rc['name']} (line {rc.get('line', '?')})")

    # Removed modules
    removed_mods = diff_result.get("removed_modules", [])
    if removed_mods:
        lines.append("\n[x] REMOVED MODULES / FILES:")
        for rm in removed_mods:
            lines.append(f"  - {rm.get('module_name', rm.get('path', 'unknown'))}")

    if not has_breaking:
        lines.append("\n[OK] All public APIs are backward-compatible!")

    lines.append(border)
    return "\n".join(lines)

