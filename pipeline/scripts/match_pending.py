"""Standalone entrypoint for the manual "Run matcher now" trigger.

Used by the /admin button, which fires the match-pending.yml GitHub
Actions workflow that runs this script. Bypasses the full daily ingest
+ extract + score + analyze loop — only the catch-up work for approved
content missing matches, playbook outputs, or product images.

Invocation:
    uv run python -m pipeline.scripts.match_pending

Two stages run in order:
  1. Backfill playbook — finds approved frictions/moments missing
     matches/marketing posts/product ideas/influencer suggestions and
     fills the gaps via the LLM pipeline.
  2. Download catalog images — for any product with a NULL image_path,
     fetches its OY CDN image and uploads to Supabase Storage.

Both stages record into pipeline_runs alongside the regular daily flow.
"""

from __future__ import annotations

import asyncio
import logging

from pipeline.ingestion.catalog_images import stage_download_catalog_images
from pipeline.orchestrator.run import stage_backfill_playbook


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("=== match_pending start (manual trigger) ===")
    await stage_backfill_playbook()
    await stage_download_catalog_images()
    logger.info("=== match_pending done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
