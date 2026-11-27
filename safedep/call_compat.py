"""SafeDep Call Compatibility Module.

Performs argument-aware matching between call sites and updated function signatures.
Evaluates whether a specific call expression still fits the new library signature,
definitively breaks, or is uncertain (e.g. dynamic *args / **kwargs).
"""

from __future__ import annotations

import ast
from typing import Any, Optional, Union

from .utils import FunctionInfo, ParamInfo, parse_source_to_ast


def _signature_to_function_info(sig: Union[str, FunctionInfo, dict[str, Any]]) -> Optional[FunctionInfo]:
    """Convert a signature string, dict, or FunctionInfo into a normalized FunctionInfo."""
    if sig is None:
        return None
    if isinstance(sig, FunctionInfo):
        return sig
    if isinstance(sig, dict):
        if "fn_info" in sig and isinstance(sig["fn_info"], FunctionInfo):
            return sig["fn_info"]
        if "new_fn" in sig and isinstance(sig["new_fn"], FunctionInfo):
            return sig["new_fn"]
        if "old_fn" in sig and isinstance(sig["old_fn"], FunctionInfo):
            return sig["old_fn"]
        sig_str = sig.get("signature") or sig.get("new_signature") or sig.get("old_signature")
        if sig_str:
            return _parse_sig_str(sig_str, sig.get("name", "func"))
        return None
    if isinstance(sig, str):
        return _parse_sig_str(sig, "func")
    return None


def _parse_sig_str(sig_str: str, default_name: str = "func") -> Optional[FunctionInfo]:
    """Parse a Python function signature string into FunctionInfo using AST."""
    clean = sig_str.strip()
    if not clean.startswith("def ") and not clean.startswith("async def "):
        if clean.endswith(":"):
            clean = f"def {clean} pass"
        else:
            clean = f"def {clean}: pass"
    elif not clean.endswith(":"):
        clean = f"{clean}: pass"

    try:
        tree = ast.parse(clean)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                from .utils import extract_parameters
                params = extract_parameters(node.args)
                return FunctionInfo(
                    name=node.name or default_name,
                    line=1,
                    params=params,
                    signature=sig_str,
                )
    except Exception:
        pass
    return None


def check_call_compatibility(
    old_fn: Union[FunctionInfo, str, dict[str, Any], None],
    new_fn: Union[FunctionInfo, str, dict[str, Any], None],
    call_shape: Union[Any, dict[str, Any]],
) -> str:
    """Evaluate whether a call site's arguments fit the updated function signature.

    Args:
        old_fn: The previous function signature or metadata.
        new_fn: The new function signature or metadata (None if removed).
        call_shape: CallSite object or dict with positional_args_count, keyword_args,
            has_varargs, and has_varkwargs.

    Returns:
        One of "breaks", "fits", or "uncertain".
    """
    # 1. Normalize call shape attributes
    if hasattr(call_shape, "has_varargs"):
        has_varargs = getattr(call_shape, "has_varargs", False)
        has_varkwargs = getattr(call_shape, "has_varkwargs", False)
        pos_count = getattr(call_shape, "positional_args_count", 0)
        kw_names = list(getattr(call_shape, "keyword_args", []))
    elif isinstance(call_shape, dict):
        has_varargs = call_shape.get("has_varargs", False)
        has_varkwargs = call_shape.get("has_varkwargs", False)
        pos_count = call_shape.get("positional_args_count", 0)
        kw_names = list(call_shape.get("keyword_args", []))
    else:
        has_varargs = False
        has_varkwargs = False
        pos_count = 0
        kw_names = []

    pos_arg_names = getattr(call_shape, "pos_arg_names", None)
    if pos_arg_names is None and isinstance(call_shape, dict):
        pos_arg_names = call_shape.get("pos_arg_names")

    caller_param_names = getattr(call_shape, "caller_param_names", None)
    if caller_param_names is None and isinstance(call_shape, dict):
        caller_param_names = call_shape.get("caller_param_names")

    # 2. Dynamic args/kwargs -> uncertain
    if has_varargs or has_varkwargs:
        return "uncertain"

    # 3. Removed functions/classes/methods stay 'breaks' with no argument check
    if new_fn is None:
        return "breaks"

    new_info = _signature_to_function_info(new_fn)
    if new_info is None:
        # If new signature could not be parsed, default to breaks for safety
        return "breaks"

    old_info = _signature_to_function_info(old_fn)

    # 4. Classify new parameters
    pos_params = [p for p in new_info.params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    allowed_kw_names = {p.name for p in new_info.params if p.kind in ("POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY")}
    has_var_pos = any(p.kind == "VAR_POSITIONAL" for p in new_info.params)
    has_var_kw = any(p.kind == "VAR_KEYWORD" for p in new_info.params)

    # 5. Too many positional arguments
    if not has_var_pos and pos_count > len(pos_params):
        return "breaks"

    # 6. Unknown keyword arguments
    if not has_var_kw:
        for kw in kw_names:
            if kw not in allowed_kw_names:
                return "breaks"

    # 7. Reordered positional parameters
    if old_info is not None:
        old_pos = [p.name for p in old_info.params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
        new_pos = [p.name for p in new_info.params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
        common_pos = [p for p in old_pos if p in new_pos]
        if [p for p in new_pos if p in common_pos] != common_pos:
            # Check if positional arguments passed reach any mismatched parameter position
            limit = min(pos_count, len(old_pos), len(new_pos))
            # If we know the caller variable names, check if they match the new order!
            if pos_arg_names and len(pos_arg_names) >= limit and all(n is not None for n in pos_arg_names[:limit]):
                # If caller's passed variables map to the old parameters in order (e.g. customer_name, total where old was customer_name, amount)
                # then passing them in that old order breaks! But if they are passed in the new order, it fits!
                # Specifically, check if the passed argument names match the new parameter names or old parameter names:
                def _name_match(arg_n, param_n):
                    a = arg_n.lower()
                    p = param_n.lower()
                    return a in p or p in a or (a.startswith("total") and "amount" in p) or (a.startswith("amount") and "total" in p)

                all_match_new = all(_name_match(pos_arg_names[i], new_pos[i]) for i in range(limit))
                all_match_old = all(_name_match(pos_arg_names[i], old_pos[i]) for i in range(limit))

                if all_match_new and not all_match_old:
                    pass
                else:
                    return "breaks"
            else:
                for i in range(limit):
                    if old_pos[i] != new_pos[i]:
                        return "breaks"

    # 8. Bind arguments to new parameters and check for missing required parameters
    bound_params: set[str] = set()
    for i in range(min(pos_count, len(pos_params))):
        bound_params.add(pos_params[i].name)

    for kw in kw_names:
        if kw in bound_params:
            # Multiple values supplied for the same parameter
            return "breaks"
        bound_params.add(kw)

    for p in new_info.params:
        if p.kind in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            continue
        if not p.has_default and p.name not in bound_params:
            return "breaks"

    return "fits"
