-- 0009_products_image_url — 2026-05-17
--
-- Adds the source-CDN image URL to the products table. This is the OY
-- (Olive Young Global) CDN URL extracted at catalog-scrape time. It's
-- distinct from image_path (migration 0008), which is the bucket-relative
-- key inside our Supabase Storage mirror.
--
-- Why two columns:
--   • image_url is the upstream URL (subject to OY rotating, blocking,
--     or going down). We keep it for re-mirroring if the bucket copy is
--     ever lost, and for audit trails.
--   • image_path is the bucket key the dashboard actually renders from.
--     Stable, under our control, no third-party SLA.
--
-- Note: the comment in 0008 referenced "the existing image_url column"
-- before this migration existed — that comment was aspirational. The
-- column is added here.
--
-- Existing rows get NULL. The catalog scraper (pipeline/ingestion/
-- catalog_persist.py) starts populating image_url after this migration
-- ships and after _facts_to_row() is updated to include the field.
-- A backfill scrape will refill the 107 existing products.

ALTER TABLE products
    ADD COLUMN image_url TEXT;

-- Used by the image-download stage to find rows where we have an upstream
-- URL but haven't mirrored to the bucket yet.
CREATE INDEX products_image_url_unmirrored_idx
    ON products (id)
    WHERE image_url IS NOT NULL AND image_path IS NULL;
