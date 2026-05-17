-- 0008_products_image_path — 2026-05-17
--
-- Adds a column for the path of the product's image within the Supabase
-- Storage `product-images` bucket. Distinct from the existing image_url
-- column, which is OY's CDN URL (subject to hot-link policy + outages).
-- Once we mirror the image to our bucket, the dashboard serves the bucket
-- URL — under our control, no external dependency at render time.
--
-- Format: `image_path` is the bucket-relative key (e.g.
-- "GA250329366.jpg"), NOT the full URL. The dashboard builds the public
-- URL by joining {SUPABASE_URL}/storage/v1/object/public/product-images/{image_path}.
--
-- A NULL image_path means "not yet downloaded." The catalog_images
-- pipeline stage finds these rows and fills them on the next run.

ALTER TABLE products
    ADD COLUMN image_path TEXT;

-- Used by "find products that still need their image downloaded".
CREATE INDEX products_image_path_missing_idx
    ON products (id)
    WHERE image_path IS NULL;
