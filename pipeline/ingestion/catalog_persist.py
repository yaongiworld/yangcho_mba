"""Persist scraped Olive Young Global products to the Supabase products table.

Pass-A persistence: writes the cheap fields we have from the JSON API
(external_id, brand, brand_no, name, public_url, image_url, category,
platform, is_lg). Pass B (vision OCR) will UPDATE these rows later with
claims and key_ingredients.

Idempotent via (platform, external_id) unique key per migration 0003.
Re-running for the same products updates name/url/image; LG flag is
authoritative from the curated brand allowlist, so we always overwrite.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from pipeline.db import supabase_client
from pipeline.ingestion.catalog import ProductFacts
from pipeline.ingestion.oy_brands import is_lg_brand_no

logger = logging.getLogger(__name__)

PLATFORM_OY_GLOBAL = "oy_global"


def _facts_to_row(facts: ProductFacts, *, platform: str = PLATFORM_OY_GLOBAL) -> dict:
    """Convert a ProductFacts into a dict ready for insert/upsert."""
    return {
        "external_id": facts.external_id,
        "platform": platform,
        "brand": facts.brand,
        "is_lg": is_lg_brand_no(facts.brand_no),
        "name": facts.name,
        "category": facts.category,
        "public_url": facts.public_url,
        "last_verified_at": datetime.now(timezone.utc).isoformat(),
        "last_scraped_at": datetime.now(timezone.utc).isoformat(),
        "is_dead_link": False,
    }


def upsert_products(
    facts_list: Iterable[ProductFacts],
    *,
    platform: str = PLATFORM_OY_GLOBAL,
) -> int:
    """Upsert ProductFacts into the Supabase products table.

    Returns the number of rows written. Failures on individual rows are
    logged and skipped — never aborts the batch.

    Postgres-side this hits the (platform, external_id) UNIQUE constraint
    from migration 0003; the upsert overwrites mutable fields on conflict.
    """
    rows = [_facts_to_row(f, platform=platform) for f in facts_list]
    if not rows:
        return 0

    client = supabase_client()
    try:
        result = (
            client.table("products")
            .upsert(rows, on_conflict="platform,external_id")
            .execute()
        )
    except Exception as exc:
        logger.error("catalog_persist: upsert failed: %s", exc)
        # Fall back to per-row inserts so a single malformed row doesn't drop the batch.
        return _upsert_one_at_a_time(client, rows)

    written = len(result.data) if result.data else 0
    logger.info("catalog_persist: upserted %d products (platform=%s)", written, platform)
    return written


def _upsert_one_at_a_time(client, rows: list[dict]) -> int:
    """Fallback when the batch upsert blows up. Slower but per-row resilient."""
    written = 0
    for row in rows:
        try:
            client.table("products").upsert(
                [row], on_conflict="platform,external_id"
            ).execute()
            written += 1
        except Exception as exc:
            logger.warning(
                "catalog_persist: row upsert failed for %s/%s: %s",
                row.get("platform"), row.get("external_id"), exc,
            )
    return written
