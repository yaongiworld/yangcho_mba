import type { NextConfig } from "next";

// Whitelist the Supabase Storage host for next/image. We mirror OY product
// images into the `product-images` public bucket (see pipeline/ingestion/
// catalog_images.py), and the dashboard renders them via /storage/v1/object/
// public/... URLs.
const supabaseHost = (() => {
  const raw = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!raw) return null;
  try {
    return new URL(raw).hostname;
  } catch {
    return null;
  }
})();

const config: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  images: {
    remotePatterns: supabaseHost
      ? [
          {
            protocol: "https",
            hostname: supabaseHost,
            pathname: "/storage/v1/object/public/**",
          },
        ]
      : [],
  },
};

export default config;
