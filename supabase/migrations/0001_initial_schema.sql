-- LLC initial schema — 2026-05-10
-- Reflects /plan-eng-review decisions on:
--   • Multi-source ingestion with last-known-good caching (signals_cache)
--   • Confidence-gated review queue (frictions.self_rating, review_queue)
--   • Catalog scraping with dead-link tracking (products.is_dead_link, last_verified_at)
--   • Prompt versioning (every AI-generated row carries prompt_version git SHA)
--   • Pipeline observability (pipeline_runs)
--   • LG-primary, competitor mix (products.is_lg flag)
--
-- All tables are in the public schema. RLS is enabled on every table; the dashboard
-- uses the anon key for public reads, the cron uses the service-role key for writes,
-- and Yangcho's review-queue access is gated via Supabase Auth.

----------------------------------------------------------------------
-- ENUMS
----------------------------------------------------------------------

CREATE TYPE pipeline_stage AS ENUM (
    'ingest_reddit',
    'ingest_calendar',
    'ingest_tiktok',
    'extract_moments',
    'score_moments',
    'analyze_friction',
    'match_product',
    'generate_playbook',
    'apply_confidence_gate'
);

CREATE TYPE pipeline_status AS ENUM ('running', 'success', 'failure', 'partial');

CREATE TYPE source_kind AS ENUM ('reddit', 'tiktok', 'calendar');

CREATE TYPE review_status AS ENUM ('pending', 'approved', 'rejected', 'retracted');

CREATE TYPE playbook_kind AS ENUM ('influencer', 'marketing_post', 'product_idea');

----------------------------------------------------------------------
-- pipeline_runs — observability spine
-- Every cron stage writes one row. Methodology page surfaces the latest
-- success timestamp ("Last successful pipeline run: …"). Notification system
-- (TODO P3) reads this for 2+ consecutive failures.
----------------------------------------------------------------------

CREATE TABLE pipeline_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    stage           pipeline_stage NOT NULL,
    status          pipeline_status NOT NULL,
    error_message   TEXT,
    -- For partial successes: how many items succeeded vs total attempted.
    items_processed INT,
    items_succeeded INT,
    -- Git SHA of the pipeline code that ran. Lets us correlate output quality
    -- to specific commits.
    code_version    TEXT NOT NULL
);

CREATE INDEX pipeline_runs_recent_idx
    ON pipeline_runs (started_at DESC, stage);

----------------------------------------------------------------------
-- signals_cache — last-known-good ingestion data
-- Each ingestion source writes its raw payload here on success. Orchestrator
-- reads from cache when a fresh fetch fails. TTL enforced at read time
-- (caller decides how stale is too stale; default 48h).
----------------------------------------------------------------------

CREATE TABLE signals_cache (
    id           BIGSERIAL PRIMARY KEY,
    source       source_kind NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload      JSONB NOT NULL,
    -- Optional fingerprint to detect "same response as last fetch" and skip
    -- redundant downstream work.
    payload_hash TEXT
);

CREATE INDEX signals_cache_latest_idx
    ON signals_cache (source, fetched_at DESC);

----------------------------------------------------------------------
-- products — scraped K-Beauty catalog (facts only, never marketing copy)
-- Refreshed weekly. Dead-link checker runs daily and flips is_dead_link.
----------------------------------------------------------------------

CREATE TABLE products (
    id                  BIGSERIAL PRIMARY KEY,
    brand               TEXT NOT NULL,
    is_lg               BOOLEAN NOT NULL DEFAULT FALSE,
    name                TEXT NOT NULL,
    category            TEXT,                   -- "moisturizer", "sunscreen", "cleanser", ...
    public_url          TEXT NOT NULL,
    claims              TEXT[] NOT NULL DEFAULT '{}',
    key_ingredients     TEXT[] NOT NULL DEFAULT '{}',
    -- Last time we verified the URL responded 200. Older than 24h triggers
    -- re-verification; dead links are excluded from match candidates.
    last_verified_at    TIMESTAMPTZ,
    is_dead_link        BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_scraped_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (brand, name)
);

