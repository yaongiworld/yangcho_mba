"""Google Trends ingestion — daily trending US searches via the public RSS feed.

The RSS at https://trends.google.com/trends/trendingsearches/daily/rss?geo=US
returns the day's top trending searches (typically 15-20 entries) with
related queries and traffic estimates. Public, no auth, stable for 15+
years.

Why this exists:
  * TikTok's Creative Center was returning 50004 errors for ~5 days
    (2026-05-13 → 2026-05-17). Even when it works, US trending hashtags
    are a thin signal for "American mainstream lifestyle." Google
    searches cover the same population, different angle.
  * Skincare-friction matching tolerates noisy upstream signals — the
    self_rating gate drops things the LLM can't reason about. So
    ingesting Lakers scores alongside skincare trends is fine; only the
    relevant ones survive to publish.

Schema-wise these signals are SourceKind.GOOGLE_TRENDS (added in
migration 0010) and surface in the dashboard's source badge.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from pipeline.cache import cache_get_last_resort, cache_put
from pipeline.schemas import RawSignal, SourceKind

logger = logging.getLogger(__name__)

RSS_URL = "https://trends.google.com/trending/rss?geo=US"
FETCH_TIMEOUT_SECONDS = 15.0
USER_AGENT = "llc-pipeline/0.1 (Google Trends RSS reader; research)"

# RSS uses an `ht:` namespace for extended fields (approx_traffic, news_item, etc.)
HT_NS = "{https://trends.google.com/trending/rss}"


def _parse_traffic(raw: str | None) -> int | None:
    """Google Trends traffic estimates are strings like "500K+" / "2M+".
    Normalize to an int (rounded down). Returns None when un-parseable."""
    if not raw:
        return None
    m = re.match(r"\s*([\d.]+)\s*([KMB]?)\+?\s*", raw)
    if not m:
        return None
    n = float(m.group(1))
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2)]
    return int(n * mult)


def _parse_rss(xml_text: str) -> list[dict]:
    """Extract trending entries from the Google Trends RSS XML.

    Returns dicts with: title, traffic (int or None), news_titles (list[str]),
    pub_date (str). Defensive on missing fields — Google ships shape changes
    occasionally and we don't want to crash on a stray missing element.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("google_trends: RSS parse failed: %s", exc)
        return []

    out: list[dict] = []
    for item in root.iter("item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        title = title_el.text.strip()
        if not title:
            continue
        traffic_el = item.find(f"{HT_NS}approx_traffic")
        traffic_raw = traffic_el.text if traffic_el is not None else None
        pub_el = item.find("pubDate")
        pub_date = pub_el.text if pub_el is not None and pub_el.text else ""
        news_titles: list[str] = []
        for news in item.findall(f"{HT_NS}news_item"):
            nt = news.find(f"{HT_NS}news_item_title")
            if nt is not None and nt.text:
                news_titles.append(nt.text.strip())
        out.append(
            {
                "title": title,
                "traffic_raw": traffic_raw,
                "traffic": _parse_traffic(traffic_raw),
                "pub_date": pub_date,
                "news_titles": news_titles,
            }
        )
    return out


def _entries_to_signals(entries: list[dict]) -> list[RawSignal]:
    out: list[RawSignal] = []
    fetched_at = datetime.now(timezone.utc)
    for e in entries:
        title = e["title"]
        # Include the first news headline in the text so the moment-extraction
        # LLM has context beyond the bare search term. Search terms alone
        # ("Aaron Judge") aren't enough for the friction analyzer to reason
        # about; the news headline ("Aaron Judge home run record") is.
        if e["news_titles"]:
            text = f"{title} — {e['news_titles'][0]}"
        else:
            text = title
        out.append(
            RawSignal(
                source=SourceKind.GOOGLE_TRENDS,
                external_id=f"gtrends:US:{title}",
                text=text,
                created_at=fetched_at,
                metadata={
                    "title": title,
                    "region": "US",
                    "traffic": e["traffic"],
                    "traffic_raw": e["traffic_raw"],
                    "news_titles": e["news_titles"],
                    "pub_date": e["pub_date"],
                },
            )
        )
    return out


def _signals_to_payload(signals: list[RawSignal]) -> list[dict]:
    return [s.model_dump(mode="json") for s in signals]


def _payload_to_signals(payload) -> list[RawSignal]:
    if not isinstance(payload, list):
        return []
    out: list[RawSignal] = []
    for item in payload:
        try:
            out.append(RawSignal.model_validate(item))
        except Exception:
            continue
    return out


async def fetch_google_trends_signals() -> list[RawSignal]:
    """Public entrypoint. Fetch the daily RSS; on failure, fall back to cache.

    Always returns a list. Never raises — Google Trends going down is rare
    but possible, and we'd rather a graceful "no Google Trends today" than
    blow up the whole cron.
    """
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(RSS_URL, timeout=FETCH_TIMEOUT_SECONDS)
            r.raise_for_status()
        entries = _parse_rss(r.text)
        if not entries:
            logger.warning("google_trends: live RSS had no parseable entries; trying cache")
            raise RuntimeError("empty entry list from RSS")
        signals = _entries_to_signals(entries)
        cache_put(SourceKind.GOOGLE_TRENDS, _signals_to_payload(signals))
        logger.info("google_trends: fetched %d trending searches", len(signals))
        return signals
    except Exception as exc:
        logger.warning("google_trends: live fetch failed: %s", exc)

    cached = cache_get_last_resort(SourceKind.GOOGLE_TRENDS)
    if cached is None:
        logger.warning("google_trends: no cached fallback; returning empty")
        return []
    signals = _payload_to_signals(cached)
    logger.info(
        "google_trends: serving %d signals from cache (graceful degradation)",
        len(signals),
    )
    return signals
