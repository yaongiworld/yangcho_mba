"""Moment enrichment — fetch event_details + example_post_url via grounded Gemini.

Two display fields the dashboard wants but ingestion can't supply on its own:
  * event_details — a 1–3 sentence plain-English summary of what the trend is.
  * example_post_url — a real, high-traction public TikTok or Instagram post.

Both come from a single GoogleSearch-grounded Gemini call. One round-trip per
moment, fired only when the moment is publishable (has approved frictions) AND
one of the two fields is missing. The friction pipeline still owns reasoning;
this module owns the "what is this and where can I see it" surface.

Hallucination posture: same as influencer suggestions. Yangcho reviews every
moment going public; a fabricated URL is a missed click, not a brand crisis.
We do a cheap shape check on the URL (must be tiktok.com / instagram.com /
youtube.com) — anything else gets dropped.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from pydantic import BaseModel, Field

from pipeline.llm import DEFAULT_MODEL, LlmResult, parse_or_default
from pipeline.version import prompt_version

logger = logging.getLogger(__name__)

# Grounded calls produce citation-padded prose AND a JSON envelope, so the
# output budget has to absorb both. 1024 was not enough — it truncated mid-
# prose on simpler trends and never reached the JSON close. 3000 leaves
# room for ~1500 tokens of grounding chatter plus the JSON object.
ENRICHMENT_MAX_TOKENS = 3000

# Allowed host suffixes for example_post_url. We keep the list narrow on purpose:
# the dashboard's "see an example post" link should land on a creator-platform
# page, not a news article, a marketing page, or someone's blog.
_ALLOWED_HOSTS = (
    "tiktok.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
)


class MomentEnrichmentOutput(BaseModel):
    """JSON shape the grounded Gemini call returns."""

    event_details: str = Field(default="", description="1–3 sentences, plain English")
    example_post_url: str | None = Field(default=None)
    reasoning: str = Field(default="", description="Why this post was chosen")


@dataclass(frozen=True)
class MomentEnrichmentInput:
    moment_name: str
    source: str  # 'tiktok' | 'calendar' | 'google_trends'
    description: str | None
    friction_context: str  # combined summaries to anchor the search


def _build_prompt(inp: MomentEnrichmentInput) -> str:
    return f"""You are a research assistant helping a dashboard explain trending US lifestyle moments to readers who may not know them.

Use Google Search to look up the moment "{inp.moment_name}". Then produce two things:

1. **event_details** — a plain-English paragraph (1–3 sentences) describing what this trend or event is, where it happens (if applicable), and when. Aim it at someone who has never heard of it. No skincare interpretation, no marketing voice — just clear cultural context drawn from public sources.

2. **example_post_url** — a single, real, high-traction public post URL from TikTok, Instagram, or YouTube that exemplifies the trend. Pick the one with the most public engagement you can verify via search. Must be a creator post or video page, not a hashtag landing page, news article, or brand marketing page. If you cannot verify a real post URL via your search, return null — do NOT fabricate.

Allowed URL hosts only: tiktok.com, instagram.com, youtube.com, youtu.be.

Context to help you search:
- Source: {inp.source}
- Description: {inp.description or '(no extra description provided)'}
- Related skin-friction notes (just for context, not for the answer): {inp.friction_context[:400] or '(none)'}

CRITICAL: Your response MUST be a single valid JSON object and NOTHING else. No prose before it, no markdown fences, no commentary after. Start your response with `{{` and end with `}}`.

The exact shape:

{{
  "event_details": "string",
  "example_post_url": "https://www.tiktok.com/@creator/video/123... or null",
  "reasoning": "one-sentence explanation of why this post was chosen"
}}
"""


def _normalize_url(url: str | None) -> str | None:
    """Trim and validate the URL host. Returns None on anything suspicious."""
    if not url:
        return None
    url = url.strip()
    if not url or url.lower() in {"null", "none"}:
        return None
    low = url.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return None
    # Force https for visual consistency; the canonical hosts all serve https.
    if low.startswith("http://"):
        url = "https://" + url[len("http://"):]
        low = url.lower()
    if not any(host in low for host in _ALLOWED_HOSTS):
        logger.info("enrich: dropping URL with disallowed host: %s", url)
        return None
    return url


def _call_grounded(prompt: str, max_tokens: int) -> LlmResult:
    """One Gemini call with GoogleSearch grounding. Same pattern as influencer.py."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) not set in environment")

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
        prompt_name="moment_enrichment",
        prompt_version=prompt_version(),
        model=DEFAULT_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def enrich_moment(
    inp: MomentEnrichmentInput,
) -> tuple[str | None, str | None]:
    """Run the enrichment prompt + URL-host sanity check.

    Returns (event_details, example_post_url). Either or both can be None on
    failure / no result. Never raises.
    """
    prompt = _build_prompt(inp)

    try:
        result = await asyncio.to_thread(_call_grounded, prompt, ENRICHMENT_MAX_TOKENS)
    except Exception as exc:
        logger.warning("enrich: grounded call failed for %r: %s", inp.moment_name, exc)
        return None, None

    parsed = parse_or_default(result, MomentEnrichmentOutput)
    if parsed is None:
        logger.warning(
            "enrich: unparseable output for %r (prompt_version=%s)",
            inp.moment_name, result.prompt_version,
        )
        return None, None

    details = parsed.event_details.strip() or None
    url = _normalize_url(parsed.example_post_url)
    logger.info(
        "enrich: %r → details=%s url=%s",
        inp.moment_name,
        "yes" if details else "no",
        url or "no",
    )
    return details, url
