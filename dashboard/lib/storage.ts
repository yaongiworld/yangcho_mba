/**
 * Supabase Storage URL helpers — public-bucket only.
 *
 * The pipeline writes product images to the `product-images` bucket
 * (see pipeline/ingestion/image_storage.py). This module builds the
 * public URL the dashboard renders.
 *
 * We don't use supabase-js's getPublicUrl() because it adds an extra
 * client init for what's a deterministic URL pattern. Constructing it
 * directly keeps the dashboard's Supabase reads server-rendered + cheap.
 */

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL!;

/** Product images bucket. Created manually in the Supabase dashboard
 *  as a public-read bucket. */
export const PRODUCT_IMAGES_BUCKET = "product-images";

/** Returns the public URL for a bucket-relative image path, or null
 *  when the path is missing (e.g. a product that hasn't been mirrored
 *  yet). Callers should handle null with a placeholder/no-image state. */
export function productImageUrl(imagePath: string | null | undefined): string | null {
  if (!imagePath) return null;
  if (!SUPABASE_URL) return null;
  // Strip any leading slash; we always join with one slash.
  const clean = imagePath.replace(/^\/+/, "");
  return `${SUPABASE_URL}/storage/v1/object/public/${PRODUCT_IMAGES_BUCKET}/${clean}`;
}
