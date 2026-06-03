"""LLM call helpers — single source of truth for prompt loading + Gemini calls.

The pipeline never calls the Gemini SDK directly. Every LLM call site goes
through `call_llm(prompt_name, vars)` which:
  1. Loads `pipeline/prompts/{prompt_name}.md`.
  2. Substitutes {{handlebars}} variables from `vars`.
  3. Calls Gemini with manual retries on transient failures.
  4. Returns an `LlmResult` carrying the response text and the prompt_version SHA.

Parsing is separate: callers pipe the response through `parse_or_default(result, schema)`
to get a Pydantic model instance or None on parse failure (logged, never raised).

Historical note: this module called Anthropic Claude until 2026-06-03. The switch
to Gemini Flash was a cost cut to keep the MBA-portfolio demo affordable through
November application deadlines. The LlmResult shape is preserved verbatim so
every call site keeps working without changes — only `model` strings and the
underlying SDK changed.

This pattern is decided in /plan-eng-review:
  • Issue 6 — single prompts/ directory + call_llm() helper
  • Issue 7 — retries + parse_or_default + pipeline_runs observability
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pipeline.version import prompt_version

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Model tiering — Gemini 2.5 Flash for the default reasoning tier (2026-06-03).
# Replaces claude-sonnet-4-6 as the friction/matcher/playbook workhorse.
# 2.5 Flash has strong structured-JSON output and the price point keeps the
# daily cron under budget through November.
DEFAULT_MODEL = "gemini-2.5-flash"
# 2.5 Flash-Lite for prompts that don't need deep reasoning: marketing copy
# (creative shape, voice-gated), and any future 1-5 / 1-10 integer scoring
# calls. ~3x cheaper than Flash; the banned-phrase voice gate in
# pipeline/analysis/marketing_post.py is the safety net for any voice slips
# the cheaper tier might make.
HAIKU_MODEL = "gemini-2.5-flash-lite"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_MAX_RETRIES = 3

# Variable interpolation: {{var_name}} only. No nested expressions, no logic.
# If a referenced var is missing, raise — the caller meant to provide it.
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


T = TypeVar("T", bound="BaseModel")


@dataclass(frozen=True)
class LlmResult:
    """The raw output of an LLM call, plus enough metadata to trace it back."""

    text: str
    prompt_name: str
    prompt_version: str
    model: str
    input_tokens: int
    output_tokens: int


class PromptNotFoundError(FileNotFoundError):
    """Raised when call_llm() is asked for a prompt file that doesn't exist."""


class MissingVariableError(KeyError):
    """A {{handlebars}} reference in the prompt has no matching key in `vars`."""


def _load_prompt(prompt_name: str) -> str:
    path = PROMPTS_DIR / f"{prompt_name}.md"
    if not path.exists():
        raise PromptNotFoundError(f"prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _interpolate(template: str, vars: dict[str, str]) -> str:
    """Substitute {{var}} references; raise if any reference is unmatched.

    Strict-mode interpolation: a missing variable is a programming error, not a
    silent empty string. We want loud failures during development.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in vars:
            raise MissingVariableError(
                f"prompt references {{{{ {name} }}}} but no value was provided"
            )
        return str(vars[name])

    return _VAR_RE.sub(replace, template)


# Transient errors worth retrying. Gemini surfaces these as HTTP 429 / 5xx
# wrapped in google.genai.errors.ServerError or .APIError. The SDK does not
# auto-retry by default, so we do it here with a simple exponential backoff.
_RETRY_BASE_DELAY_SECONDS = 1.5


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    if "429" in msg or "rate" in msg or "quota" in msg:
        return True
    if "500" in msg or "503" in msg or "internal" in msg or "unavailable" in msg:
        return True
    if "timeout" in msg or "timed out" in msg or "deadline" in msg:
        return True
    return False


def call_llm(
    prompt_name: str,
    vars: dict[str, str] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    thinking: bool = False,
) -> LlmResult:
    """Run a prompt through Gemini and return the result + traceability metadata.

    Retries transient failures (429 / 5xx / timeouts) up to `max_retries` times
    with exponential backoff. Auth errors and malformed-request errors propagate
    — those are programmer errors that should fail loud.

    `thinking` (default False) controls Gemini 2.5 Flash's "thinking" mode.
    Thinking tokens count against max_output_tokens AND cost more per token,
    so leaving it off keeps the daily-cron bill predictable. Turn it on for
    the moat friction analysis if output quality drops noticeably with it
    disabled. When True we double the output budget and allocate the extra
    half to thinking, so the caller's max_tokens still bounds the visible
    output. 2.5 Flash-Lite ignores this flag (it doesn't think).
    """
    template = _load_prompt(prompt_name)
    rendered = _interpolate(template, vars or {})

    # Lazy import: keeps `_load_prompt` and `_interpolate` testable without the
    # SDK installed (e.g., during prompt-template unit tests).
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) not set in environment"
        )

    client = genai.Client(api_key=api_key)

    if thinking:
        # Reserve max_tokens for visible output; allocate an equal budget
        # for thinking on top. Total Gemini budget becomes 2 * max_tokens.
        config_kwargs: dict[str, object] = {
            "max_output_tokens": max_tokens * 2,
            "thinking_config": types.ThinkingConfig(thinking_budget=max_tokens),
        }
    else:
        config_kwargs = {
            "max_output_tokens": max_tokens,
            "thinking_config": types.ThinkingConfig(thinking_budget=0),
        }

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=rendered,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and _is_retryable(exc):
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                logger.warning(
                    "call_llm: retryable error on attempt %d/%d for prompt=%s (sleeping %.1fs): %s",
                    attempt + 1, max_retries + 1, prompt_name, delay, exc,
                )
                time.sleep(delay)
                continue
            raise
    else:
        # Loop fell through without break — shouldn't happen given the raise above.
        raise last_exc  # type: ignore[misc]

    text = response.text or ""
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    return LlmResult(
        text=text,
        prompt_name=prompt_name,
        prompt_version=prompt_version(),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def parse_or_default(
    result: LlmResult,
    schema: type[T],
    *,
    extract_json: bool = True,
) -> T | None:
    """Validate `result.text` against a Pydantic schema. Return None on failure.

    Logs the validation error with the prompt_name + prompt_version, but never
    raises. Pipeline stages should treat None as 'this output is unusable, skip
    and record the failure to pipeline_runs' rather than crashing.

    `extract_json=True` (default) handles the common case where the model wraps
    JSON in prose or markdown code fences; it pulls the first JSON object it sees.
    Set False for plain-text outputs that aren't structured.
    """
    payload = result.text.strip()

    if extract_json:
        # Greedy match: outermost { ... } block. Good enough for portfolio scale.
        match = re.search(r"\{.*\}", payload, re.DOTALL)
        if not match:
            logger.warning(
                "parse_or_default: no JSON object found in response (prompt=%s, version=%s)",
                result.prompt_name,
                result.prompt_version,
            )
            return None
        payload = match.group(0)

    # Lazy import keeps prompt-template tests runnable without pydantic installed.
    from pydantic import ValidationError

    try:
        return schema.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning(
            "parse_or_default: schema mismatch (prompt=%s, version=%s, error=%s)",
            result.prompt_name,
            result.prompt_version,
            exc,
        )
        return None
