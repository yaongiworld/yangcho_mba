-- 0006_frictions_anon_update_for_admin — 2026-05-17
--
-- Adds an UPDATE policy on frictions so /admin's approve/reject buttons
-- (Server Actions hitting Supabase under the publishable key) can flip
-- review_status. Same architectural trade-off as 0005: relying on URL
-- obscurity for /admin until Supabase Auth lands in W7.
--
-- Defensive scoping:
--   - UPDATE policy uses WITH CHECK that the new review_status is one of
--     the valid terminal states for review (approved | rejected | retracted).
--     Pending → pending no-op writes are blocked too — there's no use case
--     for that from /admin.
--   - The policy does NOT grant UPDATE on every column. Postgres-side
--     column-level permissions narrow the allowed columns to review_status
--     and reviewed_at only. A leaked /admin can't rewrite friction_summary
--     or self_rating.
--
-- TODO when Auth lands (W7):
--   - Drop this policy.
--   - Add a new UPDATE policy with USING (auth.uid() IN admin_users)
--     and the same column-level scope.

-- Grant column-level UPDATE permissions to anon. (Required even with an
-- RLS policy — Postgres's GRANT layer comes first.)
GRANT UPDATE (review_status, reviewed_at) ON frictions TO anon;
GRANT UPDATE (review_status, reviewed_at) ON frictions TO authenticated;

-- RLS UPDATE policy. The USING clause governs WHICH rows can be updated;
-- the WITH CHECK clause governs what the rows can be updated TO.
CREATE POLICY frictions_admin_review_update
    ON frictions FOR UPDATE
    TO anon, authenticated
    USING (TRUE)
    WITH CHECK (
        review_status IN ('approved', 'rejected', 'retracted')
    );
