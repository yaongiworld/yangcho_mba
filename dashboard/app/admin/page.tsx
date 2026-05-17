/**
 * Operator dashboard. Three sections:
 *   1. Recent pipeline runs — grouped by cron tick, with stage breakdowns.
 *   2. Pending review queue — frictions waiting for Yangcho's approval.
 *   3. All moments admin lens — every moment, including pending-only and
 *      no-friction rows, with status badges and click-through to /brief/[id].
 *
 * Auth: SKIPPED for now. The SUPABASE_SECRET_KEY is intentionally NOT in
 * the dashboard's env surface (see lib/supabase.ts). Instead, migration
 * 0005 relaxed the RLS policies on frictions/matches/playbook_outputs so
 * the publishable key can read all rows including pending content. /admin
 * is unlinked from the public site; security relies on URL obscurity +
 * Vercel password protection (when deployed).
 *
 * TRADE-OFF: a leaked /admin URL would expose all pending content.
 *
 * W7 plan: add Supabase Auth (magic link to Yangcho's email), revert
 * migration 0005, add a new RLS policy granting full read to her authed
 * user only. Then this page checks the session before rendering.
 */

import Link from "next/link";

import { approveFriction, rejectFriction } from "@/app/admin/actions";
import { signoutAction } from "@/app/admin/login/actions";
import { triggerMatching } from "@/app/admin/trigger";
import {
  getRecentPipelineRunGroups,
  getPendingFrictions,
  getAllMomentsAdmin,
} from "@/lib/queries";
import type {
  AdminMomentEntry,
  PendingFrictionEntry,
  PipelineRunGroup,
  PipelineRunRow,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    timeZone: "Asia/Seoul",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    timeZone: "Asia/Seoul",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function durationMs(start: string, end: string | null): string {
  if (!end) return "running…";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

const STATUS_COLORS: Record<string, string> = {
  success: "text-emerald-700 bg-emerald-50 border-emerald-200",
  partial: "text-amber-700 bg-amber-50 border-amber-200",
  failure: "text-rose-700 bg-rose-50 border-rose-200",
  running: "text-blue-700 bg-blue-50 border-blue-200",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "text-neutral-700 bg-neutral-50 border-neutral-200";
  return (
    <span className={`inline-block text-xs font-mono uppercase tracking-wide px-2 py-0.5 border rounded ${cls}`}>
      {status}
    </span>
  );
}

export default async function AdminPage() {
  // Run queries in parallel.
  const [runGroups, pending, moments] = await Promise.all([
    getRecentPipelineRunGroups(),
    getPendingFrictions(),
    getAllMomentsAdmin(),
  ]);

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header className="border-b border-neutral-200 pb-6 mb-10">
        <p className="text-sm uppercase tracking-widest text-neutral-500">Operator</p>
        <h1 className="mt-2 text-3xl font-semibold leading-tight">Admin dashboard</h1>
        <nav className="mt-4 flex items-baseline gap-3 flex-wrap text-sm text-neutral-500">
          <Link href="/" className="underline hover:text-neutral-900">Home</Link>
          <span>·</span>
          <Link href="/trends" className="underline hover:text-neutral-900">Archive</Link>
          <span>·</span>
          <Link href="/methodology" className="underline hover:text-neutral-900">Methodology</Link>
          <form action={signoutAction} className="ml-auto">
            <button type="submit" className="underline hover:text-neutral-900">Sign out</button>
          </form>
        </nav>
      </header>

      <PipelineRunsSection groups={runGroups} />
      <PendingReviewSection pending={pending} />
      <AllMomentsSection entries={moments} />
    </main>
  );
}

async function triggerMatchingAction() {
  "use server";
  await triggerMatching();
}

function PipelineRunsSection({ groups }: { groups: PipelineRunGroup[] }) {
  return (
    <section className="mb-16">
      <div className="flex items-baseline justify-between gap-4 mb-2 flex-wrap">
        <h2 className="text-xl font-semibold">Recent pipeline runs</h2>
        <form action={triggerMatchingAction}>
          <button
            type="submit"
            className="rounded bg-neutral-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-neutral-700 transition-colors"
          >
            Run matcher now ↻
          </button>
        </form>
      </div>
      <p className="text-sm text-neutral-500 mb-6">
        Grouped by cron tick (stages within 5 minutes treated as one run).
        Newest first.{" "}
        <span className="text-neutral-700">
          Manual trigger fires the backfill matcher via GitHub Actions; check
          back in 30–60 seconds for the new pipeline_runs row.
        </span>
      </p>
      {groups.length === 0 ? (
        <p className="text-neutral-700">No pipeline runs recorded yet.</p>
      ) : (
        <ol className="space-y-6">
          {groups.map((group, i) => (
            <RunGroup key={`${group.started_at}-${i}`} group={group} />
          ))}
        </ol>
      )}
    </section>
  );
}

function RunGroup({ group }: { group: PipelineRunGroup }) {
  return (
    <li className="border border-neutral-200 rounded-lg overflow-hidden">
      <div className="px-4 py-3 bg-neutral-50 border-b border-neutral-200 flex items-baseline gap-3 flex-wrap">
        <StatusBadge status={group.overall_status} />
        <span className="text-sm font-mono">{fmtTime(group.started_at)}</span>
        <span className="text-xs text-neutral-500">
          {group.stages.length} stage{group.stages.length === 1 ? "" : "s"}
          {" · duration "}
          {durationMs(group.started_at, group.finished_at)}
        </span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs text-neutral-500 uppercase tracking-wide">
          <tr className="border-b border-neutral-200">
            <th className="text-left px-4 py-2 font-medium">Stage</th>
            <th className="text-left px-4 py-2 font-medium">Status</th>
            <th className="text-left px-4 py-2 font-medium">Items</th>
            <th className="text-left px-4 py-2 font-medium">Duration</th>
            <th className="text-left px-4 py-2 font-medium">Error</th>
          </tr>
        </thead>
        <tbody>
          {group.stages.map((stage) => (
            <StageRow key={stage.id} stage={stage} />
          ))}
        </tbody>
      </table>
    </li>
  );
}

function StageRow({ stage }: { stage: PipelineRunRow }) {
  const items =
    stage.items_processed === null
      ? "—"
      : `${stage.items_succeeded ?? 0}/${stage.items_processed}`;
  return (
    <tr className="border-b border-neutral-100 last:border-b-0">
      <td className="px-4 py-2 font-mono text-xs">{stage.stage}</td>
      <td className="px-4 py-2"><StatusBadge status={stage.status} /></td>
      <td className="px-4 py-2 font-mono text-xs">{items}</td>
      <td className="px-4 py-2 font-mono text-xs text-neutral-600">
        {durationMs(stage.started_at, stage.finished_at)}
      </td>
      <td className="px-4 py-2 text-xs text-rose-700 max-w-md truncate">
        {stage.error_message ?? ""}
      </td>
    </tr>
  );
}

function PendingReviewSection({ pending }: { pending: PendingFrictionEntry[] }) {
  return (
    <section className="mb-16">
      <h2 className="text-xl font-semibold mb-1">Pending review queue</h2>
      <p className="text-sm text-neutral-500 mb-6">
        Frictions below the confidence threshold (self_rating &lt; 7). These wait
        for Yangcho&apos;s approval before going public.
        {" "}
        <span className="text-neutral-700">{pending.length} item{pending.length === 1 ? "" : "s"} queued.</span>
      </p>
      {pending.length === 0 ? (
        <p className="text-neutral-700">Queue is empty.</p>
      ) : (
        <ul className="space-y-3">
          {pending.map((entry) => (
            <PendingRow key={entry.friction_id} entry={entry} />
          ))}
        </ul>
      )}
    </section>
  );
}

function PendingRow({ entry }: { entry: PendingFrictionEntry }) {
  // Bind the friction_id into the form-action closures so each row's buttons
  // hit the correct backend action.
  async function approve() {
    "use server";
    await approveFriction(entry.friction_id);
  }
  async function reject() {
    "use server";
    await rejectFriction(entry.friction_id);
  }

  return (
    <li className="border border-neutral-200 rounded-lg overflow-hidden">
      <details className="group">
        <summary className="cursor-pointer list-none px-4 py-3 hover:bg-neutral-50">
          <div className="flex items-baseline gap-3 flex-wrap text-xs text-neutral-500">
            <span aria-hidden className="text-neutral-400 group-open:rotate-90 transition-transform inline-block">
              ▸
            </span>
            <span className="font-mono">rating {entry.self_rating}/10</span>
            {entry.efficacy_class && (
              <span>{entry.efficacy_class.replaceAll("-", " ")}</span>
            )}
            <span className="ml-auto">
              {fmtDate(entry.moment_date)} ·{" "}
              <Link href={`/brief/${entry.moment_id}` as never} className="underline">
                {entry.moment_name}
              </Link>
            </span>
          </div>
          <p className="mt-2 text-sm text-neutral-800 leading-snug">
            {entry.friction_summary}
          </p>
        </summary>

        <div className="px-4 pb-4 border-t border-neutral-200 bg-neutral-50/50">
          <p className="mt-4 text-xs uppercase tracking-wide text-neutral-500 mb-2">
            Mechanism (R&amp;D voice)
          </p>
          <p className="text-sm text-neutral-800 leading-relaxed whitespace-pre-line">
            {entry.mechanism}
          </p>

          <div className="mt-5 flex items-center gap-3">
            <form action={approve}>
              <button
                type="submit"
                className="rounded bg-emerald-600 text-white text-sm font-medium px-4 py-2 hover:bg-emerald-700 transition-colors"
              >
                Approve
              </button>
            </form>
            <form action={reject}>
              <button
                type="submit"
                className="rounded border border-rose-300 text-rose-700 text-sm font-medium px-4 py-2 hover:bg-rose-50 transition-colors"
              >
                Reject
              </button>
            </form>
            <p className="text-xs text-neutral-500 ml-2">
              Approving publishes the friction immediately. Product matches will
              attach on the next pipeline run.
            </p>
          </div>
        </div>
      </details>
    </li>
  );
}

function AllMomentsSection({ entries }: { entries: AdminMomentEntry[] }) {
  return (
    <section className="mb-8">
      <h2 className="text-xl font-semibold mb-1">All moments</h2>
      <p className="text-sm text-neutral-500 mb-6">
        Every moment the pipeline has produced — published, pending, or empty.
        Newest first. <span className="text-neutral-700">{entries.length} total.</span>
      </p>
      {entries.length === 0 ? (
        <p className="text-neutral-700">No moments recorded yet.</p>
      ) : (
        <table className="w-full text-sm border border-neutral-200 rounded-lg overflow-hidden">
          <thead className="text-xs text-neutral-500 uppercase tracking-wide bg-neutral-50">
            <tr className="border-b border-neutral-200">
              <th className="text-left px-4 py-2 font-medium">ID</th>
              <th className="text-left px-4 py-2 font-medium">Date</th>
              <th className="text-left px-4 py-2 font-medium">Source</th>
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-left px-4 py-2 font-medium">Frictions</th>
              <th className="text-left px-4 py-2 font-medium">Matches</th>
              <th className="text-left px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <AdminMomentRow key={entry.moment.id} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function AdminMomentRow({ entry }: { entry: AdminMomentEntry }) {
  const { moment, friction_count, approved_count, pending_count, match_count } = entry;
  const status =
    approved_count > 0 ? "published" : pending_count > 0 ? "pending" : "empty";
  const statusClass =
    status === "published"
      ? "text-emerald-700 bg-emerald-50 border-emerald-200"
      : status === "pending"
        ? "text-amber-700 bg-amber-50 border-amber-200"
        : "text-neutral-600 bg-neutral-50 border-neutral-200";
  return (
    <tr className="border-b border-neutral-100 last:border-b-0">
      <td className="px-4 py-2 font-mono text-xs">{moment.id}</td>
      <td className="px-4 py-2 font-mono text-xs">{moment.moment_date}</td>
      <td className="px-4 py-2 text-xs">{moment.source}</td>
      <td className="px-4 py-2">
        <Link
          href={`/brief/${moment.id}` as never}
          className="underline hover:text-neutral-900"
        >
          {moment.name}
        </Link>
      </td>
      <td className="px-4 py-2 font-mono text-xs">
        {approved_count}✓ / {pending_count}○ / {friction_count} total
      </td>
      <td className="px-4 py-2 font-mono text-xs">{match_count}</td>
      <td className="px-4 py-2">
        <span className={`inline-block text-xs font-mono uppercase tracking-wide px-2 py-0.5 border rounded ${statusClass}`}>
          {status}
        </span>
      </td>
    </tr>
  );
}
