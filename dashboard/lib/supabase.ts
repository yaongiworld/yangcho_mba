/**
 * Supabase client factories.
 *
 * - createServerClient(): for App Router server components / route handlers.
 *   Reads RLS-restricted public tables under the publishable key. No cookies
 *   needed for the public dashboard read paths; we add cookie auth later
 *   when we wire Yangcho's review-queue page.
 * - createBrowserClient(): for client components.
 *
 * Generated types live in `dashboard/types/db.ts` (regenerated via
 * `npm run db:types`). Both factories are typed against `Database`.
 */

import {
  createBrowserClient as _createBrowserClient,
  createServerClient as _createServerClient,
} from "@supabase/ssr";
import type { Database } from "@/types/db";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const SUPABASE_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!;

export function createBrowserClient() {
  return _createBrowserClient<Database>(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
}

/**
 * Server-side client for App Router server components.
 *
 * The cookies adapter is a no-op here because the public dashboard pages
 * don't need a user session — RLS policies in 0001_initial_schema.sql
 * grant read on approved frictions / moments / matches to the anon role.
 * When we wire /admin/queue (Yangcho's auth-gated review page), we'll
 * swap in the real next/headers cookie adapter.
 */
export function createServerClient() {
  return _createServerClient<Database>(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    cookies: {
      getAll() {
        return [];
      },
      setAll() {
        // public read-only context — no auth cookies to write
      },
    },
  });
}

// NOTE: there is intentionally NO admin/service-role client factory here.
// The SUPABASE_SECRET_KEY is kept out of the dashboard's env surface entirely
// to avoid widening the trust boundary (it would otherwise live in Vercel's
// shared env, where any team member could see it and a misplaced client
// import could leak it into the browser bundle). Admin reads instead go
// through the publishable key + RLS policies relaxed in migration 0005;
// /admin remains an unlinked URL-obscurity surface until Supabase Auth
// lands in W7 and we can tighten RLS to authed-admin-only reads.
