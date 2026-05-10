"""Pydantic schemas — single source of truth for shapes flowing through the pipeline.

Mirrors `supabase/migrations/0001_initial_schema.sql` field-for-field. When the
schema changes:
  1. Add a new SQL migration under `supabase/migrations/`.
  2. Update the matching model here.
  3. Regenerate the dashboard's TypeScript types: `cd dashboard && npm run db:types`.

Convention: pipeline-generated models have an `Insert` variant for writes (no
auto-fields like `id`, `created_at`) and a `Row` variant for reads (everything).
For models that are only read OR only written, we keep one class.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ─────────────────────────────────────────────────────────────────────────────
# Enums — mirror the Postgres enum types in 0001_initial_schema.sql
# ─────────────────────────────────────────────────────────────────────────────


class PipelineStage(str, Enum):
    INGEST_CALENDAR = "ingest_calendar"
    INGEST_TIKTOK = "ingest_tiktok"
    EXTRACT_MOMENTS = "extract_moments"
    SCORE_MOMENTS = "score_moments"
    ANALYZE_FRICTION = "analyze_friction"
    MATCH_PRODUCT = "match_product"
    GENERATE_PLAYBOOK = "generate_playbook"
    APPLY_CONFIDENCE_GATE = "apply_confidence_gate"


class PipelineStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class SourceKind(str, Enum):
    TIKTOK = "tiktok"
    CALENDAR = "calendar"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETRACTED = "retracted"


class PlaybookKind(str, Enum):
    INFLUENCER = "influencer"
    MARKETING_POST = "marketing_post"
    PRODUCT_IDEA = "product_idea"


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion-layer shapes (not persisted directly; clustered into moments first)
# ─────────────────────────────────────────────────────────────────────────────


class RawSignal(BaseModel):
    """One unit of input from any ingestion source. TikTok hashtags and
    calendar moments all normalize to this shape before clustering."""

    source: SourceKind
    external_id: str  # post id, hashtag name, calendar entry name
    text: str  # the searchable content
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CalendarMoment(BaseModel):
    """A pre-known lifestyle moment loaded from data/calendar.yaml.

    Always-on input. Pure function of today's date. Never fails.
    """

    name: str
    date_pattern: str
    confidence: str  # "high" | "medium" | "low"
    friction_hints: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    category: str  # nfl | bama_rush | marathons | festivals | evergreen


# ─────────────────────────────────────────────────────────────────────────────
# pipeline_runs — observability spine
# ─────────────────────────────────────────────────────────────────────────────


class PipelineRunInsert(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    stage: PipelineStage
    status: PipelineStatus
    error_message: str | None = None
    items_processed: int | None = None
    items_succeeded: int | None = None
    code_version: str


class PipelineRunRow(PipelineRunInsert):
    id: int


# ─────────────────────────────────────────────────────────────────────────────
# signals_cache — last-known-good per source
# ─────────────────────────────────────────────────────────────────────────────


class SignalsCacheInsert(BaseModel):
    source: SourceKind
    payload: dict[str, Any] | list[Any]
    payload_hash: str | None = None


class SignalsCacheRow(SignalsCacheInsert):
    id: int
    fetched_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# products — scraped K-Beauty catalog (facts only)
# ─────────────────────────────────────────────────────────────────────────────


class ProductInsert(BaseModel):
    external_id: str  # platform-specific ID (e.g. OY's prdtNo); UNIQUE per (platform, external_id)
    brand: str
    is_lg: bool = False
    name: str
    category: str | None = None
    public_url: str
    platform: str = "oy_global"  # source provenance: oy_global, lg_brand_direct, etc.
    claims: list[str] = Field(default_factory=list)
    key_ingredients: list[str] = Field(default_factory=list)
    last_verified_at: datetime | None = None
    is_dead_link: bool = False


class ProductRow(ProductInsert):
    id: int
    first_seen_at: datetime
    last_scraped_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# moments — clustered lifestyle moments
# ─────────────────────────────────────────────────────────────────────────────


class MomentInsert(BaseModel):
    moment_date: date
    name: str
    source: SourceKind
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    description: str | None = None
    trend_velocity: float | None = None  # NUMERIC(5,2)
    purchase_intent: int | None = Field(default=None, ge=1, le=5)
    brand_risk: int | None = Field(default=None, ge=1, le=5)
    prompt_version: str


class MomentRow(MomentInsert):
    id: int
    score: float | None  # GENERATED column, read-only
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# frictions — the moat artifact
# ─────────────────────────────────────────────────────────────────────────────


class FrictionItem(BaseModel):
    """One friction observation. Multiple per FrictionAnalysis."""

    summary: str
    mechanism: str
    efficacy_class: str | None = None


class FrictionAnalysis(BaseModel):
    """The shape returned by call_llm("friction", ...) — what the LLM produces.
    Each item maps to one row in the frictions table."""

    frictions: list[FrictionItem] = Field(min_length=1, max_length=3)
    self_rating: int = Field(ge=1, le=10)
    self_rating_reasoning: str

    @field_validator("frictions")
    @classmethod
    def at_least_one_friction(cls, v: list[FrictionItem]) -> list[FrictionItem]:
        if not v:
            raise ValueError("at least one friction is required")
        return v


class FrictionInsert(BaseModel):
    moment_id: int
    friction_summary: str
    mechanism: str
    efficacy_class: str | None = None
    self_rating: int = Field(ge=1, le=10)
    review_status: ReviewStatus = ReviewStatus.PENDING
    prompt_version: str


class FrictionRow(FrictionInsert):
    id: int
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# matches — friction → product
# ─────────────────────────────────────────────────────────────────────────────


class ProductMatchItem(BaseModel):
    """One match. Multiple per LLM call output (ranked)."""

    product_id: int
    match_score: float = Field(ge=0.0, le=1.0)
    scientific_argument: str


class ProductMatchOutput(BaseModel):
    """Shape returned by call_llm("product_match", ...)."""

    matches: list[ProductMatchItem]


class MatchInsert(BaseModel):
    friction_id: int
    product_id: int | None
    match_score: float = Field(ge=0.0, le=1.0)
    rank: int
    scientific_argument: str
    prompt_version: str


class MatchRow(MatchInsert):
    id: int
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# playbook_outputs — three flavors via discriminator
# ─────────────────────────────────────────────────────────────────────────────


class InfluencerSuggestionBody(BaseModel):
    creator_handle: str
    reasoning: str
    public_evidence: str


class MarketingPostBody(BaseModel):
    headline: str = Field(max_length=80)
    body: str  # length validated separately (80–120 words is target, not hard cap)
    call_to_action: str = Field(max_length=60)


class ProductIdeaBody(BaseModel):
    concept_name: str
    target_friction: str
    hero_mechanism: str
    hero_ingredient_class: str
    target_consumer_profile: str
    competitive_white_space: str


class PlaybookOutputInsert(BaseModel):
    friction_id: int
    kind: PlaybookKind
    body: dict[str, Any]  # one of the three Body shapes above; validated at write time
    review_status: ReviewStatus = ReviewStatus.PENDING
    prompt_version: str


class PlaybookOutputRow(PlaybookOutputInsert):
    id: int
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Scoring (LLM intermediate output, not a table)
# ─────────────────────────────────────────────────────────────────────────────


class MomentScoreOutput(BaseModel):
    """Shape returned by call_llm("scoring", ...). Trend Velocity is computed
    numerically from signal volume, not by the LLM."""

    purchase_intent: int = Field(ge=1, le=5)
    brand_risk: int = Field(ge=1, le=5)
    rationale: str
