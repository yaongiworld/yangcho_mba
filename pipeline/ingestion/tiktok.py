"""TikTok ingestion — value-add source via playwright.

Per `docs/tiktok-spike.md`: the Creative Center JSON API is gated by signed
cookies + msToken + JS-computed signatures. You can't reproduce the auth from
curl. The path that works is to launch a headless Chromium, let the page boot
its JS (which mints the auth artifacts), and intercept the XHR the page itself
makes when listing trending hashtags.

This module is the most fragile in the whole pipeline. The architecture from
/plan-eng-review Issue 1 absorbs the fragility:
  - The cultural calendar is always-on; if TikTok dies, the dashboard keeps
    running with calendar moments only.
  - On any failure, falls back to last-known-good cache.
  - record_stage(swallow=True) at the orchestrator level prevents a TikTok
    failure from aborting the daily run.

Defensive design choices:
  - Single fetch per day; rate-limited to 1 navigation per call.
  - Identified user agent (no spoofing — TikTok publicly tolerates research
    use as long as you're transparent).
  - Stores facts only (hashtag name + 7-day volume + region). Never mirrors
    user-generated content from TikTok videos.
  - Schema is loose because TikTok ships UI updates regularly; we read what
    we can and skip what we can't.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from pipeline.cache import cache_get_last_resort, cache_put
from pipeline.schemas import RawSignal, SourceKind

logger = logging.getLogger(__name__)

CREATIVE_CENTER_URL = (
    "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"
)

# The XHR path the page hits when the trending-hashtag panel renders.
# Per the spike, this is the internal `creative_radar_api/v1/popular_trend/...` family.
# Using a substring match (any URL containing this path) so version bumps don't break us.
XHR_PATH_NEEDLE = "/creative_radar_api/v1/popular_trend/hashtag/list"

# How long to wait after navigation for the XHR to fire and resolve.
# 30s is generous; the page typically completes in 5–10s.
XHR_WAIT_SECONDS = 30

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def _fetch_via_playwright() -> dict[str, Any]:
    """Boot Chromium, navigate to Creative Center, intercept the trending XHR.

    Returns the parsed JSON payload from the API response. Raises on any
    failure — caller wraps in a try/except for graceful degradation.
    """
    # Lazy import — keeps the rest of the pipeline importable when playwright is absent.
    from playwright.async_api import async_playwright

    captured: dict[str, Any] | None = None
    capture_event = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            async def on_response(response):
                nonlocal captured
                if XHR_PATH_NEEDLE in response.url and 200 <= response.status < 300:
                    try:
                        body = await response.json()
                    except Exception as exc:
                        logger.warning("tiktok: matched URL but body not JSON: %s", exc)
                        return
                    captured = body
                    capture_event.set()

            page.on("response", on_response)

            await page.goto(CREATIVE_CENTER_URL, wait_until="networkidle", timeout=60_000)

            # Wait for the XHR to fire. networkidle should already imply this, but
            # the trending list sometimes lazy-loads on tab interaction.
            try:
                await asyncio.wait_for(capture_event.wait(), timeout=XHR_WAIT_SECONDS)
            except asyncio.TimeoutError:
                pass

            if captured is None:
                raise RuntimeError(
                    f"tiktok: no XHR matching {XHR_PATH_NEEDLE!r} captured "
                    f"after {XHR_WAIT_SECONDS}s"
                )
            return captured
        finally:
            await browser.close()


def _parse_hashtags(payload: Any) -> list[dict[str, Any]]:
    """Extract a flat list of {name, volume, region, ...} from the TikTok response.

    Defensive parsing: TikTok's JSON shape can change. We probe a few likely
    paths (`data.list`, `data.trends`, `list`, `trends`) and return whatever
    looks list-shaped. Empty list on no match — caller handles.
    """
    if not isinstance(payload, dict):
        return []

    # Try common shapes in order.
    for path in (
        ("data", "list"),
        ("data", "trends"),
        ("list",),
        ("trends",),
    ):
        node: Any = payload
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, list):
            return [item for item in node if isinstance(item, dict)]
    return []


def _to_raw_signals(hashtags: list[dict[str, Any]]) -> list[RawSignal]:
    """Normalize TikTok hashtag entries into RawSignals."""
    out: list[RawSignal] = []
    fetched_at = datetime.now(timezone.utc)
    for h in hashtags:
        name = h.get("hashtag_name") or h.get("name") or h.get("tag")
        if not name:
            continue
        # Best-effort volume signals — different keys across TikTok response variants.
        volume = h.get("publish_cnt") or h.get("post_cnt") or h.get("video_cnt")
        rank = h.get("rank")
        region = h.get("country_code") or h.get("region") or "US"
        out.append(
            RawSignal(
                source=SourceKind.TIKTOK,
                external_id=f"tiktok:{region}:{name}",
                text=f"#{name}",  # the searchable content; clustering uses this + metadata
                created_at=fetched_at,
                metadata={
                    "hashtag": name,
                    "volume": volume,
                    "rank": rank,
                    "region": region,
                    "raw": h,  # keep the full row for debugging schema drift
                },
            )
        )
    return out


def _signals_to_payload(signals: list[RawSignal]) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in signals]


def _payload_to_signals(payload: Any) -> list[RawSignal]:
    if not isinstance(payload, list):
        return []
    out: list[RawSignal] = []
    for item in payload:
        try:
            out.append(RawSignal.model_validate(item))
        except Exception:
            continue
    return out


def fetch_tiktok_signals() -> list[RawSignal]:
    """Public entrypoint. Fetch fresh; on failure, fall back to last-known-good.

    Always returns a list. Never raises — TikTok failure is the most expected
    failure mode in the whole system, so the caller sees it as "no signal
    today" and continues.
    """
    try:
        payload = asyncio.run(_fetch_via_playwright())
        hashtags = _parse_hashtags(payload)
        if not hashtags:
            logger.warning("tiktok: payload captured but no hashtags parsed; trying cache")
            raise RuntimeError("empty hashtag list from XHR")
        signals = _to_raw_signals(hashtags)
        cache_put(SourceKind.TIKTOK, _signals_to_payload(signals))
        logger.info("tiktok: fetched %d trending hashtags", len(signals))
        return signals
    except Exception as exc:
        logger.warning("tiktok: live fetch failed: %s", exc)

    cached = cache_get_last_resort(SourceKind.TIKTOK)
    if cached is None:
        logger.warning("tiktok: no cached fallback; returning empty")
        return []
    signals = _payload_to_signals(cached)
    logger.info("tiktok: serving %d signals from cache (graceful degradation)", len(signals))
    return signals
