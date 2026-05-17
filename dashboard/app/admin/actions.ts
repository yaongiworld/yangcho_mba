/**
 * Server Actions for /admin. Approve / reject pending frictions.
 *
 * These run server-side under the publishable key (no SUPABASE_SECRET_KEY
 * in the dashboard env per the architectural decision in lib/supabase.ts).
 * Migration 0006 grants column-level UPDATE on frictions.review_status +
 * reviewed_at to anon, with a RLS WITH CHECK gate restricting writes to
 * the three terminal review states.
 *
 * Matching deferral: approving a friction does NOT run product matching
 * synchronously. The next pipeline cron tick catches up via a backfill
 * stage that finds approved frictions with no matches and runs
 * match_one_friction on them. Yangcho's approve becomes "live" within
 * one cron interval (currently daily; can shorten if needed).
 */

"use server";

import { revalidatePath } from "next/cache";

import { createServerClient } from "@/lib/supabase";

export interface ReviewActionResult {
  ok: boolean;
  error?: string;
}

async function setReviewStatus(
  frictionId: number,
  status: "approved" | "rejected",
): Promise<ReviewActionResult> {
  if (!Number.isFinite(frictionId) || frictionId <= 0) {
    return { ok: false, error: "invalid friction id" };
  }

  const supabase = createServerClient();
  // Cast at the boundary — Supabase's typed update() narrows to `never`
  // when the generated types include enums + nullable fields together,
  // a quirk we already worked around in app/methodology/page.tsx.
  const update = {
    review_status: status,
    reviewed_at: new Date().toISOString(),
  } as never;
  const { error } = await supabase
    .from("frictions")
    .update(update)
    .eq("id", frictionId);

  if (error) {
    return { ok: false, error: error.message };
  }

  // Refresh the admin page (queue, all-moments lens) + the public archive
  // (an approval just made a brief visible). The home page re-evaluates
  // its "latest approved moment" query on next visit.
  revalidatePath("/admin");
  revalidatePath("/trends");
  revalidatePath("/");
  return { ok: true };
}

export async function approveFriction(frictionId: number): Promise<ReviewActionResult> {
  return setReviewStatus(frictionId, "approved");
}

export async function rejectFriction(frictionId: number): Promise<ReviewActionResult> {
  return setReviewStatus(frictionId, "rejected");
}

// ─────────────────────────────────────────────────────────────────────────────
// Playbook approve/reject — same shape as friction actions, different table.
// Enabled by migration 0007 (anon UPDATE policy on playbook_outputs).
// ─────────────────────────────────────────────────────────────────────────────

async function setPlaybookReviewStatus(
  playbookId: number,
  status: "approved" | "rejected",
): Promise<ReviewActionResult> {
  if (!Number.isFinite(playbookId) || playbookId <= 0) {
    return { ok: false, error: "invalid playbook id" };
  }

  const supabase = createServerClient();
  // Same as the friction action — typed update narrows to `never` on the
  // generated supabase types; cast at the boundary.
  const update = {
    review_status: status,
    reviewed_at: new Date().toISOString(),
  } as never;
  const { error } = await supabase
    .from("playbook_outputs")
    .update(update)
    .eq("id", playbookId);

  if (error) {
    return { ok: false, error: error.message };
  }

  revalidatePath("/admin");
  revalidatePath("/trends");
  revalidatePath("/");
  return { ok: true };
}

export async function approvePlaybook(playbookId: number): Promise<ReviewActionResult> {
  return setPlaybookReviewStatus(playbookId, "approved");
}

export async function rejectPlaybook(playbookId: number): Promise<ReviewActionResult> {
  return setPlaybookReviewStatus(playbookId, "rejected");
}
