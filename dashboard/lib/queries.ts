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

// ─────────────────────────────────────────────────────────────────────────────
// Archive: every moment that has at least one approved friction.
// Used by /trends. Public read; no auth.
// ─────────────────────────────────────────────────────────────────────────────

export interface ArchiveEntry {
  moment: PublicMoment;
  friction_count: number;
  match_count: number;
}

export async function getAllApprovedMoments(): Promise<ArchiveEntry[]> {
  const supabase = createServerClient();

  // 1) All approved frictions, projected to (moment_id, id).
  //    We do two queries instead of one big join because RLS-restricted
  //    aggregate queries are awkward via supabase-js.
  const { data: frictionRows, error: frictionErr } = await supabase
    .from("frictions")
    .select("id, moment_id")
    .eq("review_status", "approved");
  if (frictionErr || !frictionRows || frictionRows.length === 0) return [];

  type FrictionLite = { id: number; moment_id: number };
  const frictions = frictionRows as unknown as FrictionLite[];

  // Index: moment_id -> set of approved friction ids
  const frictionsByMoment = new Map<number, number[]>();
  for (const f of frictions) {
    const arr = frictionsByMoment.get(f.moment_id) ?? [];
    arr.push(f.id);
    frictionsByMoment.set(f.moment_id, arr);
  }

  const momentIds = Array.from(frictionsByMoment.keys());

  // 2) Matches for any of those frictions (only need count per moment).
  const allFrictionIds = frictions.map((f) => f.id);
  const { data: matchRows } = await supabase
    .from("matches")
    .select("friction_id")
    .in("friction_id", allFrictionIds);
  type MatchLite = { friction_id: number };
  const matches = (matchRows ?? []) as unknown as MatchLite[];

  // Per-moment match count: for each match, look up its friction's moment_id.
  const frictionToMoment = new Map<number, number>();
  for (const f of frictions) frictionToMoment.set(f.id, f.moment_id);
  const matchCountByMoment = new Map<number, number>();
  for (const m of matches) {
    const momId = frictionToMoment.get(m.friction_id);
    if (momId == null) continue;
    matchCountByMoment.set(momId, (matchCountByMoment.get(momId) ?? 0) + 1);
  }

  // 3) Fetch the moments themselves, newest first.
  const { data: momentRows, error: momentErr } = await supabase
    .from("moments")
    .select("id, name, source, description, trend_velocity, score, moment_date, created_at")
    .in("id", momentIds)
    .order("moment_date", { ascending: false })
    .order("created_at", { ascending: false });
  if (momentErr || !momentRows) return [];

  return (momentRows as unknown as PublicMoment[]).map((m) => ({
    moment: m,
    friction_count: frictionsByMoment.get(m.id)?.length ?? 0,
    match_count: matchCountByMoment.get(m.id) ?? 0,
  }));
}

// ─────────────────────────────────────────────────────────────────────────────
// Admin queries — operator-only, not gated yet (TODO: Supabase Auth).
// ─────────────────────────────────────────────────────────────────────────────

export interface PipelineRunRow {
  id: number;
  stage: string;
  status: "running" | "success" | "failure" | "partial";
  started_at: string;
  finished_at: string | null;
  items_processed: number | null;
  items_succeeded: number | null;
  error_message: string | null;
  code_version: string;
}

export interface PipelineRunGroup {
  /** First-stage start time — the run's effective start. */
  started_at: string;
  /** Last-stage finish time, or null if anything is still running. */
  finished_at: string | null;
  stages: PipelineRunRow[];
  /** Overall status — failure if any stage failed, partial if any partial,
   *  success if all stages succeeded, running otherwise. */
  overall_status: "success" | "failure" | "partial" | "running";
}

const RUN_GROUP_GAP_MS = 5 * 60 * 1000; // 5 minutes between cron ticks

