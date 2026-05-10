"""Friction analyzer — the moat call site.

Given a lifestyle moment (with raw signal sample), invokes the friction prompt
anchored by Yangcho's 3 hero case studies. Returns a FrictionAnalysis (1–3
frictions + self_rating) or None on parse/network failure.

This is the ONLY place the friction prompt is called. The orchestrator runs
many of these in parallel via asyncio.gather() per /plan-eng-review Issue 7
(async fan-out cuts wall time from ~10min serial to ~2min).
"""

from __future__ import annotations

import asyncio
import logging
from functools import cache
from pathlib import Path

from pipeline.llm import call_llm, parse_or_default
from pipeline.schemas import FrictionAnalysis, RawSignal

logger = logging.getLogger(__name__)

HERO_CASES_DIR = Path(__file__).parent.parent / "prompts" / "hero_cases"

# How many representative signal posts to include in the prompt. More than
# this and the prompt blows past the model's effective attention window for
# the moat reasoning. Picked empirically — tune in W7 calibration.
SIGNAL_SAMPLE_SIZE = 8

# How many tokens to allocate. The friction prompt is the heaviest in the
# pipeline because of the 3 hero cases as exemplars (~1200 words each).
# Output is structured JSON, ~400-600 tokens typical.
FRICTION_MAX_TOKENS = 2048


@cache
def _hero_cases() -> tuple[str, str, str]:
    """Load the 3 hero case studies from disk. Cached for the process lifetime —
    if Yangcho updates a case, the cron picks it up on next run."""
    return (
        (HERO_CASES_DIR / "1_long_outdoor_uv_sweat.md").read_text(encoding="utf-8"),
        (HERO_CASES_DIR / "2_hard_water_film.md").read_text(encoding="utf-8"),
        (HERO_CASES_DIR / "3_post_microneedling_repair.md").read_text(encoding="utf-8"),
    )


def _format_signal_sample(signals: list[RawSignal]) -> str:
    """Render up to N signals as a compact bulleted list for the prompt.

    Trims long bodies — the LLM doesn't need the full source content, just
    enough to grok the friction. ~280 chars per signal is the Twitter-era sweet
    spot for "enough to understand without bloating the prompt."
    """
    lines: list[str] = []
    for s in signals[:SIGNAL_SAMPLE_SIZE]:
        excerpt = s.text.strip().replace("\n", " ")[:280]
        lines.append(f"- [{s.source.value}] {excerpt}")
    return "\n".join(lines) if lines else "- (no source signals — moment from cultural calendar)"


async def analyze_friction(
    moment_name: str,
    moment_description: str,
    signals: list[RawSignal],
) -> FrictionAnalysis | None:
    """Run the moat prompt for one moment. Returns None if the LLM call fails
    or the output can't be parsed.

    None is a normal return value — the orchestrator records it as a failed
    item in pipeline_runs.items_succeeded and continues. Other moments
    succeed independently because we run these in parallel.
    """
    h1, h2, h3 = _hero_cases()

    # The Anthropic SDK's sync client is what call_llm uses. Drop it on a
    # thread so we can asyncio.gather a batch of these from the orchestrator.
    try:
        result = await asyncio.to_thread(
            call_llm,
            "friction",
            {
                "hero_case_1": h1,
                "hero_case_2": h2,
                "hero_case_3": h3,
                "moment_name": moment_name,
                "moment_description": moment_description or moment_name,
                "signal_sample": _format_signal_sample(signals),
            },
            max_tokens=FRICTION_MAX_TOKENS,
        )
    except Exception as exc:
        # Network failure, auth error, anything that escapes the SDK's max_retries.
        # parse_or_default handles malformed responses; this branch is for
        # cases where there IS no response at all.
        logger.warning("friction: call_llm failed for %r: %s", moment_name, exc)
        return None

    parsed = parse_or_default(result, FrictionAnalysis)
    if parsed is None:
        logger.warning(
            "friction: model returned unparseable output for %r (prompt_version=%s)",
            moment_name,
            result.prompt_version,
        )
        return None

    logger.info(
        "friction: %r → %d frictions, self_rating=%d (prompt_version=%s)",
        moment_name,
        len(parsed.frictions),
        parsed.self_rating,
        result.prompt_version,
    )
    return parsed
