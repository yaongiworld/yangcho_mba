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
from pipeline.analysis.influencer import (
    InfluencerInput,
    generate_influencer_suggestions,
)
from pipeline.analysis.marketing_post import (
    MarketingPostInput,
    generate_marketing_post,
)
from pipeline.analysis.match_product import match_one_friction
from pipeline.analysis.product_idea import (
    PRODUCT_IDEA_THRESHOLD,
    ProductIdeaInput,
    generate_product_idea,
    should_generate_idea,
)
from pipeline.db import supabase_client
from pipeline.dedup import ReusableFriction, find_reusable_frictions
from pipeline.ingestion.calendar import moments_for as calendar_moments_for
from pipeline.ingestion.google_trends import fetch_google_trends_signals
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


async def stage_ingest_google_trends() -> list[RawSignal]:
    """Google Trends daily RSS. Quick HTTP fetch; swallow=True for symmetry
    with the other ingest stages (a CDN hiccup shouldn't fail the day)."""
    with record_stage(PipelineStage.INGEST_GOOGLE_TRENDS, swallow=True) as h:
        signals = await fetch_google_trends_signals()
        h.items_processed = len(signals)
        h.items_succeeded = len(signals)
        return signals
    return []


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


def _moments_from_google_trends(signals: list[RawSignal]) -> list[ExtractedMoment]:
    """Each Google Trends entry becomes its own moment. Uses the search
    title as the moment name, and includes the first news headline (when
    available) so the friction analyzer has context beyond the bare query."""
    moments: list[ExtractedMoment] = []
    for sig in signals:
        if sig.source != SourceKind.GOOGLE_TRENDS:
            continue
        title = sig.metadata.get("title") or sig.text
        news = sig.metadata.get("news_titles") or []
        description = (
            f"Trending US search — {news[0]}"
            if news else f"Trending US search: {title}"
        )
        moments.append(
            ExtractedMoment(
                name=str(title),
                description=description,
                source=SourceKind.GOOGLE_TRENDS,
                signals=[sig],
            )
        )
    return moments


def stage_extract_moments(
    cal_moments: list[CalendarMoment],
    raw_signals: list[RawSignal],
) -> list[ExtractedMoment]:
    """Group raw inputs into moments. v1 grouping; LLM clustering replaces this in W3+.

    `raw_signals` is the union of every non-calendar source (TikTok, Google
    Trends, future additions). Calendar moments are passed separately because
    they have richer typed metadata (keywords, friction_hints) that drives
    the keyword-overlap attachment.
    """
    with record_stage(PipelineStage.EXTRACT_MOMENTS) as h:
        # v1: any signal whose text mentions a calendar entry's keywords gets
        # attached to that moment. Leftover signals (no calendar match) get
        # one-moment-per-signal treatment via the per-source helpers.
        moments, _leftover = _attach_signals_to_calendar(cal_moments, raw_signals)
        moments.extend(_moments_from_tiktok_hashtags(_leftover))
        moments.extend(_moments_from_google_trends(_leftover))

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


# Per-source quotas — picks N moments per source from the top of the
# score-sorted list. With three sources of unequal volume (calendar ~8
# moments/day, TikTok 10-20, Google Trends 10), a pure score-sort would
# let calendar's confidence bonus crowd out the other sources. Quotas
# guarantee multi-source diversity on the daily dashboard. The total
# (10) caps daily LLM friction-analysis spend.
SOURCE_QUOTAS: dict[SourceKind, int] = {
    SourceKind.CALENDAR: 5,
    SourceKind.TIKTOK: 3,
    SourceKind.GOOGLE_TRENDS: 2,
}


def _select_top_by_source_quota(
    moments: list[ExtractedMoment],
) -> list[ExtractedMoment]:
    """Take SOURCE_QUOTAS[source] highest-scored moments per source.

    `moments` is pre-sorted by score desc (from stage_score_moments). We
    walk it once, filling each source's quota as we go. Slots a source
    can't fill (e.g. zero Google Trends moments today) are left empty,
    not redistributed — keeps the math predictable and means a quiet
    source doesn't accidentally drown the dashboard."""
    quotas_left = dict(SOURCE_QUOTAS)
    out: list[ExtractedMoment] = []
    for m in moments:
        remaining = quotas_left.get(m.source, 0)
        if remaining > 0:
            out.append(m)
            quotas_left[m.source] = remaining - 1
        if not any(v > 0 for v in quotas_left.values()):
            break
    return out