CREATE INDEX products_brand_idx ON products (brand);
CREATE INDEX products_lg_alive_idx ON products (is_lg, is_dead_link)
    WHERE is_dead_link = FALSE;

----------------------------------------------------------------------
-- moments — clustered lifestyle moments per day
-- Top-10-by-score advance to friction analysis. Score formula:
--   score = (trend_velocity × purchase_intent) − brand_risk
----------------------------------------------------------------------

CREATE TABLE moments (
    id                BIGSERIAL PRIMARY KEY,
    moment_date       DATE NOT NULL,
    name              TEXT NOT NULL,
    -- Where the signal came from (mostly TikTok hashtag, Reddit thread, calendar entry).
    source            source_kind NOT NULL,
    source_refs       JSONB NOT NULL DEFAULT '[]'::JSONB,
    description       TEXT,
    -- Scoring inputs.
    trend_velocity    NUMERIC(5,2),  -- 7-day rolling volume delta
    purchase_intent   SMALLINT CHECK (purchase_intent BETWEEN 1 AND 5),
    brand_risk        SMALLINT CHECK (brand_risk BETWEEN 1 AND 5),
    score             NUMERIC(6,2) GENERATED ALWAYS AS
                          (COALESCE(trend_velocity, 0) * COALESCE(purchase_intent, 0)
                           - COALESCE(brand_risk, 0)) STORED,
    prompt_version    TEXT NOT NULL,         -- git SHA of pipeline code that scored this
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX moments_today_idx ON moments (moment_date DESC, score DESC);

----------------------------------------------------------------------
-- frictions — AI-generated friction analysis per moment
-- The MOAT artifact. Each friction has a self_rating 1–10 used by the
-- confidence gate: ≥8 auto-publishes, <8 queues for review.
----------------------------------------------------------------------

CREATE TABLE frictions (
    id                  BIGSERIAL PRIMARY KEY,
    moment_id           BIGINT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    -- The 1–3 frictions extracted (e.g. "4–6 hr outdoor + UV + sweat + grass dust").
    friction_summary    TEXT NOT NULL,
    -- The mechanism explanation in R&D voice (rheology, lipid biology, efficacy).
    mechanism           TEXT NOT NULL,
    efficacy_class      TEXT,
    self_rating         SMALLINT NOT NULL CHECK (self_rating BETWEEN 1 AND 10),
    -- Auto-publish if self_rating ≥ 8 AND review_status = 'approved'.
    -- Yangcho can retract any auto-published row.
    review_status       review_status NOT NULL DEFAULT 'pending',
    reviewed_by         UUID REFERENCES auth.users(id),
    reviewed_at         TIMESTAMPTZ,
    review_notes        TEXT,
    prompt_version      TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX frictions_review_queue_idx ON frictions (review_status, self_rating)
    WHERE review_status = 'pending';
CREATE INDEX frictions_moment_idx ON frictions (moment_id);

----------------------------------------------------------------------
-- matches — friction → product
-- LG-primary policy enforced in application code; the rank field captures
-- the order returned by the matcher.
----------------------------------------------------------------------

CREATE TABLE matches (
    id                  BIGSERIAL PRIMARY KEY,
    friction_id         BIGINT NOT NULL REFERENCES frictions(id) ON DELETE CASCADE,
    product_id          BIGINT REFERENCES products(id) ON DELETE SET NULL,
    -- 0–1 confidence in the match. Used for "no good match found" thresholding,
    -- which triggers the new-product-idea generator instead.
    match_score         NUMERIC(3,2) NOT NULL CHECK (match_score BETWEEN 0 AND 1),
    rank                SMALLINT NOT NULL,
    scientific_argument TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX matches_friction_idx ON matches (friction_id, rank);

----------------------------------------------------------------------
-- playbook_outputs — three flavors per friction (influencer, marketing_post, product_idea)
-- Discriminator on `kind`; payload-shape per flavor lives in the JSONB body.
-- Marketing posts always default to draft (review_status='pending') regardless
-- of confidence — different bar than friction analysis.
----------------------------------------------------------------------

CREATE TABLE playbook_outputs (
    id              BIGSERIAL PRIMARY KEY,
    friction_id     BIGINT NOT NULL REFERENCES frictions(id) ON DELETE CASCADE,
    kind            playbook_kind NOT NULL,
    body            JSONB NOT NULL,
    review_status   review_status NOT NULL DEFAULT 'pending',
    reviewed_by     UUID REFERENCES auth.users(id),
    reviewed_at     TIMESTAMPTZ,
    review_notes    TEXT,
    prompt_version  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (friction_id, kind)
);

CREATE INDEX playbook_review_queue_idx ON playbook_outputs (review_status, kind)
    WHERE review_status = 'pending';

----------------------------------------------------------------------
-- review_queue is a VIEW, not a table — it unions frictions and playbook_outputs
-- needing Yangcho's attention. Keeps the queue UI simple.
----------------------------------------------------------------------

CREATE VIEW review_queue AS
SELECT
    'friction'::TEXT  AS item_kind,
    f.id              AS item_id,
    f.moment_id       AS context_id,
    f.friction_summary AS preview,
    f.self_rating     AS confidence,
    f.created_at,
    f.review_status
FROM frictions f
WHERE f.review_status = 'pending'
UNION ALL
SELECT
    'playbook'::TEXT  AS item_kind,
    p.id              AS item_id,
    p.friction_id     AS context_id,
    LEFT(p.body::TEXT, 200) AS preview,
    NULL              AS confidence,
    p.created_at,
    p.review_status
FROM playbook_outputs p
WHERE p.review_status = 'pending';

----------------------------------------------------------------------
-- RLS policies
-- Public read on the tables that drive the dashboard; everything else
-- requires the service role or an authed Yangcho session.
----------------------------------------------------------------------

ALTER TABLE pipeline_runs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals_cache       ENABLE ROW LEVEL SECURITY;
ALTER TABLE products            ENABLE ROW LEVEL SECURITY;
ALTER TABLE moments             ENABLE ROW LEVEL SECURITY;
ALTER TABLE frictions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE matches             ENABLE ROW LEVEL SECURITY;
ALTER TABLE playbook_outputs    ENABLE ROW LEVEL SECURITY;

-- Public can read the latest pipeline_run timestamp (for "last refreshed" UI).
CREATE POLICY pipeline_runs_public_read
    ON pipeline_runs FOR SELECT
    TO anon, authenticated
    USING (TRUE);

-- Public can read products (they're public market data anyway), excluding dead links.
CREATE POLICY products_public_read
    ON products FOR SELECT
    TO anon, authenticated
    USING (is_dead_link = FALSE);

-- Public can read moments (they're the dashboard's content).
CREATE POLICY moments_public_read
    ON moments FOR SELECT
    TO anon, authenticated
    USING (TRUE);

-- Public can read approved frictions only. Pending/rejected stay private.
CREATE POLICY frictions_public_read_approved
    ON frictions FOR SELECT
    TO anon, authenticated
    USING (review_status = 'approved');

-- Public can read matches whose friction is approved.
CREATE POLICY matches_public_read
    ON matches FOR SELECT
    TO anon, authenticated
    USING (EXISTS (
        SELECT 1 FROM frictions f
        WHERE f.id = matches.friction_id AND f.review_status = 'approved'
    ));

-- Public can read approved playbook outputs.
CREATE POLICY playbook_public_read_approved
    ON playbook_outputs FOR SELECT
    TO anon, authenticated
    USING (review_status = 'approved');

-- signals_cache stays internal — service role only.
-- (No policy granted to anon/authenticated; default-deny applies.)
