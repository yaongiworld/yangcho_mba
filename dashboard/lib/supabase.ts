/**
 * Supabase client factories. Two flavors:
 *   - createServerClient(): for App Router server components, uses cookies for auth.
 *   - createBrowserClient(): for client components.
 *
 * Generated types live in `dashboard/types/db.ts` (regenerated via
 * `npm run db:types`). Both factories are typed against `Database`.
 *
 * Real implementation lands in W5 — this stub keeps imports valid.
 */

import { createBrowserClient as _createBrowserClient } from "@supabase/ssr";
import type { Database } from "@/types/db";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const SUPABASE_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!;

export function createBrowserClient() {
  return _createBrowserClient<Database>(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
}
