"""Tests verifying that the offline guard fixture is active during every test run."""

from __future__ import annotations

import os

import pytest

from safedep.patcher import get_active_provider


def test_no_api_keys_in_environment():
    """Inside any test, neither GROQ_API_KEY nor DEEPSEEK_API_KEY must be present."""
    assert "GROQ_API_KEY" not in os.environ, (
        "GROQ_API_KEY leaked into test environment. "
        "The conftest.py offline guard should have removed it."
    )
    assert "DEEPSEEK_API_KEY" not in os.environ, (
        "DEEPSEEK_API_KEY leaked into test environment. "
        "The conftest.py offline guard should have removed it."
    )


def test_patcher_selects_no_remote_provider():
    """With no API keys present, get_active_provider must report no remote provider."""
    active_provider, resolved_key = get_active_provider()
    assert active_provider is None, (
        f"Expected no remote provider, but got '{active_provider}'. "
        "A real API key may have leaked into the environment."
    )
    assert resolved_key is None, (
        f"Expected no resolved key, but got a key. "
        "A real API key may have leaked into the environment."
    )
