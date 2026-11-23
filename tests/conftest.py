"""Session-scoped offline guards for the entire test suite.

Every test runs with:
  1. GROQ_API_KEY and DEEPSEEK_API_KEY removed from os.environ so that
     safedep.patcher never selects a remote AI provider by accident.
  2. urllib.request.urlopen patched to raise RuntimeError so that any
     accidental live network call fails loudly instead of hitting a real
     API endpoint.

Tests that intentionally exercise the HTTP path (e.g. test_patcher.py) already
wrap their own `patch("urllib.request.urlopen", ...)` context managers.  Those
context-manager patches are applied *inside* the test body, after this fixture
has set up its own patch.  unittest.mock.patch is re-entrant and innermost wins,
so test-level patches override this fixture's block without any conflict.
"""

from __future__ import annotations

import urllib.request
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    """Remove real API keys and block live network calls for every test."""
    # 1. Strip API keys so get_active_provider() returns (None, None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    # 2. Block urllib.request.urlopen so accidental live calls fail loudly.
    #    Tests that need to simulate HTTP responses supply their own
    #    patch("urllib.request.urlopen", ...) context manager inside the test
    #    body; that inner patch takes precedence over this one.
    def _no_network(request, **kwargs):  # noqa: ARG001
        raise RuntimeError(
            "Network call attempted in test suite. "
            "Mock urllib.request.urlopen in your test to simulate HTTP responses."
        )

    with patch("urllib.request.urlopen", side_effect=_no_network):
        yield