function groupPipelineRuns(rows: PipelineRunRow[]): PipelineRunGroup[] {
  // Sort ASC so we can walk and bucket. We'll reverse-sort the final groups
  // at the end so the page shows newest first.
  const sorted = [...rows].sort(
    (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
  );

  const groups: PipelineRunGroup[] = [];
  let current: PipelineRunRow[] = [];
  let lastTs: number | null = null;

  for (const row of sorted) {
    const ts = new Date(row.started_at).getTime();
    if (lastTs !== null && ts - lastTs > RUN_GROUP_GAP_MS) {
      groups.push(finalizeGroup(current));
      current = [];
    }
    current.push(row);
    lastTs = ts;
  }
  if (current.length > 0) groups.push(finalizeGroup(current));

  return groups.reverse();
}

function finalizeGroup(stages: PipelineRunRow[]): PipelineRunGroup {
  let overall: PipelineRunGroup["overall_status"] = "success";
  for (const s of stages) {
    if (s.status === "running") {
      overall = "running";
      break;
    }
    if (s.status === "failure") {
      overall = "failure";
      break;
    }
    if (s.status === "partial") {
      overall = "partial";
    }
  }
  const finishedTimes = stages
    .map((s) => (s.finished_at ? new Date(s.finished_at).getTime() : null))
    .filter((t): t is number => t !== null);
  const lastFinish = finishedTimes.length === stages.length && finishedTimes.length > 0
    ? new Date(Math.max(...finishedTimes)).toISOString()
    : null;
  return {
    started_at: stages[0].started_at,
    finished_at: lastFinish,
    stages,
    overall_status: overall,
  };
}

export async function getRecentPipelineRunGroups(
  limit: number = 200,
): Promise<PipelineRunGroup[]> {
  const supabase = createServerClient();
  const { data, error } = await supabase
    .from("pipeline_runs")
    .select(
      "id, stage, status, started_at, finished_at, items_processed, items_succeeded, error_message, code_version",
    )
    .order("started_at", { ascending: false })
    .limit(limit);
  if (error || !data) return [];
  return groupPipelineRuns(data as unknown as PipelineRunRow[]);
}

export interface PendingFrictionEntry {
  friction_id: number;
  moment_id: number;
  moment_name: string;
  moment_date: string;
  friction_summary: string;
  /** Full mechanism text — what Yangcho actually reads to decide approve/reject. */
  mechanism: string;
  efficacy_class: string | null;
  self_rating: number;
  created_at: string;
}

export async function getPendingFrictions(): Promise<PendingFrictionEntry[]> {
  // Per migration 0005, the publishable key can read all frictions
  // (including pending). When Supabase Auth lands (W7), the RLS gate
  // will return and this query will need an authed-admin session.
  const supabase = createServerClient();

  const { data: frictionRows, error } = await supabase
    .from("frictions")
    .select(
      "id, moment_id, friction_summary, mechanism, efficacy_class, self_rating, created_at",
    )
    .eq("review_status", "pending")
    .order("created_at", { ascending: false })
    .limit(200);
  if (error || !frictionRows || frictionRows.length === 0) return [];

  type FrictionLite = {
    id: number;
    moment_id: number;
    friction_summary: string;
    mechanism: string;
    efficacy_class: string | null;
    self_rating: number;
    created_at: string;
  };
  const frictions = frictionRows as unknown as FrictionLite[];

  // Hydrate moment names in one query.
  const momentIds = Array.from(new Set(frictions.map((f) => f.moment_id)));
  const { data: momentRows } = await supabase
    .from("moments")
    .select("id, name, moment_date")
    .in("id", momentIds);
  type MomentLite = { id: number; name: string; moment_date: string };
  const moments = (momentRows ?? []) as unknown as MomentLite[];
  const byId = new Map(moments.map((m) => [m.id, m]));

  return frictions.map((f) => {
    const m = byId.get(f.moment_id);
    return {
      friction_id: f.id,
      moment_id: f.moment_id,
      moment_name: m?.name ?? `(missing moment ${f.moment_id})`,
      moment_date: m?.moment_date ?? "",
      friction_summary: f.friction_summary,
      mechanism: f.mechanism,
      efficacy_class: f.efficacy_class,
      self_rating: f.self_rating,
      created_at: f.created_at,
    };
  });
}

export interface AdminMomentEntry {
  moment: PublicMoment;
  friction_count: number;
  approved_count: number;
  pending_count: number;
  match_count: number;
}

export async function getAllMomentsAdmin(): Promise<AdminMomentEntry[]> {
  // Reads all frictions including pending — enabled by migration 0005
  // for now; tightens when Supabase Auth lands.
  const supabase = createServerClient();

  const { data: momentRows, error: momentErr } = await supabase
    .from("moments")
    .select("id, name, source, description, trend_velocity, score, moment_date, created_at")
    .order("created_at", { ascending: false })
    .limit(200);
  if (momentErr || !momentRows) return [];
  const moments = momentRows as unknown as PublicMoment[];

  const { data: frictionRows } = await supabase
    .from("frictions")
    .select("id, moment_id, review_status");
  type FrictionLite = { id: number; moment_id: number; review_status: string };
  const frictions = (frictionRows ?? []) as unknown as FrictionLite[];

  const { data: matchRows } = await supabase.from("matches").select("friction_id");
  const matches = (matchRows ?? []) as unknown as { friction_id: number }[];

  const fricByMom = new Map<number, FrictionLite[]>();
  for (const f of frictions) {
    const arr = fricByMom.get(f.moment_id) ?? [];
    arr.push(f);
    fricByMom.set(f.moment_id, arr);
  }
  const matchCountByMom = new Map<number, number>();
  for (const m of matches) {
    const friction = frictions.find((f) => f.id === m.friction_id);
    if (!friction) continue;
    matchCountByMom.set(
      friction.moment_id,
      (matchCountByMom.get(friction.moment_id) ?? 0) + 1,
    );
  }

  return moments.map((m) => {
    const fric = fricByMom.get(m.id) ?? [];
    return {
      moment: m,
      friction_count: fric.length,
      approved_count: fric.filter((f) => f.review_status === "approved").length,
      pending_count: fric.filter((f) => f.review_status === "pending").length,
      match_count: matchCountByMom.get(m.id) ?? 0,
    };
  });
}
