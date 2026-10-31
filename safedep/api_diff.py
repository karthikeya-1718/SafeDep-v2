"""SafeDep API Diff Module.

Uses Python's ast module to extract public functions and classes
from two versions of a Python file or directory, and detects breaking changes:
- Removed public functions
- Removed public classes
- Removed public class methods
- Incompatible signature changes (added required params, removed params,
  reordered positional params, removed defaults, parameter kind changes)
- Removed class base classes
- Removed public module constants
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Union

from .utils import (
    ClassInfo,
    FunctionInfo,
    ModuleSnapshot,
    ParamInfo,
    extract_public_snapshot,
    parse_source_to_ast,
)


def compare_signatures(
    old_fn: FunctionInfo,
    new_fn: FunctionInfo,
    is_method: bool = False,
    is_static: bool = False,
) -> list[str]:
    """Compare two function/method signatures and return a list of breaking reasons.

    If the change is backward-compatible (e.g. adding an optional parameter with default,
    adding *args or **kwargs), returns an empty list.
    """
    reasons: list[str] = []

    # Decorator-level breaking changes for methods
    if is_method:
        old_is_prop = "property" in old_fn.decorators
        new_is_prop = "property" in new_fn.decorators
        if old_is_prop and not new_is_prop:
            reasons.append(f"Method '{old_fn.name}' changed from @property to regular method")
        elif not old_is_prop and new_is_prop:
            reasons.append(f"Method '{old_fn.name}' changed from regular method to @property")

        old_is_static = "staticmethod" in old_fn.decorators
        new_is_static = "staticmethod" in new_fn.decorators
        if old_is_static and not new_is_static:
            reasons.append(f"Method '{old_fn.name}' changed from @staticmethod to instance method")

    # For standard instance/class methods, strip the receiver parameter (self/cls)
    # when comparing caller-facing signatures, unless it's a staticmethod.
    if is_method and not is_static:
        old_params = old_fn.params[1:] if old_fn.params else []
        new_params = new_fn.params[1:] if new_fn.params else []
    else:
        old_params = old_fn.params
        new_params = new_fn.params

    old_map = {p.name: p for p in old_params}
    new_map = {p.name: p for p in new_params}

    old_vararg = next((p for p in old_params if p.kind == "VAR_POSITIONAL"), None)
    new_vararg = next((p for p in new_params if p.kind == "VAR_POSITIONAL"), None)

    old_kwarg = next((p for p in old_params if p.kind == "VAR_KEYWORD"), None)
    new_kwarg = next((p for p in new_params if p.kind == "VAR_KEYWORD"), None)

    # 1. Removed parameters (excluding *args, **kwargs)
    for p in old_params:
        if p.kind in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            continue
        if p.name not in new_map:
            reasons.append(f"Parameter '{p.name}' was removed")

    # 2. Removed *args
    if old_vararg and not new_vararg:
        reasons.append(f"Variable positional parameter '*{old_vararg.name}' was removed")

    # 3. Removed **kwargs
    if old_kwarg and not new_kwarg:
        reasons.append(f"Variable keyword parameter '**{old_kwarg.name}' was removed")

    # 4. Added required parameter without a default value
    for p in new_params:
        if p.kind in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            continue
        if p.name not in old_map:
            if not p.has_default:
                reasons.append(f"New required parameter '{p.name}' added without a default value")

    # 5. Default value removed from an existing parameter (making it required)
    for name, p_old in old_map.items():
        if name in new_map:
            p_new = new_map[name]
            if p_old.has_default and not p_new.has_default:
                reasons.append(f"Default value removed for parameter '{name}', making it required")

    # 6. Parameter kind changes that break callers
    for name, p_old in old_map.items():
        if name in new_map:
            p_new = new_map[name]
            if p_old.kind == "POSITIONAL_OR_KEYWORD" and p_new.kind == "KEYWORD_ONLY":
                reasons.append(f"Parameter '{name}' changed from positional-or-keyword to keyword-only")
            elif p_old.kind == "POSITIONAL_OR_KEYWORD" and p_new.kind == "POSITIONAL_ONLY":
                reasons.append(f"Parameter '{name}' changed from positional-or-keyword to positional-only")
            elif p_old.kind == "KEYWORD_ONLY" and p_new.kind == "POSITIONAL_ONLY":
                reasons.append(f"Parameter '{name}' changed from keyword-only to positional-only")

    # 7. Positional parameter reordering
    old_pos = [p.name for p in old_params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    new_pos = [p.name for p in new_params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    common_pos = [p for p in old_pos if p in new_pos]

    if [p for p in new_pos if p in common_pos] != common_pos:
        reasons.append(f"Positional parameters were reordered: {old_pos} -> {new_pos}")
    else:
        # Check if an existing parameter shifted position due to newly inserted preceding parameter
        for p in common_pos:
            old_idx = old_pos.index(p)
            new_idx = new_pos.index(p)
            if new_idx > old_idx:
                reasons.append(
                    f"Positional parameter '{p}' shifted from index {old_idx} to index {new_idx} by preceding parameter"
                )
                break

    return reasons


def compare_classes(
    old_cls: ClassInfo,
    new_cls: ClassInfo,
    module_name: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare two class definitions for removed methods, changed signatures, and removed bases."""
    removed_methods: list[dict[str, Any]] = []
    changed_signatures: list[dict[str, Any]] = []
    removed_bases: list[dict[str, Any]] = []

    # Check removed methods
    for m_name, m_info in old_cls.methods.items():
        if m_name not in new_cls.methods:
            removed_methods.append({
                "class_name": old_cls.name,
                "method_name": m_name,
                "line": m_info.line,
                "signature": m_info.signature,
                "module": module_name,
                "description": f"Public method '{old_cls.name}.{m_name}' was removed",
            })

    # Check changed method signatures
    for m_name, m_old in old_cls.methods.items():
        if m_name in new_cls.methods:
            m_new = new_cls.methods[m_name]
            old_is_static = "staticmethod" in m_old.decorators
            reasons = compare_signatures(m_old, m_new, is_method=True, is_static=old_is_static)
            if reasons:
                changed_signatures.append({
                    "symbol_type": "method",
                    "name": f"{old_cls.name}.{m_name}",
                    "class_name": old_cls.name,
                    "method_name": m_name,
                    "old_signature": m_old.signature,
                    "new_signature": m_new.signature,
                    "old_line": m_old.line,
                    "new_line": m_new.line,
                    "module": module_name,
                    "reasons": reasons,
                })

    # Check removed base classes
    for b in old_cls.bases:
        if b not in new_cls.bases:
            removed_bases.append({
                "class_name": old_cls.name,
                "removed_base": b,
                "old_bases": old_cls.bases,
                "new_bases": new_cls.bases,
                "module": module_name,
                "description": f"Base class '{b}' was removed from class '{old_cls.name}'",
            })

    return removed_methods, changed_signatures, removed_bases


