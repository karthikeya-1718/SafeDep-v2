"""Unit tests for safedep.patcher module."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.patcher import (
    PROVIDERS,
    _ast_fallback_patch,
    _patch_with_deepseek,
    _patch_with_groq,
    get_active_provider,
    propose_patch,
)


class TestAstFallbackPatch(unittest.TestCase):
    """Tests for the deterministic AST rule-based fallback engine."""

    def test_parameter_removal_via_keyword(self):
        """Remove a keyword argument that no longer exists in the new signature."""
        result = _ast_fallback_patch(
            "query(sql, timeout=5)",
            "query: Parameter 'timeout' was removed",
        )
        self.assertEqual(result, "query(sql)")

    def test_parameter_removal_via_old_new_signatures(self):
        """Remove parameter detected by diffing old vs new signature ASTs."""
        result = _ast_fallback_patch(
            "query(sql, timeout=5)",
            "",
            old_signature="def query(sql, timeout=10)",
            new_signature="def query(sql)",
        )
        self.assertEqual(result, "query(sql)")

    def test_positional_reordering(self):
        """Reorder positional arguments based on reordered: [...] -> [...] pattern."""
        result = _ast_fallback_patch(
            "render_template(my_name, my_ctx)",
            "render_template: Positional parameters were reordered: ['name', 'context'] -> ['context', 'name']",
        )
        self.assertEqual(result, "render_template(my_ctx, my_name)")

    def test_added_required_parameter(self):
        """Insert a placeholder for a new required parameter."""
        result = _ast_fallback_patch(
            "fetch_user(user_id)",
            "fetch_user: New required parameter 'api_token' added without a default value",
        )
        self.assertIn("api_token=", result)
        self.assertIn("API_TOKEN", result)

    def test_default_value_removed(self):
        """Insert placeholder when a parameter's default is removed (now required)."""
        result = _ast_fallback_patch(
            "connect()",
            "connect: Default value removed for parameter 'host'",
        )
        self.assertIn("host=", result)

    def test_non_call_expression_returned_unchanged(self):
        """Non-call expressions pass through unchanged."""
        result = _ast_fallback_patch("x + 1", "some change")
        self.assertEqual(result, "x + 1")

    def test_empty_expression_returned_unchanged(self):
        """Empty string passes through unchanged."""
        result = _ast_fallback_patch("", "some change")
        self.assertEqual(result, "")

    def test_unparseable_expression_returned_unchanged(self):
        """Syntactically broken expressions pass through unchanged."""
        result = _ast_fallback_patch("(((broken", "some change")
        self.assertEqual(result, "(((broken")

    def test_no_matching_pattern_unchanged(self):
        """When no rule fires, the original expression is returned."""
        result = _ast_fallback_patch("foo(a, b)", "some unrelated change text")
        self.assertEqual(result, "foo(a, b)")

    def test_positional_reorder_via_signatures(self):
        """Reorder detected via old/new signature diff (AST strategy 1)."""
        result = _ast_fallback_patch(
            "process(old_first, old_second)",
            "",
            old_signature="def process(x, y)",
            new_signature="def process(y, x)",
        )
        self.assertEqual(result, "process(old_second, old_first)")


class TestProposePatch(unittest.TestCase):
    """Tests for the public propose_patch() entry-point."""

    def setUp(self):
        # Ensure clean environment for each test
        self._orig_env = os.environ.copy()
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_delegates_to_ast_fallback_without_api_key(self):
        """Without an API key, propose_patch uses the AST engine."""
        result = propose_patch(
            code_snippet="query(sql, timeout=5)",
            breaking_change_info={"breaking_change": "Parameter 'timeout' was removed"},
        )
        self.assertEqual(result, "query(sql)")

    def test_accepts_old_new_signature(self):
        """propose_patch forwards old_signature/new_signature to the AST engine."""
        result = propose_patch(
            code_snippet="fetch(uid, timeout=10)",
            breaking_change_info={
                "breaking_change": "",
                "old_signature": "def fetch(uid, timeout=10)",
                "new_signature": "def fetch(uid)",
            },
        )
        self.assertEqual(result, "fetch(uid)")

    def test_passes_code_context_to_deepseek(self):
        """propose_patch correctly bundles code_context into the DeepSeek payload."""
        captured: dict = {}

        def fake_deepseek(call_expression, breaking_change, old_signature, new_signature, code_context, api_key, model):
            captured["code_context"] = code_context
            return call_expression  # echo unchanged

        with patch("safedep.patcher._patch_with_deepseek", side_effect=fake_deepseek):
            propose_patch(
                code_snippet="foo()",
                breaking_change_info={
                    "breaking_change": "x",
                    "code_context": "def bar():\n    foo()\n",
                },
            )

        self.assertIn("def bar", captured["code_context"])

    def test_returns_deepseek_result_when_api_key_present(self):
        """When the DeepSeek API responds, propose_patch returns that result."""
        mock_resp_data = b'{"choices": [{"message": {"content": "fixed_call()"}}]}'

        mock_response = MagicMock()
        mock_response.read.return_value = mock_resp_data
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = propose_patch(
                code_snippet="broken_call(old_param=1)",
                breaking_change_info={"breaking_change": "Parameter 'old_param' was removed"},
                api_key="fake-key-xyz",
            )

        self.assertEqual(result, "fixed_call()")

    def test_falls_back_to_ast_when_deepseek_fails(self):
        """When the DeepSeek network call raises, the AST engine is used instead."""
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = propose_patch(
                code_snippet="query(sql, timeout=5)",
                breaking_change_info={"breaking_change": "Parameter 'timeout' was removed"},
                api_key="fake-key-xyz",
            )

        self.assertEqual(result, "query(sql)")

    def test_strips_markdown_fences_from_deepseek_response(self):
        """propose_patch strips ```python ... ``` blocks from the API response."""
        mock_resp_data = b'{"choices": [{"message": {"content": "```python\\nfixed()\\n```"}}]}'

        mock_response = MagicMock()
        mock_response.read.return_value = mock_resp_data
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = propose_patch(
                code_snippet="broken()",
                breaking_change_info={"breaking_change": "something"},
                api_key="fake-key",
            )

        self.assertEqual(result, "fixed()")


