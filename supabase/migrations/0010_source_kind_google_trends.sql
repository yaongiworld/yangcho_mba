-- 0010_source_kind_google_trends — 2026-05-18
--
-- Adds 'google_trends' to the source_kind enum. Part of expanding the
-- trend-signal sources beyond TikTok Creative Center (which has been
-- returning 50004 "no available es index" errors since at least
-- 2026-05-14, and reportedly broken on TikTok's side for users too).
--
-- Plan: keep 'tiktok' for any TikTok source (Creative Center XHR, the
-- newer /api/discover/challenge endpoint, future additions) so the
-- dashboard's "source" badge stays readable. Add new ENUM values only
-- for genuinely-different platforms.
--
-- ENUM ADD VALUE is non-transactional, which is why this migration is
-- single-statement. If Supabase's migration runner wraps in a tx,
-- run it manually via psql with --no-tx.

ALTER TYPE source_kind ADD VALUE IF NOT EXISTS 'google_trends';

-- Track the Google Trends ingest stage in pipeline_runs so /admin can show
-- per-source observability the same way it does for tiktok and calendar.
ALTER TYPE pipeline_stage ADD VALUE IF NOT EXISTS 'ingest_google_trends';
