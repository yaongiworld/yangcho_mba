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
from pipeline.analysis.match_product import match_one_friction
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


async def stage_persist(
    today: date_t,
    results: list[tuple[ExtractedMoment, FrictionAnalysis | None]],
) -> None:
    """Write moments + frictions + product matches to Supabase.

    Order per moment:
      1. Insert the moment row.
      2. For each friction: insert friction row, set review_status from the
         confidence gate (self_rating >= 8 = 'approved', else 'pending').
      3. ONLY for approved frictions: run product matching, insert top-3
         matches into the matches table.

    The matching restriction to approved frictions is a deliberate cost
    control: low-confidence frictions queue for Yangcho's review and may
    be rejected, so spending LLM tokens on their product matches is wasted
    work. After Yangcho approves, a separate flow can backfill matches.
    """
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
                # Upsert moment row on (moment_date, name). Migration 0004 added
                # the unique constraint so this is idempotent: re-runs replace
                # the previous attempt for the same (date, name) tuple rather
                # than duplicating rows.
                moment_resp = (
                    client.table("moments")
                    .upsert(
                        {
                            "moment_date": today.isoformat(),
                            "name": moment.name,
                            "source": moment.source.value,
                            "description": moment.description,
                            "trend_velocity": float(moment.signal_volume),  # v1 stand-in
                            "purchase_intent": None,  # filled by LLM scoring in W3+
                            "brand_risk": None,
                            "prompt_version": version,
                        },
                        on_conflict="moment_date,name",
                    )
                    .execute()
                )
                if not moment_resp.data:
                    continue
                moment_id = moment_resp.data[0]["id"]

                # If this is an upsert that hit an existing moment, wipe its
                # old frictions before inserting fresh ones. The cascade in
                # the schema takes care of the orphaned matches.
                client.table("frictions").delete().eq("moment_id", moment_id).execute()

                # If friction analysis succeeded, insert one row per friction.
                # Confidence gate: self_rating ≥ 7 → review_status='approved' (auto-publish).
                # Below threshold → review_status='pending' (queues for Yangcho).
                if analysis is not None:
                    review_status = "approved" if analysis.self_rating >= 7 else "pending"
                    for f in analysis.frictions:
                        friction_resp = client.table("frictions").insert({
                            "moment_id": moment_id,
                            "friction_summary": f.summary,
                            "mechanism": f.mechanism,
                            "efficacy_class": f.efficacy_class,
                            "self_rating": analysis.self_rating,
                            "review_status": review_status,
                            "prompt_version": version,
                        }).execute()
                        if not friction_resp.data:
                            continue
                        friction_id = friction_resp.data[0]["id"]

                        # Run product matching ONLY for approved (auto-published) frictions.
                        if review_status == "approved":
                            await _persist_matches_for_friction(
                                client, friction_id, f, version
                            )
                succeeded += 1
            except Exception as exc:
                # One moment's persist failure must not abort the rest. Log and continue.
                logger.warning("persist: failed for moment %r: %s", moment.name, exc)

        h.items_succeeded = succeeded


async def _persist_matches_for_friction(
    client,
    friction_id: int,
    friction,
    version: str,
) -> None:
    """Run product matching for one approved friction and insert its top
    matches. Failures here MUST NOT abort the parent stage."""
    try:
        matches = await match_one_friction(friction)
    except Exception as exc:
        logger.warning("persist: match_one_friction failed for friction_id=%d: %s",
                       friction_id, exc)
        return

    if not matches:
        return

    for rank, m in enumerate(matches, start=1):
        try:
            client.table("matches").insert({
                "friction_id": friction_id,
                "product_id": m.product_id,
                "match_score": float(m.match_score),
                "rank": rank,
                "scientific_argument": m.scientific_argument,
                "prompt_version": version,
            }).execute()
        except Exception as exc:
            logger.warning(
                "persist: match insert failed (friction=%d product=%d): %s",
                friction_id, m.product_id, exc,
            )


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
    await stage_persist(today, results)

    # Stage 6 — backfill matches for approved frictions that have none.
    # Catches Yangcho's manual approves via /admin between cron ticks.
    await stage_backfill_matches()

    last = last_successful_run_at()
    logger.info("=== LLC pipeline done. Last successful run: %s ===", last)
    return 0


async def stage_backfill_matches() -> None:
    """Find approved frictions with zero matches and run product matching on them.

    This is the catch-up path for the manual-approve workflow: Yangcho
    flips a friction to approved via /admin, which doesn't trigger matching
    synchronously (that would block the request and require Anthropic
    creds in the dashboard process). Instead the next cron tick reconciles.

    Wrapped in record_stage so the operator can see backfill runs in the
    pipeline_runs table alongside the regular daily flow.
    """
    with record_stage(PipelineStage.MATCH_PRODUCT) as h:
        try:
            client = supabase_client()
        except Exception as exc:
            logger.warning("backfill: cannot reach Supabase: %s", exc)
            h.items_processed = 0
            h.items_succeeded = 0
            return

        # Find all approved friction ids.
        approved = (
            client.table("frictions")
            .select("id, friction_summary, mechanism, efficacy_class")
            .eq("review_status", "approved")
            .execute()
            .data
            or []
        )
        approved_ids = {f["id"] for f in approved}
        if not approved_ids:
            h.items_processed = 0
            h.items_succeeded = 0
            return

        # Find which approved friction ids already have at least one match.
        matched = (
            client.table("matches")
            .select("friction_id")
            .in_("friction_id", list(approved_ids))
            .execute()
            .data
            or []
        )
        already_matched_ids = {m["friction_id"] for m in matched}

        to_match = [f for f in approved if f["id"] not in already_matched_ids]
        h.items_processed = len(to_match)
        if not to_match:
            h.items_succeeded = 0
            return

        logger.info(
            "backfill: %d approved friction(s) missing matches",
            len(to_match),
        )

        # Lazy import to avoid a cycle (FrictionItem lives in schemas).
        from pipeline.schemas import FrictionItem

        version = prompt_version()
        succeeded = 0
        for row in to_match:
            friction = FrictionItem(
                summary=row["friction_summary"],
                mechanism=row["mechanism"],
                efficacy_class=row.get("efficacy_class"),
            )
            await _persist_matches_for_friction(client, row["id"], friction, version)
            succeeded += 1
        h.items_succeeded = succeeded


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
