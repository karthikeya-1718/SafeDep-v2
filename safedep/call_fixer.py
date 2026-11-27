"""SafeDep Call Fixer Module (R2 rules).

Provides deterministic, source-span-based fixes for call sites affected by
library signature changes:
  - Removed keyword parameter  → drop it from the call
  - Parameter lost default, call omits it → restore old default as keyword arg
  - New required parameter (no default) → resolve via R3; if unresolved → manual
  - Reordered positionals → reorder args in source
  - star-args present → review (uncertain)
  - Removal → manual

No external imports; standard library only.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FixResult:
    """Result of attempting to fix a single call site."""

    status: str  # "applied" | "manual" | "review" | "failed"
    new_call_bytes: Optional[bytes]  # bytes of the replacement call expression, or None
    reason: str  # human-readable reason


# ---------------------------------------------------------------------------
# R3 — Value resolver
# ---------------------------------------------------------------------------


def resolve_value(
    param_name: str,
    caller_name: str,
    file_path: str,
    project_path: str,
) -> Optional[str]:
    """Attempt to resolve a suitable expression for *param_name* at *caller_name*.

    Strategy (R3):
      (a) Enclosing function's own parameters — return the param name directly.
      (b) Module-level variable with the same name — return the variable name.
      (c) `from X import Y` / `import X` where Y (or X) exposes an attribute
          named param_name inside the imported file → return 'Y.param_name'.

    Returns the expression string, or None if nothing was found.
    """
    try:
        source = Path(file_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=file_path)
    except Exception:
        return None

    # (a) Enclosing function parameter
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == caller_name:
                for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                    if arg.arg.lower() == param_name.lower():
                        return arg.arg
                if node.args.vararg and node.args.vararg.arg.lower() == param_name.lower():
                    return node.args.vararg.arg
                if node.args.kwarg and node.args.kwarg.arg.lower() == param_name.lower():
                    return node.args.kwarg.arg

    # (b) Module-level variable
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.lower() == param_name.lower():
                    return target.id
                if isinstance(target, ast.Attribute) and target.attr.lower() == param_name.lower():
                    try:
                        return ast.unparse(target)
                    except Exception:
                        pass
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.lower() == param_name.lower():
                return node.target.id

    # (c) Imports — search imported file for attribute
    file_dir = Path(file_path).parent
    proj_root = Path(project_path)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                # Try to find the imported file
                mod_parts = node.module.split(".")
                mod_name = alias.name

                # Look for the imported module file
                candidates = _find_module_file(mod_parts + [mod_name], file_dir, proj_root)
                candidates += _find_module_file(mod_parts, file_dir, proj_root)

                for cand in candidates:
                    attr = _find_module_attribute(cand, param_name)
                    if attr:
                        return f"{local_name}.{attr}"

        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                mod_parts = alias.name.split(".")
                candidates = _find_module_file(mod_parts, file_dir, proj_root)
                for cand in candidates:
                    attr = _find_module_attribute(cand, param_name)
                    if attr:
                        return f"{local_name}.{attr}"

    return None


def _find_module_file(
    parts: list[str], file_dir: Path, proj_root: Path
) -> list[Path]:
    """Return candidate file paths for an import chain (best-effort)."""
    candidates = []
    # Search bases: file_dir, proj_root, parent of proj_root, grandparent
    bases = [file_dir, proj_root]
    curr = proj_root
    for _ in range(3):
        if curr.parent != curr:
            curr = curr.parent
            if curr not in bases:
                bases.append(curr)

    for base in bases:
        p = base
        for part in parts:
            p = p / part
        # Try as package __init__.py
        init = p / "__init__.py"
        if init.is_file():
            candidates.append(init)
        # Try as direct module
        mod = p.with_suffix(".py")
        if mod.is_file():
            candidates.append(mod)
    return candidates


def _find_module_attribute(file_path: Path, attr_name: str) -> Optional[str]:
    """Return the exact name of *attr_name* if defined at module level in *file_path*."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.lower() == attr_name.lower():
                    return target.id
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.lower() == attr_name.lower():
                return node.target.id
    return None


