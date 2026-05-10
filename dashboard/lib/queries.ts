/**
 * Server-side data queries for the public dashboard.
 *
 * Centralized here so individual pages stay declarative and the typing/casting
 * dance with the supabase-js generated types lives in one place.
 *
 * RLS policies in 0001_initial_schema.sql:
 *   - moments: public read on all rows
 *   - frictions: public read only when review_status='approved'
 *   - matches: public read only when the parent friction is approved
 *   - products: public read on all non-dead rows
 *   - pipeline_runs: public read on all rows (for transparency)
 */

import { createServerClient } from "@/lib/supabase";

export interface PublicMoment {
  id: number;
  name: string;
  source: "tiktok" | "calendar";
  description: string | null;
  trend_velocity: number | null;
  score: number | null;
  moment_date: string;
  created_at: string;
}

export interface PublicFriction {
  id: number;
  moment_id: number;
  friction_summary: string;
  mechanism: string;
  efficacy_class: string | null;
  self_rating: number;
  created_at: string;
}

/**
 * Latest moment that has at least one approved friction.
 * "Latest" = most recently created. We rank inside the page if needed.
 */
export async function getLatestApprovedMoment(): Promise<{
  moment: PublicMoment;
  frictions: PublicFriction[];
} | null> {
  const supabase = createServerClient();

  // 1) Find the latest approved friction; chase it back to its moment.
  //    Two-query pattern is simpler than a complex join under RLS.
  const { data: frictionRows, error: frictionErr } = await supabase
    .from("frictions")
    .select("id, moment_id, friction_summary, mechanism, efficacy_class, self_rating, created_at")
    .eq("review_status", "approved")
    .order("created_at", { ascending: false })
    .limit(20); // pull a window so we have all frictions for the latest moment

  if (frictionErr || !frictionRows || frictionRows.length === 0) return null;

  // The first row's moment_id is the latest approved moment.
  // Filter the window to just that moment's frictions.
  const latestMomentId = (frictionRows[0] as { moment_id: number }).moment_id;
  const frictions = (frictionRows as PublicFriction[]).filter(
    (f) => f.moment_id === latestMomentId,
  );

  // 2) Fetch the moment row itself.
  const { data: momentData, error: momentErr } = await supabase
    .from("moments")
    .select("id, name, source, description, trend_velocity, score, moment_date, created_at")
    .eq("id", latestMomentId)
    .limit(1);

  if (momentErr || !momentData || momentData.length === 0) return null;
  const moment = momentData[0] as PublicMoment;

  return { moment, frictions };
}

// ─────────────────────────────────────────────────────────────────────────────
// Brief detail: a moment + its approved frictions + matched products.
// ─────────────────────────────────────────────────────────────────────────────

export interface PublicProduct {
  id: number;
  brand: string;
  name: string;
  category: string | null;
  public_url: string;
  is_lg: boolean;
  platform: string;
}

export interface PublicMatch {
  id: number;
  product_id: number;
  match_score: number;
  rank: number;
  scientific_argument: string;
  product: PublicProduct;
}

export interface FrictionWithMatches extends PublicFriction {
  matches: PublicMatch[];
}

export async function getBriefByMomentId(momentId: number): Promise<{
  moment: PublicMoment;
  frictions: FrictionWithMatches[];
} | null> {
  const supabase = createServerClient();

  // 1) The moment.
  const { data: momentData, error: momentErr } = await supabase
    .from("moments")
    .select("id, name, source, description, trend_velocity, score, moment_date, created_at")
    .eq("id", momentId)
    .limit(1);
  if (momentErr || !momentData || momentData.length === 0) return null;
  const moment = momentData[0] as PublicMoment;

  // 2) Approved frictions for this moment.
  const { data: frictionData, error: frictionErr } = await supabase
    .from("frictions")
    .select("id, moment_id, friction_summary, mechanism, efficacy_class, self_rating, created_at")
    .eq("moment_id", momentId)
    .eq("review_status", "approved")
    .order("id");
  if (frictionErr || !frictionData) return { moment, frictions: [] };
  const frictions = frictionData as PublicFriction[];
  if (frictions.length === 0) return { moment, frictions: [] };

  // 3) Matches for those frictions, joined to products.
  const frictionIds = frictions.map((f) => f.id);
  const { data: matchData, error: matchErr } = await supabase
    .from("matches")
    .select(
      "id, friction_id, product_id, match_score, rank, scientific_argument, products(id, brand, name, category, public_url, is_lg, platform)",
    )
    .in("friction_id", frictionIds)
    .order("rank");
  if (matchErr) return { moment, frictions: frictions.map((f) => ({ ...f, matches: [] })) };

  type MatchRow = {
    id: number;
    friction_id: number;
    product_id: number;
    match_score: number;
    rank: number;
    scientific_argument: string;
    products: PublicProduct | null;
  };
  const matches = (matchData ?? []) as unknown as MatchRow[];

  const byFriction = new Map<number, PublicMatch[]>();
  for (const m of matches) {
    if (!m.products) continue;
    const arr = byFriction.get(m.friction_id) ?? [];
    arr.push({
      id: m.id,
      product_id: m.product_id,
      match_score: Number(m.match_score),
      rank: m.rank,
      scientific_argument: m.scientific_argument,
      product: m.products,
    });
    byFriction.set(m.friction_id, arr);
  }

  const frictionsWithMatches: FrictionWithMatches[] = frictions.map((f) => ({
    ...f,
    matches: byFriction.get(f.id) ?? [],
  }));

  return { moment, frictions: frictionsWithMatches };
}
