"""URL verifier — does this URL exist AND match the moment topic?

Gemini's GoogleSearch grounding fabricates YouTube video IDs at a high rate
(~60% in our June 7 sample). The IDs look syntactically valid but resolve
to 404. Worse, when an ID happens to resolve, it's often unrelated to the
moment ("Bonnaroo" returning a Morgan Wallen restaurant tour).

This module validates both:

1. **Existence** — call the platform's metadata endpoint. YouTube has oEmbed
   which returns 404 for missing/private IDs. TikTok and Instagram serve
   OpenGraph tags on their public URLs.
2. **Topic match** — tokenize the moment name; require ≥1 meaningful keyword
   to appear in the post title or channel handle. Loose on purpose — a real
   Bonnaroo highlight reel might be titled "Best festival sets 2026" so we
   pull keywords from both moment.name and the channel.

Used both inline (by `moment_enrichment.enrich_moment` for the retry loop)
and as a one-time cleanup tool (by `scripts/clean_broken_urls.py`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

VERIFY_TIMEOUT_SECONDS = 8.0

# Tokens shorter than this aren't worth comparing — too many false matches
# ("nba" is OK but "vs", "the", "of" should be ignored).
_MIN_KEYWORD_LEN = 4

# A baseline browser UA — TikTok and Instagram serve a real (-ish) HTML
# response to mainstream UAs but stub bots aggressively.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_YT_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    title: str | None
    reason: str  # short tag — "ok", "not_found", "http_<code>", "topic_mismatch", "no_match"


def _meaningful_keywords(name: str) -> list[str]:
    """Extract topic keywords from a moment name. Drops short noise words
    and hashtag glue. Anything >= _MIN_KEYWORD_LEN survives."""
    cleaned = re.sub(r"[^a-zA-Z0-9 ]+", " ", name.lower())
    return [w for w in cleaned.split() if len(w) >= _MIN_KEYWORD_LEN]


def _topic_match(title: str | None, moment_name: str) -> bool:
    """Loose topic match: any meaningful keyword from moment_name appearing in
    title is good enough. Returns True if moment_name has no meaningful
    keywords (we have nothing to match against, so don't reject)."""
    keywords = _meaningful_keywords(moment_name)
    if not keywords:
        return True
    if not title:
        return False
    title_low = title.lower()
    return any(k in title_low for k in keywords)


async def _verify_youtube(client: httpx.AsyncClient, url: str) -> VerifyResult:
    """YouTube's oEmbed endpoint returns 404 for missing/private/deleted videos
    and 200 + JSON title+author for real ones. The cleanest existence check
    available for YT without an API key."""
    m = _YT_VIDEO_ID_RE.search(url)
    if not m:
        return VerifyResult(ok=False, title=None, reason="bad_format")
    vid = m.group(1)
    oembed = (
        "https://www.youtube.com/oembed"
        f"?url=https://www.youtube.com/watch?v={vid}&format=json"
    )
    try:
        r = await client.get(oembed)
    except Exception as exc:
        return VerifyResult(ok=False, title=None, reason=f"err:{type(exc).__name__}")
    if r.status_code == 404:
        return VerifyResult(ok=False, title=None, reason="not_found")
    if r.status_code != 200:
        return VerifyResult(ok=False, title=None, reason=f"http_{r.status_code}")
    try:
        data = r.json()
    except Exception:
        return VerifyResult(ok=False, title=None, reason="bad_json")
    title = data.get("title")
    author = data.get("author_name", "")
    # Match against title OR channel — a creator may title a clip without
    # the topic word (Bonnaroo highlight on the festival's own channel).
    combined = f"{title} {author}".strip() if title else None
    return VerifyResult(ok=True, title=combined, reason="ok")


async def _verify_html_og(
    client: httpx.AsyncClient, url: str
) -> VerifyResult:
    """TikTok and Instagram: fetch the page, parse og:title. Their bot-stub
    pages still carry og:title with the post's caption — and when a URL is
    invalid both platforms 404 or redirect to a generic error landing."""
    headers = {"User-Agent": _UA, "Accept": "text/html"}
    try:
        r = await client.get(url, headers=headers, follow_redirects=True)
    except Exception as exc:
        return VerifyResult(ok=False, title=None, reason=f"err:{type(exc).__name__}")
    if r.status_code == 404:
        return VerifyResult(ok=False, title=None, reason="not_found")
    if r.status_code != 200:
        return VerifyResult(ok=False, title=None, reason=f"http_{r.status_code}")
    m = _OG_TITLE_RE.search(r.text)
    if not m:
        # Platforms sometimes serve a non-OG bot stub. Treat as "exists but
        # opaque" — we accept these without topic-checking because we can't
        # see the content. The Yangcho review queue is the safety net.
        return VerifyResult(ok=True, title=None, reason="ok_no_og")
    return VerifyResult(ok=True, title=m.group(1).strip(), reason="ok")


async def verify_url(url: str, moment_name: str) -> VerifyResult:
    """Combined existence + topic check.

    Returns ok=True only when:
      - The URL host is one we know how to verify (YT / TT / IG).
      - The platform's metadata endpoint confirms the resource exists.
      - The title or channel contains at least one meaningful keyword from
        the moment name (skipped when we couldn't extract a title at all).

    Network failures are reported as ok=False with a typed reason; callers
    decide whether to retry or drop the URL.
    """
    low = url.lower()
    async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SECONDS) as client:
        if "youtube.com" in low or "youtu.be" in low:
            res = await _verify_youtube(client, url)
        elif "tiktok.com" in low or "instagram.com" in low:
            res = await _verify_html_og(client, url)
        else:
            return VerifyResult(ok=False, title=None, reason="unknown_host")

    if not res.ok:
        return res

    # Existence confirmed — now topic-check (only when we extracted a title).
    if res.title and not _topic_match(res.title, moment_name):
        logger.info(
            "verify: topic mismatch — title=%r moment=%r",
            res.title[:80], moment_name,
        )
        return VerifyResult(ok=False, title=res.title, reason="topic_mismatch")

    return res
