"""Standalone entrypoint for refreshing the OY Global product catalog.

Scrapes Olive Young Global's Skincare category and upserts the results
into Supabase `products`. Idempotent via the (platform, external_id)
unique constraint from migration 0003 — re-running updates mutable
fields (name, public_url, image_url, category) without duplicating rows
or disturbing approved matches.

Why this exists as a separate script:
  * Catalog data is independent of the daily moment/friction loop. Don't
    bottleneck the daily cron on it.
  * After schema migrations that add product columns (e.g. image_url in
    migration 0009), a refresh repopulates the new field across the
    existing catalog.
  * Manual invocation is rare enough that a hand-pulled script is
    simpler than orchestrating a new pipeline stage.

Invocation:
    uv run python -m pipeline.scripts.refresh_catalog

Optional env knob:
    OY_CATEGORY   — category name to scrape (default: "Skincare")
"""

from __future__ import annotations

import asyncio
import logging
import os

from pipeline.ingestion.catalog import scrape_category
from pipeline.ingestion.catalog_persist import upsert_products


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    category = os.environ.get("OY_CATEGORY", "Skincare")
    logger.info("=== refresh_catalog start (category=%s) ===", category)

    facts = await scrape_category(category)
    if not facts:
        logger.warning("refresh_catalog: no products returned; aborting upsert")
        return 1

    written = upsert_products(facts)
    logger.info(
        "refresh_catalog: done — scraped %d, persisted %d",
        len(facts), written,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
