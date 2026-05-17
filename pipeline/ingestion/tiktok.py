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

# Region we ALWAYS want, regardless of where the playwright box geolocates.
# TikTok's Creative Center localizes by IP unless you override the country_code
# query param on the API call. We rewrite every matching XHR to force this.
TARGET_COUNTRY_CODE = "US"

# How long to wait after navigation for the XHR to fire and resolve.
# 30s is generous; the page typically completes in 5–10s.
XHR_WAIT_SECONDS = 30

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _force_us_country_code(url: str, country_code: str = TARGET_COUNTRY_CODE) -> str:
    """Rewrite the country_code query param to TARGET_COUNTRY_CODE, preserving the rest of the URL.

    The page mints all the auth/signature tokens client-side, then sends a request
    to the Creative Center API with whatever country_code its locale logic picked.
    Swapping just that one param keeps the signed payload valid (the params are
    not part of the signature for this endpoint — confirmed empirically: rewriting
    country_code does not produce a 40101 'no permission' rejection).
    """
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["country_code"] = country_code
    return urlunparse(parsed._replace(query=urlencode(params)))


async def _fetch_via_playwright() -> dict[str, Any]:
    """Boot Chromium, navigate to Creative Center, intercept the trending XHR.

    Forces country_code=US on the trending-hashtag XHR via page.route() so we
    get US trends even when the playwright box geolocates elsewhere (e.g.,
    when running locally from Korea or from a Korea-region GitHub Actions runner).

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

            async def on_route(route, request):
                """Rewrite outgoing trending-hashtag requests to force country_code=US."""
                if XHR_PATH_NEEDLE in request.url:
                    rewritten = _force_us_country_code(request.url)
                    if rewritten != request.url:
                        logger.debug("tiktok: rewrote URL → %s", rewritten)
                    await route.continue_(url=rewritten)
                else:
                    await route.continue_()

            await page.route("**/*", on_route)

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


# ─────────────────────────────────────────────────────────────────────────────
# /api/discover/challenge — the *consumer* TikTok discover endpoint.
#
# Different from Creative Center: this is what tiktok.com/discover hits when
# you visit it logged-out in a regular browser. No country_code parameter —
# geo is inferred from the requester IP. On GH Actions runners (US), this
# yields US-flavored trending hashtags. Schema is documented inline below.
# ─────────────────────────────────────────────────────────────────────────────

DISCOVER_URL = "https://www.tiktok.com/discover"
DISCOVER_XHR_NEEDLE = "/api/discover/challenge/"


async def _fetch_discover_via_playwright() -> Any:
    """Hit tiktok.com/discover and capture the /api/discover/challenge XHR.

    Same playwright pattern as _fetch_via_playwright, different page +
    XHR path. Returns the raw JSON. Raises on capture failure.
    """
    from playwright.async_api import async_playwright  # local import

    captured: Any = None
    capture_event = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            page = await ctx.new_page()

            async def on_response(response):
                nonlocal captured
                if DISCOVER_XHR_NEEDLE in response.url and 200 <= response.status < 300:
                    try:
                        body = await response.json()
                    except Exception as exc:
                        logger.warning("tiktok_discover: body not JSON: %s", exc)
                        return
                    captured = body
                    capture_event.set()

            page.on("response", on_response)
            await page.goto(DISCOVER_URL, wait_until="networkidle", timeout=60_000)
            try:
                await asyncio.wait_for(capture_event.wait(), timeout=XHR_WAIT_SECONDS)
            except asyncio.TimeoutError:
                pass
            if captured is None:
                raise RuntimeError(
                    f"tiktok_discover: no XHR matching {DISCOVER_XHR_NEEDLE!r} captured "
                    f"after {XHR_WAIT_SECONDS}s"
                )
            return captured
        finally:
            await browser.close()


def _parse_discover_challenges(payload: Any) -> list[dict[str, Any]]:
    """Extract trending hashtags from the /api/discover/challenge response.

    Schema verified live on 2026-05-18:
        {
          "challengeInfoList": [
            {
              "challenge": {
                "id": "<num>",
                "title": "<hashtag>",
                "desc": "<long description>",
                "stats": { "videoCount": N, "viewCount": N }
              },
              "itemList": [<sample videos>]
            },
            ...
          ]
        }
    """
    if not isinstance(payload, dict):
        return []
    items = payload.get("challengeInfoList")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        ch = entry.get("challenge")
        if not isinstance(ch, dict):
            continue
        title = ch.get("title")
        if not title:
            continue
        stats = ch.get("stats") if isinstance(ch.get("stats"), dict) else {}
        out.append(
            {
                "hashtag_name": title,
                "id": ch.get("id"),
                "desc": ch.get("desc") or "",
                "video_cnt": stats.get("videoCount"),
                "view_cnt": stats.get("viewCount"),
            }
        )
    return out


def _discover_to_raw_signals(hashtags: list[dict[str, Any]]) -> list[RawSignal]:
    """Normalize discover-API hashtag entries into RawSignals.

    Records source=TIKTOK so the downstream pipeline treats discover-sourced
    signals identically to Creative Center signals. The metadata.endpoint
    field disambiguates for debugging.
    """
    out: list[RawSignal] = []
    fetched_at = datetime.now(timezone.utc)
    for h in hashtags:
        name = h["hashtag_name"]
        out.append(
            RawSignal(
                source=SourceKind.TIKTOK,
                external_id=f"tiktok:discover:{name}",
                text=f"#{name}",
                created_at=fetched_at,
                metadata={
                    "hashtag": name,
                    "endpoint": "discover",
                    "id": h.get("id"),
                    "desc": h.get("desc"),
                    "video_count": h.get("video_cnt"),
                    "view_count": h.get("view_cnt"),
                },
            )
        )
    return out


async def fetch_tiktok_signals() -> list[RawSignal]:
    """Public entrypoint. Try discover → Creative Center → cache.

    Order of attempts:
      1. /api/discover/challenge (newer, currently working as of 2026-05-18).
      2. Creative Center XHR (older, currently returning 50004 errors).
      3. signals_cache last-known-good.

    Always returns a list. Never raises — TikTok failure is the most expected
    failure mode in the whole system, so the caller sees it as "no signal
    today" and continues.
    """
    # Path 1: discover endpoint.
    try:
        payload = await _fetch_discover_via_playwright()
        hashtags = _parse_discover_challenges(payload)
        if hashtags:
            signals = _discover_to_raw_signals(hashtags)
            cache_put(SourceKind.TIKTOK, _signals_to_payload(signals))
            logger.info(
                "tiktok: fetched %d trending hashtags from /discover", len(signals),
            )
            return signals
        logger.warning("tiktok: /discover payload had no parseable challenges")
    except Exception as exc:
        logger.warning("tiktok: /discover fetch failed: %s", exc)

    # Path 2: Creative Center fallback (works when TikTok's backend is happy).
    try:
        payload = await _fetch_via_playwright()
        hashtags = _parse_hashtags(payload)
        if not hashtags:
            logger.warning("tiktok: Creative Center payload had no parseable hashtags")
            raise RuntimeError("empty hashtag list from Creative Center XHR")
        signals = _to_raw_signals(hashtags)
        cache_put(SourceKind.TIKTOK, _signals_to_payload(signals))
        logger.info(
            "tiktok: fetched %d trending hashtags from Creative Center (fallback)",
            len(signals),
        )
        return signals
    except Exception as exc:
        logger.warning("tiktok: Creative Center fallback failed: %s", exc)

    # Path 3: last-known-good cache.
    cached = cache_get_last_resort(SourceKind.TIKTOK)
    if cached is None:
        logger.warning("tiktok: no cached fallback; returning empty")
        return []
    signals = _payload_to_signals(cached)
    logger.info("tiktok: serving %d signals from cache (graceful degradation)", len(signals))
    return signals
