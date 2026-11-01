"""SafeDep Patcher Module.

Provides a single public entry-point for generating code patches that fix
API breaking-change call sites.  Two strategies are tried in order:

1. **DeepSeek API** (remote, requires ``DEEPSEEK_API_KEY`` in the environment
   or passed explicitly) — returns an LLM-generated replacement expression.
2. **AST rule-based fallback** (offline, deterministic) — handles the most
   common signature-change patterns using Python's ``ast`` module.

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
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def propose_patch(
    code_snippet: str,
    breaking_change_info: dict[str, Any],
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
) -> str:
    """Propose a patched replacement for a broken call-site expression.

    Tries the DeepSeek API first; falls back to the deterministic AST engine
    when the API key is absent or the network call fails.

    Args:
        code_snippet: The original call expression that needs to be fixed,
            e.g. ``"fetch_user(uid, timeout=30)"``.
        breaking_change_info: A dictionary describing the change.  Recognised
            keys (all optional):

            * ``"breaking_change"`` – human-readable description of the change.
            * ``"old_signature"``   – old ``def ...`` signature string.
            * ``"new_signature"``   – new ``def ...`` signature string.
            * ``"code_context"``    – surrounding source lines for richer AI
              prompts.
            * ``"suggested_fix"``   – optional explicit replacement for fallback.

        api_key: Override the ``DEEPSEEK_API_KEY`` environment variable.
        model: DeepSeek model name (default ``"deepseek-chat"``).

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
    feedback = str(breaking_change_info.get("feedback", "")).strip()

    return _patch_with_deepseek(
        call_expression=code_snippet,
        breaking_change=breaking_change,
        old_signature=old_signature,
        new_signature=new_signature,
        code_context=code_context,
        feedback=feedback,
        api_key=api_key,
        model=model,
    )


# ---------------------------------------------------------------------------
# DeepSeek strategy
# ---------------------------------------------------------------------------


