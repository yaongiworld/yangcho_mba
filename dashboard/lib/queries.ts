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
  /** Bucket-relative path inside product-images. Null when the image
   *  has not yet been mirrored from OY's CDN. Build the public URL via
   *  productImageUrl() in lib/storage.ts. */
  image_path: string | null;
}

export interface PublicMatch {
  id: number;
  product_id: number;
  match_score: number;
  rank: number;
  scientific_argument: string;
  product: PublicProduct;
}

// ─────────────────────────────────────────────────────────────────────────────
// Playbook output bodies — three flavors, JSON-shaped, gated by `kind`.
// ─────────────────────────────────────────────────────────────────────────────

export interface MarketingPostBody {
  headline: string;
  body: string;
  call_to_action: string;
}

export interface ProductIdeaBody {
  concept_name: string;
  target_friction: string;
  hero_mechanism: string;
  hero_ingredient_class: string;
  target_consumer_profile: string;
  competitive_white_space: string;
}

export interface InfluencerSuggestionEntry {
  creator_handle: string;
  reasoning: string;
  public_evidence: string;
}

export interface InfluencerOutputBody {
  suggestions: InfluencerSuggestionEntry[];
}

export interface FrictionWithMatches extends PublicFriction {
  matches: PublicMatch[];
  /** Approved marketing post for this friction, if any. */
  marketing_post: MarketingPostBody | null;
  /** Approved new-product idea for this friction, if any. */
  product_idea: ProductIdeaBody | null;
}

