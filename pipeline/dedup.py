"""Cross-day moment dedup — name normalization + recent-friction reuse.

Same-day dedup is enforced by the UNIQUE (moment_date, name) constraint on
moments. Cross-day dedup is application-level: calendar events re-emit the
same moment every day they're in window, so without this layer the pipeline
re-runs friction analysis (~5K tokens) + matcher + playbook for the same
"Met Gala" every single day. With this layer, the second sighting copies
the prior day's frictions for $0.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date as date_t, timedelta

logger = logging.getLogger(__name__)

REUSE_WINDOW_DAYS = 14

# Strip 4-digit years (2024, 2025, 2026, ...) so "Bama Rush 2026" and
# "Bama Rush" collapse. Limited to the 20xx range to avoid stripping
# unrelated 4-digit numbers (event capacities, room numbers, etc.).
_YEAR_RE = re.compile(r"\b20\d{2}\b")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_moment_name(name: str) -> str:
    """Lowercase, drop year suffixes, collapse non-alphanumerics to single space.

    Examples:
        "Bama Rush 2026"         -> "bama rush"
        "#TikTokGoSummerStays"   -> "tiktokgosummerstays"
        "Electric Daisy Carnival (EDC) Las Vegas" -> "electric daisy carnival edc las vegas"
    """
    s = name.lower().strip()
    s = _YEAR_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s).strip()
    return s


@dataclass(frozen=True)
class ReusableFriction:
    """A friction row from a prior moment that can be copied verbatim."""

    summary: str
    mechanism: str
    efficacy_class: str | None
    self_rating: int
    review_status: str  # 'approved' | 'pending' | 'rejected' | 'retracted'
    source_prompt_version: str
    source_moment_id: int


def find_reusable_frictions(
    client,
    moment_name: str,
    today: date_t,
    *,
    window_days: int = REUSE_WINDOW_DAYS,
) -> list[ReusableFriction] | None:
    """Look up frictions from a recent moment with the same normalized name.

    Returns the friction set from the most recent matching moment, or None if
    no match within the window. Callers should use this BEFORE invoking the
    friction LLM — a non-None return means "copy these instead of calling".

    Excludes rejected/retracted frictions (no point reviving Yangcho's no-go).
    """
    norm = normalize_moment_name(moment_name)
    if not norm:
        return None

    cutoff = (today - timedelta(days=window_days)).isoformat()

    # Pull candidates by date window, then filter by normalized name in Python.
    # Supabase doesn't expose our normalize function, and the table is small
    # enough (<1000 rows over any 14-day window) that the filter is cheap.
    try:
        rows = (
            client.table("moments")
            .select("id, moment_date, name")
            .gte("moment_date", cutoff)
            .lt("moment_date", today.isoformat())
            .order("moment_date", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("dedup: moment lookup failed for %r: %s", moment_name, exc)
        return None

    candidates = [r for r in rows if normalize_moment_name(r["name"]) == norm]
    if not candidates:
        return None

    # Walk newest-first; return the first candidate that has usable frictions.
    for cand in candidates:
        try:
            fric_rows = (
                client.table("frictions")
                .select(
                    "friction_summary, mechanism, efficacy_class, self_rating, "
                    "review_status, prompt_version"
                )
                .eq("moment_id", cand["id"])
                .in_("review_status", ["approved", "pending"])
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning(
                "dedup: friction lookup failed for moment_id=%d: %s", cand["id"], exc
            )
            continue

        if not fric_rows:
            continue

        return [
            ReusableFriction(
                summary=r["friction_summary"],
                mechanism=r["mechanism"],
                efficacy_class=r.get("efficacy_class"),
                self_rating=r["self_rating"],
                review_status=r["review_status"],
                source_prompt_version=r["prompt_version"],
                source_moment_id=cand["id"],
            )
            for r in fric_rows
        ]

    return None
