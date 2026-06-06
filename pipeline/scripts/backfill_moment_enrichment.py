"""Backfill event_details + example_post_url for existing moments.

Run once after deploying the moment_enrichment feature. Scans every moment
row that the live dashboard could show (has at least one approved friction),
fires a grounded Gemini call only when the row is missing fields or the
existing event_details looks like a friction-hint dump.

Usage:
    set -a && source .env && set +a
    uv run python -m pipeline.scripts.backfill_moment_enrichment

Idempotent: re-running skips rows that already have both fields populated
with a real sentence. Rate-limited to 2s between calls to stay polite to
the Gemini API. Logs every action so you can audit what was filled.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from pipeline.analysis.moment_enrichment import (
    MomentEnrichmentInput, enrich_moment,
)
from pipeline.db import supabase_client
from pipeline.orchestrator.run import _needs_enrichment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

RATE_LIMIT_SECONDS = 2.0


async def main() -> int:
    client = supabase_client()

    # 1. Pull moments that are publishable (at least one approved friction).
    approved_fric = (
        client.table("frictions")
        .select("moment_id, friction_summary")
        .eq("review_status", "approved")
        .execute()
        .data
        or []
    )
    publishable_ids = {f["moment_id"] for f in approved_fric}
    if not publishable_ids:
        logger.info("backfill: no publishable moments; nothing to do")
        return 0

    moments = (
        client.table("moments")
        .select("id, name, source, description, event_details, example_post_url")
        .in_("id", list(publishable_ids))
        .execute()
        .data
        or []
    )
    logger.info("backfill: %d publishable moments to scan", len(moments))

    # Build a per-moment friction-context lookup so the grounded prompt has
    # something to anchor on beyond just the name.
    friction_ctx: dict[int, str] = {}
    for f in approved_fric:
        mid = f["moment_id"]
        friction_ctx.setdefault(mid, "")
        friction_ctx[mid] = (friction_ctx[mid] + " " + f["friction_summary"]).strip()

    filled = 0
    skipped = 0
    failed = 0

    for i, m in enumerate(moments):
        if not _needs_enrichment(m.get("event_details"), m.get("example_post_url")):
            skipped += 1
            continue

        logger.info(
            "backfill: %d/%d enriching moment_id=%d name=%r",
            i + 1, len(moments), m["id"], m["name"],
        )
        details, url = await enrich_moment(
            MomentEnrichmentInput(
                moment_name=m["name"],
                source=m["source"],
                description=m.get("description"),
                friction_context=friction_ctx.get(m["id"], ""),
            )
        )

        payload: dict[str, object] = {}
        if details and _needs_enrichment(m.get("event_details"), "x"):
            payload["event_details"] = details
        if url and not m.get("example_post_url"):
            payload["example_post_url"] = url

        if not payload:
            logger.info("backfill: nothing to write for moment_id=%d", m["id"])
            failed += 1
        else:
            try:
                client.table("moments").update(payload).eq("id", m["id"]).execute()
                logger.info(
                    "backfill: wrote moment_id=%d fields=%s",
                    m["id"], list(payload.keys()),
                )
                filled += 1
            except Exception as exc:
                logger.warning(
                    "backfill: update failed for moment_id=%d: %s", m["id"], exc,
                )
                failed += 1

        # Be polite to the Gemini API.
        if i < len(moments) - 1:
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    logger.info(
        "backfill: done. filled=%d skipped=%d failed=%d",
        filled, skipped, failed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
