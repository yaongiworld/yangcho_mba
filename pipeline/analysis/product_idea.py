"""New-product-idea generator — W4 second leg of the playbook.

Fires ONLY when the best product match score is below the threshold (0.50
per the /office-hours design doc). The AI looked at the K-Beauty catalog,
honestly couldn't find a strong fit, and instead writes a one-page brief
for a new product that should be developed to fill the gap.

This is the "honest competitor / white space" angle: the dashboard
occasionally says 'no LG product fits — here's what to build.' That
signals integrity to adcom + intrapreneurship potential to Yangcho's
future LG team.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pipeline.llm import call_llm, parse_or_default
from pipeline.schemas import FrictionItem, ProductIdeaBody, ProductMatchItem

logger = logging.getLogger(__name__)

PRODUCT_IDEA_MAX_TOKENS = 1200

# Threshold below which we generate a new-product idea. Aligned with the
# match_product prompt's confidence scale (0.40-0.59 = "same category but
# unclear mechanism alignment"; below 0.50 = honest no-fit).
PRODUCT_IDEA_THRESHOLD = 0.50


@dataclass(frozen=True)
class ProductIdeaInput:
    """Context for the idea generator: friction + the FAILED best match."""

    friction: FrictionItem
    best_match_brand: str
    best_match_name: str
    best_match_score: float
    best_match_argument: str


def should_generate_idea(best_match_score: float | None) -> bool:
    """True when the catalog's best fit is below the threshold (or absent).

    None match score means we had no candidates at all — definitely a
    white space case.
    """
    if best_match_score is None:
        return True
    return best_match_score < PRODUCT_IDEA_THRESHOLD


async def generate_product_idea(
    inp: ProductIdeaInput,
) -> ProductIdeaBody | None:
    """Run the product_idea prompt for one friction-with-failed-match.

    Returns the parsed ProductIdeaBody, or None on LLM/parse failure.
    Never raises.
    """
    try:
        result = await asyncio.to_thread(
            call_llm,
            "product_idea",
            {
                "friction_summary": inp.friction.summary,
                "friction_mechanism": inp.friction.mechanism,
                "efficacy_class": inp.friction.efficacy_class or "(unspecified)",
                "best_match_brand": inp.best_match_brand,
                "best_match_name": inp.best_match_name,
                "best_match_score": f"{inp.best_match_score:.2f}",
                "best_match_argument": inp.best_match_argument,
            },
            max_tokens=PRODUCT_IDEA_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning("product_idea: call_llm failed: %s", exc)
        return None

    parsed = parse_or_default(result, ProductIdeaBody)
    if parsed is None:
        logger.warning(
            "product_idea: unparseable output (prompt_version=%s)",
            result.prompt_version,
        )
        return None

    logger.info(
        "product_idea: generated %r (prompt_version=%s)",
        parsed.concept_name,
        result.prompt_version,
    )
    return parsed
