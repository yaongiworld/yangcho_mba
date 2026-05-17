"""One-off: capture the TikTok Creative Center trending-hashtag JSON and
pretty-print its shape so we can update the parser to match.

The production scraper (pipeline/ingestion/tiktok.py) probes four likely
JSON paths and falls back to empty. TikTok ships UI updates regularly,
and as of 2026-05-18 every live fetch returns 'empty hashtag list from
XHR' — meaning the XHR fires but none of our four paths match. Run this
once, see the actual keys, patch _parse_hashtags() to add the new path.

Usage:
    uv run python -m pipeline.scripts.inspect_tiktok

Defaults to headless=True so it works on the GH Actions runner too;
override with INSPECT_HEADLESS=0 for a visible browser locally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from playwright.async_api import async_playwright

from pipeline.ingestion.tiktok import (
    CREATIVE_CENTER_URL,
    USER_AGENT,
    XHR_PATH_NEEDLE,
    XHR_WAIT_SECONDS,
    _force_us_country_code,
)


def _summarize_shape(value: Any, depth: int = 0, max_depth: int = 4) -> str:
    """Render the JSON shape (keys + types) without dumping every value.
    Bounded depth so we don't blow up on deeply nested objects."""
    indent = "  " * depth
    if depth >= max_depth:
        return f"{indent}<truncated at depth {max_depth}>"

    if isinstance(value, dict):
        if not value:
            return f"{indent}{{}}"
        lines = [f"{indent}{{"]
        for k, v in value.items():
            lines.append(f"{indent}  {k!r}: {type(v).__name__}")
            if isinstance(v, (dict, list)):
                lines.append(_summarize_shape(v, depth + 2, max_depth))
        lines.append(f"{indent}}}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return f"{indent}[]"
        lines = [f"{indent}[ ({len(value)} items, first shown):"]
        lines.append(_summarize_shape(value[0], depth + 1, max_depth))
        lines.append(f"{indent}]")
        return "\n".join(lines)

    return f"{indent}{type(value).__name__} = {value!r}"


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    headless = os.environ.get("INSPECT_HEADLESS", "1") != "0"
    captured: Any = None
    capture_event = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            ctx = await browser.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            page = await ctx.new_page()

            async def on_route(route, request):
                if XHR_PATH_NEEDLE in request.url:
                    await route.continue_(url=_force_us_country_code(request.url))
                else:
                    await route.continue_()
            await page.route("**/*", on_route)

            async def on_response(response):
                nonlocal captured
                if XHR_PATH_NEEDLE in response.url and 200 <= response.status < 300:
                    try:
                        captured = await response.json()
                    except Exception as exc:
                        logger.warning("payload not JSON: %s", exc)
                        return
                    logger.info("captured XHR from %s", response.url)
                    capture_event.set()
            page.on("response", on_response)

            logger.info("navigating to %s", CREATIVE_CENTER_URL)
            await page.goto(CREATIVE_CENTER_URL, wait_until="networkidle", timeout=60_000)

            try:
                await asyncio.wait_for(capture_event.wait(), timeout=XHR_WAIT_SECONDS)
            except asyncio.TimeoutError:
                logger.error("no XHR captured after %ds", XHR_WAIT_SECONDS)
                return 1
        finally:
            await browser.close()

    if captured is None:
        logger.error("no payload captured")
        return 1

    print("\n" + "=" * 60)
    print("RAW PAYLOAD (full JSON, first 5000 chars):")
    print("=" * 60)
    raw = json.dumps(captured, indent=2, ensure_ascii=False)
    print(raw[:5000])
    if len(raw) > 5000:
        print(f"... (truncated, total {len(raw)} chars)")

    print("\n" + "=" * 60)
    print("SHAPE SUMMARY (keys + types, max depth 4):")
    print("=" * 60)
    print(_summarize_shape(captured))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
