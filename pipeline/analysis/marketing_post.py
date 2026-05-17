"""Marketing post generator — W4 first leg of the playbook.

For each approved friction-with-a-matched-product, generates an 80–120 word
English marketing post in mainstream-American voice. NEVER uses K-Beauty
cultural framings (banned list enforced in the prompt itself).

Per the /office-hours design doc, marketing posts ALWAYS queue for review
regardless of the AI's self-rating — voice is a high-bar editorial concern
and Yangcho is the line of defense against cultural-marketing leakage.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pipeline.llm import call_llm, parse_or_default
from pipeline.schemas import FrictionItem, MarketingPostBody, ProductMatchItem

logger = logging.getLogger(__name__)

MARKETING_POST_MAX_TOKENS = 600


@dataclass(frozen=True)
class MarketingPostInput:
    """The context the generator needs: a friction + the matched product + its argument."""

    friction: FrictionItem
    product_brand: str
    product_name: str
    match: ProductMatchItem  # has match_score + scientific_argument


async def generate_marketing_post(
    inp: MarketingPostInput,
) -> MarketingPostBody | None:
    """Run the marketing_post prompt for one friction-match pair.

    Returns the parsed MarketingPostBody, or None on failure (LLM error,
    parse failure, banned-phrase override). Never raises.
    """
    try:
        result = await asyncio.to_thread(
            call_llm,
            "marketing_post",
            {
                "friction_summary": inp.friction.summary,
                "friction_mechanism": inp.friction.mechanism,
                "efficacy_class": inp.friction.efficacy_class or "(unspecified)",
                "product_brand": inp.product_brand,
                "product_name": inp.product_name,
                "scientific_argument": inp.match.scientific_argument,
            },
            max_tokens=MARKETING_POST_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning("marketing_post: call_llm failed: %s", exc)
        return None

    parsed = parse_or_default(result, MarketingPostBody)
    if parsed is None:
        logger.warning(
            "marketing_post: unparseable output (prompt_version=%s)",
            result.prompt_version,
        )
        return None

    # Belt-and-suspenders voice gate: even with the prompt's ban list, the
    # model occasionally lapses. If the body contains any banned phrase,
    # discard and let the caller treat as a generation failure (which queues
    # for review with no playbook output).
    banned = (
        "k-beauty",
        "k beauty",
        "korean beauty",
        "korean skincare",
        "korean ritual",
        "korean secret",
        "korean tradition",
        "ancient korean",
        "glass skin",
        "glass-skin",
        "seoul-inspired",
        "from seoul",
        "born in korea",
    )
    body_lower = (parsed.headline + " " + parsed.body + " " + parsed.call_to_action).lower()
    leaks = [phrase for phrase in banned if phrase in body_lower]
    if leaks:
        logger.warning(
            "marketing_post: voice gate caught banned phrases %s; discarding output",
            leaks,
        )
        return None

    logger.info(
        "marketing_post: generated (prompt_version=%s, body=%d chars)",
        result.prompt_version,
        len(parsed.body),
    )
    return parsed
