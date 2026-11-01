"""SafeDep Patcher Module.

Provides a single public entry-point for generating code patches that fix
API breaking-change call sites. Supported strategies (in priority order):

1. **Groq API** (remote, checked first via ``GROQ_API_KEY``) — uses fast
   inference models such as ``llama-3.3-70b-versatile`` or ``openai/gpt-oss-20b``.
2. **DeepSeek API** (remote, checked second via ``DEEPSEEK_API_KEY`` or explicit
   key) — uses ``deepseek-chat``.
3. **AST rule-based fallback** (offline, deterministic) — handles common
   signature-change patterns using Python's ``ast`` module when no API key
   is configured or when remote network calls fail.

Usage::

    from safedep.patcher import propose_patch

    fixed = propose_patch(
        code_snippet="fetch_user(user_id, timeout=30)",
        breaking_change_info={
            "breaking_change": "Parameter 'timeout' was removed",
            "old_signature": "def fetch_user(user_id, timeout=10)",
            "new_signature": "def fetch_user(user_id)",
        },
    )
    # fixed == "fetch_user(user_id)"
"""

from __future__ import annotations

import ast
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Load .env file — supports both d:\AIML_Project\.env and SafeDep/.env
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Load environment variables from the nearest .env file.

    Search order (stops at the first .env found):
    1. SafeDep project root  → ``SafeDep/.env``
    2. Parent workspace root → ``d:/AIML_Project/.env``

    Uses python-dotenv when available; silently skips loading when the
    package is not installed (all other functionality is unaffected).
    """
    try:
        from dotenv import load_dotenv  # type: ignore[import]
    except ImportError:
        return  # python-dotenv not installed — skip silently

    # Walk upward from this file (safedep/patcher.py) to find .env
    search_dirs = [
        Path(__file__).resolve().parent.parent,          # SafeDep/
        Path(__file__).resolve().parent.parent.parent,   # d:\AIML_Project\
    ]
    for directory in search_dirs:
        env_file = directory / ".env"
        if env_file.is_file():
            load_dotenv(dotenv_path=env_file, override=False)  # don't overwrite real env vars
            break


_load_dotenv()


# ---------------------------------------------------------------------------
# Provider Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for an OpenAI-compatible LLM provider."""

    name: str
    endpoint: str
    default_model: str
    env_var: str


PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        default_model="llama-3.3-70b-versatile",
        env_var="GROQ_API_KEY",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        default_model="deepseek-chat",
        env_var="DEEPSEEK_API_KEY",
    ),
}


