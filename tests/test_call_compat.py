"""Unit tests for safedep.call_compat argument-aware matching."""

import pytest
from safedep.call_compat import check_call_compatibility
from safedep.utils import FunctionInfo, ParamInfo


def _make_fn(name: str, params_spec: list[tuple[str, str, bool]]) -> FunctionInfo:
    """Helper to construct FunctionInfo from (name, kind, has_default)."""
    params = [
        ParamInfo(name=pname, kind=pkind, has_default=pdef)
        for pname, pkind, pdef in params_spec
    ]
    sig = f"def {name}({', '.join(p.name for p in params)}):"
    return FunctionInfo(name=name, line=1, params=params, signature=sig)


def test_execute_query_fits_without_timeout():
    """execute_query(sql) fits v2 signature where timeout parameter was removed."""
    # v1: execute_query(sql, timeout=10)
    old_fn = _make_fn("execute_query", [
        ("sql", "POSITIONAL_OR_KEYWORD", False),
        ("timeout", "POSITIONAL_OR_KEYWORD", True),
    ])
    # v2: execute_query(sql)
    new_fn = _make_fn("execute_query", [
        ("sql", "POSITIONAL_OR_KEYWORD", False),
    ])

    call_shape_fits = {
        "positional_args_count": 1,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_shape_fits) == "fits"


def test_execute_query_breaks_with_timeout_kwarg():
    """execute_query(sql, timeout=10) breaks on v2 where timeout was removed."""
    old_fn = _make_fn("execute_query", [
        ("sql", "POSITIONAL_OR_KEYWORD", False),
        ("timeout", "POSITIONAL_OR_KEYWORD", True),
    ])
    new_fn = _make_fn("execute_query", [
        ("sql", "POSITIONAL_OR_KEYWORD", False),
    ])

    call_shape_breaks = {
        "positional_args_count": 1,
        "keyword_args": ["timeout"],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_shape_breaks) == "breaks"


def test_set_notification_channel_default_removed():
    """Removing default breaks calls with no args, but calls with arg fit."""
    # v1: set_notification_channel(channel="email")
    old_fn = _make_fn("set_notification_channel", [
        ("channel", "POSITIONAL_OR_KEYWORD", True),
    ])
    # v2: set_notification_channel(channel)
    new_fn = _make_fn("set_notification_channel", [
        ("channel", "POSITIONAL_OR_KEYWORD", False),
    ])

    call_with_arg = {
        "positional_args_count": 1,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_with_arg) == "fits"

    call_no_arg = {
        "positional_args_count": 0,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_no_arg) == "breaks"


def test_reordered_positional_parameters():
    """Reordered positional parameters break when call passes positionals at those slots."""
    # v1: format_invoice(customer_name, amount)
    old_fn = _make_fn("format_invoice", [
        ("customer_name", "POSITIONAL_OR_KEYWORD", False),
        ("amount", "POSITIONAL_OR_KEYWORD", False),
    ])
    # v2: format_invoice(amount, customer_name)
    new_fn = _make_fn("format_invoice", [
        ("amount", "POSITIONAL_OR_KEYWORD", False),
        ("customer_name", "POSITIONAL_OR_KEYWORD", False),
    ])

    call_positional = {
        "positional_args_count": 2,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_positional) == "breaks"


def test_varargs_and_varkwargs_uncertain():
    """Calls using *args or **kwargs must be reported as uncertain."""
    old_fn = _make_fn("query", [("sql", "POSITIONAL_OR_KEYWORD", False)])
    new_fn = _make_fn("query", [("sql", "POSITIONAL_OR_KEYWORD", False)])

    call_with_star = {
        "positional_args_count": 0,
        "keyword_args": [],
        "has_varargs": True,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_with_star) == "uncertain"

    call_with_starstar = {
        "positional_args_count": 1,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": True,
    }
    assert check_call_compatibility(old_fn, new_fn, call_with_starstar) == "uncertain"


def test_removed_function_always_breaks():
    """Removed functions (new_fn is None) always return 'breaks'."""
    old_fn = _make_fn("legacy_discount", [("amount", "POSITIONAL_OR_KEYWORD", False)])
    call_shape = {
        "positional_args_count": 1,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, None, call_shape) == "breaks"


def test_too_many_positional_args():
    """Passing more positional args than accepted without *args breaks."""
    old_fn = _make_fn("test_fn", [("a", "POSITIONAL_OR_KEYWORD", False)])
    new_fn = _make_fn("test_fn", [("a", "POSITIONAL_OR_KEYWORD", False)])

    call_shape = {
        "positional_args_count": 3,
        "keyword_args": [],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_shape) == "breaks"


def test_unknown_keyword_arg():
    """Passing an unexpected keyword argument without **kwargs breaks."""
    old_fn = _make_fn("test_fn", [("a", "POSITIONAL_OR_KEYWORD", False)])
    new_fn = _make_fn("test_fn", [("a", "POSITIONAL_OR_KEYWORD", False)])

    call_shape = {
        "positional_args_count": 1,
        "keyword_args": ["unexpected_kw"],
        "has_varargs": False,
        "has_varkwargs": False,
    }
    assert check_call_compatibility(old_fn, new_fn, call_shape) == "breaks"
