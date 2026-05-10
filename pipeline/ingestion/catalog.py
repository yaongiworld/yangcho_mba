"""Olive Young Global product catalog scraper.

Two-pass scraping pattern (per /plan-eng-review Issue 3 + W2 spike on 2026-05-11):

  Pass A (this module): the cheap pass.
    Hit OY Global's category-listing JSON API directly. Returns structured
    product data (name, brand, brand_no, prdtNo, category) with pagination.
    No HTML parsing, no playwright — straight POST + JSON.

  Pass B (pipeline/ingestion/vision.py, separate module): the expensive pass.
    For products that pass the brand filter, capture marketing images via
    playwright, run Gemini Flash 2.5 vision-OCR. Only on filtered subset.

How we got here:
  - Initial sitemap+og:meta scrape found OY Global's full sitemap is health
    & beauty broadly (sanitary pads, French pharmacy, bath bombs, etc.).
  - Spike on the live category page revealed a public POST endpoint that
    returns clean JSON: /display/category/product-data/.
  - The endpoint exposes brand IDs as `brandNoList` and supports server-side
    filtering. We use this to fetch only K-Beauty skincare/makeup/suncare.

OY Korea (oliveyoung.co.kr) — explicitly out of scope: returns 403 with an
anti-bot interstitial. We respect their signal and don't bypass it.

robots.txt: /display is `Allow:`-listed for major crawlers. We send an
identified UA + rate-limit at 1 req/sec.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

API_URL = "https://global.oliveyoung.com/display/category/product-data/"

# Category IDs for K-Beauty-relevant top-level categories. Pulled from the
# nav menu of global.oliveyoung.com on 2026-05-11. Each call to the API
# scopes to one ctgrNo at a time.
KBEAUTY_CATEGORIES = {
    "Skincare": "1000000008",
    "Suncare": "1000000011",
    "Face Masks": "1000000003",
    "Makeup": "1000000031",
}

# OY's API paginates 24-by-default, but accepts higher rowsPerPage. Capping
# at 100 to stay polite and avoid any hidden server limit.
PAGE_SIZE = 100

# Rate limit: 1 request per second between API calls. OY's robots.txt allows
# Googlebot/Bingbot crawling, so 1 rps is conservative.
RATE_LIMIT_SECONDS = 1.0

REQUEST_TIMEOUT_SECONDS = 30.0
USER_AGENT = "llc-pipeline/0.1 (catalog scrape; research; contact via repo)"

# OY Global serves product images from a separate CDN host. The product-data
# API returns relative paths (e.g. "prdtImg/1980/abc.jpg"); we prefix with
# this host to get a fetchable URL.
IMAGE_CDN_HOST = "https://cdn-image.oliveyoung.com/"

# Cap to avoid runaway pagination during smoke runs.
DEFAULT_MAX_PAGES_PER_CATEGORY = 50  # = up to 5000 products per category at PAGE_SIZE=100


# ─────────────────────────────────────────────────────────────────────────────
# Output shape
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProductFacts:
    """Pass-A scraping output. Pass-B vision-OCR fills claims/ingredients later."""

    external_id: str       # OY's prdtNo
    brand: str             # human-readable brand name
    brand_no: str          # OY's internal brand ID (e.g., "B00096")
    name: str              # product name
    public_url: str
    image_url: str | None
    category: str          # high-level category from OY (Skincare/Makeup/...)


@dataclass(frozen=True)
class BrandFacet:
    """One entry from the brandFacets array — used to discover what brands
    OY actually carries. The format from the API is `B00096^BEYOND` — we
    split into (brand_no, name)."""

    brand_no: str
    name: str
    product_count: int


# ─────────────────────────────────────────────────────────────────────────────
# API request helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_request_body(
    ctgr_no: str,
    page_num: int,
    rows_per_page: int = PAGE_SIZE,
    brand_nos: list[str] | None = None,
) -> dict[str, Any]:
    """Construct the POST body for /display/category/product-data/.

    Mirrors the body the SPA sends. `brandNoList` is a server-side filter:
    pass a list of brand_no strings (e.g. ["B00096"]) to restrict to those
    brands only. Empty list = all brands in the category.
    """
    return {
        "accParam": "",
        "langCode": "en",
        "previewDate": "",
        "encKey": "",
        "encText": "",
        "dlvCntry": "9999",
        "mrgnCntryCode": "",
        "attrValNo": "",
        "ctgrNo": ctgr_no,
        "prdtSortStdrCode": "10",  # default sort
        "pageNum": page_num,
        "rowsPerPage": str(rows_per_page),
        "attrValNoList": {},
        "brandNoList": brand_nos or [],
        "ctgrNoList": [],
        "eventSlprcDscntRt": [],
        "reviewScore": [],
        "scrollY": 0,
    }


async def _post_json(client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(API_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# Parsing OY's product hit shape
# ─────────────────────────────────────────────────────────────────────────────


def _hit_to_facts(hit: dict[str, Any], category: str) -> ProductFacts | None:
    """Normalize one entry from data['hits']['hit'] into ProductFacts.

    Field names verified empirically on 2026-05-11 against OY Global's
    product-data API: `prdtNo`, `prdtName`, `brandName`, `brandNo`, `imagePath`.
    `imagePath` is a relative CDN path; we prefix with IMAGE_CDN_HOST.
    """
    fields = hit.get("fields") or {}

    external_id = fields.get("prdtNo")
    if not external_id:
        return None

    name = fields.get("prdtName")
    if not name or not isinstance(name, str):
        return None

    brand = fields.get("brandName") or ""
    brand_no = fields.get("brandNo") or ""

    # imagePath is a relative CDN path; build a fetchable URL.
    image_url: str | None = None
    image_path = fields.get("imagePath")
    if isinstance(image_path, str) and image_path.strip():
        image_url = IMAGE_CDN_HOST + image_path.lstrip("/")

    public_url = f"https://global.oliveyoung.com/product/detail?prdtNo={external_id}"

    return ProductFacts(
        external_id=str(external_id),
        brand=str(brand),
        brand_no=str(brand_no),
        name=str(name).strip(),
        public_url=public_url,
        image_url=image_url,
        category=category,
    )


def _parse_brand_facets(brand_facets: list[dict[str, Any]]) -> list[BrandFacet]:
    """Parse brandFacets entries. Each `value` is "BRAND_NO^BRAND_NAME"."""
    out: list[BrandFacet] = []
    for f in brand_facets:
        raw = f.get("value", "")
        count = int(f.get("count", 0))
        if "^" not in raw:
            continue
        brand_no, name = raw.split("^", 1)
        if not brand_no or not name:
            continue
        out.append(BrandFacet(brand_no=brand_no, name=name, product_count=count))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def fetch_brand_facets(
    *,
    category: str = "Skincare",
    client: httpx.AsyncClient | None = None,
) -> list[BrandFacet]:
    """Discover what brands OY Global carries in a given category.

    One API call. Returns the full brand list with product counts. Useful
    for building / refreshing the K-Beauty brand allowlist.
    """
    if client is None:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as c:
            return await fetch_brand_facets(category=category, client=c)

    ctgr_no = KBEAUTY_CATEGORIES.get(category)
    if ctgr_no is None:
        raise ValueError(f"unknown category {category!r}; known: {list(KBEAUTY_CATEGORIES)}")

    data = await _post_json(client, _build_request_body(ctgr_no, page_num=1, rows_per_page=24))
    return _parse_brand_facets(data.get("brandFacets", []))


async def scrape_category(
    category: str,
    *,
    brand_nos: list[str] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES_PER_CATEGORY,
    rate_limit_seconds: float = RATE_LIMIT_SECONDS,
    client: httpx.AsyncClient | None = None,
) -> list[ProductFacts]:
    """Pull all products in a top-level OY category, optionally filtered by brand IDs.

    Pages through results until we've drained the category or hit max_pages.
    Per-page failures are logged and skipped — never raises.
    """
    if client is None:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as c:
            return await scrape_category(
                category,
                brand_nos=brand_nos,
                max_pages=max_pages,
                rate_limit_seconds=rate_limit_seconds,
                client=c,
            )

    ctgr_no = KBEAUTY_CATEGORIES.get(category)
    if ctgr_no is None:
        raise ValueError(f"unknown category {category!r}; known: {list(KBEAUTY_CATEGORIES)}")

    out: list[ProductFacts] = []
    seen_ids: set[str] = set()
    total_found: int | None = None

    for page in range(1, max_pages + 1):
        body = _build_request_body(ctgr_no, page_num=page, brand_nos=brand_nos)
        try:
            data = await _post_json(client, body)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("catalog: %s page %d failed: %s", category, page, exc)
            break

        hits = data.get("hits", {}).get("hit") or []
        if not hits:
            break

        if total_found is None:
            total_found = int(data.get("hits", {}).get("found", 0))
            logger.info(
                "catalog: %s — %d total products (filter brand_nos=%s)",
                category, total_found, brand_nos or "(all)",
            )

        new_this_page = 0
        for hit in hits:
            facts = _hit_to_facts(hit, category=category)
            if facts is None:
                continue
            if facts.external_id in seen_ids:
                continue
            seen_ids.add(facts.external_id)
            out.append(facts)
            new_this_page += 1

        # If we got 0 new results, we've reached the end (some sites repeat the
        # last page when paging past the limit).
        if new_this_page == 0:
            break

        # Stop early once we've passed the reported total.
        if total_found is not None and len(out) >= total_found:
            break

        if page < max_pages:
            await asyncio.sleep(rate_limit_seconds)

    logger.info("catalog: %s scrape complete — %d products captured", category, len(out))
    return out
