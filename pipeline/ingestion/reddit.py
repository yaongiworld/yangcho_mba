"""Reddit ingestion — always-on, the most reliable scraping source.

Per /plan-eng-review Issue 1: Reddit is the always-on backbone of the multi-
source design. TikTok value-adds richness when it works; cultural calendar is
deterministic; Reddit is the realtime signal that keeps the dashboard alive.

Subreddits scanned (all public, all from the design doc):
  - r/SkincareAddiction      — primary signal volume
  - r/AsianBeauty            — K-Beauty-aware audience, lower volume but high relevance
  - r/MakeupAddiction        — long-wear / sweat / heat complaints
  - r/30PlusSkinCare         — barrier / aging frictions
  - r/Sephora                — purchase-intent signal

Filtering: most posts on these subs are NOT complaints. We filter for
negative-sentiment / problem language using a keyword heuristic before passing
to the LLM clustering stage. Heuristic is deliberately permissive — false
positives are cheaper than false negatives at this stage.

On failure: cache_get_last_resort returns the most recent payload, so the
orchestrator still gets data. Empty cache + failed fetch = empty list,
which the orchestrator handles via graceful degradation.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from pipeline.cache import cache_get_last_resort, cache_put
from pipeline.schemas import RawSignal, SourceKind

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "SkincareAddiction",
    "AsianBeauty",
    "MakeupAddiction",
    "30PlusSkinCare",
    "Sephora",
]

# How many top posts to pull per subreddit per run.
POSTS_PER_SUBREDDIT = 50

# Look-back window for "top of last 24 hours" — we use 'day' time filter on PRAW.
# Pulls the highest-scoring posts from the past 24h.
TIME_FILTER = "day"

# Keyword heuristic for "this post is probably a complaint / problem".
# Permissive on purpose — filters out clear non-complaints (showcase, FOTD,
# product hauls) without trying to catch every nuance.
COMPLAINT_PATTERNS = re.compile(
    r"\b("
    r"help|why|problem|issue|broke|breakout|breaking out|burning|stinging|"
    r"itchy|itching|tight|stripped|pilling|melting|patchy|cakey|"
    r"dry|dehydrated|oily|greasy|red|redness|flaking|peeling|"
    r"hate|disappointed|terrible|awful|ruined|"
    r"recommend|alternative|swap|dupe|substitute|"
    r"sensitive|reaction|allergic"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_complaint(text: str) -> bool:
    """Heuristic: does this text contain problem-language?"""
    if not text:
        return False
    return bool(COMPLAINT_PATTERNS.search(text))


def _to_raw_signal(post: Any, subreddit: str) -> RawSignal:
    """Normalize a PRAW submission into a RawSignal."""
    title = post.title or ""
    body = post.selftext or ""
    text = f"{title}\n\n{body}".strip()
    created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
    return RawSignal(
        source=SourceKind.REDDIT,
        external_id=f"reddit:{subreddit}:{post.id}",
        text=text,
        created_at=created,
        metadata={
            "subreddit": subreddit,
            "title": title,
            "score": getattr(post, "score", None),
            "num_comments": getattr(post, "num_comments", None),
            "url": f"https://reddit.com{post.permalink}",
        },
    )


def _build_client():
    """Lazy-init PRAW. Raises clearly if env vars are missing."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "llc-pipeline/0.1 (research)")
    if not client_id or not client_secret:
        raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")

    # Lazy import keeps the rest of the pipeline importable without praw installed.
    import praw

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        check_for_async=False,
    )


def _fetch_live() -> list[RawSignal]:
    """Pull top posts from each subreddit. Filter for complaints. Raise on hard failure."""
    client = _build_client()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    signals: list[RawSignal] = []
    for sub in SUBREDDITS:
        try:
            for post in client.subreddit(sub).top(time_filter=TIME_FILTER, limit=POSTS_PER_SUBREDDIT):
                # Defensive: PRAW occasionally returns posts older than the time filter.
                created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                if created < cutoff:
                    continue
                signal = _to_raw_signal(post, sub)
                if _looks_like_complaint(signal.text):
                    signals.append(signal)
        except Exception as exc:
            # Per-subreddit failure: log and continue. One sub being down doesn't
            # block the rest.
            logger.warning("reddit: subreddit %s failed: %s", sub, exc)
    return signals


def _signals_to_payload(signals: list[RawSignal]) -> list[dict[str, Any]]:
    """Serialize for cache storage (model_dump → JSON-able)."""
    return [s.model_dump(mode="json") for s in signals]


def _payload_to_signals(payload: Any) -> list[RawSignal]:
    """Deserialize cached payload back to RawSignals."""
    if not isinstance(payload, list):
        return []
    out: list[RawSignal] = []
    for item in payload:
        try:
            out.append(RawSignal.model_validate(item))
        except Exception:
            continue
    return out


def fetch_reddit_signals() -> list[RawSignal]:
    """Public entrypoint. Fetch fresh; on failure, fall back to last-known-good cache.

    Always returns a list (possibly empty). Never raises — Reddit failure must
    not break the pipeline. The orchestrator decides what to do with an empty
    list (typically: log and continue with calendar + tiktok).
    """
    try:
        signals = _fetch_live()
        if signals:
            cache_put(SourceKind.REDDIT, _signals_to_payload(signals))
            logger.info("reddit: fetched %d complaint-like posts", len(signals))
            return signals
        # Fresh fetch returned empty (no complaints in last 24h, or all subs failed).
        # Fall through to last-known-good below — better stale than empty.
        logger.warning("reddit: live fetch returned 0 signals; trying cache")
    except Exception as exc:
        logger.warning("reddit: live fetch failed entirely: %s", exc)

    cached = cache_get_last_resort(SourceKind.REDDIT)
    if cached is None:
        logger.warning("reddit: no cached fallback available; returning empty")
        return []
    signals = _payload_to_signals(cached)
    logger.info("reddit: serving %d signals from cache (graceful degradation)", len(signals))
    return signals
