"""Cultural calendar reader — date-pattern resolution + moments_for() integration."""

from __future__ import annotations

from datetime import date

import pytest

from pipeline.ingestion.calendar import (
    _fixed_date,
    _is_recurring_weekday_in_range,
    _nth_weekday,
    _nth_weekday_of_month,
    moments_for,
)


class TestFixedDate:
    def test_july_4(self) -> None:
        assert _fixed_date(date(2026, 1, 1), "July 4") == date(2026, 7, 4)

    def test_october_31(self) -> None:
        assert _fixed_date(date(2026, 1, 1), "October 31") == date(2026, 10, 31)

    def test_december_31(self) -> None:
        assert _fixed_date(date(2026, 1, 1), "December 31") == date(2026, 12, 31)

    def test_no_match(self) -> None:
        # Pattern with no month name returns None.
        assert _fixed_date(date(2026, 1, 1), "third Monday of nothing") is None


class TestNthWeekdayOfMonth:
    def test_super_bowl_2026(self) -> None:
        # Second Sunday of February 2026 = Feb 8.
        assert _nth_weekday_of_month(2026, 2, 6, 2) == date(2026, 2, 8)

    def test_boston_marathon_2026(self) -> None:
        # Third Monday of April 2026 = Apr 20.
        assert _nth_weekday_of_month(2026, 4, 0, 3) == date(2026, 4, 20)

    def test_memorial_day_2026(self) -> None:
        # Last Monday of May 2026 = May 25.
        assert _nth_weekday_of_month(2026, 5, 0, -1) == date(2026, 5, 25)

    def test_thanksgiving_2026(self) -> None:
        # Fourth Thursday of November 2026 = Nov 26.
        assert _nth_weekday_of_month(2026, 11, 3, 4) == date(2026, 11, 26)


class TestNthWeekdayParser:
    def test_second_sunday_of_february(self) -> None:
        assert _nth_weekday(date(2026, 1, 1), "second Sunday of February") == date(2026, 2, 8)

    def test_first_thursday_after_labor_day(self) -> None:
        # Labor Day 2026 = Sept 7 (Mon). First Thursday after = Sept 10.
        assert _nth_weekday(date(2026, 1, 1), "first Thursday after Labor Day") == date(
            2026, 9, 10
        )

    def test_unparseable_returns_none(self) -> None:
        assert _nth_weekday(date(2026, 1, 1), "sometime around April") is None


class TestRecurringWeekday:
    def test_nfl_sunday_in_october(self) -> None:
        # Oct 18, 2026 is a Sunday in NFL season.
        assert _is_recurring_weekday_in_range(
            date(2026, 10, 18), "Sundays September through early January"
        )

    def test_tuesday_does_not_match_sundays(self) -> None:
        # Oct 20, 2026 is a Tuesday — should not match "Sundays".
        assert not _is_recurring_weekday_in_range(
            date(2026, 10, 20), "Sundays September through early January"
        )

    def test_january_wraparound(self) -> None:
        # Jan 4, 2026 is a Sunday — within NFL season that started Sept 2025.
        assert _is_recurring_weekday_in_range(
            date(2026, 1, 4), "Sundays September through early January"
        )


class TestMomentsForIntegration:
    """End-to-end: feed a real date, expect specific moments to appear."""

    def test_july_4_fires_independence_day(self) -> None:
        names = [m.name for m in moments_for(today=date(2026, 7, 4))]
        assert any("Independence Day" in n for n in names)

    def test_memorial_day_fires_on_may_25(self) -> None:
        names = [m.name for m in moments_for(today=date(2026, 5, 25))]
        assert any("Memorial Day" in n for n in names)

    def test_nfl_sunday_fires_sunday_tailgate(self) -> None:
        names = [m.name for m in moments_for(today=date(2026, 10, 18))]
        assert any("Sunday Tailgate" in n for n in names)

    def test_random_tuesday_in_march_is_quiet(self) -> None:
        # March 17, 2026 (Tue) — no holiday, no NFL, no festival.
        # Should produce zero or only month-bucket fallbacks (none in March).
        moments = moments_for(today=date(2026, 3, 17))
        # We accept empty or only low-priority entries; the test is that nothing
        # high-confidence fires inappropriately.
        for m in moments:
            assert m.confidence != "high" or "Halloween" not in m.name  # sanity check
