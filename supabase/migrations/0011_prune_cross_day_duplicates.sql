-- 0011_prune_cross_day_duplicates — 2026-06-03
--
-- Context: the UNIQUE (moment_date, name) constraint from 0004 prevents
-- same-day duplicates but does nothing for cross-day repeats. Calendar
-- events emit the same moment every day they're in window, so "Electric
-- Daisy Carnival" has 18 rows, "The Met Gala" has 15, etc. Each repeat
-- has burned through friction + matcher + playbook LLM calls.
--
-- This migration is the one-time cleanup; the application-level reuse
-- logic in pipeline/dedup.py prevents future repeats from costing tokens.
--
-- Keep policy: for each normalized name, keep the row with the highest
-- summed friction self_rating (defensible "best read" of the moment).
-- Tiebreak by newest moment_date — freshest signal_volume / context wins
-- when neither analysis has rated higher than the other (including the
-- common case where neither has any frictions yet).
--
-- Cascades: frictions.moment_id ON DELETE CASCADE → frictions die with
-- their moments. matches.friction_id ON DELETE CASCADE → matches die
-- with their frictions. playbook_outputs.friction_id ON DELETE CASCADE
-- → same.

BEGIN;

-- normalize_moment_name() mirrors pipeline/dedup.py:normalize_moment_name.
-- Defined IMMUTABLE so the planner can use it; LANGUAGE SQL keeps it
-- inspectable without a plpgsql shim.
CREATE OR REPLACE FUNCTION pg_temp.normalize_moment_name(n TEXT)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT TRIM(
        REGEXP_REPLACE(
            REGEXP_REPLACE(LOWER(n), '\b20\d{2}\b', '', 'g'),
            '[^a-z0-9]+',
            ' ',
            'g'
        )
    );
$$;

WITH ranked AS (
    SELECT
        m.id,
        m.moment_date,
        m.name,
        pg_temp.normalize_moment_name(m.name) AS norm_name,
        COALESCE((
            SELECT SUM(f.self_rating)
            FROM frictions f
            WHERE f.moment_id = m.id
        ), 0) AS total_rating,
        ROW_NUMBER() OVER (
            PARTITION BY pg_temp.normalize_moment_name(m.name)
            ORDER BY
                COALESCE((
                    SELECT SUM(f.self_rating)
                    FROM frictions f
                    WHERE f.moment_id = m.id
                ), 0) DESC,
                m.moment_date DESC,
                m.created_at DESC
        ) AS rn
    FROM moments m
)
DELETE FROM moments
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

COMMIT;