# ---------------------------------------------------------------------------
# Source-span helpers
# ---------------------------------------------------------------------------


def _lines_to_byte_offsets(source_bytes: bytes) -> list[int]:
    """Return byte offset of the start of each 1-based line number."""
    offsets = [0]  # line 1 starts at byte 0
    for byte in source_bytes:
        if byte == ord("\n"):
            offsets.append(offsets[-1] + 1)
        else:
            offsets[-1] += 1
    # Rebuild properly: cumulative
    offsets2 = [0]
    pos = 0
    for byte_val in source_bytes:
        pos += 1
        if byte_val == ord(b"\n"):
            offsets2.append(pos)
    return offsets2


def apply_span_edit(
    source_bytes: bytes,
    line: int,
    col_offset: int,
    end_line: int,
    end_col_offset: int,
    new_call_bytes: bytes,
) -> bytes:
    """Replace [line:col_offset, end_line:end_col_offset) in source_bytes with new_call_bytes.

    Lines are 1-based; col offsets are 0-based byte positions within the
    UTF-8 encoded line (which is what Python's AST reports in 3.8+).
    """
    # Split into individual lines (keeping line endings)
    raw_lines: list[bytes] = []
    start = 0
    for i, b in enumerate(source_bytes):
        if b == ord("\n"):
            raw_lines.append(source_bytes[start:i + 1])
            start = i + 1
    if start < len(source_bytes):
        raw_lines.append(source_bytes[start:])

    # Convert 1-based line + 0-based byte col to absolute byte offsets
    def line_col_to_abs(ln: int, col: int) -> int:
        abs_off = 0
        for idx in range(ln - 1):
            abs_off += len(raw_lines[idx]) if idx < len(raw_lines) else 0
        abs_off += col
        return abs_off

    start_abs = line_col_to_abs(line, col_offset)
    end_abs = line_col_to_abs(end_line, end_col_offset)

    return source_bytes[:start_abs] + new_call_bytes + source_bytes[end_abs:]


# ---------------------------------------------------------------------------
# Quote preservation helpers
# ---------------------------------------------------------------------------


def _unparse_preserving_quotes(node: ast.expr, orig_bytes: bytes, start_abs: int, end_abs: int) -> bytes:
    """Return the bytes for a single argument, preferring original source bytes."""
    # We use the original bytes when possible (preserves quote style)
    if hasattr(node, "lineno") and hasattr(node, "col_offset") and \
       hasattr(node, "end_lineno") and hasattr(node, "end_col_offset") and \
       node.end_lineno is not None:
        return orig_bytes[start_abs:end_abs]
    try:
        return ast.unparse(node).encode("utf-8")
    except Exception:
        return b""


# ---------------------------------------------------------------------------
# Core fix logic (R2)
# ---------------------------------------------------------------------------


