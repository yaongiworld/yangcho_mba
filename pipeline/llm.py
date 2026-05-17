"""LLM call helpers — single source of truth for prompt loading + Claude calls.

The pipeline never calls the Anthropic SDK directly. Every LLM call site goes
through `call_llm(prompt_name, vars)` which:
  1. Loads `pipeline/prompts/{prompt_name}.md`.
  2. Substitutes {{handlebars}} variables from `vars`.
  3. Calls Claude with max_retries=3 (SDK-level retry on 429/5xx/timeout).
  4. Returns an `LlmResult` carrying the response text and the prompt_version SHA.

Parsing is separate: callers pipe the response through `parse_or_default(result, schema)`
to get a Pydantic model instance or None on parse failure (logged, never raised).

This pattern is decided in /plan-eng-review:
  • Issue 6 — single prompts/ directory + call_llm() helper
  • Issue 7 — SDK retries + parse_or_default + pipeline_runs observability
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from typing import TYPE_CHECKING

from pipeline.version import prompt_version

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Model tiering — Sonnet 4.6 as the default reasoning tier (2026-05-17).
# An earlier pass set this to "claude-sonnet-4-7", which the API rejected
# (404 not_found_error) — that ID does not exist yet. 4.6 is the current
# Sonnet generation.
# Each call site can override via call_llm(model=...) when a different
# tier fits the task. See HAIKU_MODEL below for the cheap-fast option.
DEFAULT_MODEL = "claude-sonnet-4-6"
# Haiku 4.5 for prompts that don't need deep mechanism reasoning:
# marketing_post (creative copy, voice-gated), scoring (1-5 integers),
# self_rating (1-10 integer). ~5x cheaper, ~3x faster, frees rate-limit
# headroom for the Sonnet calls that actually need it.
HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_MAX_RETRIES = 3

# Variable interpolation: {{var_name}} only. No nested expressions, no logic.
# If a referenced var is missing, raise — the caller meant to provide it.
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


T = TypeVar("T", bound="BaseModel")


@dataclass(frozen=True)
class LlmResult:
    """The raw output of a Claude call, plus enough metadata to trace it back."""

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


def call_llm(
    prompt_name: str,
    vars: dict[str, str] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> LlmResult:
    """Run a prompt through Claude and return the result + traceability metadata.

    The Anthropic SDK handles retries on 429 / 5xx / timeout via `max_retries`.
    Other exceptions (auth, malformed request) propagate — those are programmer
    errors that should fail loud.
    """
    template = _load_prompt(prompt_name)
    rendered = _interpolate(template, vars or {})

    # Lazy import: keeps `_load_prompt` and `_interpolate` testable without the SDK
    # installed (e.g., during prompt-template unit tests).
    from anthropic import Anthropic

    client = Anthropic(max_retries=max_retries)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": rendered}],
    )

    # Claude's content is a list of blocks; we expect a single text block at portfolio scale.
    text = "".join(block.text for block in response.content if block.type == "text")

    return LlmResult(
        text=text,
        prompt_name=prompt_name,
        prompt_version=prompt_version(),
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
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

    `extract_json=True` (default) handles the common case where Claude wraps
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
