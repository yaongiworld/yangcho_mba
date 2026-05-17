"""Supabase Storage helper for the product-images bucket.

Thin wrapper around supabase-py's storage API. The bucket itself is
created manually in the Supabase dashboard as a public-read bucket
(see README "Dashboard storage" section).

Why this lives in pipeline/ingestion/: it's only ever called from
catalog_images.py during the daily cron. The dashboard never uploads —
it just reads public URLs that this module produces.
"""

from __future__ import annotations

import logging

from pipeline.db import supabase_client

logger = logging.getLogger(__name__)

BUCKET = "product-images"


def storage_path_for(external_id: str, ext: str = "jpg") -> str:
    """Bucket-relative path for a product's image.

    Keyed on the product's external_id (OY's prdtNo) so re-runs are
    deterministic. Extension defaults to jpg because every image we've
    seen from OY is JPEG.
    """
    return f"{external_id}.{ext}"


_CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def upload_image(external_id: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str | None:
    """Upload an image to the product-images bucket. Returns the bucket-
    relative path on success, None on failure.

    Idempotent in spirit — uses upsert=True so a re-upload for the same
    external_id replaces the existing file. Safe to call repeatedly.
    """
    ext = _CONTENT_TYPE_TO_EXT.get(content_type, "jpg")
    path = storage_path_for(external_id, ext=ext)
    try:
        client = supabase_client()
        client.storage.from_(BUCKET).upload(
            path=path,
            file=image_bytes,
            file_options={
                "content-type": content_type,
                "upsert": "true",  # supabase-py wants this as a string
            },
        )
    except Exception as exc:
        logger.warning(
            "image_storage: upload failed for external_id=%s: %s",
            external_id, exc,
        )
        return None
    return path


def public_url(image_path: str) -> str | None:
    """Build the public URL for an image_path. Returns None on misconfig.

    Used by tests and any pipeline-side code that needs the URL. The
    dashboard builds its own URLs in TypeScript via lib/storage.ts —
    duplicated by design so neither side depends on the other.
    """
    try:
        client = supabase_client()
        return client.storage.from_(BUCKET).get_public_url(image_path)
    except Exception as exc:
        logger.warning("image_storage: public_url failed for %s: %s", image_path, exc)
        return None
