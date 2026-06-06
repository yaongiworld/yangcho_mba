-- 0012_moments_example_post_event_details — 2026-06-06
--
-- Add two display columns to moments:
--   • example_post_url — a real, clickable URL representative of the trend
--     (TikTok video, IG post, news article, or hashtag landing page as a
--     fallback). Surfaces in the dashboard MomentCard so screenshots have
--     a "here's what this trend looks like on the platform" anchor.
--   • event_details — a 1–3 sentence what/where/when paragraph that
--     answers "what is this trend / event?" for readers who haven't heard
--     of it. For calendar moments, this comes from data/calendar.yaml.
--     For TikTok/Trends moments, the friction prompt produces it.
--
-- Both nullable: backfill is opportunistic, no pre-fill needed. Older rows
-- will gain values on their next pipeline tick (or stay null if reused).

BEGIN;

ALTER TABLE moments
    ADD COLUMN IF NOT EXISTS example_post_url TEXT,
    ADD COLUMN IF NOT EXISTS event_details   TEXT;

COMMIT;
