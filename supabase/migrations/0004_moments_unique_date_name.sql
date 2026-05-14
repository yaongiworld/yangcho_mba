-- 0004_moments_unique_date_name — 2026-05-15
--
-- Adds UNIQUE (moment_date, name) on moments so re-running the daily pipeline
-- on the same day cannot duplicate moments. Without this, every cron tick
-- inserts a fresh row for #SundayTailgate even when one already exists.
--
-- Pre-migration cleanup: we have 14 rows on 2026-05-10 from W1+W2 testing,
-- many duplicating "Electric Daisy Carnival (EDC) Las Vegas". Deduping policy:
--   - Keep the row whose frictions have the highest max(self_rating). That's
--     the most defensible "best read" of the moment.
--   - Tiebreak by max(created_at) — newest wins.
--   - Delete the losers + their orphaned frictions + matches via FK cascade.

BEGIN;

-- 1. Find the canonical moment_id per (moment_date, name): the one with the
--    highest-scoring approved or pending friction, newest-first on ties.
WITH ranked AS (
    SELECT
        m.id,
        m.moment_date,
        m.name,
        m.created_at,
        COALESCE((
            SELECT MAX(f.self_rating)
            FROM frictions f
            WHERE f.moment_id = m.id
        ), 0) AS best_rating,
        ROW_NUMBER() OVER (
            PARTITION BY m.moment_date, m.name
            ORDER BY COALESCE((
                SELECT MAX(f.self_rating)
                FROM frictions f
                WHERE f.moment_id = m.id
            ), 0) DESC, m.created_at DESC
        ) AS rn
    FROM moments m
)
DELETE FROM moments
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
-- frictions.moment_id has ON DELETE CASCADE (from 0001), so the losers'
-- frictions and (via frictions.id cascade) their matches are removed in
-- the same transaction.

-- 2. Add the constraint. Now that duplicates are gone, this succeeds.
ALTER TABLE moments
    ADD CONSTRAINT moments_date_name_key UNIQUE (moment_date, name);

COMMIT;
