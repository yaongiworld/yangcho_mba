"""Cultural calendar reader — always-on ingestion source.

Loads `data/calendar.yaml` and resolves each entry's `date_pattern` against a
target date to determine whether the moment is "active" today. The bar for
"active" is intentionally loose: a moment counts as today's signal if today
falls within a window around the pattern's resolved date.

Design choices, all deliberate:

1. **Loose matching beats false negatives.** The dashboard's failure mode is
   "no content today, looks broken". Better to surface Memorial Day Weekend
   for the whole 3-day window than to miss it because today is technically
   the day before.
2. **Recurring weekday-in-range patterns get an "is active today?" check.**
   Sundays in NFL season pass when today is a Sunday in that range.
3. **Vague month patterns ("early-to-mid October") fall back to month bucketing.**
   They surface for the whole month with lower priority. Fine at portfolio scale.
4. **Unparseable patterns are not errors.** They just don't fire and we log
   once. Better than crashing the always-on source.

Pure function. No I/O beyond reading the YAML file. Fully unit-testable.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from pipeline.schemas import CalendarMoment

logger = logging.getLogger(__name__)

# Default search path. Tests override via `load_calendar(path=...)`.
DEFAULT_CALENDAR_PATH = Path(__file__).parent.parent.parent / "data" / "calendar.yaml"

# How many days around a one-shot date to consider the moment "active".
# A festival that runs Friday–Sunday should still appear on Thursday afternoon
# and Monday morning in trending content.
DEFAULT_WINDOW_DAYS = 3

# How many days of slack to apply around recurring weekday-in-range patterns.
# Sundays in NFL season should fire on Sundays only, no slack.
RECURRING_WINDOW_DAYS = 0

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}

ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
}

# US federal holidays we reference relative to ("first Thursday after Labor Day").
# Labor Day = first Monday of September.
# Patriots' Day = third Monday of April (Massachusetts).
# Memorial Day = last Monday of May.


@cache
def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_calendar(path: Path | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Return a flat list of (category, entry) pairs from the YAML file.

    Treats every top-level key as a category whose value is a list of entries.
    Skips metadata keys (`version`, `last_reviewed`, `notes`) so the YAML can
    grow new categories without code changes — adding `sports_championships`
    or `music_festivals` Just Works.
    """
    p = path or DEFAULT_CALENDAR_PATH
    data = _load_yaml(p)
    METADATA_KEYS = {"version", "last_reviewed", "notes"}
    out: list[tuple[str, dict[str, Any]]] = []
    for category, entries in data.items():
        if category in METADATA_KEYS or not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                out.append((category, entry))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Date pattern resolvers — one function per pattern shape
# ─────────────────────────────────────────────────────────────────────────────


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date | None:
    """`first Thursday of November`, `last Monday of May` style.

    n: 1..5 for first..fifth, -1 for last.
    Returns None if the month doesn't have that many of the weekday.
    """
    first_of_month = date(year, month, 1)
    days_to_first = (weekday - first_of_month.weekday()) % 7
    first_match = first_of_month + timedelta(days=days_to_first)
    if n == -1:
        # Walk forward in 7-day steps until we'd cross into the next month.
        d = first_match
        while True:
            nxt = d + timedelta(days=7)
            if nxt.month != month:
                return d
            d = nxt
    else:
        candidate = first_match + timedelta(days=7 * (n - 1))
        if candidate.month != month:
            return None
        return candidate


def _fixed_date(today: date, pattern: str) -> date | None:
    """`July 4`, `October 31`, `December 31`."""
    m = re.search(r"\b([A-Z][a-z]+)\s+(\d{1,2})\b", pattern)
    if not m:
        return None
    month_name = m.group(1).lower()
    if month_name not in MONTHS:
        return None
    return date(today.year, MONTHS[month_name], int(m.group(2)))


def _nth_weekday(today: date, pattern: str) -> date | None:
    """`first Thursday after Labor Day`, `second Sunday of February`,
    `third Monday of April`, `last Monday of May`, `fourth Thursday of November`."""

    # Match: "<ordinal> <weekday> of <month>" or "<ordinal> <weekday> after <holiday>"
    m = re.search(
        r"\b(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"\s+(?:of\s+([A-Z][a-z]+)|after\s+(Labor Day|Memorial Day))",
        pattern,
        re.IGNORECASE,
    )
    if not m:
        return None
    ordinal = ORDINALS[m.group(1).lower()]
    weekday = WEEKDAYS[m.group(2).lower()]

    if m.group(3):  # "...of <Month>"
        month_name = m.group(3).lower()
        if month_name not in MONTHS:
            return None
        return _nth_weekday_of_month(today.year, MONTHS[month_name], weekday, ordinal)

    # "...after <holiday>"
    holiday = m.group(4).lower()
    if holiday == "labor day":
        # Labor Day = first Monday of September
        anchor = _nth_weekday_of_month(today.year, 9, WEEKDAYS["monday"], 1)
    elif holiday == "memorial day":
        anchor = _nth_weekday_of_month(today.year, 5, WEEKDAYS["monday"], -1)
    else:
        return None
    if not anchor:
        return None
    # Walk forward to the next occurrence of the named weekday after the anchor.
    days_after = (weekday - anchor.weekday()) % 7 or 7
    return anchor + timedelta(days=days_after)


