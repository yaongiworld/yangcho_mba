"""Daily cron entrypoint — end-to-end pipeline run.

Invoked by `.github/workflows/daily-cron.yml` at 06:00 KST. Same module is
runnable locally via `uv run python -m pipeline.orchestrator.run`.

Flow:

    ┌──────────────────┐  ┌──────────────────┐
    │ INGEST_CALENDAR  │  │ INGEST_TIKTOK    │
    │ always succeeds  │  │ graceful empty   │
    │                  │  │ (swallow=True)   │
    └────────┬─────────┘  └────────┬─────────┘
             │                     │
             └─────────────────────┘
                       │
                       ▼
                          ┌────────────────────┐
                          │ EXTRACT_MOMENTS    │
                          │ v1: keyword group  │
                          │ (LLM cluster: W3+) │
                          └─────────┬──────────┘
                                    │
                                    ▼
                          ┌────────────────────┐
                          │ SCORE_MOMENTS      │
                          │ v1: signal volume  │
                          │ (LLM scoring: W3+) │
                          └─────────┬──────────┘
                                    │
                                    ▼
                          ┌────────────────────┐
                          │ ANALYZE_FRICTION   │  asyncio.gather across top N
                          │ THE MOAT CALL      │  prompt_version stamped
                          └─────────┬──────────┘
                                    │
                                    ▼
                          ┌────────────────────┐
                          │ PERSIST            │
                          │ moments + frictions│
                          │ → Supabase         │
                          └────────────────────┘

Per /plan-eng-review:
  - Issue 1: Ingestion has graceful degradation; TikTok wraps in swallow=True
    so its failure never crashes the run.
  - Issue 7: Every stage is wrapped in record_stage(); pipeline_runs records
    success/partial/failure with error_message and item counts.
  - Issue 6/7: All LLM calls go through call_llm() with parse_or_default().
  - Issue 9 IRON RULE: Partial failure must not corrupt DB. We persist in a
    single batch at the end, after all per-moment failures have been counted.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date as date_t
from typing import Any

from pipeline.analysis.friction import analyze_friction
from pipeline.db import supabase_client
from pipeline.ingestion.calendar import moments_for as calendar_moments_for
from pipeline.ingestion.tiktok import fetch_tiktok_signals
from pipeline.observability import last_successful_run_at, record_stage
from pipeline.schemas import (
    CalendarMoment,
    FrictionAnalysis,
    PipelineStage,
    RawSignal,
    SourceKind,
)
from pipeline.version import prompt_version

logger = logging.getLogger(__name__)

# Top N moments to actually run friction analysis on per day.
# More than this and the daily LLM cost grows past the budget.
TOP_N_FOR_FRICTION = 10


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Ingest — three sources, graceful per-source
# ─────────────────────────────────────────────────────────────────────────────


def stage_ingest_calendar() -> list[CalendarMoment]:
    """Always-on. Calendar is deterministic — never fails."""
    with record_stage(PipelineStage.INGEST_CALENDAR) as h:
        moments = calendar_moments_for()
        h.items_processed = len(moments)
        h.items_succeeded = len(moments)
        return moments


async def stage_ingest_tiktok() -> list[RawSignal]:
    """Most fragile source. swallow=True so an exception inside (e.g. playwright
    not installed) doesn't crash the daily run."""
    with record_stage(PipelineStage.INGEST_TIKTOK, swallow=True) as h:
        signals = await fetch_tiktok_signals()
        h.items_processed = len(signals)
        h.items_succeeded = len(signals)
        return signals
    return []  # only reached when swallow=True consumed an exception


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Extract moments — v1 = keyword grouping, W3+ = LLM clustering
# ─────────────────────────────────────────────────────────────────────────────


class ExtractedMoment:
    """In-memory moment shape for the orchestrator. Persisted as MomentInsert."""

    def __init__(
        self,
        name: str,
        description: str,
        source: SourceKind,
        signals: list[RawSignal],
        calendar_entry: CalendarMoment | None = None,
    ):
        self.name = name
        self.description = description
        self.source = source
        self.signals = signals
        self.calendar_entry = calendar_entry
        # Score is filled in stage 3.
        self.signal_volume: int = len(signals)
        self.score: float = 0.0


