-- 0003_products_external_id_unique — 2026-05-11
--
-- Replaces the UNIQUE (brand, name) constraint on products with a more
-- accurate natural key: (platform, external_id). The original constraint
-- was a guess from before we knew what scraping platforms looked like;
-- in practice (brand, name) collides across:
--   - Different SKU sizes of the same product line ("CAREPLUS Spot Patch 102P"
--     vs "CAREPLUS Spot Patch 252P" — same brand, names differ but a future
--     truncation/normalization could collide).
--   - Re-launches under the same name with new prdtNo on OY's side.
--
-- The right unique key is the platform's own external ID. (platform, external_id)
-- never collides because each platform's IDs are local to itself.

-- Add the external_id column. Existing rows (only the test data from earlier
-- live runs) get NULL, then we drop those rows because they predate this
-- W2 catalog work and have no real external_id to backfill.
ALTER TABLE products ADD COLUMN external_id TEXT;

-- Drop any pre-W2 test rows. There shouldn't be any — moments and frictions
-- have data, but products has been empty until now. Defensive cleanup.
DELETE FROM products WHERE external_id IS NULL;

-- Now NOT NULL the column. Future inserts must provide it.
ALTER TABLE products ALTER COLUMN external_id SET NOT NULL;

-- Drop the old (brand, name) unique constraint. PostgreSQL auto-named it
-- products_brand_name_key when we declared `UNIQUE (brand, name)` in
-- 0001_initial_schema.sql.
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_brand_name_key;

-- Add the new constraint.
ALTER TABLE products ADD CONSTRAINT products_platform_external_id_key
    UNIQUE (platform, external_id);

-- Index for "look up product by its OY prdtNo" queries.
CREATE INDEX products_external_id_idx ON products (external_id);
