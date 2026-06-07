"""One-time cleanup: null out moments.example_post_url rows that don't verify.

Run after deploying the URL-verifier feature to remove the 8+ fabricated
YouTube URLs the first enrichment pass wrote. The verifier does the same
existence + topic-match check the daily pipeline now applies inline, so
this script's logic stays aligned with the production path.

Usage:
    set -a && source .env && set +a
    uv run python -m pipeline.scripts.clean_broken_urls
    # add --dry-run to preview without writing.

Idempotent: re-running re-checks all URLs and only nulls the ones still bad.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from pipeline.analysis.url_verify import verify_url
from pipeline.db import supabase_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def main(dry_run: bool) -> int:
    client = supabase_client()

    rows = (
        client.table("moments")
        .select("id, name, example_post_url")
        .not_.is_("example_post_url", "null")
        .execute()
        .data
        or []
    )
    logger.info("clean: %d moments with non-null URLs to verify", len(rows))

    kept = 0
    nulled = 0
    for i, m in enumerate(rows):
        url = m["example_post_url"]
        result = await verify_url(url, m["name"])
        if result.ok:
            logger.info(
                "  KEEP   id=%d %r -> %s",
                m["id"], m["name"][:30], url,
            )
            kept += 1
            continue

        logger.info(
            "  NULL   id=%d %r reason=%s url=%s",
            m["id"], m["name"][:30], result.reason, url,
        )
        nulled += 1
        if not dry_run:
            try:
                client.table("moments").update({"example_post_url": None}).eq(
                    "id", m["id"]
                ).execute()
            except Exception as exc:
                logger.warning("  update failed for id=%d: %s", m["id"], exc)

        # Don't hammer the verifier endpoints.
        if i < len(rows) - 1:
            await asyncio.sleep(0.5)

    logger.info(
        "clean: done. kept=%d nulled=%d (dry_run=%s)",
        kept, nulled, dry_run,
    )
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
