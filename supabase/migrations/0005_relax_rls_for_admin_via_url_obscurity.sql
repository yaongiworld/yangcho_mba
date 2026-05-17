-- 0005_relax_rls_for_admin_via_url_obscurity — 2026-05-17
--
-- Trade-off explicitly accepted: drop the "approved-only" RLS gating on
-- frictions and playbook_outputs so the dashboard's /admin page can read
-- pending content under the publishable key, with no Supabase Auth wired
-- yet. The /admin URL is not linked from the public surface; security
-- relies on URL obscurity + Vercel password protection (when deployed).
--
-- TODO: revert this migration once Supabase Auth + an admin RLS policy
-- (read all on frictions and playbook_outputs WHERE auth.uid() IS in
-- the admin user list) are in place. W7 scope.

-- frictions: was 'review_status = approved' for anon/authenticated.
-- Now: anon/authenticated can read ALL rows.
DROP POLICY IF EXISTS frictions_public_read_approved ON frictions;

CREATE POLICY frictions_public_read_all
    ON frictions FOR SELECT
    TO anon, authenticated
    USING (TRUE);

-- matches: was gated by "EXISTS frictions f where f.review_status = approved".
-- Now: anon/authenticated can read ALL match rows (the gating becomes
-- redundant once frictions are unrestricted, but explicit replacement
-- avoids a NOT-NULL subquery on every read).
DROP POLICY IF EXISTS matches_public_read ON matches;

CREATE POLICY matches_public_read_all
    ON matches FOR SELECT
    TO anon, authenticated
    USING (TRUE);

-- playbook_outputs: was 'review_status = approved' for anon/authenticated.
-- Now: anon/authenticated can read ALL rows.
DROP POLICY IF EXISTS playbook_public_read_approved ON playbook_outputs;

CREATE POLICY playbook_public_read_all
    ON playbook_outputs FOR SELECT
    TO anon, authenticated
    USING (TRUE);

-- moments was already public-read-all in 0001; no change needed.
-- products was already public-read-non-dead in 0001; no change needed.
-- pipeline_runs was already public-read-all in 0001; no change needed.
-- signals_cache stays service-role-only (no public policy granted).