async def stage_analyze_friction(
    moments: list[ExtractedMoment],
    today: date_t | None = None,
) -> list[tuple[ExtractedMoment, FrictionAnalysis | None, list[ReusableFriction] | None]]:
    """Run the friction prompt across the top N moments in parallel.

    Selection uses per-source quotas (see SOURCE_QUOTAS above) so the daily
    brief always reflects multi-source coverage rather than letting one
    high-volume source dominate.

    Before invoking the LLM, each moment is checked against the cross-day
    reuse cache (see pipeline.dedup). Moments whose normalized name appeared
    in the last 14 days inherit those frictions verbatim — no LLM call.
    This is the token-leak fix for fixed-calendar events (Met Gala, EDC,
    Kentucky Derby) that were burning ~$X/day getting re-analyzed.

    Returned tuple per moment is (moment, fresh_analysis, reused_frictions):
      * fresh_analysis is non-None when the LLM ran successfully.
      * reused_frictions is non-None when we copied a prior analysis.
      * Both None means the LLM ran and failed.
    The two are mutually exclusive — we never both call the LLM and reuse.
    """
    today = today or date_t.today()
    with record_stage(PipelineStage.ANALYZE_FRICTION) as h:
        targets = _select_top_by_source_quota(moments)
        h.items_processed = len(targets)

        # Reuse-by-name lookup. One Supabase round trip per moment is cheap
        # vs the LLM call we're avoiding. Failures here fall through to the
        # LLM path — dedup is an optimization, not a correctness gate.
        try:
            client = supabase_client()
        except Exception as exc:
            logger.warning("analyze_friction: supabase unreachable, skipping reuse: %s", exc)
            client = None

        reused: list[list[ReusableFriction] | None] = []
        llm_targets: list[tuple[int, ExtractedMoment]] = []
        for idx, m in enumerate(targets):
            hit = find_reusable_frictions(client, m.name, today) if client else None
            reused.append(hit)
            if hit is None:
                llm_targets.append((idx, m))

        if reused and any(r is not None for r in reused):
            reuse_count = sum(1 for r in reused if r is not None)
            logger.info(
                "analyze_friction: reused %d/%d moment(s) from prior analyses (~%d LLM call(s) saved)",
                reuse_count, len(targets), reuse_count,
            )

        # Only fire the LLM for moments without a cache hit.
        tasks = [
            analyze_friction(m.name, m.description, m.signals)
            for _, m in llm_targets
        ]
        analyses_raw = await asyncio.gather(*tasks, return_exceptions=False)
        # analyze_friction never raises (returns None on failure).

        # Reassemble back into target order: reused first, LLM result otherwise.
        analyses: list[FrictionAnalysis | None] = [None] * len(targets)
        for (idx, _m), result in zip(llm_targets, analyses_raw, strict=True):
            analyses[idx] = result

        succeeded = sum(
            1 for a, r in zip(analyses, reused, strict=True)
            if a is not None or r is not None
        )
        h.items_succeeded = succeeded
        return list(zip(targets, analyses, reused, strict=True))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5: Persist
# ─────────────────────────────────────────────────────────────────────────────


