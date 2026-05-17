"""Standalone entrypoint to run JUST the backfill-matches stage.

Used by the /admin "Run matcher now" button, which fires a GitHub Actions
workflow that runs this script. Bypasses the full daily ingest + extract +
score + analyze loop — only the catch-up matching for approved frictions
that have no matches yet.

Invocation:
    uv run python -m pipeline.scripts.match_pending

Same observability as a normal cron tick: the backfill stage opens a row
in pipeline_runs labeled match_product, with item counts and status, so
the /admin pipeline-runs section shows the trigger ran.
"""

from __future__ import annotations

import asyncio
import logging

from pipeline.orchestrator.run import stage_backfill_matches


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("=== match_pending start (manual trigger) ===")
    await stage_backfill_matches()
    logger.info("=== match_pending done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
