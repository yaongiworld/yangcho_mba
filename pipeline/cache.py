"""Last-known-good cache for ingestion sources.

Implements the graceful-degradation primitive from /plan-eng-review Issue 1:
every ingestion source writes its raw payload here on success; on a fresh
fetch failure, the source falls back to the most recent cached payload.

TTL is enforced at READ time, not write time, so stale entries hang around as
fallback for emergencies (better stale than empty during application week).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pipeline.db import supabase_client
from pipeline.schemas import SourceKind

logger = logging.getLogger(__name__)

# Default TTL for "fresh enough to skip a re-fetch". Sources that fail entirely
# can still get older cache via cache_get_last_resort().
DEFAULT_FRESH_HOURS = 6


def _hash_payload(payload: Any) -> str:
    """Stable hash for change-detection. Sorted-key JSON so dict ordering doesn't fool us."""
    s = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cache_put(source: SourceKind, payload: dict[str, Any] | list[Any]) -> None:
    """Write a successful fetch into signals_cache. Never raises — best-effort write."""
    try:
        client = supabase_client()
        client.table("signals_cache").insert({
            "source": source.value,
            "payload": payload,
            "payload_hash": _hash_payload(payload),
        }).execute()
    except Exception as exc:
        # Caching failures must NOT break ingestion. Just log.
        logger.warning("cache_put failed for %s: %s", source.value, exc)


def cache_get_fresh(
    source: SourceKind,
    *,
    fresh_hours: int = DEFAULT_FRESH_HOURS,
) -> dict[str, Any] | list[Any] | None:
    """Return the latest cached payload IF it's fresher than `fresh_hours` ago.

    Used to skip redundant work — if TikTok was fetched 2h ago and we're rate-
    limited or just want to save API calls, return the cached version.
    """
    try:
        client = supabase_client()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=fresh_hours)
        rows = (
            client.table("signals_cache")
            .select("payload, fetched_at")
            .eq("source", source.value)
            .gte("fetched_at", cutoff.isoformat())
            .order("fetched_at", desc=True)
            .limit(1)
            .execute()
        )
        if not rows.data:
            return None
        return rows.data[0]["payload"]
    except Exception as exc:
        logger.warning("cache_get_fresh failed for %s: %s", source.value, exc)
        return None


def cache_get_last_resort(source: SourceKind) -> dict[str, Any] | list[Any] | None:
    """Return the most recent cached payload regardless of age.

    Used as the graceful-degradation fallback when a fresh fetch fails. Better
    to surface yesterday's data with a "Data refresh delayed" banner than to
    crash the dashboard.
    """
    try:
        client = supabase_client()
        rows = (
            client.table("signals_cache")
            .select("payload, fetched_at")
            .eq("source", source.value)
            .order("fetched_at", desc=True)
            .limit(1)
            .execute()
        )
        if not rows.data:
            return None
        row = rows.data[0]
        age_hours = (
            datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
        ).total_seconds() / 3600
        logger.info(
            "cache_get_last_resort: serving %s payload from %.1fh ago",
            source.value,
            age_hours,
        )
        return row["payload"]
    except Exception as exc:
        logger.warning("cache_get_last_resort failed for %s: %s", source.value, exc)
        return None
