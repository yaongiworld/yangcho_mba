"""Product matching — friction → ranked K-Beauty product matches.

Given a FrictionAnalysis (1-3 frictions + self_rating) and the catalog of
products in Supabase, calls call_llm("product_match", ...) once per friction
and returns ranked matches.

Catalog scope per call: products in the OY category most aligned with the
friction's `efficacy_class`, split into two pools:
  * LG pool — up to LG_LIMIT LG-owned products (the LG-primary thesis).
  * Competitor pool — up to COMPETITOR_LIMIT non-LG K-Beauty products
    (so the model can recommend a competitor with scientific integrity
    when LG has no good fit).

This keeps prompt size at ~35 products × ~80 tokens regardless of how
big the catalog grows (e.g. 3887 OY Skincare products as of 2026-05-17).
The full-catalog "send everything" path stops scaling around N≈200 — at
3887 it would blow the context window.

LG-primary policy is enforced inside the prompt itself, not in code: the
candidate list flags which products are LG-owned and the prompt instructs
the model to prefer LG when matches are roughly tied.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipeline.db import supabase_client
from pipeline.llm import call_llm, parse_or_default
from pipeline.schemas import (
    FrictionItem,
    ProductMatchItem,
    ProductMatchOutput,
)

logger = logging.getLogger(__name__)

# Map a friction's efficacy_class to one or more OY catalog categories. Used
# to pre-filter the candidate list before sending to the LLM. The set returned
# here is conservative — when in doubt, include more categories rather than
# miss a match. The LLM is the final filter via match_score.
EFFICACY_TO_CATEGORIES: dict[str, list[str]] = {
    "long-wear-film": ["Suncare", "Makeup", "Skincare"],
    "antioxidant-uv-defense": ["Suncare", "Skincare"],
    "cooling": ["Suncare", "Skincare", "Face Masks"],
    "hydration-barrier-repair": ["Skincare", "Face Masks"],
    "sensitive-skin-soothing": ["Skincare", "Face Masks"],
    "post-procedure-repair": ["Skincare", "Face Masks"],
    "chelation-cleansing": ["Skincare"],
    "sebum-control": ["Skincare", "Face Masks"],
    "anti-inflammatory": ["Skincare", "Face Masks"],
}

# Two-pool candidate caps: LG-primary thesis with competitor fallback.
# LG_LIMIT 25 covers nearly the full LG catalog (~107 LG products across all
# categories; per-category counts are small). COMPETITOR_LIMIT 10 is enough
# to give the LLM a fallback when LG has no good fit — competitor matches
# are signal, not noise. Combined: ~35 products max per call, ~3K input
# tokens. Stable regardless of total catalog size.
LG_LIMIT = 25
COMPETITOR_LIMIT = 10

# Top N matches to keep per friction. The prompt is told to return up to 3.
MATCHES_PER_FRICTION = 3

FRICTION_PROMPT_MAX_TOKENS = 1500


def _categories_for(efficacy_class: str | None) -> list[str]:
    """Map an efficacy class to OY catalog categories. Falls back to all
    K-Beauty-relevant categories when we don't recognize the class."""
    if not efficacy_class:
        return ["Skincare", "Suncare", "Face Masks", "Makeup"]
    return EFFICACY_TO_CATEGORIES.get(
        efficacy_class,
        ["Skincare", "Suncare", "Face Masks", "Makeup"],
    )


def _format_candidates(rows: list[dict[str, Any]]) -> str:
    """Render product rows as `{id} | {brand} | {is_lg} | {category} | {name}` lines.

    The LLM sees this as the catalog excerpt; the order is preserved (database
    order, no ranking applied here — that's the LLM's job).
    """
    lines: list[str] = []
    for row in rows:
        is_lg = "LG" if row.get("is_lg") else "competitor"
        line = f"{row['id']} | {row.get('brand', '?')} | {is_lg} | {row.get('category', '?')} | {row.get('name', '?')}"
        lines.append(line)
    return "\n".join(lines) if lines else "(no candidate products in matching categories)"


async def _fetch_candidates(efficacy_class: str | None) -> list[dict[str, Any]]:
    """Read product rows from Supabase that match the friction's efficacy class.

    Two-pool query: LG-owned (up to LG_LIMIT) + competitor (up to
    COMPETITOR_LIMIT). Returned with LG products first so the prompt's LG
    bias has the right anchor order. Pulls (id, brand, is_lg, category, name).
    """
    cats = _categories_for(efficacy_class)
    client = supabase_client()

    lg_res = (
        client.table("products")
        .select("id, brand, is_lg, category, name")
        .in_("category", cats)
        .eq("is_lg", True)
        .eq("is_dead_link", False)
        .order("id")
        .limit(LG_LIMIT)
        .execute()
    )
    comp_res = (
        client.table("products")
        .select("id, brand, is_lg, category, name")
        .in_("category", cats)
        .eq("is_lg", False)
        .eq("is_dead_link", False)
        .order("id")
        .limit(COMPETITOR_LIMIT)
        .execute()
    )
    return (lg_res.data or []) + (comp_res.data or [])


async def match_one_friction(
    friction: FrictionItem,
) -> list[ProductMatchItem]:
    """Run the product-match prompt for a single friction.

    Returns a list of ProductMatchItem (possibly empty when no candidate
    fits well). Never raises — LLM errors return [] and the caller logs.
    """
    candidates = await _fetch_candidates(friction.efficacy_class)
    if not candidates:
        logger.info(
            "match_product: no candidates for friction (efficacy_class=%s)",
            friction.efficacy_class,
        )
        return []

    try:
        result = await asyncio.to_thread(
            call_llm,
            "product_match",
            {
                "friction_summary": friction.summary,
                "friction_mechanism": friction.mechanism,
                "efficacy_class": friction.efficacy_class or "(unspecified)",
                "candidate_products": _format_candidates(candidates),
            },
            max_tokens=FRICTION_PROMPT_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning("match_product: call_llm failed: %s", exc)
        return []

    parsed = parse_or_default(result, ProductMatchOutput)
    if parsed is None:
        logger.warning(
            "match_product: unparseable output (prompt_version=%s)",
            result.prompt_version,
        )
        return []

    # Keep top N. The prompt asked for up to 3 already, but cap defensively.
    valid_ids = {row["id"] for row in candidates}
    out: list[ProductMatchItem] = []
    for m in parsed.matches[:MATCHES_PER_FRICTION]:
        # Drop hallucinated product_ids that aren't in the candidate list.
        if m.product_id not in valid_ids:
            logger.warning(
                "match_product: dropping hallucinated product_id %d", m.product_id,
            )
            continue
        out.append(m)

    logger.info(
        "match_product: friction %r → %d matches (top score %s)",
        friction.summary[:60],
        len(out),
        f"{out[0].match_score:.2f}" if out else "—",
    )
    return out
