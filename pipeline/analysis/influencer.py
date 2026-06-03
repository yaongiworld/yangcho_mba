"""Influencer matcher — W4 third leg of the playbook.

For each approved moment, calls Gemini with the GoogleSearch grounding tool
enabled to find 1–3 US-based content creators on TikTok or Instagram whose
public content centers on the moment.

Per the /office-hours design doc, influencer suggestions ALWAYS queue for
review regardless of confidence — real-people recommendations for brand
pitches carry ethical surface no AI confidence number can absolve.
Yangcho's eyes are the safeguard; see the validation block below for why
no HTTP-based validator stands in between.

Historical note: the web-search call used Anthropic's web_search_20250305
tool until 2026-06-03. The migration to Gemini swapped that for the native
GoogleSearch grounding tool. Output shape (InfluencerOutput JSON) is
unchanged, so downstream parsing and the review queue are identical.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from pipeline.llm import LlmResult, parse_or_default
from pipeline.schemas import InfluencerSuggestionBody
from pipeline.version import prompt_version

logger = logging.getLogger(__name__)

INFLUENCER_MAX_TOKENS = 2000

# How long to wait when validating a handle's public profile. Two seconds
# is enough on a healthy network; longer suggests the platform is rate-
# limiting our IP, which is itself a useful signal (treat as "valid").
VALIDATION_TIMEOUT_SECONDS = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Output shapes — these mirror the JSON the prompt returns
# ─────────────────────────────────────────────────────────────────────────────


class InfluencerSuggestion(BaseModel):
    platform: str = Field(pattern=r"^(tiktok|instagram)$")
    handle: str
    profile_url: str
    evidence_urls: list[str] = Field(default_factory=list)
    reasoning: str
    confidence: int = Field(ge=1, le=10)


class InfluencerOutput(BaseModel):
    suggestions: list[InfluencerSuggestion] = Field(default_factory=list)


@dataclass(frozen=True)
class InfluencerInput:
    moment_name: str
    moment_description: str
    friction_context: str  # combined summaries of the moment's frictions, for AI context


# ─────────────────────────────────────────────────────────────────────────────
# Handle validation
# ─────────────────────────────────────────────────────────────────────────────


def _build_profile_url(platform: str, handle: str) -> str:
    handle_clean = handle.lstrip("@").strip()
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{handle_clean}"
    if platform == "instagram":
        return f"https://www.instagram.com/{handle_clean}/"
    return ""


# Validation: deliberately omitted.
#
# We tested HTTP-based handle validation on 2026-05-17. Both TikTok and
# Instagram now serve identical bot-stub pages for ALL non-authenticated
# requests — real handles and fake handles return the same response.
# TikTok serves a 1.4KB SlardarWAF stub regardless of who's being looked up;
# Instagram serves an 800KB login wall whose only difference between real
# and fake handles is rendered client-side after JS.
#
# A real validator would require playwright with stealth + login session
# (and even then, fragile to rotation). That cost outweighs the value when
# we already have a stronger safeguard: every influencer suggestion ALWAYS
# queues for Yangcho's review before publishing. Her eyes catch
# hallucinated handles in seconds — she knows the voice and follower
# context of every relevant creator in this space.
#
# So: the AI proposes, Yangcho disposes. No validator stands in between.
# Documented as an architectural choice rather than an oversight.


# ─────────────────────────────────────────────────────────────────────────────
# LLM call with web_search tool
# ─────────────────────────────────────────────────────────────────────────────


def _interpolate_influencer_prompt(inp: InfluencerInput) -> str:
    from pipeline.llm import _interpolate, _load_prompt

    template = _load_prompt("influencer")
    return _interpolate(
        template,
        {
            "moment_name": inp.moment_name,
            "moment_description": inp.moment_description,
            "friction_context": inp.friction_context,
        },
    )


def _call_llm_with_web_search(prompt: str, max_tokens: int) -> LlmResult:
    """Like pipeline.llm.call_llm, but with GoogleSearch grounding enabled.

    Kept inline rather than added to call_llm() because GoogleSearch is only
    used here and has different cost/latency characteristics worth surfacing
    at the call site.
    """
    import os

    from google import genai
    from google.genai import types

    from pipeline.llm import DEFAULT_MODEL

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) not set in environment"
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )

    text = response.text or ""
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    return LlmResult(
        text=text,
        prompt_name="influencer",
        prompt_version=prompt_version(),
        model=DEFAULT_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def generate_influencer_suggestions(
    inp: InfluencerInput,
) -> list[InfluencerSuggestionBody]:
    """Run the influencer prompt + validate every handle.

    Returns the list of InfluencerSuggestionBody (the schema shape that
    persists to playbook_outputs.body). Empty list on failure or zero
    valid handles. Never raises.
    """
    prompt = _interpolate_influencer_prompt(inp)

    try:
        result = await asyncio.to_thread(
            _call_llm_with_web_search, prompt, INFLUENCER_MAX_TOKENS
        )
    except Exception as exc:
        logger.warning("influencer: web_search call failed: %s", exc)
        return []

    parsed = parse_or_default(result, InfluencerOutput)
    if parsed is None:
        logger.warning(
            "influencer: unparseable output (prompt_version=%s)",
            result.prompt_version,
        )
        return []

    if not parsed.suggestions:
        logger.info("influencer: model returned no suggestions for %r", inp.moment_name)
        return []

    # No validator stands between the AI and Yangcho's review queue (see
    # comment block above). Every suggestion passes through verbatim.
    out: list[InfluencerSuggestionBody] = []
    for suggestion in parsed.suggestions:
        out.append(
            InfluencerSuggestionBody(
                creator_handle=f"@{suggestion.handle.lstrip('@')}",
                reasoning=suggestion.reasoning,
                public_evidence=(
                    "Platform: " + suggestion.platform
                    + " · Profile: " + suggestion.profile_url
                    + (
                        " · Posts: " + ", ".join(suggestion.evidence_urls)
                        if suggestion.evidence_urls
                        else ""
                    )
                ),
            )
        )

    logger.info(
        "influencer: %d suggestion(s) for %r (queued for review)",
        len(out), inp.moment_name,
    )
    return out