export async function getBriefByMomentId(momentId: number): Promise<{
  moment: PublicMoment;
  frictions: FrictionWithMatches[];
  /** Influencer suggestions for the whole moment (anchored to its first
   *  approved friction in storage). Null when no approved suggestions exist. */
  influencer_suggestions: InfluencerOutputBody | null;
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
  if (frictionErr || !frictionData) {
    return { moment, frictions: [], influencer_suggestions: null };
  }
  const frictions = frictionData as PublicFriction[];
  if (frictions.length === 0) {
    return { moment, frictions: [], influencer_suggestions: null };
  }

  // 3) Matches for those frictions, joined to products.
  const frictionIds = frictions.map((f) => f.id);
  const { data: matchData, error: matchErr } = await supabase
    .from("matches")
    .select(
      "id, friction_id, product_id, match_score, rank, scientific_argument, products(id, brand, name, category, public_url, is_lg, platform, image_path)",
    )
    .in("friction_id", frictionIds)
    .order("rank");
  if (matchErr) {
    return {
      moment,
      frictions: frictions.map((f) => ({
        ...f,
        matches: [],
        marketing_post: null,
        product_idea: null,
      })),
      influencer_suggestions: null,
    };
  }

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

  // 4) Playbook outputs (3 kinds) for those frictions. Approved only.
  const { data: playbookData } = await supabase
    .from("playbook_outputs")
    .select("id, friction_id, kind, body")
    .in("friction_id", frictionIds)
    .eq("review_status", "approved");

  type PlaybookRow = {
    id: number;
    friction_id: number;
    kind: "marketing_post" | "product_idea" | "influencer";
    body: Record<string, unknown>;
  };
  const playbook = (playbookData ?? []) as unknown as PlaybookRow[];

  const marketingByFriction = new Map<number, MarketingPostBody>();
  const ideaByFriction = new Map<number, ProductIdeaBody>();
  let influencerSuggestions: InfluencerOutputBody | null = null;

  for (const p of playbook) {
    if (p.kind === "marketing_post") {
      marketingByFriction.set(p.friction_id, p.body as unknown as MarketingPostBody);
    } else if (p.kind === "product_idea") {
      ideaByFriction.set(p.friction_id, p.body as unknown as ProductIdeaBody);
    } else if (p.kind === "influencer") {
      // Per-moment, anchored to the first friction's id. Pick whichever we find.
      influencerSuggestions = p.body as unknown as InfluencerOutputBody;
    }
  }

  const frictionsWithMatches: FrictionWithMatches[] = frictions.map((f) => ({
    ...f,
    matches: byFriction.get(f.id) ?? [],
    marketing_post: marketingByFriction.get(f.id) ?? null,
    product_idea: ideaByFriction.get(f.id) ?? null,
  }));

  return {
    moment,
    frictions: frictionsWithMatches,
    influencer_suggestions: influencerSuggestions,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Home dashboard cards: one row per approved moment, projected to the bits
// the home page renders (top friction, top match, marketing post, top
// influencer). Pre-flattened server-side so the page stays declarative.
// ─────────────────────────────────────────────────────────────────────────────

export interface DashboardCard {
  moment: PublicMoment;
  /** The highest-self-rated approved friction for this moment. Cards always
   *  have one — moments with no approved frictions are filtered out upstream. */
  friction: PublicFriction;
  /** Rank-1 match for the chosen friction. Null when the friction has no
   *  product matches yet (manual approval between cron ticks). */
  top_match: PublicMatch | null;
  /** Approved marketing post for the chosen friction. Null when not yet
   *  generated/approved. */
  marketing_post: MarketingPostBody | null;
  /** First approved influencer suggestion for this moment. Influencer outputs
   *  are stored per-moment (anchored to one friction), so we don't filter by
   *  friction here. Null when none exist. */
  top_influencer: InfluencerSuggestionEntry | null;
}

export async function getDashboardCards(): Promise<DashboardCard[]> {
  const supabase = createServerClient();

  // 1) All approved frictions. We need every row to compute the per-moment
  //    "top friction" (highest self_rating). Keep this query unscoped by
  //    moment to avoid an N+1.
  const { data: frictionRows, error: frictionErr } = await supabase
    .from("frictions")
    .select("id, moment_id, friction_summary, mechanism, efficacy_class, self_rating, created_at")
    .eq("review_status", "approved");
  if (frictionErr || !frictionRows || frictionRows.length === 0) return [];

  const frictions = frictionRows as unknown as PublicFriction[];

  // Pick the highest self_rating per moment; tiebreak on most recent.
  const topByMoment = new Map<number, PublicFriction>();
  for (const f of frictions) {
    const cur = topByMoment.get(f.moment_id);
    if (
      !cur ||
      f.self_rating > cur.self_rating ||
      (f.self_rating === cur.self_rating && f.created_at > cur.created_at)
    ) {
      topByMoment.set(f.moment_id, f);
    }
  }

  const topFrictionIds = Array.from(topByMoment.values()).map((f) => f.id);
  const momentIds = Array.from(topByMoment.keys());

  // 2) Moments themselves, sorted by moment_date desc (newest first matches
  //    the "daily updating" feel of the dashboard).
  const { data: momentRows, error: momentErr } = await supabase
    .from("moments")
    .select("id, name, source, description, trend_velocity, score, moment_date, created_at")
    .in("id", momentIds)
    .order("moment_date", { ascending: false })
    .order("created_at", { ascending: false });
  if (momentErr || !momentRows) return [];
  const moments = momentRows as unknown as PublicMoment[];

  // 3) Rank-1 matches for the chosen frictions, joined to products.
  const { data: matchData } = await supabase
    .from("matches")
    .select(
      "id, friction_id, product_id, match_score, rank, scientific_argument, products(id, brand, name, category, public_url, is_lg, platform, image_path)",
    )
    .in("friction_id", topFrictionIds)
    .eq("rank", 1);
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
  const matchByFriction = new Map<number, PublicMatch>();
  for (const m of matches) {
    if (!m.products) continue;
    matchByFriction.set(m.friction_id, {
      id: m.id,
      product_id: m.product_id,
      match_score: Number(m.match_score),
      rank: m.rank,
      scientific_argument: m.scientific_argument,
      product: m.products,
    });
  }

  // 4) Approved marketing posts for chosen frictions.
  //    Influencer outputs for the moments. One query for both kinds.
  const allFrictionIdsForMoments = frictions.map((f) => f.id);
  const { data: playbookData } = await supabase
    .from("playbook_outputs")
    .select("id, friction_id, kind, body")
    .in("friction_id", allFrictionIdsForMoments)
    .in("kind", ["marketing_post", "influencer"])
    .eq("review_status", "approved");
  type PlaybookRow = {
    id: number;
    friction_id: number;
    kind: "marketing_post" | "product_idea" | "influencer";
    body: Record<string, unknown>;
  };
  const playbook = (playbookData ?? []) as unknown as PlaybookRow[];

  const marketingByFriction = new Map<number, MarketingPostBody>();
  // Influencer outputs are anchored to one friction; reverse-lookup that to
  // moment_id so we can attach the post to whichever card matches.
  const frictionToMoment = new Map<number, number>();
  for (const f of frictions) frictionToMoment.set(f.id, f.moment_id);
  const influencerByMoment = new Map<number, InfluencerSuggestionEntry>();

  for (const p of playbook) {
    if (p.kind === "marketing_post") {
      marketingByFriction.set(p.friction_id, p.body as unknown as MarketingPostBody);
    } else if (p.kind === "influencer") {
      const body = p.body as unknown as InfluencerOutputBody;
      const momId = frictionToMoment.get(p.friction_id);
      if (momId != null && body.suggestions && body.suggestions.length > 0) {
        // Take the first suggestion only — the home card is a teaser; full
        // list lives on /brief/[id].
        influencerByMoment.set(momId, body.suggestions[0]);
      }
    }
  }

  // 5) Assemble cards in moment-sort order.
  const cards: DashboardCard[] = [];
  for (const m of moments) {
    const friction = topByMoment.get(m.id);
    if (!friction) continue;
    cards.push({
      moment: m,
      friction,
      top_match: matchByFriction.get(friction.id) ?? null,
      marketing_post: marketingByFriction.get(friction.id) ?? null,
      top_influencer: influencerByMoment.get(m.id) ?? null,
    });
  }
  return cards;
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

// ─────────────────────────────────────────────────────────────────────────────
// Pending playbook queue — extends the admin review surface to cover the
// three playbook kinds. Each kind's body shape lives behind a discriminated
// union; the page renders per kind.
// ─────────────────────────────────────────────────────────────────────────────

export type PlaybookKind = "marketing_post" | "product_idea" | "influencer";

export interface PendingPlaybookEntry {
  playbook_id: number;
  kind: PlaybookKind;
  friction_id: number;
  moment_id: number;
  moment_name: string;
  moment_date: string;
  friction_summary: string;
  body: MarketingPostBody | ProductIdeaBody | InfluencerOutputBody;
  created_at: string;
}

export async function getPendingPlaybook(): Promise<PendingPlaybookEntry[]> {
  const supabase = createServerClient();

  const { data: playbookRows, error } = await supabase
    .from("playbook_outputs")
    .select("id, friction_id, kind, body, created_at")
    .eq("review_status", "pending")
    .order("created_at", { ascending: false })
    .limit(200);
  if (error || !playbookRows || playbookRows.length === 0) return [];

  type PlaybookLite = {
    id: number;
    friction_id: number;
    kind: PlaybookKind;
    body: Record<string, unknown>;
    created_at: string;
  };
  const playbook = playbookRows as unknown as PlaybookLite[];

  // Hydrate friction context (summary + moment_id) for every entry.
  const frictionIds = Array.from(new Set(playbook.map((p) => p.friction_id)));
  const { data: frictionRows } = await supabase
    .from("frictions")
    .select("id, moment_id, friction_summary")
    .in("id", frictionIds);
  type FrictionLite = { id: number; moment_id: number; friction_summary: string };
  const frictions = (frictionRows ?? []) as unknown as FrictionLite[];
  const frictionById = new Map(frictions.map((f) => [f.id, f]));

  // Hydrate moment names + dates.
  const momentIds = Array.from(new Set(frictions.map((f) => f.moment_id)));
  const { data: momentRows } = await supabase
    .from("moments")
    .select("id, name, moment_date")
    .in("id", momentIds);
  type MomentLite = { id: number; name: string; moment_date: string };
  const moments = (momentRows ?? []) as unknown as MomentLite[];
  const momentById = new Map(moments.map((m) => [m.id, m]));

  return playbook
    .map((p) => {
      const f = frictionById.get(p.friction_id);
      if (!f) return null;
      const m = momentById.get(f.moment_id);
      return {
        playbook_id: p.id,
        kind: p.kind,
        friction_id: p.friction_id,
        moment_id: f.moment_id,
        moment_name: m?.name ?? `(missing moment ${f.moment_id})`,
        moment_date: m?.moment_date ?? "",
        friction_summary: f.friction_summary,
        // Body shape is known per-kind at runtime; we trust the writer
        // (pipeline) to put the right JSON in based on `kind`. The
        // dashboard discriminates on kind to pick the rendering.
        body: p.body as unknown as PendingPlaybookEntry["body"],
        created_at: p.created_at,
      } satisfies PendingPlaybookEntry;
    })
    .filter((e): e is PendingPlaybookEntry => e !== null);
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
