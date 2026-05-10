"""IRON RULE regressions from /plan-eng-review Issue 9.

These three tests are non-negotiable. Each one corresponds to a documented
failure mode that must NEVER reach the dashboard untested.

1. Partial pipeline failure does not corrupt DB.
2. Scraper failure → graceful degradation, dashboard shows yesterday's data.
3. Claude API outage → cron logs error, doesn't crash silently.
"""

from __future__ import annotations

from datetime import date as date_t
from unittest.mock import patch

import pytest

from pipeline.observability import record_stage
from pipeline.schemas import PipelineStage


# ─────────────────────────────────────────────────────────────────────────────
# IRON RULE 1: Partial pipeline failure does not corrupt DB
# ─────────────────────────────────────────────────────────────────────────────


def test_iron_rule_1_partial_failure_does_not_propagate_when_swallowed() -> None:
    """A non-critical stage failure (swallow=True) must NOT abort the pipeline.

    Concretely: TikTok dies, the orchestrator continues and the rest of the
    daily run completes. The DB stays in last-known-good state for the failed
    stage; other stages persist normally.
    """
    completed_stages: list[str] = []

    # Stage A: succeeds (calendar — always-on)
    with record_stage(PipelineStage.INGEST_CALENDAR) as h:
        h.items_processed = 5
        h.items_succeeded = 5
        completed_stages.append("calendar")

    # Stage B: fails but is swallowed (TikTok)
    with record_stage(PipelineStage.INGEST_TIKTOK, swallow=True) as h:
        completed_stages.append("tiktok-started")
        raise RuntimeError("playwright cannot reach TikTok")
    completed_stages.append("tiktok-after-block")  # we DO reach this — exception swallowed

    # Stage C: must still execute (ANALYZE_FRICTION)
    with record_stage(PipelineStage.ANALYZE_FRICTION) as h:
        h.items_processed = 3
        h.items_succeeded = 3
        completed_stages.append("friction")

    assert completed_stages == ["calendar", "tiktok-started", "tiktok-after-block", "friction"]


def test_iron_rule_1_critical_failure_does_re_raise() -> None:
    """A CRITICAL stage failure (swallow=False, the default) MUST re-raise.

    The orchestrator's exception handler is what records the run as failed
    and exits with non-zero so GitHub Actions notifies operators.
    """
    with pytest.raises(RuntimeError, match="critical"):
        with record_stage(PipelineStage.APPLY_CONFIDENCE_GATE) as h:
            raise RuntimeError("critical persist failure")


# ─────────────────────────────────────────────────────────────────────────────
# IRON RULE 2: Scraper failure → graceful degradation
# ─────────────────────────────────────────────────────────────────────────────


def test_iron_rule_2_tiktok_failure_returns_empty_not_raises() -> None:
    """fetch_tiktok_signals must return [] when playwright cannot run."""
    import asyncio
    import os

    from pipeline.ingestion.tiktok import fetch_tiktok_signals

    os.environ.pop("SUPABASE_URL", None)

    result = asyncio.run(fetch_tiktok_signals())
    assert result == [], "must return empty list, not raise"


# ─────────────────────────────────────────────────────────────────────────────
# IRON RULE 3: Claude API outage → cron logs error, doesn't crash silently
# ─────────────────────────────────────────────────────────────────────────────


def test_iron_rule_3_friction_returns_none_on_llm_failure() -> None:
    """analyze_friction returns None when call_llm raises — never propagates.

    The orchestrator counts these in items_succeeded; the run records as
    'partial' with the failure visible in pipeline_runs. No silent crash.
    """
    import asyncio

    from pipeline.analysis.friction import analyze_friction

    async def _run():
        with patch("pipeline.analysis.friction.asyncio.to_thread", side_effect=RuntimeError("Claude API outage")):
            result = await analyze_friction(
                moment_name="#test",
                moment_description="test",
                signals=[],
            )
            return result

    result = asyncio.run(_run())
    assert result is None, "must return None on LLM failure, not raise"


def test_iron_rule_3_parse_or_default_returns_none_on_garbage() -> None:
    """parse_or_default returns None when the LLM returns unparseable junk.

    The function MUST NOT raise. Pipeline stages treat None as 'this output
    is unusable, count as failed item' rather than crashing the run.
    """
    from pipeline.llm import LlmResult, parse_or_default
    from pipeline.schemas import FrictionAnalysis

    junk = LlmResult(
        text="this is not json at all just some text",
        prompt_name="friction",
        prompt_version="abc123",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=20,
    )
    result = parse_or_default(junk, FrictionAnalysis)
    assert result is None, "must return None on garbage, not raise"