def _is_recurring_weekday_in_range(today: date, pattern: str) -> bool:
    """`Sundays September through early January` — fires every matching weekday in range.

    We approximate "early January" as Jan 15, "mid-X" as the 15th, "late-X" as the 25th.
    """
    # Find the weekday plural ("Sundays")
    wm = re.search(
        r"\b(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b",
        pattern,
        re.IGNORECASE,
    )
    if not wm:
        return False
    weekday = WEEKDAYS[wm.group(1).lower().rstrip("s")]
    if today.weekday() != weekday:
        return False

    # Find a "<month> through <month>" range.
    rm = re.search(
        r"\b([A-Z][a-z]+)\s+through\s+(?:early\s+|mid-?|late\s+)?([A-Z][a-z]+)",
        pattern,
        re.IGNORECASE,
    )
    if not rm:
        return False
    start_month = MONTHS.get(rm.group(1).lower())
    end_month = MONTHS.get(rm.group(2).lower())
    if not start_month or not end_month:
        return False

    # Build start/end dates anchored on this year. Handle wraparound (Sept→Jan).
    start = date(today.year, start_month, 1)
    if end_month >= start_month:
        last_day = calendar.monthrange(today.year, end_month)[1]
        end = date(today.year, end_month, last_day)
    else:
        # wraps to next year
        if today.month >= start_month:
            last_day = calendar.monthrange(today.year + 1, end_month)[1]
            end = date(today.year + 1, end_month, last_day)
        else:
            # we're in the wraparound months (Jan/Feb side), shift start back a year
            start = date(today.year - 1, start_month, 1)
            last_day = calendar.monthrange(today.year, end_month)[1]
            end = date(today.year, end_month, last_day)
    return start <= today <= end


def _vague_month_match(today: date, pattern: str) -> bool:
    """Last-resort matcher for "approximately mid-August", "early-to-mid October",
    "two consecutive weekends in mid-April", "third weekend of May".

    Returns True if today is in the month named in the pattern. Coarse but safe —
    a moment surfacing for the whole month is better than missing it entirely.
    """
    # Find the first month name in the pattern.
    for token in re.findall(r"\b[A-Z][a-z]+\b", pattern):
        m = MONTHS.get(token.lower())
        if m == today.month:
            return True
    return False


def _resolve_pattern(today: date, pattern: str) -> date | bool | None:
    """Return:
    - a `date` if the pattern resolves to a one-shot day this year
    - True if the pattern resolves to "today is in a recurring window"
    - False if the pattern resolves but we're not in the window
    - None if the pattern is unparseable
    """
    # Fixed date — most specific, try first.
    fixed = _fixed_date(today, pattern)
    if fixed:
        return fixed

    # Nth-weekday-of-month / Nth-weekday-after-holiday.
    nth = _nth_weekday(today, pattern)
    if nth:
        return nth

    # Recurring weekday in date range — only meaningful as is-today-active.
    if _is_recurring_weekday_in_range(today, pattern):
        return True

    # Vague month bucket fallback.
    if _vague_month_match(today, pattern):
        return True

    return None


def _is_active(today: date, pattern: str, window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """Decide whether a moment is active today given its pattern."""
    resolved = _resolve_pattern(today, pattern)
    if resolved is None:
        logger.debug("calendar: unparseable pattern %r", pattern)
        return False
    if isinstance(resolved, bool):
        return resolved
    # `resolved` is a date — active if today is within ±window_days.
    return abs((today - resolved).days) <= window_days


def moments_for(today: date | None = None, *, path: Path | None = None) -> list[CalendarMoment]:
    """Return all CalendarMoments that are active on `today` (defaults to date.today()).

    This is the public API the orchestrator calls. Always succeeds (worst case
    returns an empty list — never raises on bad patterns).
    """
    if today is None:
        today = date.today()

    out: list[CalendarMoment] = []
    for category, entry in load_calendar(path):
        pattern = entry.get("date_pattern", "")
        if not pattern:
            continue
        if _is_active(today, pattern):
            out.append(
                CalendarMoment(
                    name=entry["name"],
                    date_pattern=pattern,
                    confidence=entry.get("confidence", "medium"),
                    friction_hints=entry.get("friction_hints", []),
                    keywords=entry.get("keywords", []),
                    category=category,
                    details=entry.get("details"),
                )
            )
    return out