def fix_call(
    site: dict[str, Any],
    breaking_change_entry: dict[str, Any],
    source_bytes: bytes,
) -> FixResult:
    """Generate a fix for a single call site according to R2 rules.

    Args:
        site: Call site dict (from call_graph.get_affected_call_sites).
        breaking_change_entry: Changed-signature entry from api_diff (may include
            old_fn / new_fn as FunctionInfo, old_signature / new_signature as str).
        source_bytes: Raw UTF-8 bytes of the file containing the call.

    Returns:
        FixResult with status ∈ {"applied", "manual", "review", "failed"}.
    """
    # --- Extract call shape ---
    has_varargs: bool = site.get("has_varargs", False)
    has_varkwargs: bool = site.get("has_varkwargs", False)
    is_removal: bool = site.get("is_removal", False)
    callee: str = str(site.get("callee_name") or site.get("function_name", ""))
    caller: str = str(site.get("caller_name") or site.get("caller", "<module>"))
    file_path: str = str(site.get("file_path", ""))
    line: int = int(site.get("line_number") or site.get("line", 0))
    col: int = int(site.get("col_offset", 0))
    end_line: int = int(site.get("end_line") or line)
    end_col: int = int(site.get("end_col_offset", 0))
    kw_names: list[str] = list(site.get("keyword_args", []))
    pos_count: int = int(site.get("positional_args_count", 0))

    # R2 rule 1: varargs/varkwargs → review
    if has_varargs or has_varkwargs:
        return FixResult(status="review", new_call_bytes=None, reason="call contains *args or **kwargs")

    # R2 rule 2: removal → manual
    if is_removal:
        return FixResult(status="manual", new_call_bytes=None, reason=f"{callee} was removed — manual replacement required")

    # Try to get old/new FunctionInfo
    old_fn = breaking_change_entry.get("old_fn")
    new_fn = breaking_change_entry.get("new_fn")

    # Also parse from signature strings if FunctionInfo not available
    if old_fn is None:
        old_sig_str = breaking_change_entry.get("old_signature", "")
        if old_sig_str:
            old_fn = _parse_sig_to_params(old_sig_str, callee)
    if new_fn is None:
        new_sig_str = breaking_change_entry.get("new_signature", "")
        if new_sig_str:
            new_fn = _parse_sig_to_params(new_sig_str, callee)

    if new_fn is None:
        # Can't determine new signature; nothing to fix
        return FixResult(status="applied", new_call_bytes=source_bytes[_abs_range(source_bytes, line, col, end_line, end_col)[0]:_abs_range(source_bytes, line, col, end_line, end_col)[1]], reason="no signature info")

    # Parse the actual call node from source
    call_node, orig_call_bytes = _parse_call_node(source_bytes, line, col, end_line, end_col, callee)
    if call_node is None or orig_call_bytes is None:
        return FixResult(status="failed", new_call_bytes=None, reason="could not parse call node from source")

    # Get old/new param lists
    old_params = _get_params(old_fn) if old_fn else []
    new_params = _get_params(new_fn) if new_fn else []

    # Check for star-arg in call args
    if any(isinstance(a, ast.Starred) for a in call_node.args):
        return FixResult(status="review", new_call_bytes=None, reason="call contains starred positional arg")
    if any(kw.arg is None for kw in call_node.keywords):
        return FixResult(status="review", new_call_bytes=None, reason="call contains **kwargs spread")

    old_param_names = [p["name"] for p in old_params if p["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")]
    new_param_names = [p["name"] for p in new_params if p["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")]
    old_param_map = {p["name"]: p for p in old_params}
    new_param_map = {p["name"]: p for p in new_params}

    changes_applied = False
    args_list = list(call_node.args)  # positional args (ast.expr nodes)
    kwargs_list = list(call_node.keywords)  # keyword args (ast.keyword nodes)

    # --- R2 rule 3: Removed keyword parameter (old has it, new doesn't) ---
    removed_kw_params = {
        p["name"] for p in old_params
        if p["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")
        and p["name"] not in new_param_map
    }
    new_kwargs = []
    for kw in kwargs_list:
        if kw.arg in removed_kw_params:
            changes_applied = True
            # drop it
        else:
            new_kwargs.append(kw)
    kwargs_list = new_kwargs

    # --- R2 rule 4: Parameter lost default, call omits it ---
    # Find params that were optional in old sig but are now required, and are not in call
    for p in new_params:
        if p["kind"] in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            continue
        pname = p["name"]
        if p["has_default"]:
            continue  # still has default, no issue
        old_p = old_param_map.get(pname)
        if old_p is None:
            continue  # new param — handled below
        if not old_p["has_default"]:
            continue  # was already required

        # Was optional (had default) in old, now required (no default) in new
        # Check if call already supplies this param
        pindex = [i for i, pp in enumerate(new_params) if pp["name"] == pname and pp["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")]
        pos_index = pindex[0] if pindex else -1

        supplied_positionally = pos_index >= 0 and pos_index < len(args_list)
        supplied_as_keyword = any(kw.arg == pname for kw in kwargs_list)

        if not supplied_positionally and not supplied_as_keyword:
            # Add old default as keyword arg
            old_default = old_p.get("default_repr", "")
            if old_default:
                # Build a fake keyword node
                fake_kw = ast.keyword(arg=pname, value=ast.Constant(value=None))
                # We'll store the raw text
                new_kw_text = f"{pname}={old_default}"
                kwargs_list.append(("RAW", new_kw_text))
                changes_applied = True

    # --- R2 rule 5: New required parameter (in new sig, not in old, no default) ---
    for p in new_params:
        if p["kind"] in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            continue
        pname = p["name"]
        if p["has_default"]:
            continue
        if pname in old_param_map:
            continue  # was in old sig

        # Truly new required param — not in old sig at all
        supplied_as_keyword = any(
            (kw.arg == pname if isinstance(kw, ast.keyword) else kw[1].startswith(f"{pname}="))
            for kw in kwargs_list
        )
        pindex = [i for i, pp in enumerate(new_params) if pp["name"] == pname and pp["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")]
        pos_index = pindex[0] if pindex else -1
        supplied_positionally = pos_index >= 0 and pos_index < len(args_list)

        if not supplied_positionally and not supplied_as_keyword:
            # Try R3
            project_path = str(Path(file_path).parent)
            resolved = resolve_value(pname, caller, file_path, project_path)
            if resolved is not None:
                new_kw_text = f"{pname}={resolved}"
                kwargs_list.append(("RAW", new_kw_text))
                changes_applied = True
            else:
                return FixResult(status="manual", new_call_bytes=None, reason=f"new required parameter '{pname}' could not be resolved")

    # --- R2 rule 6: Reordered positionals ---
    old_pos_params = [p for p in old_params if p["kind"] in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    new_pos_params = [p for p in new_params if p["kind"] in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]

    if old_pos_params and new_pos_params and len(args_list) >= 2:
        # Build old index → name map
        old_names = [p["name"] for p in old_pos_params]
        new_names = [p["name"] for p in new_pos_params]

        # Check if any positional arg position maps differently
        common_names = [n for n in old_names if n in new_names]
        old_order = [n for n in old_names if n in common_names]
        new_order = [n for n in new_names if n in common_names]

        if old_order != new_order and len(args_list) >= 2:
            # Need to reorder: map old positions → arg nodes, rearrange to new order
            # Only reorder args up to len(common_names)
            limit = min(len(args_list), len(old_names), len(new_names))
            if limit >= 2:
                # Build mapping: for each position in new order, find which old position has that name
                old_name_to_idx = {name: i for i, name in enumerate(old_names)}
                new_reordered = []
                any_reorder = False
                for new_i, new_name in enumerate(new_names[:limit]):
                    old_i = old_name_to_idx.get(new_name, new_i)
                    if old_i < len(args_list):
                        new_reordered.append(args_list[old_i])
                        if old_i != new_i:
                            any_reorder = True
                    else:
                        new_reordered.append(args_list[new_i] if new_i < len(args_list) else args_list[old_i])

                if any_reorder:
                    # Keep trailing args beyond limit unchanged
                    args_list = new_reordered + list(args_list[limit:])
                    changes_applied = True

    # --- Reconstruct call bytes ---
    if not changes_applied:
        return FixResult(status="applied", new_call_bytes=orig_call_bytes, reason="no changes needed")

    # Reconstruct the call expression
    new_call = _reconstruct_call(call_node, args_list, kwargs_list, source_bytes)
    if new_call is None:
        return FixResult(status="failed", new_call_bytes=None, reason="could not reconstruct call")

    return FixResult(status="applied", new_call_bytes=new_call, reason="fix applied")


# ---------------------------------------------------------------------------
# Helpers for fix_call
# ---------------------------------------------------------------------------


def _abs_range(source_bytes: bytes, line: int, col: int, end_line: int, end_col: int) -> tuple[int, int]:
    """Convert line/col positions to absolute byte offsets."""
    raw_lines: list[bytes] = []
    start = 0
    for i, b in enumerate(source_bytes):
        if b == ord("\n"):
            raw_lines.append(source_bytes[start:i + 1])
            start = i + 1
    if start < len(source_bytes):
        raw_lines.append(source_bytes[start:])

    def to_abs(ln: int, co: int) -> int:
        abs_off = sum(len(raw_lines[i]) for i in range(min(ln - 1, len(raw_lines))))
        return abs_off + co

    return to_abs(line, col), to_abs(end_line, end_col)


def _parse_call_node(
    source_bytes: bytes,
    line: int,
    col: int,
    end_line: int,
    end_col: int,
    callee: str,
) -> tuple[Optional[ast.Call], Optional[bytes]]:
    """Parse the AST Call node at the given source span."""
    try:
        source_str = source_bytes.decode("utf-8", errors="replace")
        tree = ast.parse(source_str)
    except SyntaxError:
        return None, None

    start_abs, end_abs = _abs_range(source_bytes, line, col, end_line, end_col)
    orig_call_bytes = source_bytes[start_abs:end_abs]

    # Walk tree to find matching Call node
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if node.lineno == line and node.col_offset == col:
                return node, orig_call_bytes
            # Try matching by callee name too
            if node.lineno == line:
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name == callee and node.col_offset == col:
                    return node, orig_call_bytes

    # Fallback: look for any call on the same line matching callee
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.lineno == line:
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name == callee:
                # Recalculate orig bytes with this node's actual col offsets
                n_start, n_end = _abs_range(source_bytes, node.lineno, node.col_offset,
                                             node.end_lineno or node.lineno,
                                             node.end_col_offset or node.col_offset)
                return node, source_bytes[n_start:n_end]

    return None, orig_call_bytes


def _reconstruct_call(
    orig_node: ast.Call,
    new_args: list,
    new_kwargs: list,
    source_bytes: bytes,
) -> Optional[bytes]:
    """Reconstruct the call expression bytes from modified arg/kwarg lists."""
    try:
        # Get the function expression (prefix) from original source bytes
        source_str = source_bytes.decode("utf-8", errors="replace")
        # Get the function part (before the opening paren)
        func_start_abs, _ = _abs_range(
            source_bytes,
            orig_node.lineno, orig_node.col_offset,
            orig_node.end_lineno or orig_node.lineno,
            orig_node.end_col_offset or orig_node.col_offset,
        )
        # Find the opening paren
        orig_call_bytes = source_bytes[
            func_start_abs:
            _abs_range(source_bytes,
                       orig_node.end_lineno or orig_node.lineno,
                       orig_node.end_col_offset or orig_node.col_offset,
                       orig_node.end_lineno or orig_node.lineno,
                       orig_node.end_col_offset or orig_node.col_offset,
            )[0]
        ]
        func_bytes = _get_func_bytes(orig_node, source_bytes)

        # Build argument bytes
        arg_parts = []
        for arg in new_args:
            if isinstance(arg, ast.expr):
                # Preserve original source bytes for this arg
                a_start, a_end = _abs_range(
                    source_bytes,
                    arg.lineno, arg.col_offset,
                    arg.end_lineno or arg.lineno,
                    arg.end_col_offset or arg.col_offset,
                )
                arg_parts.append(source_bytes[a_start:a_end])
            else:
                # Shouldn't happen
                arg_parts.append(str(arg).encode("utf-8"))

        for kw in new_kwargs:
            if isinstance(kw, tuple) and kw[0] == "RAW":
                arg_parts.append(kw[1].encode("utf-8"))
            elif isinstance(kw, ast.keyword):
                if kw.arg is None:
                    # **kwargs
                    v_start, v_end = _abs_range(
                        source_bytes,
                        kw.value.lineno, kw.value.col_offset,
                        kw.value.end_lineno or kw.value.lineno,
                        kw.value.end_col_offset or kw.value.col_offset,
                    )
                    arg_parts.append(b"**" + source_bytes[v_start:v_end])
                else:
                    v_start, v_end = _abs_range(
                        source_bytes,
                        kw.value.lineno, kw.value.col_offset,
                        kw.value.end_lineno or kw.value.lineno,
                        kw.value.end_col_offset or kw.value.col_offset,
                    )
                    arg_parts.append(kw.arg.encode("utf-8") + b"=" + source_bytes[v_start:v_end])

        # Detect indentation/whitespace style (single-line vs multi-line)
        result = func_bytes + b"(" + b", ".join(arg_parts) + b")"
        return result

    except Exception:
        return None


def _get_func_bytes(orig_node: ast.Call, source_bytes: bytes) -> bytes:
    """Extract the function expression bytes (before the '(')."""
    try:
        # The call node's col_offset marks the start of the entire call expression
        # including the function reference.  Find the opening '(' by scanning forward
        # from the call node's position.
        start_abs, end_abs = _abs_range(
            source_bytes,
            orig_node.lineno, orig_node.col_offset,
            orig_node.end_lineno or orig_node.lineno,
            orig_node.end_col_offset or orig_node.col_offset,
        )
        # The function part is from start_abs up to the first '(' (tracking nesting)
        raw = source_bytes[start_abs:end_abs]
        # Find first '('
        paren_pos = raw.index(b"(")
        return raw[:paren_pos]
    except Exception:
        # Fallback: unparse the func attribute
        try:
            return ast.unparse(orig_node.func).encode("utf-8")
        except Exception:
            return b""


def _parse_sig_to_params(sig_str: str, func_name: str) -> Optional[list]:
    """Parse a function signature string into a list of param dicts."""
    clean = sig_str.strip()
    if not clean.startswith("def ") and not clean.startswith("async def "):
        if clean.endswith(":"):
            clean = f"def {clean} pass"
        else:
            clean = f"def {clean}: pass"
    else:
        if clean.endswith(":"):
            clean = f"{clean} pass"
        else:
            clean = f"{clean}: pass"
    try:
        tree = ast.parse(clean)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return _extract_param_dicts(node.args)
    except Exception:
        pass
    return None


def _get_params(fn_obj: Any) -> list[dict]:
    """Normalize a FunctionInfo (or list) to a list of param dicts."""
    if fn_obj is None:
        return []
    # If it's already a list of dicts
    if isinstance(fn_obj, list):
        return fn_obj
    # If it's a FunctionInfo-like object with .params
    if hasattr(fn_obj, "params"):
        params = fn_obj.params
        result = []
        for p in params:
            if hasattr(p, "name"):
                result.append({
                    "name": p.name,
                    "kind": getattr(p, "kind", "POSITIONAL_OR_KEYWORD"),
                    "has_default": getattr(p, "has_default", False),
                    "default_repr": getattr(p, "default_repr", None),
                })
            elif isinstance(p, dict):
                result.append(p)
        return result
    return []


def _extract_param_dicts(args: ast.arguments) -> list[dict]:
    """Convert ast.arguments to a list of param dicts."""
    params = []

    def _default_map(arg_list: list, defaults: list, offset: int = 0) -> dict:
        """Map arg index to default node (right-aligned)."""
        n = len(arg_list)
        nd = len(defaults)
        return {n - nd + i + offset: d for i, d in enumerate(defaults)}

    # positional-only
    po_defaults = _default_map(args.posonlyargs, args.defaults[:len(args.posonlyargs)] if args.posonlyargs else [])
    for i, arg in enumerate(args.posonlyargs):
        params.append({
            "name": arg.arg,
            "kind": "POSITIONAL_ONLY",
            "has_default": i in po_defaults,
            "default_repr": ast.unparse(po_defaults[i]) if i in po_defaults else None,
        })

    # positional-or-keyword
    n_po = len(args.posonlyargs)
    n_pk = len(args.args)
    # defaults are right-aligned across posonlyargs + args
    all_pos = args.posonlyargs + args.args
    all_defaults_map = {len(all_pos) - len(args.defaults) + i: d for i, d in enumerate(args.defaults)}
    for i, arg in enumerate(args.args):
        abs_i = n_po + i
        params.append({
            "name": arg.arg,
            "kind": "POSITIONAL_OR_KEYWORD",
            "has_default": abs_i in all_defaults_map,
            "default_repr": ast.unparse(all_defaults_map[abs_i]) if abs_i in all_defaults_map else None,
        })

    # *args
    if args.vararg:
        params.append({
            "name": args.vararg.arg,
            "kind": "VAR_POSITIONAL",
            "has_default": False,
            "default_repr": None,
        })

    # keyword-only
    kw_defaults = {i: d for i, d in enumerate(args.kw_defaults) if d is not None}
    for i, arg in enumerate(args.kwonlyargs):
        params.append({
            "name": arg.arg,
            "kind": "KEYWORD_ONLY",
            "has_default": i in kw_defaults,
            "default_repr": ast.unparse(kw_defaults[i]) if i in kw_defaults else None,
        })

    # **kwargs
    if args.kwarg:
        params.append({
            "name": args.kwarg.arg,
            "kind": "VAR_KEYWORD",
            "has_default": False,
            "default_repr": None,
        })

    return params


# ---------------------------------------------------------------------------
# patch_file
# ---------------------------------------------------------------------------


def patch_file(
    file_path: str,
    sites: list[dict[str, Any]],
    breaking_changes: dict[str, Any],
    project_path: str,
) -> list[FixResult]:
    """Apply fixes to all call sites in a file using bottom-up span editing.

    Args:
        file_path: Path to the Python source file.
        sites: List of call site dicts (from get_affected_call_sites).
        breaking_changes: api_diff result dict.
        project_path: Root path of the client project.

    Returns:
        List of FixResult, one per site in input order.
    """
    source_bytes = Path(file_path).read_bytes()
    original_bytes = source_bytes

    # Build a map from callee → breaking_change_entry
    bc_map = _build_breaking_change_map(breaking_changes)

    # Sort sites bottom-up (highest line first, then highest col)
    indexed_sites = list(enumerate(sites))
    sorted_indexed = sorted(
        indexed_sites,
        key=lambda x: (-(x[1].get("line_number") or x[1].get("line") or 0),
                       -(x[1].get("col_offset") or 0)),
    )

    results: list[Optional[FixResult]] = [None] * len(sites)

    for orig_idx, site in sorted_indexed:
        callee = str(site.get("callee_name") or site.get("function_name", ""))
        bc_entry = bc_map.get(callee, {})

        result = fix_call(site, bc_entry, source_bytes)
        results[orig_idx] = result

        if result.status == "applied" and result.new_call_bytes is not None:
            line = int(site.get("line_number") or site.get("line") or 0)
            col = int(site.get("col_offset", 0))
            end_line = int(site.get("end_line") or line)
            end_col = int(site.get("end_col_offset", 0))

            orig_start, orig_end = _abs_range(source_bytes, line, col, end_line, end_col)
            orig_call = source_bytes[orig_start:orig_end]

            if result.new_call_bytes == orig_call:
                # No actual change — don't modify source
                pass
            else:
                source_bytes = apply_span_edit(
                    source_bytes, line, col, end_line, end_col, result.new_call_bytes
                )

    # Validate result is parseable Python
    try:
        ast.parse(source_bytes.decode("utf-8", errors="replace"))
    except SyntaxError as exc:
        # Restore original and mark all as failed
        Path(file_path).write_bytes(original_bytes)
        return [
            FixResult(status="failed", new_call_bytes=None, reason=f"SyntaxError after edit: {exc}")
            for _ in sites
        ]

    # Write patched bytes
    if source_bytes != original_bytes:
        Path(file_path).write_bytes(source_bytes)

    # Fill in any None results (shouldn't happen)
    for i in range(len(results)):
        if results[i] is None:
            results[i] = FixResult(status="failed", new_call_bytes=None, reason="unknown error")

    return results  # type: ignore[return-value]


def _build_breaking_change_map(breaking_changes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a name → breaking_change_entry mapping from api_diff output."""
    bc_map: dict[str, dict[str, Any]] = {}
    if not isinstance(breaking_changes, dict):
        return bc_map
    for sig in breaking_changes.get("changed_signatures", []):
        if isinstance(sig, dict) and "name" in sig:
            name = sig["name"]
            bc_map[name] = sig
            if "." in name:
                bc_map[name.split(".")[-1]] = sig
    for fn in breaking_changes.get("removed_functions", []):
        if isinstance(fn, dict) and "name" in fn:
            bc_map[fn["name"]] = {"is_removal": True, **fn}
    return bc_map
