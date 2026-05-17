-- 0007_playbook_anon_update_for_admin — 2026-05-17
--
-- Mirror of 0006 but for playbook_outputs. Grants the anon role
-- column-level UPDATE on review_status + reviewed_at so the /admin
-- Server Actions can approve / reject pending playbook items
-- (marketing_post, product_idea, influencer) under the publishable key.
--
-- Same URL-obscurity trade-off as 0005 + 0006: /admin is not linked
-- from public pages and the dashboard's login gate is the actual safeguard
-- until Supabase Auth lands.
--
-- TODO when Auth lands (W7+):
--   - Drop this policy.
--   - Add a new UPDATE policy with USING (auth.uid() IN admin_users)
--     and the same column-level scope.

GRANT UPDATE (review_status, reviewed_at) ON playbook_outputs TO anon;
GRANT UPDATE (review_status, reviewed_at) ON playbook_outputs TO authenticated;

CREATE POLICY playbook_admin_review_update
    ON playbook_outputs FOR UPDATE
    TO anon, authenticated
    USING (TRUE)
    WITH CHECK (
        review_status IN ('approved', 'rejected', 'retracted')
    );