def _clean_llm_code_response(text: str) -> str:
    """Clean the raw LLM response text, stripping markdown and explanatory prefixes."""
    cleaned = text.strip()
    if not cleaned:
        return ""

    # Check for markdown code fences: ```python ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        # Strip leading ```python or ``` and trailing ```
        cleaned = re.sub(r"^```(?:python)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # If single-line wrapped in backticks: `expr`
    if cleaned.startswith("`") and cleaned.endswith("`") and cleaned.count("`") == 2:
        cleaned = cleaned[1:-1].strip()

    # Strip conversational prefixes if the LLM output something like:
    # "Replacement: foo(bar)" or "Fixed code: foo(bar)"
    prefix_patterns = [
        r"^(?:here\s+is\s+(?:the\s+)?(?:fixed\s+code|fix|replacement|patch):?)\s*",
        r"^(?:replacement|fixed\s+code|patch|fix):\s*",
    ]
    for pattern in prefix_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned


def _is_valid_python_code(code: str, original_code: str = "") -> bool:
    """Validate that code string is syntactically valid Python and not an English explanation."""
    if not code or not code.strip():
        return False
    try:
        parsed = ast.parse(code.strip())
        # An empty AST (e.g. only comments or blank) is not executable replacement code
        if not parsed.body:
            return False
        # If the AST is just a single string literal (e.g. "This function was removed"),
        # treat it as English text unless the original was also a string literal.
        if (
            len(parsed.body) == 1
            and isinstance(parsed.body[0], ast.Expr)
            and isinstance(parsed.body[0].value, ast.Constant)
            and isinstance(parsed.body[0].value.value, str)
        ):
            if original_code and original_code.strip():
                try:
                    orig_parsed = ast.parse(original_code.strip())
                    if (
                        len(orig_parsed.body) == 1
                        and isinstance(orig_parsed.body[0], ast.Expr)
                        and isinstance(orig_parsed.body[0].value, ast.Constant)
                        and isinstance(orig_parsed.body[0].value.value, str)
                    ):
                        return True
                except Exception:
                    pass
            return False
        return True
    except SyntaxError:
        return False


def _patch_with_deepseek(
    call_expression: str,
    breaking_change: str,
    old_signature: Optional[str] = None,
    new_signature: Optional[str] = None,
    code_context: str = "",
    feedback: str = "",
    api_key: Optional[str] = None,
    model: str = "deepseek-chat",
) -> str:
    """Request a signature refactoring patch from the LLM (Groq or DeepSeek API).

    Uses an OpenAI-compatible chat completions endpoint with strict formatting
    instructions to ensure valid Python code output and prevent natural language
    responses. Falls back to :func:`_ast_fallback_patch` on any error or invalid
    syntax.
    """
    effective_api_key = (
        api_key
        or os.environ.get("GROQ_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
    )

    if effective_api_key:
        try:
            # Determine LLM provider: Groq (preferred) vs DeepSeek
            is_groq = False
            if effective_api_key.startswith("gsk_") or (
                not api_key and os.environ.get("GROQ_API_KEY") == effective_api_key
            ):
                is_groq = True
            elif any(k in model.lower() for k in ("llama", "mixtral", "gemma", "groq")):
                is_groq = True

            if is_groq:
                url = "https://api.groq.com/openai/v1/chat/completions"
                effective_model = (
                    "llama-3.3-70b-versatile" if model == "deepseek-chat" else model
                )
            else:
                url = "https://api.deepseek.com/chat/completions"
                effective_model = model

            system_prompt = (
                "You are SafeDep's automated Python refactoring engine.\n"
                "Your role is to patch broken Python call sites caused by library upgrades and API breaking changes.\n\n"
                "STRICT RULES:\n"
                "1. Output ONLY valid, executable Python code.\n"
                "2. Return ONLY the replacement code snippet (an expression or statement) that directly replaces the original code snippet.\n"
                "3. Do NOT include markdown commentary, conversational text, descriptions, or explanations.\n"
                "4. Do NOT add comments or explanations unless strictly necessary for Python syntax.\n"
                "5. NEVER return English sentences (such as 'This function was removed' or 'Manual intervention required') as code.\n"
                "6. If the breaking change cannot be fixed automatically or requires manual intervention, output the original snippet unchanged."
            )

            prompt_sections = [
                "### TASK: Automated Python Code Repair",
                "Fix the broken Python code snippet below to resolve the specified API breaking change.",
                "",
                "### EXACT BREAKING CHANGE INFORMATION:",
                f"- Issue: {breaking_change.strip()}",
            ]
            if old_signature:
                prompt_sections.append(f"- Old Signature: {old_signature.strip()}")
            if new_signature:
                prompt_sections.append(f"- New Signature: {new_signature.strip()}")

            prompt_sections.extend([
                "",
                "### ORIGINAL CODE SNIPPET TO FIX:",
                "```python",
                call_expression.strip(),
                "```",
            ])

            if code_context and code_context.strip():
                prompt_sections.extend([
                    "",
                    "### SURROUNDING CODE CONTEXT:",
                    "```python",
                    code_context.strip(),
                    "```",
                ])

            if feedback and feedback.strip():
                prompt_sections.extend([
                    "",
                    "### TEST FEEDBACK FROM PREVIOUS ATTEMPT:",
                    f"- Error details: {feedback.strip()}",
                    "- Please refine your replacement code to resolve this error and ensure tests pass.",
                ])

            prompt_sections.extend([
                "",
                "### STRICT INSTRUCTIONS FOR CODE GENERATION:",
                "1. Return ONLY the replacement Python code that directly replaces the original snippet.",
                "2. The returned code MUST be syntactically valid Python.",
                "3. Do NOT add any explanations, introductory text, markdown commentary, or notes.",
                "4. Do NOT add comments unless strictly necessary for Python syntax.",
                "5. NEVER return English sentences or advice as code. If you cannot produce a valid Python code fix, output the original snippet unchanged.",
                "6. Output ONLY the raw replacement Python code without markdown code blocks unless necessary.",
                "",
                "Replacement Code:"
            ])
            user_prompt = "\n".join(prompt_sections)

            req_payload = {
                "model": effective_model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {effective_api_key}",
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(req_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                result_text = resp_json["choices"][0]["message"]["content"].strip()
                cleaned_result = _clean_llm_code_response(result_text)
                if cleaned_result and _is_valid_python_code(cleaned_result, original_code=call_expression):
                    return cleaned_result
        except Exception:
            # Network, API error, or invalid code — fall through to the AST engine
            pass

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