class TestMultiProviderSupport(unittest.TestCase):
    """Tests for Groq and DeepSeek provider selection and execution."""

    def setUp(self):
        self._orig_env = os.environ.copy()
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_groq_used_when_groq_api_key_set(self):
        """When GROQ_API_KEY is present, Groq endpoint and llama model are used."""
        os.environ["GROQ_API_KEY"] = "gsk_test123"

        captured_req: dict = {}

        def mock_urlopen(req, timeout=15):
            captured_req["url"] = req.full_url
            captured_req["auth"] = req.headers.get("Authorization")
            payload = json.loads(req.data.decode("utf-8"))
            captured_req["model"] = payload["model"]

            resp = MagicMock()
            resp.read.return_value = b'{"choices": [{"message": {"content": "groq_fixed()"}}]}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            res = propose_patch(
                code_snippet="old_func()",
                breaking_change_info={"breaking_change": "some change"},
            )

        self.assertEqual(res, "groq_fixed()")
        self.assertEqual(captured_req["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(captured_req["auth"], "Bearer gsk_test123")
        self.assertEqual(captured_req["model"], "llama-3.3-70b-versatile")

    def test_groq_custom_model_option(self):
        """Groq respects custom models such as openai/gpt-oss-20b."""
        os.environ["GROQ_API_KEY"] = "gsk_test123"

        captured_model = []

        def mock_urlopen(req, timeout=15):
            payload = json.loads(req.data.decode("utf-8"))
            captured_model.append(payload["model"])
            resp = MagicMock()
            resp.read.return_value = b'{"choices": [{"message": {"content": "fixed()"}}]}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            propose_patch(
                code_snippet="old_func()",
                breaking_change_info={"breaking_change": "some change"},
                model="openai/gpt-oss-20b",
            )

        self.assertEqual(captured_model[0], "openai/gpt-oss-20b")

    def test_groq_preferred_over_deepseek_when_both_keys_present(self):
        """When both GROQ_API_KEY and DEEPSEEK_API_KEY are set, Groq takes precedence."""
        os.environ["GROQ_API_KEY"] = "gsk_groq"
        os.environ["DEEPSEEK_API_KEY"] = "ds_deepseek"

        captured_url = []

        def mock_urlopen(req, timeout=15):
            captured_url.append(req.full_url)
            resp = MagicMock()
            resp.read.return_value = b'{"choices": [{"message": {"content": "fixed()"}}]}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            propose_patch("call()", {"breaking_change": "change"})

        self.assertEqual(captured_url[0], "https://api.groq.com/openai/v1/chat/completions")

    def test_deepseek_used_when_only_deepseek_key_present(self):
        """When only DEEPSEEK_API_KEY is present, DeepSeek is used."""
        os.environ["DEEPSEEK_API_KEY"] = "ds_deepseek"

        captured_url = []

        def mock_urlopen(req, timeout=15):
            captured_url.append(req.full_url)
            resp = MagicMock()
            resp.read.return_value = b'{"choices": [{"message": {"content": "fixed()"}}]}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            propose_patch("call()", {"breaking_change": "change"})

        self.assertEqual(captured_url[0], "https://api.deepseek.com/chat/completions")

    def test_groq_falls_back_to_ast_on_network_error(self):
        """When Groq network request fails, it falls back to the AST engine."""
        import urllib.error

        os.environ["GROQ_API_KEY"] = "gsk_test123"

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection reset")):
            result = propose_patch(
                code_snippet="query(sql, timeout=5)",
                breaking_change_info={"breaking_change": "Parameter 'timeout' was removed"},
            )

        self.assertEqual(result, "query(sql)")

    def test_explicit_provider_override(self):
        """Passing provider='deepseek' explicitly overrides GROQ_API_KEY."""
        os.environ["GROQ_API_KEY"] = "gsk_groq"
        os.environ["DEEPSEEK_API_KEY"] = "ds_deepseek"

        captured_url = []

        def mock_urlopen(req, timeout=15):
            captured_url.append(req.full_url)
            resp = MagicMock()
            resp.read.return_value = b'{"choices": [{"message": {"content": "fixed()"}}]}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            propose_patch("call()", {"breaking_change": "change"}, provider="deepseek")

        self.assertEqual(captured_url[0], "https://api.deepseek.com/chat/completions")


class TestBackwardsCompatShims(unittest.TestCase):
    """Verify the shim functions in pre_install_repair still work after refactor."""

    def test_generate_fallback_patch_shim(self):
        """generate_fallback_patch() shim in pre_install_repair delegates correctly."""
        from safedep.pre_install_repair import generate_fallback_patch

        result = generate_fallback_patch("query(sql, timeout=5)", "Parameter 'timeout' was removed")
        self.assertEqual(result, "query(sql)")

    def test_generate_patch_with_deepseek_shim_no_key(self):
        """generate_patch_with_deepseek() without API key falls back to AST engine."""
        from safedep.pre_install_repair import generate_patch_with_deepseek

        result = generate_patch_with_deepseek(
            "fetch_user(uid, timeout=10)",
            "",
            old_signature="def fetch_user(uid, timeout=10)",
            new_signature="def fetch_user(uid)",
        )
        self.assertEqual(result, "fetch_user(uid)")


if __name__ == "__main__":
    unittest.main()
