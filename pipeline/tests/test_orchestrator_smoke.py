"""Happy-path E2E smoke test for the orchestrator.

Per /plan-eng-review Issue 9: one happy-path test that walks the orchestrator
through the full pipeline with mocked-out external deps. Verifies wiring,
not behavior of individual modules (those have their own tests).
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import patch

from pipeline.orchestrator.run import (
    ExtractedMoment,
    stage_extract_moments,
    stage_score_moments,
)
from pipeline.schemas import (
    CalendarMoment,
    FrictionAnalysis,
    FrictionItem,
    RawSignal,
    SourceKind,
)


def test_extract_moments_groups_calendar_and_tiktok() -> None:
    """Calendar moments and TikTok hashtags both surface; TikTok hashtags
    matching a calendar moment's keywords attach to it; non-matching
    TikTok hashtags become standalone moments."""
    cal = [
        CalendarMoment(
            name="Sunday Tailgate",
            date_pattern="Sundays September through early January",
            confidence="high",
            friction_hints=["UV + sweat"],
            keywords=["tailgate", "NFL"],
            category="nfl",
        ),
    ]
    tiktok = [
        # Matches the "tailgate" keyword on Sunday Tailgate
        RawSignal(
            source=SourceKind.TIKTOK,
            external_id="t1",
            text="#tailgateprep",
            metadata={"hashtag": "tailgateprep", "volume": 8000, "rank": 2},
        ),
        # Doesn't match any calendar keyword — should become a standalone moment
        RawSignal(
            source=SourceKind.TIKTOK,
            external_id="t2",
            text="#bamarush",
            metadata={"hashtag": "bamarush", "volume": 5000, "rank": 3},
        ),
    ]

    moments = stage_extract_moments(cal, tiktok)

    # Expect: 1 calendar moment (Sunday Tailgate, with t1 attached)
    #         + 1 standalone TikTok moment (#bamarush, didn't match)
    assert len(moments) == 2
    tailgate = next(m for m in moments if "Tailgate" in m.name)
    assert len(tailgate.signals) == 1
    assert tailgate.signals[0].external_id == "t1"

    bamarush = next(m for m in moments if "bamarush" in m.name)
    assert len(bamarush.signals) == 1
    assert bamarush.signals[0].external_id == "t2"


def test_score_moments_ranks_higher_confidence_above_lower() -> None:
    """High-confidence calendar moments edge out low-volume TikTok hashtags
    when signal volume is similar."""
    cal_high = CalendarMoment(
        name="cal-high",
        date_pattern="x",
        confidence="high",
        friction_hints=[],
        keywords=[],
        category="nfl",
    )

    moments = [
        ExtractedMoment(
            name="tiktok-only",
            description="",
            source=SourceKind.TIKTOK,
            signals=[
                RawSignal(source=SourceKind.TIKTOK, external_id="t1", text="x", metadata={})
            ],
            calendar_entry=None,
        ),
        ExtractedMoment(
            name="cal-with-1-signal",
            description="",
            source=SourceKind.CALENDAR,
            signals=[
                RawSignal(source=SourceKind.TIKTOK, external_id="t2", text="y", metadata={})
            ],
            calendar_entry=cal_high,
        ),
    ]

    scored = stage_score_moments(moments)
    # cal-with-1-signal scores 1 + 1.5 (high-confidence bonus) = 2.5
    # tiktok-only scores 1
    assert scored[0].name == "cal-with-1-signal"
    assert scored[0].score > scored[1].score