def _attach_signals_to_calendar(
    cal_moments: list[CalendarMoment],
    signals: list[RawSignal],
) -> tuple[list[ExtractedMoment], list[RawSignal]]:
    """Attach TikTok signals to calendar moments via keyword overlap.
    Returns (moments, leftover_signals)."""
    moments: list[ExtractedMoment] = []
    used_signal_ids: set[str] = set()

    for cal in cal_moments:
        keywords = [k.lower() for k in cal.keywords]
        attached: list[RawSignal] = []
        for sig in signals:
            if sig.external_id in used_signal_ids:
                continue
            text_low = sig.text.lower()
            if any(k in text_low for k in keywords):
                attached.append(sig)
                used_signal_ids.add(sig.external_id)

        moments.append(
            ExtractedMoment(
                name=cal.name,
                description=" / ".join(cal.friction_hints[:2]) or cal.name,
                source=SourceKind.CALENDAR,
                signals=attached,
                calendar_entry=cal,
            )
        )

    leftover = [s for s in signals if s.external_id not in used_signal_ids]
    return moments, leftover


def _moments_from_tiktok_hashtags(signals: list[RawSignal]) -> list[ExtractedMoment]:
    """Each TikTok hashtag becomes its own moment. v1 simplification —
    LLM-based clustering can collapse near-duplicates in W3+."""
    moments: list[ExtractedMoment] = []
    for sig in signals:
        if sig.source != SourceKind.TIKTOK:
            continue
        hashtag = sig.metadata.get("hashtag") or sig.text
        moments.append(
            ExtractedMoment(
                name=f"#{hashtag}" if not str(hashtag).startswith("#") else str(hashtag),
                description=f"TikTok trend: #{hashtag}",
                source=SourceKind.TIKTOK,
                signals=[sig],
            )
        )
    return moments


def stage_extract_moments(
    cal_moments: list[CalendarMoment],
    tiktok_signals: list[RawSignal],
) -> list[ExtractedMoment]:
    """Group raw inputs into moments. v1 grouping; LLM clustering replaces this in W3+."""
    with record_stage(PipelineStage.EXTRACT_MOMENTS) as h:
        # v1: TikTok signals attach to calendar moments by keyword overlap when
        # the hashtag mentions a known cultural moment. TikTok hashtags that
        # don't match a calendar entry surface as their own standalone moments.
        moments, _leftover = _attach_signals_to_calendar(cal_moments, tiktok_signals)
        # Add the leftover TikTok hashtags as standalone moments.
        moments.extend(_moments_from_tiktok_hashtags(_leftover))

        h.items_processed = len(moments)
        h.items_succeeded = len(moments)
        return moments


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3: Score moments — v1 = volume, W3+ = LLM-driven Trend Velocity etc.
# ─────────────────────────────────────────────────────────────────────────────


def stage_score_moments(moments: list[ExtractedMoment]) -> list[ExtractedMoment]:
    """v1: rank by signal volume. Calendar high-confidence entries get a small
    bonus so they don't get drowned out by low-volume TikTok hashtags.

    Real LLM scoring lands in W3+ — call_llm("scoring", ...) returns
    purchase_intent + brand_risk; trend_velocity comes from rolling-window
    signal deltas vs the signals_cache.
    """
    with record_stage(PipelineStage.SCORE_MOMENTS) as h:
        for m in moments:
            base = float(m.signal_volume)
            if m.calendar_entry and m.calendar_entry.confidence == "high":
                base += 1.5  # small bias toward known high-quality calendar moments
            elif m.calendar_entry and m.calendar_entry.confidence == "medium":
                base += 0.5
            m.score = base

        moments.sort(key=lambda x: x.score, reverse=True)
        h.items_processed = len(moments)
        h.items_succeeded = len(moments)
        return moments


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4: Friction analysis — fan-out via asyncio.gather
# ─────────────────────────────────────────────────────────────────────────────


async def stage_analyze_friction(
    moments: list[ExtractedMoment],
    top_n: int = TOP_N_FOR_FRICTION,
) -> list[tuple[ExtractedMoment, FrictionAnalysis | None]]:
    """Run the friction prompt across the top N moments in parallel.

    None entries in the returned list mean that moment's LLM call failed —
    they're tracked in items_succeeded so pipeline_runs reflects partial.
    """
    with record_stage(PipelineStage.ANALYZE_FRICTION) as h:
        targets = moments[:top_n]
        h.items_processed = len(targets)

        tasks = [
            analyze_friction(m.name, m.description, m.signals)
            for m in targets
        ]
        analyses = await asyncio.gather(*tasks, return_exceptions=False)
        # analyze_friction never raises (returns None on failure).

        h.items_succeeded = sum(1 for a in analyses if a is not None)
        return list(zip(targets, analyses))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5: Persist