def compare_modules(
    old_mod: ModuleSnapshot,
    new_mod: ModuleSnapshot,
) -> dict[str, Any]:
    """Compare two module snapshots and return breaking changes."""
    removed_functions: list[dict[str, Any]] = []
    removed_classes: list[dict[str, Any]] = []
    removed_methods: list[dict[str, Any]] = []
    changed_signatures: list[dict[str, Any]] = []
    removed_bases: list[dict[str, Any]] = []
    removed_constants: list[dict[str, Any]] = []

    mod_name = old_mod.module_name

    # 1. Removed functions
    for f_name, f_info in old_mod.functions.items():
        if f_name not in new_mod.functions:
            removed_functions.append({
                "name": f_name,
                "line": f_info.line,
                "signature": f_info.signature,
                "module": mod_name,
                "description": f"Public function '{f_name}' was removed",
            })

    # 2. Removed classes
    for c_name, c_info in old_mod.classes.items():
        if c_name not in new_mod.classes:
            removed_classes.append({
                "name": c_name,
                "line": c_info.line,
                "bases": c_info.bases,
                "module": mod_name,
                "description": f"Public class '{c_name}' was removed",
            })

    # 3. Changed function signatures
    for f_name, f_old in old_mod.functions.items():
        if f_name in new_mod.functions:
            f_new = new_mod.functions[f_name]
            reasons = compare_signatures(f_old, f_new, is_method=False)
            if reasons:
                changed_signatures.append({
                    "symbol_type": "function",
                    "name": f_name,
                    "old_signature": f_old.signature,
                    "new_signature": f_new.signature,
                    "old_line": f_old.line,
                    "new_line": f_new.line,
                    "module": mod_name,
                    "reasons": reasons,
                })

    # 4. Classes common to both versions
    for c_name, c_old in old_mod.classes.items():
        if c_name in new_mod.classes:
            c_new = new_mod.classes[c_name]
            r_meths, c_sigs, r_bases = compare_classes(c_old, c_new, module_name=mod_name)
            removed_methods.extend(r_meths)
            changed_signatures.extend(c_sigs)
            removed_bases.extend(r_bases)

    # 5. Removed constants
    for c_name, c_line in old_mod.constants.items():
        if c_name not in new_mod.constants:
            removed_constants.append({
                "name": c_name,
                "line": c_line,
                "module": mod_name,
                "description": f"Public module-level constant '{c_name}' was removed",
            })

    return {
        "removed_functions": removed_functions,
        "removed_classes": removed_classes,
        "removed_methods": removed_methods,
        "changed_signatures": changed_signatures,
        "removed_base_classes": removed_bases,
        "removed_constants": removed_constants,
    }


