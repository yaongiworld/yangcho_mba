"""Shared pytest fixtures.

We avoid hitting the real Supabase or Anthropic SDK in tests. The pipeline
modules are designed to be testable without those — every external client
is lazy-loaded and every external call is wrapped in try/except.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pipeline.schemas import RawSignal, SourceKind


@pytest.fixture
def tiktok_signal() -> RawSignal:
    return RawSignal(
        source=SourceKind.TIKTOK,
        external_id="tiktok:US:SundayTailgate",
        text="#SundayTailgate",
        created_at=datetime(2026, 5, 10, 6, 0, tzinfo=timezone.utc),
        metadata={"hashtag": "SundayTailgate", "volume": 12345, "rank": 1},
    )
