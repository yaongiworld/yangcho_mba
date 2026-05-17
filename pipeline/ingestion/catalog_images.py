"""Product-image downloader — pulls OY CDN images into Supabase Storage.

For each product row where `image_path` is NULL, fetch the image at
`image_url` (OY's CDN), upload to the public `product-images` bucket,
then set `image_path` so future runs skip it. Idempotent.

Why we mirror instead of hot-linking from OY's CDN:
  - OY's CDN headers permit reads but offer no SLA. If they ever
    rotate the URLs or block our user agent on a Wednesday, every
    product card on the dashboard breaks.
  - Mirroring once-and-stable means the dashboard renders from our
    bucket; total reliability under our control.
  - At 107 products × ~30KB each, the whole catalog fits in ~3.2MB.
    Well under Supabase's free-tier 1GB storage cap.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from pipeline.db import supabase_client
from pipeline.ingestion.image_storage import storage_path_for, upload_image
from pipeline.observability import record_stage
from pipeline.schemas import PipelineStage

logger = logging.getLogger(__name__)

# OY's CDN is fast; 2 req/sec is well under what their robots.txt+infrastructure
# tolerates and keeps us well-mannered.
DOWNLOAD_RATE_LIMIT_SECONDS = 0.5

# Max wait per image. OY's CDN typically responds in <500ms, but a slow
# image shouldn't block the whole catalog refresh.
DOWNLOAD_TIMEOUT_SECONDS = 15.0

USER_AGENT = "llc-pipeline/0.1 (catalog image mirror; research; contact via repo)"


@dataclass(frozen=True)
class ImageDownloadResult:
    total_missing: int
    succeeded: int
    failed: int


def _sniff_content_type(image_bytes: bytes) -> str | None:
    """Detect MIME type from the first bytes of a file. Returns None when
    the magic number isn't a recognized web-friendly image format.

    OY's CDN sometimes returns content-type: application/octet-stream for
    files that are valid JPEGs/PNGs/WebPs. Supabase Storage's bucket-level
    MIME whitelist rejects octet-stream, so we re-derive the real type from
    the bytes themselves. Cheaper + more correct than trusting the header.
    """
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    return None


async def _download_one(
    client: httpx.AsyncClient,
    external_id: str,
    image_url: str,
) -> str | None:
    """Fetch the image bytes from OY's CDN and upload to Supabase Storage.
    Returns the bucket-relative image_path on success, None on failure."""
    try:
        r = await client.get(image_url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        r.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning(
            "catalog_images: download failed for %s: %s",
            external_id, exc,
        )
        return None

    # Sniff the actual type from the bytes — OY occasionally returns
    # application/octet-stream in the response header, which Supabase
    # rejects. The bytes still match a real image format.
    content_type = _sniff_content_type(r.content)
    if content_type is None:
        logger.warning(
            "catalog_images: %s downloaded but bytes are not a known image format (size=%d, header=%r)",
            external_id, len(r.content), r.headers.get("content-type"),
        )
        return None
    return upload_image(external_id, r.content, content_type=content_type)


async def download_missing_images(*, limit: int | None = None) -> ImageDownloadResult:
    """Find products with NULL image_path and download/upload each one.

    `limit` caps the number of products processed per call (useful for smoke
    runs against a small subset). None = process every missing image.
    """
    try:
        db = supabase_client()
    except Exception as exc:
        logger.warning("catalog_images: cannot reach Supabase: %s", exc)
        return ImageDownloadResult(0, 0, 0)

    # PostgREST returns at most 1000 rows per request by default. For a
    # catalog of ~3900 products this would silently leave ~75% un-mirrored
    # on the first run. Paginate via a range() loop until we get a short
    # page or hit the caller's `limit`.
    PAGE_SIZE = 1000
    rows: list[dict] = []
    offset = 0
    while True:
        page_size = PAGE_SIZE
        if limit is not None:
            remaining = limit - len(rows)
            if remaining <= 0:
                break
            page_size = min(PAGE_SIZE, remaining)

        page = (
            db.table("products")
            .select("id, external_id, image_url")
            .is_("image_path", "null")
            .neq("image_url", None)
            .eq("is_dead_link", False)
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    if not rows:
        return ImageDownloadResult(0, 0, 0)

    logger.info(
        "catalog_images: %d product(s) missing image_path; starting downloads",
        len(rows),
    )

    succeeded = 0
    failed = 0
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for i, row in enumerate(rows):
            image_path = await _download_one(
                client, row["external_id"], row["image_url"]
            )
            if image_path is None:
                failed += 1
            else:
                try:
                    db.table("products").update(
                        {"image_path": image_path}
                    ).eq("id", row["id"]).execute()
                    succeeded += 1
                except Exception as exc:
                    logger.warning(
                        "catalog_images: db update failed for product %d: %s",
                        row["id"], exc,
                    )
                    failed += 1

            # Rate-limit between requests, but not after the last one.
            if i < len(rows) - 1:
                await asyncio.sleep(DOWNLOAD_RATE_LIMIT_SECONDS)

            if (i + 1) % 25 == 0:
                logger.info(
                    "catalog_images: %d/%d processed (%d succeeded)",
                    i + 1, len(rows), succeeded,
                )

    logger.info(
        "catalog_images: complete — %d succeeded / %d failed of %d total",
        succeeded, failed, len(rows),
    )
    return ImageDownloadResult(
        total_missing=len(rows),
        succeeded=succeeded,
        failed=failed,
    )


async def stage_download_catalog_images(*, limit: int | None = None) -> None:
    """Pipeline stage wrapper — records into pipeline_runs."""
    with record_stage(PipelineStage.MATCH_PRODUCT, swallow=True) as h:
        result = await download_missing_images(limit=limit)
        h.items_processed = result.total_missing
        h.items_succeeded = result.succeeded