def _find_py_files(directory: Path) -> dict[str, Path]:
    """Find all public python files in a directory recursively, mapped to relative path string."""
    py_files: dict[str, Path] = {}
    for root, dirs, files in os.walk(directory):
        # Exclude hidden or cache directories
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv", "build", "dist")]
        for file in files:
            if file.endswith(".py"):
                full_path = Path(root) / file
                rel_path = str(full_path.relative_to(directory)).replace("\\", "/")
                # Ignore private internal modules (unless it's __init__.py)
                file_base = full_path.stem
                if file_base.startswith("_") and not (file_base.startswith("__") and file_base.endswith("__")):
                    continue
                py_files[rel_path] = full_path
    return py_files


def get_breaking_changes(
    old_path: Union[str, Path],
    new_path: Union[str, Path],
) -> dict[str, Any]:
    """Analyze two versions of Python code and return a dictionary of breaking changes.

    Uses Python's ast module to extract public functions and classes from both versions.
    Accepts either two Python file paths or two directory paths.

    Args:
        old_path: Path to the original (older) file or directory.
        new_path: Path to the new (updated) file or directory.

    Returns:
        dict: A clear dictionary containing:
            - breaking_changes_found (bool): True if breaking changes are detected
            - summary (dict): Total counts of each breaking change category
            - breaking_changes (list[str]): Human-readable descriptions of all breaking changes
            - removed_functions (list[dict])
            - removed_classes (list[dict])
            - removed_methods (list[dict])
            - changed_signatures (list[dict])
            - removed_base_classes (list[dict])
            - removed_constants (list[dict])
            - removed_modules (list[dict])
    """
    old_p = Path(old_path)
    new_p = Path(new_path)

    if not old_p.exists():
        raise FileNotFoundError(f"SafeDep: Old path does not exist: {old_path}")
    if not new_p.exists():
        raise FileNotFoundError(f"SafeDep: New path does not exist: {new_path}")

    removed_functions: list[dict[str, Any]] = []
    removed_classes: list[dict[str, Any]] = []
    removed_methods: list[dict[str, Any]] = []
    changed_signatures: list[dict[str, Any]] = []
    removed_base_classes: list[dict[str, Any]] = []
    removed_constants: list[dict[str, Any]] = []
    removed_modules: list[dict[str, Any]] = []

    if old_p.is_file() and new_p.is_file():
        old_tree = parse_source_to_ast(old_p)
        new_tree = parse_source_to_ast(new_p)

        old_mod = extract_public_snapshot(old_tree, file_path=str(old_p), module_name=old_p.stem)
        new_mod = extract_public_snapshot(new_tree, file_path=str(new_p), module_name=new_p.stem)

        diff = compare_modules(old_mod, new_mod)
        removed_functions.extend(diff["removed_functions"])
        removed_classes.extend(diff["removed_classes"])
        removed_methods.extend(diff["removed_methods"])
        changed_signatures.extend(diff["changed_signatures"])
        removed_base_classes.extend(diff["removed_base_classes"])
        removed_constants.extend(diff["removed_constants"])

    elif old_p.is_dir() and new_p.is_dir():
        old_files = _find_py_files(old_p)
        new_files = _find_py_files(new_p)

        # Removed modules/files
        for rel_path, file_path in old_files.items():
            if rel_path not in new_files:
                removed_modules.append({
                    "path": rel_path,
                    "module_name": Path(rel_path).stem,
                    "description": f"Module '{rel_path}' was removed",
                })
                # Everything public inside that removed module was also removed
                tree = parse_source_to_ast(file_path)
                mod = extract_public_snapshot(tree, file_path=str(file_path), module_name=Path(rel_path).stem)
                for fn in mod.functions.values():
                    removed_functions.append({
                        "name": fn.name,
                        "line": fn.line,
                        "signature": fn.signature,
                        "module": rel_path,
                        "description": f"Public function '{fn.name}' in removed module '{rel_path}' was removed",
                    })
                for cls in mod.classes.values():
                    removed_classes.append({
                        "name": cls.name,
                        "line": cls.line,
                        "bases": cls.bases,
                        "module": rel_path,
                        "description": f"Public class '{cls.name}' in removed module '{rel_path}' was removed",
                    })

        # Compare modules present in both
        for rel_path, old_file_path in old_files.items():
            if rel_path in new_files:
                new_file_path = new_files[rel_path]
                old_tree = parse_source_to_ast(old_file_path)
                new_tree = parse_source_to_ast(new_file_path)

                old_mod = extract_public_snapshot(old_tree, file_path=str(old_file_path), module_name=rel_path)
                new_mod = extract_public_snapshot(new_tree, file_path=str(new_file_path), module_name=rel_path)

                diff = compare_modules(old_mod, new_mod)
                removed_functions.extend(diff["removed_functions"])
                removed_classes.extend(diff["removed_classes"])
                removed_methods.extend(diff["removed_methods"])
                changed_signatures.extend(diff["changed_signatures"])
                removed_base_classes.extend(diff["removed_base_classes"])
                removed_constants.extend(diff["removed_constants"])

    else:
        raise ValueError(
            f"SafeDep: Cannot compare mismatched paths. Both paths must be files or both directories. "
            f"(old: {'dir' if old_p.is_dir() else 'file'}, new: {'dir' if new_p.is_dir() else 'file'})"
        )

    # Flatten descriptions for quick inspection
    flat_descriptions: list[str] = []
    for fn in removed_functions:
        flat_descriptions.append(f"[REMOVED FUNCTION] {fn['description']}")
    for cls in removed_classes:
        flat_descriptions.append(f"[REMOVED CLASS] {cls['description']}")
    for m in removed_methods:
        flat_descriptions.append(f"[REMOVED METHOD] {m['description']}")
    for sc in changed_signatures:
        for r in sc["reasons"]:
            flat_descriptions.append(f"[CHANGED SIGNATURE] {sc['name']}: {r}")
    for rb in removed_base_classes:
        flat_descriptions.append(f"[REMOVED BASE CLASS] {rb['description']}")
    for rc in removed_constants:
        flat_descriptions.append(f"[REMOVED CONSTANT] {rc['description']}")
    for rm in removed_modules:
        flat_descriptions.append(f"[REMOVED MODULE] {rm['description']}")

    total_breaking = len(flat_descriptions)

    return {
        "breaking_changes_found": total_breaking > 0,
        "summary": {
            "total": total_breaking,
            "removed_functions": len(removed_functions),
            "removed_classes": len(removed_classes),
            "removed_methods": len(removed_methods),
            "changed_signatures": len(changed_signatures),
            "removed_base_classes": len(removed_base_classes),
            "removed_constants": len(removed_constants),
            "removed_modules": len(removed_modules),
        },
        "breaking_changes": flat_descriptions,
        "removed_functions": removed_functions,
        "removed_classes": removed_classes,
        "removed_methods": removed_methods,
        "changed_signatures": changed_signatures,
        "removed_base_classes": removed_base_classes,
        "removed_constants": removed_constants,
        "removed_modules": removed_modules,
    }