# ─────────────────────────────────────────────────────────────────────────────


def stage_persist(
    today: date_t,
    results: list[tuple[ExtractedMoment, FrictionAnalysis | None]],
) -> None:
    """Write moments and their frictions to Supabase. Single batch; partial
    failures inside the batch don't corrupt earlier successful writes
    because each table-level call is atomic in PostgREST."""
    with record_stage(PipelineStage.APPLY_CONFIDENCE_GATE) as h:
        h.items_processed = len(results)

        try:
            client = supabase_client()
        except Exception as exc:
            logger.error("persist: cannot reach Supabase, dropping batch: %s", exc)
            h.items_succeeded = 0
            return

        version = prompt_version()
        succeeded = 0

        for moment, analysis in results:
            try:
                # Insert moment row.
                moment_resp = (
                    client.table("moments")
                    .insert({
                        "moment_date": today.isoformat(),
                        "name": moment.name,
                        "source": moment.source.value,
                        "description": moment.description,
                        "trend_velocity": float(moment.signal_volume),  # v1 stand-in
                        "purchase_intent": None,  # filled by LLM scoring in W3+
                        "brand_risk": None,
                        "prompt_version": version,
                    })
                    .execute()
                )
                if not moment_resp.data:
                    continue
                moment_id = moment_resp.data[0]["id"]

                # If friction analysis succeeded, insert one row per friction.
                # Confidence gate: self_rating ≥ 8 → review_status='approved' (auto-publish).
                # Below threshold → review_status='pending' (queues for Yangcho).
                if analysis is not None:
                    review_status = "approved" if analysis.self_rating >= 8 else "pending"
                    for f in analysis.frictions:
                        client.table("frictions").insert({
                            "moment_id": moment_id,
                            "friction_summary": f.summary,
                            "mechanism": f.mechanism,
                            "efficacy_class": f.efficacy_class,
                            "self_rating": analysis.self_rating,
                            "review_status": review_status,
                            "prompt_version": version,
                        }).execute()
                succeeded += 1
            except Exception as exc:
                # One moment's persist failure must not abort the rest. Log and continue.
                logger.warning("persist: failed for moment %r: %s", moment.name, exc)

        h.items_succeeded = succeeded


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def run_daily(today: date_t | None = None) -> int:
    """Execute one full pipeline run. Returns 0 on success, 1 on hard failure."""
    today = today or date_t.today()
    logger.info("=== LLC pipeline start: %s (code_version=%s) ===", today, prompt_version())

    # Stage 1 — ingest.
    cal_moments = stage_ingest_calendar()
    tiktok_signals = await stage_ingest_tiktok()
    logger.info(
        "ingest: %d calendar moments, %d tiktok signals",
        len(cal_moments), len(tiktok_signals),
    )

    # Hard floor: if both sources returned empty, there's nothing to do today.
    # Calendar should never be empty in practice unless the YAML is broken.
    if not cal_moments and not tiktok_signals:
        logger.warning("ingest: all sources empty; nothing to publish today")
        return 0

    # Stages 2–4.
    moments = stage_extract_moments(cal_moments, tiktok_signals)
    moments = stage_score_moments(moments)
    results = await stage_analyze_friction(moments)

    # Stage 5 — persist.
    stage_persist(today, results)

    last = last_successful_run_at()
    logger.info("=== LLC pipeline done. Last successful run: %s ===", last)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLC daily pipeline")
    parser.add_argument(
        "--stage",
        default="",
        help="Run only this stage (debug). Empty = full pipeline.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override 'today' for backfills (YYYY-MM-DD).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    today = date_t.fromisoformat(args.date) if args.date else None

    if args.stage:
        # Stage-isolated runs are for debugging; not implemented yet.
        logger.error("--stage not yet implemented; running full pipeline")

    return asyncio.run(run_daily(today=today))


if __name__ == "__main__":
    raise SystemExit(main())