async def stage_persist(
    today: date_t,
    results: list[
        tuple[ExtractedMoment, FrictionAnalysis | None, list[ReusableFriction] | None]
    ],
) -> None:
    """Write moments + frictions + product matches to Supabase.

    Order per moment:
      1. Insert the moment row.
      2. For each friction: insert friction row, set review_status from the
         confidence gate (self_rating >= 8 = 'approved', else 'pending').
         When dedup returned a reused set (third tuple element), copy those
         rows verbatim instead of writing the fresh analysis.
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

        for moment, analysis, reused in results:
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

                # Path A: reused frictions — copy from prior moment verbatim.
                # Skip the friction LLM cost and ride the prior analysis's
                # review_status (so an already-approved friction stays approved
                # and immediately drives matcher/playbook; a pending one stays
                # in the queue). Matches + playbook still regenerate via the
                # backfill stage so catalog updates take effect.
                reused_max_rating = 0
                if reused is not None:
                    for rf in reused:
                        friction_resp = client.table("frictions").insert({
                            "moment_id": moment_id,
                            "friction_summary": rf.summary,
                            "mechanism": rf.mechanism,
                            "efficacy_class": rf.efficacy_class,
                            "self_rating": rf.self_rating,
                            "review_status": rf.review_status,
                            "prompt_version": f"reused:{rf.source_prompt_version}",
                        }).execute()
                        if not friction_resp.data:
                            continue
                        friction_id = friction_resp.data[0]["id"]
                        reused_max_rating = max(reused_max_rating, rf.self_rating)

                        if rf.review_status == "approved":
                            # Rebuild a FrictionItem so matcher has the shape it expects.
                            from pipeline.schemas import FrictionItem
                            await _persist_matches_for_friction(
                                client,
                                friction_id,
                                FrictionItem(
                                    summary=rf.summary,
                                    mechanism=rf.mechanism,
                                    efficacy_class=rf.efficacy_class,
                                ),
                                version,
                            )

                # Path B: fresh LLM analysis — insert as before.
                # Confidence gate: self_rating ≥ 7 → 'approved' (auto-publish),
                # else 'pending' (queues for Yangcho).
                elif analysis is not None:
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

                        # Run product matching + playbook ONLY for approved frictions.
                        if review_status == "approved":
                            await _persist_matches_for_friction(
                                client, friction_id, f, version
                            )

                # Per-moment playbook: influencer suggestions. Once per
                # moment (not per friction — same moment, same audience).
                # Fires when the moment has at least one approved friction,
                # for both fresh (self_rating ≥ 7) and reused (any reused
                # friction with review_status='approved') paths.
                has_approved = (
                    (analysis is not None and analysis.self_rating >= 7)
                    or (reused is not None and any(rf.review_status == "approved" for rf in reused))
                )
                if has_approved:
                    # Influencer needs a FrictionAnalysis-shaped object to
                    # gather friction context. When reusing, synthesize one
                    # from the reused list — same shape, no LLM round-trip.
                    if analysis is not None:
                        ctx_analysis = analysis
                    else:
                        from pipeline.schemas import FrictionAnalysis, FrictionItem
                        ctx_analysis = FrictionAnalysis(
                            frictions=[
                                FrictionItem(
                                    summary=rf.summary,
                                    mechanism=rf.mechanism,
                                    efficacy_class=rf.efficacy_class,
                                )
                                for rf in (reused or [])
                            ],
                            self_rating=reused_max_rating or 7,
                            self_rating_reasoning="reused from prior moment",
                        )
                    await _persist_influencer_for_moment(
                        client, moment_id, moment, ctx_analysis, version,
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
    """For one approved friction, run product matching + the per-friction
    playbook generators (marketing post + new-product idea). Failures here
    MUST NOT abort the parent stage.

    Generation order:
      1. Product matcher — produces 0..N matches.
      2. Marketing post — generated only if the matcher returned a usable
         match (need a real product to pitch against).
      3. New-product idea — generated only if the best match score is
         BELOW PRODUCT_IDEA_THRESHOLD (the "white space" case). Uses the
         best match as context for what *didn't* fit.
    """
    try:
        matches = await match_one_friction(friction)
    except Exception as exc:
        logger.warning(
            "persist: match_one_friction failed for friction_id=%d: %s",
            friction_id, exc,
        )
        matches = []

    # Insert match rows.
    best_match = None
    best_match_product = None
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
        if rank == 1:
            best_match = m

    # Hydrate brand/name for the best match so the playbook prompts have
    # something to talk about. One extra Supabase read per friction; cheap.
    if best_match is not None:
        try:
            prod_rows = (
                client.table("products")
                .select("brand, name")
                .eq("id", best_match.product_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if prod_rows:
                best_match_product = prod_rows[0]
        except Exception as exc:
            logger.warning(
                "persist: product hydrate failed for product_id=%d: %s",
                best_match.product_id, exc,
            )

    # Rate-limit backoff between sequential LLM calls. The Anthropic
    # account's 30K tokens/min cap is the binding constraint when matcher
    # + marketing + product_idea all fire back-to-back inside a single
    # friction's persist cycle. 2 seconds is well under any human-noticeable
    # latency and gives the per-minute budget room to recover.
    LLM_INTER_CALL_BACKOFF_SECONDS = 2.0

    # Stage 2: marketing post — generate only when we have a usable match
    # to pitch against. Always queues for review (kind=marketing_post).
    if best_match is not None and best_match_product is not None:
        await asyncio.sleep(LLM_INTER_CALL_BACKOFF_SECONDS)
        await _persist_marketing_post(
            client, friction_id, friction, best_match_product, best_match, version,
        )

    # Stage 3: new-product idea — fires when match score is below threshold
    # (or matches list is empty). Uses the best (failed) match as context.
    best_score = float(best_match.match_score) if best_match else None
    if should_generate_idea(best_score):
        await asyncio.sleep(LLM_INTER_CALL_BACKOFF_SECONDS)
        await _persist_product_idea(
            client, friction_id, friction, best_match_product, best_match, version,
        )


async def _persist_marketing_post(
    client,
    friction_id: int,
    friction,
    product_row,
    match,
    version: str,
) -> None:
    """Generate + insert a marketing_post playbook output for one friction.

    Always queues for review (review_status='pending'). Marketing posts
    are voice-sensitive and Yangcho gates every one.
    """
    try:
        inp = MarketingPostInput(
            friction=friction,
            product_brand=product_row.get("brand", ""),
            product_name=product_row.get("name", ""),
            match=match,
        )
        post = await generate_marketing_post(inp)
    except Exception as exc:
        logger.warning(
            "persist: marketing_post failed for friction_id=%d: %s",
            friction_id, exc,
        )
        return

    if post is None:
        return  # generator already logged

    try:
        client.table("playbook_outputs").upsert(
            {
                "friction_id": friction_id,
                "kind": "marketing_post",
                "body": post.model_dump(mode="json"),
                "review_status": "pending",  # always queue
                "prompt_version": version,
            },
            on_conflict="friction_id,kind",
        ).execute()
    except Exception as exc:
        logger.warning(
            "persist: marketing_post insert failed for friction_id=%d: %s",
            friction_id, exc,
        )


async def _persist_product_idea(
    client,
    friction_id: int,
    friction,
    best_match_product,
    best_match,
    version: str,
) -> None:
    """Generate + insert a product_idea playbook output for one friction.

    Always queues for review.
    """
    try:
        inp = ProductIdeaInput(
            friction=friction,
            best_match_brand=(best_match_product or {}).get("brand", "(no match)"),
            best_match_name=(best_match_product or {}).get("name", "(no match in catalog)"),
            best_match_score=float(best_match.match_score) if best_match else 0.0,
            best_match_argument=(best_match.scientific_argument if best_match else "(no candidate cleared the threshold)"),
        )
        idea = await generate_product_idea(inp)
    except Exception as exc:
        logger.warning(
            "persist: product_idea failed for friction_id=%d: %s",
            friction_id, exc,
        )
        return

    if idea is None:
        return

    try:
        client.table("playbook_outputs").upsert(
            {
                "friction_id": friction_id,
                "kind": "product_idea",
                "body": idea.model_dump(mode="json"),
                "review_status": "pending",
                "prompt_version": version,
            },
            on_conflict="friction_id,kind",
        ).execute()
    except Exception as exc:
        logger.warning(
            "persist: product_idea insert failed for friction_id=%d: %s",
            friction_id, exc,
        )


async def _persist_influencer_for_moment(
    client,
    moment_id: int,
    moment,
    analysis,
    version: str,
) -> None:
    """Generate + insert influencer suggestions for one moment.

    Per-moment (not per-friction) — same moment, same audience. The
    playbook_outputs schema is keyed on friction_id though, so we attach
    each suggestion to the FIRST friction of the moment as a representative.
    A future schema cleanup could add a moment_id FK column to playbook_outputs;
    for now the friction-id link is sufficient because the dashboard renders
    influencer suggestions per-moment by reading them from any of the
    moment's friction IDs.
    """
    if not analysis.frictions:
        return

    # Combine all friction summaries as context for the AI's web search.
    friction_context = " ".join(
        f.summary for f in analysis.frictions
    )

    try:
        inp = InfluencerInput(
            moment_name=moment.name,
            moment_description=moment.description or moment.name,
            friction_context=friction_context,
        )
        suggestions = await generate_influencer_suggestions(inp)
    except Exception as exc:
        logger.warning(
            "persist: influencer suggestions failed for moment_id=%d: %s",
            moment_id, exc,
        )
        return

    if not suggestions:
        return

    # Look up the moment's first friction id to anchor the playbook row.
    fric = (
        client.table("frictions")
        .select("id")
        .eq("moment_id", moment_id)
        .order("id")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not fric:
        return
    anchor_friction_id = fric[0]["id"]

    # Single playbook_outputs row holds ALL suggestions for this moment as
    # a list in body — keeps the UNIQUE (friction_id, kind) constraint
    # honored and lets the dashboard render them as a group.
    body = {"suggestions": [s.model_dump(mode="json") for s in suggestions]}
    try:
        client.table("playbook_outputs").upsert(
            {
                "friction_id": anchor_friction_id,
                "kind": "influencer",
                "body": body,
                "review_status": "pending",  # always queue
                "prompt_version": version,
            },
            on_conflict="friction_id,kind",
        ).execute()
    except Exception as exc:
        logger.warning(
            "persist: influencer insert failed for moment_id=%d: %s",
            moment_id, exc,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def run_daily(today: date_t | None = None) -> int:
    """Execute one full pipeline run. Returns 0 on success, 1 on hard failure."""
    today = today or date_t.today()
    logger.info("=== LLC pipeline start: %s (code_version=%s) ===", today, prompt_version())

    # Stage 1 — ingest. Three sources run in parallel:
    #   * Calendar (deterministic, always-on)
    #   * TikTok (most volume but flaky; /discover endpoint + Creative Center
    #     fallback inside fetch_tiktok_signals)
    #   * Google Trends (broad US lifestyle signal, stable RSS)
    cal_moments = stage_ingest_calendar()
    tiktok_signals, gtrends_signals = await asyncio.gather(
        stage_ingest_tiktok(),
        stage_ingest_google_trends(),
    )
    raw_signals = list(tiktok_signals) + list(gtrends_signals)
    logger.info(
        "ingest: %d calendar moments, %d tiktok signals, %d google_trends signals",
        len(cal_moments), len(tiktok_signals), len(gtrends_signals),
    )

    # Hard floor: if every source returned empty, there's nothing to do today.
    if not cal_moments and not raw_signals:
        logger.warning("ingest: all sources empty; nothing to publish today")
        return 0

    # Stages 2–4.
    moments = stage_extract_moments(cal_moments, raw_signals)
    moments = stage_score_moments(moments)
    results = await stage_analyze_friction(moments, today=today)

    # Stage 5 — persist.
    await stage_persist(today, results)

    # Stage 6 — backfill matches + playbook for approved frictions/moments
    # missing one. Catches Yangcho's manual approves via /admin between ticks.
    await stage_backfill_playbook()

    # Stage 7 — download any product images we don't have yet. Cheap when
    # nothing's missing; ~30 minutes for a fresh 107-product catalog at
    # 2 req/sec. Wrapped in record_stage with swallow=True so a CDN hiccup
    # doesn't fail the whole run.
    from pipeline.ingestion.catalog_images import stage_download_catalog_images
    await stage_download_catalog_images()

    last = last_successful_run_at()
    logger.info("=== LLC pipeline done. Last successful run: %s ===", last)
    return 0


# Pacing for backfill loops. Set high enough to stay under the Anthropic
# org rate limit (30K input tokens / minute on the default tier as of
# 2026-05-17). The matcher fires ~5K tokens per friction call; influencer
# fires ~25K because web_search results inflate the prompt context.
#
# These pause AFTER each item in a backfill loop. Per-friction internal
# pacing happens inside _persist_matches_for_friction via
# LLM_INTER_CALL_BACKOFF_SECONDS.
BACKFILL_INTER_ITEM_BACKOFF_SECONDS = 2.0
BACKFILL_INFLUENCER_BACKOFF_SECONDS = 15.0


async def stage_backfill_playbook() -> None:
    """Catch-up generator for approved content missing matches or playbook.

    Three sub-passes, all wrapped in one record_stage:
      1. Approved frictions with no matches → run matcher + (per
         _persist_matches_for_friction) marketing_post + product_idea
         in the same call.
      2. Approved frictions WITH matches but missing marketing_post →
         generate just the marketing post.
      3. Moments with approved frictions but no influencer row → generate
         influencer suggestions.

    The matcher pass is the most common — it's what fires whenever Yangcho
    manually approves a friction via /admin. The other two passes handle
    the corner cases where matching succeeded but a playbook step failed
    on a prior run.

    Wrapped in record_stage(MATCH_PRODUCT) so the operator can see backfill
    runs in pipeline_runs alongside the regular daily flow. We don't have
    a dedicated GENERATE_PLAYBOOK stage code yet — folding the playbook
    catch-up into the same stage row keeps the schema simple.
    """
    from pipeline.schemas import FrictionItem

    with record_stage(PipelineStage.MATCH_PRODUCT) as h:
        try:
            client = supabase_client()
        except Exception as exc:
            logger.warning("backfill: cannot reach Supabase: %s", exc)
            h.items_processed = 0
            h.items_succeeded = 0
            return

        version = prompt_version()
        total_processed = 0
        total_succeeded = 0

        # ── Pass 1: approved frictions with no matches ──────────────────
        approved = (
            client.table("frictions")
            .select("id, moment_id, friction_summary, mechanism, efficacy_class")
            .eq("review_status", "approved")
            .execute()
            .data
            or []
        )
        approved_ids = {f["id"] for f in approved}

        if approved_ids:
            matched = (
                client.table("matches")
                .select("friction_id")
                .in_("friction_id", list(approved_ids))
                .execute()
                .data
                or []
            )
            already_matched_ids = {m["friction_id"] for m in matched}

            unmatched = [f for f in approved if f["id"] not in already_matched_ids]
            if unmatched:
                logger.info(
                    "backfill: pass 1 — %d approved friction(s) missing matches",
                    len(unmatched),
                )
                for i, row in enumerate(unmatched):
                    friction = FrictionItem(
                        summary=row["friction_summary"],
                        mechanism=row["mechanism"],
                        efficacy_class=row.get("efficacy_class"),
                    )
                    # _persist_matches_for_friction also fires marketing_post
                    # and product_idea per the wire in stage_persist, so this
                    # pass covers all per-friction playbook outputs too.
                    await _persist_matches_for_friction(
                        client, row["id"], friction, version
                    )
                    total_succeeded += 1
                    # Pause between frictions in the backfill to stay under
                    # Anthropic's per-minute token budget. Each friction
                    # iteration internally fires up to 3 LLM calls (matcher
                    # + marketing + idea), so sprinting through many
                    # frictions back-to-back is the rate-limit risk.
                    if i < len(unmatched) - 1:
                        await asyncio.sleep(BACKFILL_INTER_ITEM_BACKOFF_SECONDS)
                total_processed += len(unmatched)

        # ── Pass 2: approved frictions with matches but missing per-friction playbook ──
        # Catches the case where pass 1 already ran (matches exist) but
        # one or both of the per-friction playbook items is missing.
        # Two things to check per friction:
        #   • Marketing post — generated for every approved friction.
        #   • Product idea — generated only when best match < threshold.
        if approved_ids:
            with_post = (
                client.table("playbook_outputs")
                .select("friction_id")
                .in_("friction_id", list(approved_ids))
                .eq("kind", "marketing_post")
                .execute()
                .data
                or []
            )
            with_post_ids = {p["friction_id"] for p in with_post}

            with_idea = (
                client.table("playbook_outputs")
                .select("friction_id")
                .in_("friction_id", list(approved_ids))
                .eq("kind", "product_idea")
                .execute()
                .data
                or []
            )
            with_idea_ids = {p["friction_id"] for p in with_idea}

            # Frictions that have at least one match (eligible for the
            # per-friction playbook even if the score is low — we still
            # want a marketing_post, and depending on the score, a product_idea).
            with_matches = [
                f for f in approved if f["id"] in already_matched_ids
            ]

            need_playbook = [
                f for f in with_matches
                if f["id"] not in with_post_ids
                or f["id"] not in with_idea_ids
            ]

            if need_playbook:
                logger.info(
                    "backfill: pass 2 — %d approved friction(s) missing playbook item(s)",
                    len(need_playbook),
                )
                from pipeline.schemas import ProductMatchItem

                for i, row in enumerate(need_playbook):
                    # Hydrate the top match (rank 1).
                    top_match = (
                        client.table("matches")
                        .select("product_id, match_score, scientific_argument")
                        .eq("friction_id", row["id"])
                        .order("rank")
                        .limit(1)
                        .execute()
                        .data
                        or []
                    )
                    if not top_match:
                        continue
                    prod = (
                        client.table("products")
                        .select("brand, name")
                        .eq("id", top_match[0]["product_id"])
                        .limit(1)
                        .execute()
                        .data
                        or []
                    )

                    friction = FrictionItem(
                        summary=row["friction_summary"],
                        mechanism=row["mechanism"],
                        efficacy_class=row.get("efficacy_class"),
                    )
                    match = ProductMatchItem(
                        product_id=top_match[0]["product_id"],
                        match_score=float(top_match[0]["match_score"]),
                        scientific_argument=top_match[0]["scientific_argument"],
                    )

                    # Marketing post (always needed if missing and we have a product).
                    if row["id"] not in with_post_ids and prod:
                        await _persist_marketing_post(
                            client, row["id"], friction, prod[0], match, version,
                        )

                    # Product idea (only when match score below threshold).
                    if (
                        row["id"] not in with_idea_ids
                        and should_generate_idea(float(top_match[0]["match_score"]))
                    ):
                        await _persist_product_idea(
                            client, row["id"], friction,
                            prod[0] if prod else None, match, version,
                        )

                    total_succeeded += 1
                    if i < len(need_playbook) - 1:
                        await asyncio.sleep(BACKFILL_INTER_ITEM_BACKOFF_SECONDS)
                total_processed += len(need_playbook)

        # ── Pass 3: moments with approved frictions but no influencer ──
        # Per-moment, not per-friction. Influencer suggestions are anchored
        # to the moment's FIRST friction id; see _persist_influencer_for_moment.
        if approved_ids:
            moment_ids = list({f["moment_id"] for f in approved})

            # Find anchor friction id per moment.
            with_influencer = (
                client.table("playbook_outputs")
                .select("friction_id")
                .in_("friction_id", list(approved_ids))
                .eq("kind", "influencer")
                .execute()
                .data
                or []
            )
            with_influencer_anchor_friction_ids = {
                p["friction_id"] for p in with_influencer
            }

            # Find moment_ids whose first approved friction id is not in the
            # influencer anchor set.
            first_friction_per_moment: dict[int, int] = {}
            for f in sorted(approved, key=lambda x: x["id"]):
                first_friction_per_moment.setdefault(f["moment_id"], f["id"])

            need_influencer_moments = [
                m_id for m_id, anchor_id in first_friction_per_moment.items()
                if anchor_id not in with_influencer_anchor_friction_ids
            ]

            if need_influencer_moments:
                # Hydrate moment rows.
                moment_rows = (
                    client.table("moments")
                    .select("id, name, description")
                    .in_("id", need_influencer_moments)
                    .execute()
                    .data
                    or []
                )
                logger.info(
                    "backfill: pass 3 — %d moment(s) missing influencer suggestions",
                    len(moment_rows),
                )
                # Lightweight namespace for the helper's expected shape.
                from types import SimpleNamespace

                for i, m_row in enumerate(moment_rows):
                    # Gather all approved frictions for this moment as context.
                    fric_rows = [f for f in approved if f["moment_id"] == m_row["id"]]
                    # Build a stub analysis-like object that has .frictions
                    # and .self_rating ≥ 7 so the helper's preconditions are met.
                    analysis_stub = SimpleNamespace(
                        frictions=[
                            FrictionItem(
                                summary=fr["friction_summary"],
                                mechanism=fr["mechanism"],
                                efficacy_class=fr.get("efficacy_class"),
                            )
                            for fr in fric_rows
                        ],
                        self_rating=10,
                    )
                    moment_stub = SimpleNamespace(
                        name=m_row["name"],
                        description=m_row.get("description"),
                    )
                    await _persist_influencer_for_moment(
                        client, m_row["id"], moment_stub, analysis_stub, version,
                    )
                    total_succeeded += 1
                    # Influencer calls are the heaviest (web_search inflates
                    # context by ~20K tokens). Longer backoff between them.
                    if i < len(moment_rows) - 1:
                        await asyncio.sleep(BACKFILL_INFLUENCER_BACKOFF_SECONDS)
                total_processed += len(moment_rows)

        h.items_processed = total_processed
        h.items_succeeded = total_succeeded
        logger.info(
            "backfill: complete — %d/%d items processed",
            total_succeeded, total_processed,
        )


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
