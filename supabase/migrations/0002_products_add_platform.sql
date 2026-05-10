-- 0002_products_add_platform — 2026-05-11
--
-- Adds source-provenance tracking to the products table so we can tell
-- where each row came from: an aggregator scrape (OY Global today; OY Korea
-- and others future) or a hand-curated brand-direct seed.
--
-- Why the column matters operationally:
--   • Re-scraping a platform replaces only that platform's rows, never
--     overwrites manually-curated LG-direct entries.
--   • Dashboard can show provenance ("12 of these matches are from a
--     hand-curated LG catalog; 28 are from Olive Young Global").
--   • Different platforms have different freshness expectations — the
--     dead-link checker can run more aggressively on aggregator scrapes
--     than on hand-curated seeds.
--
-- Existing rows get the default 'oy_global' since that was the only intended
-- source pre-pivot. After this migration ships, every new product insert
-- explicitly sets platform.

ALTER TABLE products
    ADD COLUMN platform TEXT NOT NULL DEFAULT 'oy_global';

-- Index for "show me only LG-direct products" / "rescrape oy_global only" queries.
CREATE INDEX products_platform_idx ON products (platform);

-- The is_lg flag still represents corporate ownership (a CARE PLUS product
-- from OY Global is still LG-owned). The platform column is orthogonal to
-- ownership. Both filters compose: is_lg=true AND platform='lg_brand_direct'
-- = "premium LG products we hand-curated".