def get_active_provider(
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Determine the active LLM provider and resolved API key.

    Checks:
    1. Explicit provider argument (if given).
    2. GROQ_API_KEY environment variable (or gsk_ prefixed key).
    3. DEEPSEEK_API_KEY environment variable (or default DeepSeek key).

    Returns:
        tuple of (provider_name, api_key_or_none)
    """
    if provider:
        p = provider.lower()
        env_var = PROVIDERS[p].env_var if p in PROVIDERS else ""
        key = api_key or (os.environ.get(env_var) if env_var else None)
        return p, key

    # 1. First check for GROQ_API_KEY environment variable
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key or (api_key and api_key.startswith("gsk_")):
        return "groq", api_key or groq_key

    # 2. Check for DEEPSEEK_API_KEY environment variable
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if deepseek_key:
        return "deepseek", api_key or deepseek_key

    if api_key:
        return "deepseek", api_key

    return None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def propose_patch(
    code_snippet: str,
    breaking_change_info: dict[str, Any],
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
    provider: Optional[str] = None,
) -> str:
    """Propose a patched replacement for a broken call-site expression.

    Checks for Groq API first (via ``GROQ_API_KEY``), then DeepSeek API
    (via ``DEEPSEEK_API_KEY``), and falls back to the deterministic AST
    engine when no key is present or remote calls fail.

    Args:
        code_snippet: The original call expression that needs to be fixed,
            e.g. ``"fetch_user(uid, timeout=30)"``.
        breaking_change_info: A dictionary describing the change. Recognised
            keys (all optional):

            * ``"breaking_change"`` – human-readable description of the change.
            * ``"old_signature"``   – old ``def ...`` signature string.
            * ``"new_signature"``   – new ``def ...`` signature string.
            * ``"code_context"``    – surrounding source lines for richer AI
              prompts.
            * ``"suggested_fix"``   – optional explicit replacement for fallback.

        api_key: Explicit API key override.
        model: Model name. Defaults to ``"deepseek-chat"`` (automatically maps to
            ``"llama-3.3-70b-versatile"`` when Groq is the active provider unless
            a custom model is specified).
        provider: Explicit provider override (``"groq"`` or ``"deepseek"``).

    Returns:
        The fixed call expression string, or *code_snippet* unchanged when no
        patch can be generated.
    """
    breaking_change = str(breaking_change_info.get("breaking_change", ""))
    suggested_fix = breaking_change_info.get("suggested_fix")
    if suggested_fix and "[SUGGESTED_FIX]" not in breaking_change:
        breaking_change = f"{breaking_change} [SUGGESTED_FIX] {suggested_fix}".strip()

    old_signature = breaking_change_info.get("old_signature")
    new_signature = breaking_change_info.get("new_signature")
    code_context = str(breaking_change_info.get("code_context", ""))

    # Explicit empty string forces AST engine (used by shims)
    if api_key == "":
        return _ast_fallback_patch(
            call_expression=code_snippet,
            breaking_change=breaking_change,
            old_signature=old_signature,
            new_signature=new_signature,
        )

    # Determine provider and key
    active_provider, resolved_key = get_active_provider(api_key=api_key, provider=provider)

    if active_provider == "groq":
        groq_model = (
            PROVIDERS["groq"].default_model
            if model == "deepseek-chat" or not model
            else model
        )
        return _patch_with_groq(
            call_expression=code_snippet,
            breaking_change=breaking_change,
            old_signature=old_signature,
            new_signature=new_signature,
            code_context=code_context,
            api_key=resolved_key,
            model=groq_model,
        )

    # 2. Otherwise default to DeepSeek path (checks key or falls back to AST)
    ds_model = model or PROVIDERS["deepseek"].default_model
    return _patch_with_deepseek(
        call_expression=code_snippet,
        breaking_change=breaking_change,
        old_signature=old_signature,
        new_signature=new_signature,
        code_context=code_context,
        api_key=resolved_key,
        model=ds_model,
    )


# ---------------------------------------------------------------------------
# Remote LLM Execution Helpers
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are SafeDep's automated Python code refactoring engine.\n"
    "Your sole task is to rewrite a single broken Python call expression or statement to make it compatible with an updated library API.\n"
    "CRITICAL CONSTRAINTS:\n"
    "1. Return ONLY the single replacement Python expression or statement.\n"
    "2. Do NOT output markdown formatting, backticks, explanations, comments, or quotes.\n"
    "3. Keep all unchanged arguments and expressions exactly as they were.\n"
    "4. If an existing argument/parameter was renamed or changed to keyword-only, update the keyword name (e.g. from priority=1 to level=1) and preserve its passed value.\n"
    "5. Ensure the output is valid Python code that can directly replace the original call."
)


def _build_refactor_prompt(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
    code_context: str = "",
) -> str:
    """Construct the standardized refactoring prompt."""
    parts = [
        f"API Breaking Change: {breaking_change}",
        f"Original Call Expression: {call_expression}",
    ]
    if old_signature:
        parts.append(f"Old API Signature: {old_signature}")
    if new_signature:
        parts.append(f"New API Signature: {new_signature}")
    if code_context:
        parts.append(f"Surrounding Code Context:\n{code_context}")

    parts.append(
        "Instruction: Rewrite the original call expression to adhere to the new API signature. "
        "Return ONLY the single fixed Python call expression or statement. Nothing else."
    )
    return "\n".join(parts)


def _clean_model_response(raw_text: str) -> str:
    """Clean and extract single Python statement from LLM response."""
    cleaned = raw_text.strip()
    # Remove markdown code blocks if any
    cleaned = re.sub(r"^```(?:python)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
    # Strip any accidental wrapping quotes if the whole line is quoted
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        inner = cleaned[1:-1].strip()
        if "(" in inner and ")" in inner:
            cleaned = inner
    return cleaned


def _execute_chat_completion(
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float = 15.0,
    system_prompt: str = _SYSTEM_PROMPT,
) -> Optional[str]:
    """Execute an OpenAI-compatible chat completion HTTP request."""
    models_to_try = [model]
    # If using Groq and the default model llama-3.3-70b-versatile is decommissioned or unavailable,
    # gracefully fall back to the top available open-weights models on Groq
    if "groq.com" in endpoint and model == "llama-3.3-70b-versatile":
        for fallback_m in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"):
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "SafeDep/0.5.0",
    }

    for m in models_to_try:
        req_payload = {
            "model": m,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(req_payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                result_text = resp_json["choices"][0]["message"]["content"]
                cleaned = _clean_model_response(result_text)
                if cleaned:
                    return cleaned
        except urllib.error.HTTPError as err:
            # If 404 or 400 (model decommissioned/not found), try next model candidate in list
            if err.code in (400, 404) and len(models_to_try) > 1:
                continue
            pass
        except Exception:
            pass

    return None


def _call_groq_sdk(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str = _SYSTEM_PROMPT,
    timeout: float = 15.0,
) -> Optional[str]:
    """Execute completion using official `groq` package if installed."""
    try:
        import groq  # type: ignore[import]
    except ImportError:
        return None

    models_to_try = [model]
    if model == "llama-3.3-70b-versatile":
        for fallback_m in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"):
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

    try:
        client = groq.Groq(api_key=api_key, timeout=timeout)
        for m in models_to_try:
            try:
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    model=m,
                    temperature=0.0,
                )
                if chat_completion.choices and chat_completion.choices[0].message.content:
                    return _clean_model_response(chat_completion.choices[0].message.content)
            except Exception as e:
                status = getattr(e, "status_code", None)
                if status in (400, 404) and len(models_to_try) > 1:
                    continue
                break
    except Exception:
        pass

    return None


def _patch_with_groq(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
    code_context: str = "",
    api_key: Optional[str] = None,
    model: str = "llama-3.3-70b-versatile",
) -> str:
    """Request a refactoring patch using Groq's API.
    
    Tries the official `groq` SDK first if available, then urllib HTTP request,
    and falls back to the deterministic AST engine.
    """
    effective_key = api_key or os.environ.get("GROQ_API_KEY")
    if effective_key:
        prompt = _build_refactor_prompt(
            call_expression=call_expression,
            breaking_change=breaking_change,
            old_signature=old_signature,
            new_signature=new_signature,
            code_context=code_context,
        )
        
        # 1. Prefer official `groq` Python package if available
        # (Skipped if urllib is specifically mocked during testing)
        sdk_res = _call_groq_sdk(
            api_key=effective_key,
            model=model,
            prompt=prompt,
        )
        if sdk_res:
            return sdk_res

        # 2. Pure urllib HTTP fallback (OpenAI-compatible)
        result = _execute_chat_completion(
            endpoint=PROVIDERS["groq"].endpoint,
            api_key=effective_key,
            model=model,
            prompt=prompt,
        )
        if result:
            return result

    # Fallback to AST engine on missing key or network failure
    return _ast_fallback_patch(
        call_expression,
        breaking_change,
        old_signature,
        new_signature,
    )


def _patch_with_deepseek(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
    code_context: str = "",
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
) -> str:
    """Request a refactoring patch using DeepSeek API."""
    effective_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if effective_key:
        prompt = _build_refactor_prompt(
            call_expression=call_expression,
            breaking_change=breaking_change,
            old_signature=old_signature,
            new_signature=new_signature,
            code_context=code_context,
        )
        result = _execute_chat_completion(
            endpoint=PROVIDERS["deepseek"].endpoint,
            api_key=effective_key,
            model=model,
            prompt=prompt,
        )
        if result:
            return result

    # Fallback to AST engine on missing key or network failure
    return _ast_fallback_patch(
        call_expression,
        breaking_change,
        old_signature,
        new_signature,
    )


# ---------------------------------------------------------------------------
# AST rule-based fallback strategy
# ---------------------------------------------------------------------------


def _ast_fallback_patch(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
) -> str:
    """Generate a deterministic rule-based patch for common signature breaking changes.

    Handles the following patterns (in priority order):

    * Explicit suggested fix provided in breaking change info.
    * Old / new signatures provided — compute removed / reordered params via AST diff.
    * ``"Parameter 'x' was removed"`` — strip keyword argument ``x`` from the call.
    * ``"reordered: ['a', 'b'] -> ['b', 'a']"`` — reorder positional args.
    * ``"New required parameter 'x' added"`` — insert ``x=<X>`` placeholder.
    * ``"Default value removed for parameter 'x'"`` — insert ``x=<REQUIRED_VALUE>``.

    Returns *call_expression* unchanged when none of the patterns match.
    """
    # 0. Check for explicit suggested fix tag
    suggest_match = re.search(r"\[(?:SUGGESTED_FIX|REPLACE)\]\s*(.+)$", breaking_change)
    if suggest_match:
        return suggest_match.group(1).strip()

    clean_expr = call_expression.strip()
    if not clean_expr:
        return clean_expr

    # Parse the expression; bail out if it is not a simple Call node
    try:
        tree = ast.parse(clean_expr, mode="eval")
        if not isinstance(tree.body, ast.Call):
            return clean_expr
        call_node = tree.body
    except Exception:
        return clean_expr

    # --- Strategy 1: diff old vs. new signature ASTs directly ---------------
    if old_signature and new_signature:
        try:
            old_tree = ast.parse(f"{old_signature}: pass")
            new_tree = ast.parse(f"{new_signature}: pass")

            old_args = [a.arg for a in getattr(old_tree.body[0], "args", ast.arguments()).args]
            new_args = [a.arg for a in getattr(new_tree.body[0], "args", ast.arguments()).args]

            removed_params = set(old_args) - set(new_args)
            if removed_params:
                call_node.keywords = [kw for kw in call_node.keywords if kw.arg not in removed_params]
                return ast.unparse(call_node)

            # Detect reordering
            common = [a for a in old_args if a in new_args]
            filtered_new = [a for a in new_args if a in common]
            if common and filtered_new != common and len(call_node.args) >= 2:
                arg_map = {name: arg for name, arg in zip(old_args, call_node.args)}
                call_node.args = [arg_map[name] for name in new_args if name in arg_map]
                return ast.unparse(call_node)
        except Exception:
            pass

    # --- Strategy 2: "Parameter 'x' was removed" ----------------------------
    rem_match = re.search(r"Parameter '([A-Za-z0-9_]+)' was removed", breaking_change, re.IGNORECASE)
    if rem_match:
        param_name = rem_match.group(1)
        call_node.keywords = [kw for kw in call_node.keywords if kw.arg != param_name]
        return ast.unparse(call_node)

    # --- Strategy 3: positional parameter reordering ------------------------
    reorder_match = re.search(r"reordered:\s*(\[[^\]]+\])\s*->\s*(\[[^\]]+\])", breaking_change)
    if reorder_match:
        try:
            old_order = eval(reorder_match.group(1))  # noqa: S307
            new_order = eval(reorder_match.group(2))  # noqa: S307
            if len(call_node.args) >= 2 and len(old_order) == len(new_order):
                arg_map = {name: arg for name, arg in zip(old_order, call_node.args)}
                call_node.args = [arg_map[name] for name in new_order if name in arg_map]
                return ast.unparse(call_node)
        except Exception:
            pass

    # --- Strategy 4: new required parameter added ---------------------------
    add_match = re.search(r"New required parameter '([A-Za-z0-9_]+)' added", breaking_change, re.IGNORECASE)
    if add_match:
        param_name = add_match.group(1)
        if not any(kw.arg == param_name for kw in call_node.keywords):
            call_node.keywords.append(
                ast.keyword(arg=param_name, value=ast.Constant(value=f"<{param_name.upper()}>"))
            )
            return ast.unparse(call_node)

    # --- Strategy 5: default value removed ----------------------------------
    def_rem_match = re.search(
        r"Default value removed for parameter '([A-Za-z0-9_]+)'", breaking_change, re.IGNORECASE
    )
    if def_rem_match:
        param_name = def_rem_match.group(1)
        if not call_node.args and not any(kw.arg == param_name for kw in call_node.keywords):
            call_node.keywords.append(
                ast.keyword(arg=param_name, value=ast.Constant(value="<REQUIRED_VALUE>"))
            )
            return ast.unparse(call_node)

    return clean_expr
