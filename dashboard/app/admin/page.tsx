/**
 * Operator dashboard.
 *
 * Four tabs, URL-routed:
 *   ?tab=frictions  (default) — Pending friction review queue
 *   ?tab=playbook            — Pending playbook items (marketing/idea/influencer)
 *   ?tab=runs                — Recent pipeline run history
 *   ?tab=moments             — All moments admin lens
 *
 * Each tab is independently paginated via ?page=N (1-indexed). The defaults
 * keep the page small so it loads fast even when the queues grow.
 *
 * Auth: gated upstream by middleware.ts (HMAC-signed session cookie set by
 * /admin/login). The publishable Supabase key still respects RLS, but per
 * migration 0005 it can read pending content. /admin is unlinked from the
 * public site; security boundary is the login + middleware.
 *
 * W7 plan: Supabase Auth (magic link), revert 0005, RLS gates pending
 * content to authed-admin reads.
 */

import Link from "next/link";

import {
  approveFriction,
  approvePlaybook,
  rejectFriction,
  rejectPlaybook,
} from "@/app/admin/actions";
import { signoutAction } from "@/app/admin/login/actions";
import { TriggerButton } from "@/app/admin/TriggerButton";
import {
  getAllMomentsAdminPage,
  getPendingFrictionsPage,
  getPendingPlaybookPage,
  getPipelineRunGroupsPage,
} from "@/lib/queries";
import type {
  AdminMomentEntry,
  InfluencerOutputBody,
  MarketingPostBody,
  PendingFrictionEntry,
  PendingPlaybookEntry,
  PipelineRunGroup,
  PipelineRunRow,
  ProductIdeaBody,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 20;

type TabKey = "frictions" | "playbook" | "runs" | "moments";
const TAB_ORDER: TabKey[] = ["frictions", "playbook", "runs", "moments"];
const TAB_LABEL: Record<TabKey, string> = {
  frictions: "Friction approvals",
  playbook: "Playbook approvals",
  runs: "Pipeline runs",
  moments: "All moments",
};

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

// ─────────────────────────────────────────────────────────────────────────────
// Confidence badges for the friction queue.
//
// self_rating ranges 1–10. The pipeline auto-publishes ≥8 (no human gate);
// the queue contains everything 1–7. Within the queue:
//   * ≥6 — green ("close to threshold, prioritize")
//   * 4–5 — yellow
//   * <4 — plain
// ─────────────────────────────────────────────────────────────────────────────

function ConfidenceBadge({ rating }: { rating: number }) {
  let cls: string;
  let label: string;
  if (rating >= 6) {
    cls = "text-emerald-700 bg-emerald-50 border-emerald-200";
    label = `high · ${rating}/10`;
  } else if (rating >= 4) {
    cls = "text-amber-700 bg-amber-50 border-amber-200";
    label = `medium · ${rating}/10`;
  } else {
    cls = "text-neutral-600 bg-neutral-50 border-neutral-200";
    label = `low · ${rating}/10`;
  }
  return (
    <span className={`inline-block text-xs font-mono uppercase tracking-wide px-2 py-0.5 border rounded ${cls}`}>
      {label}
    </span>
  );
}

function parseTab(raw: string | string[] | undefined): TabKey {
  const v = Array.isArray(raw) ? raw[0] : raw;
  if (v && (TAB_ORDER as string[]).includes(v)) return v as TabKey;
  return "frictions";
}

function parsePage(raw: string | string[] | undefined): number {
  const v = Array.isArray(raw) ? raw[0] : raw;
  const n = v ? Number.parseInt(v, 10) : 1;
  return Number.isFinite(n) && n >= 1 ? n : 1;
}

export default async function AdminPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const tab = parseTab(sp.tab);
  const page = parsePage(sp.page);
  const offset = (page - 1) * PAGE_SIZE;

  // Only fetch data for the active tab — keeps each render lean.
  let pageData:
    | { kind: "frictions"; data: { rows: PendingFrictionEntry[]; total: number } }
    | { kind: "playbook"; data: { rows: PendingPlaybookEntry[]; total: number } }
    | { kind: "runs"; data: { rows: PipelineRunGroup[]; total: number } }
    | { kind: "moments"; data: { rows: AdminMomentEntry[]; total: number } };

  if (tab === "frictions") {
    pageData = { kind: "frictions", data: await getPendingFrictionsPage(offset, PAGE_SIZE) };
  } else if (tab === "playbook") {
    pageData = { kind: "playbook", data: await getPendingPlaybookPage(offset, PAGE_SIZE) };
  } else if (tab === "runs") {
    pageData = { kind: "runs", data: await getPipelineRunGroupsPage(offset, PAGE_SIZE) };
  } else {
    pageData = { kind: "moments", data: await getAllMomentsAdminPage(offset, PAGE_SIZE) };
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header className="border-b border-neutral-200 pb-6 mb-8">
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

      <TabNav active={tab} />

      <section className="mt-8">
        {pageData.kind === "frictions" && (
          <FrictionsTab page={page} pageSize={PAGE_SIZE} total={pageData.data.total} rows={pageData.data.rows} />
        )}
        {pageData.kind === "playbook" && (
          <PlaybookTab page={page} pageSize={PAGE_SIZE} total={pageData.data.total} rows={pageData.data.rows} />
        )}
        {pageData.kind === "runs" && (
          <RunsTab page={page} pageSize={PAGE_SIZE} total={pageData.data.total} rows={pageData.data.rows} />
        )}
        {pageData.kind === "moments" && (
          <MomentsTab page={page} pageSize={PAGE_SIZE} total={pageData.data.total} rows={pageData.data.rows} />
        )}
      </section>
    </main>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab nav + pagination shells
// ─────────────────────────────────────────────────────────────────────────────

function TabNav({ active }: { active: TabKey }) {
  return (
    <nav role="tablist" className="flex flex-wrap gap-1 border-b border-neutral-200">
      {TAB_ORDER.map((tab) => {
        const isActive = tab === active;
        return (
          <Link
            key={tab}
            role="tab"
            aria-selected={isActive}
            href={{ pathname: "/admin", query: { tab } }}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              isActive
                ? "border-neutral-900 text-neutral-900"
                : "border-transparent text-neutral-500 hover:text-neutral-900"
            }`}
          >
            {TAB_LABEL[tab]}
          </Link>
        );
      })}
    </nav>
  );
}

function Pagination({
  tab,
  page,
  pageSize,
  total,
}: {
  tab: TabKey;
  page: number;
  pageSize: number;
  total: number;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;
  const prev = Math.max(1, page - 1);
  const next = Math.min(totalPages, page + 1);
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div className="mt-8 flex items-center justify-between text-sm text-neutral-600 gap-3 flex-wrap">
      <p>
        Showing <span className="font-mono">{from}–{to}</span> of{" "}
        <span className="font-mono">{total}</span>
      </p>
      <div className="flex items-center gap-2">
        {page > 1 ? (
          <Link
            href={{ pathname: "/admin", query: { tab, page: prev } }}
            className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-50"
          >
            ← Prev
          </Link>
        ) : (
          <span className="rounded border border-neutral-200 px-3 py-1 text-neutral-300">← Prev</span>
        )}
        <span className="font-mono text-xs text-neutral-500">
          page {page} / {totalPages}
        </span>
        {page < totalPages ? (
          <Link
            href={{ pathname: "/admin", query: { tab, page: next } }}
            className="rounded border border-neutral-300 px-3 py-1 hover:bg-neutral-50"
          >
            Next →
          </Link>
        ) : (
          <span className="rounded border border-neutral-200 px-3 py-1 text-neutral-300">Next →</span>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Friction approvals
// ─────────────────────────────────────────────────────────────────────────────

function FrictionsTab({
  page, pageSize, total, rows,
}: {
  page: number; pageSize: number; total: number; rows: PendingFrictionEntry[];
}) {
  return (
    <>
      <header className="mb-6">
        <h2 className="text-xl font-semibold">Pending friction approvals</h2>
        <p className="mt-1 text-sm text-neutral-500">
          Frictions below the auto-publish threshold (self_rating &lt; 8) wait
          for Yangcho&apos;s approval. Sorted by confidence descending —
          highest-rated items are the closest to the threshold and the most
          worth your attention.
          {" "}
          <span className="text-neutral-700">{total} item{total === 1 ? "" : "s"} in queue.</span>
        </p>
      </header>
      {rows.length === 0 ? (
        <p className="text-neutral-700">Queue is empty.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((entry) => (
            <PendingFrictionRow key={entry.friction_id} entry={entry} />
          ))}
        </ul>
      )}
      <Pagination tab="frictions" page={page} pageSize={pageSize} total={total} />
    </>
  );
}

function PendingFrictionRow({ entry }: { entry: PendingFrictionEntry }) {
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
            <ConfidenceBadge rating={entry.self_rating} />
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

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Playbook approvals
// ─────────────────────────────────────────────────────────────────────────────

function PlaybookTab({
  page, pageSize, total, rows,
}: {
  page: number; pageSize: number; total: number; rows: PendingPlaybookEntry[];
}) {
  return (
    <>
      <header className="mb-6">
        <h2 className="text-xl font-semibold">Pending playbook approvals</h2>
        <p className="mt-1 text-sm text-neutral-500">
          Marketing posts, new-product ideas, and influencer suggestions waiting
          for editorial approval. Playbook items always queue regardless of the
          AI&apos;s confidence — your eyes are the only line of defense for
          voice and real-person recommendations.{" "}
          <span className="text-neutral-700">{total} item{total === 1 ? "" : "s"} in queue.</span>
        </p>
      </header>
      {rows.length === 0 ? (
        <p className="text-neutral-700">Queue is empty.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((entry) => (
            <PendingPlaybookRow key={entry.playbook_id} entry={entry} />
          ))}
        </ul>
      )}
      <Pagination tab="playbook" page={page} pageSize={pageSize} total={total} />
    </>
  );
}

function PendingPlaybookRow({ entry }: { entry: PendingPlaybookEntry }) {
  async function approve() {
    "use server";
    await approvePlaybook(entry.playbook_id);
  }
  async function reject() {
    "use server";
    await rejectPlaybook(entry.playbook_id);
  }

  const kindLabel: Record<typeof entry.kind, string> = {
    marketing_post: "Marketing post",
    product_idea: "New-product idea",
    influencer: "Influencer suggestions",
  };

  return (
    <li className="border border-neutral-200 rounded-lg overflow-hidden">
      <details className="group">
        <summary className="cursor-pointer list-none px-4 py-3 hover:bg-neutral-50">
          <div className="flex items-baseline gap-3 flex-wrap text-xs text-neutral-500">
            <span aria-hidden className="text-neutral-400 group-open:rotate-90 transition-transform inline-block">
              ▸
            </span>
            <span className="font-mono uppercase tracking-wide">
              {kindLabel[entry.kind]}
            </span>
            <span className="ml-auto">
              {fmtDate(entry.moment_date)} ·{" "}
              <Link href={`/brief/${entry.moment_id}` as never} className="underline">
                {entry.moment_name}
              </Link>
            </span>
          </div>
          <p className="mt-2 text-sm text-neutral-700 italic leading-snug">
            for friction: {entry.friction_summary}
          </p>
        </summary>

        <div className="px-4 pb-4 border-t border-neutral-200 bg-neutral-50/50">
          <div className="mt-4">
            {entry.kind === "marketing_post" && (
              <PendingMarketingPostBody body={entry.body as MarketingPostBody} />
            )}
            {entry.kind === "product_idea" && (
              <PendingProductIdeaBody body={entry.body as ProductIdeaBody} />
            )}
            {entry.kind === "influencer" && (
              <PendingInfluencerBody body={entry.body as InfluencerOutputBody} />
            )}
          </div>

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
              Approving publishes this item to the public brief immediately.
            </p>
          </div>
        </div>
      </details>
    </li>
  );
}

function PendingMarketingPostBody({ body }: { body: MarketingPostBody }) {
  return (
    <div className="rounded border border-neutral-300 bg-white p-4">
      <h3 className="text-lg font-semibold leading-tight">{body.headline}</h3>
      <p className="mt-3 text-sm text-neutral-800 leading-relaxed whitespace-pre-line">
        {body.body}
      </p>
      <p className="mt-3 text-xs font-medium uppercase tracking-wide text-neutral-700">
        {body.call_to_action}
      </p>
    </div>
  );
}

function PendingProductIdeaBody({ body }: { body: ProductIdeaBody }) {
  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-4 space-y-3 text-sm">
      <div>
        <p className="text-xs uppercase tracking-wide text-amber-700">Concept</p>
        <p className="text-base font-semibold leading-tight">{body.concept_name}</p>
        <p className="text-neutral-700 italic">{body.target_friction}</p>
      </div>
      <Detail label="Hero mechanism" value={body.hero_mechanism} />
      <Detail label="Hero ingredient class" value={body.hero_ingredient_class} />
      <Detail label="Target consumer" value={body.target_consumer_profile} />
      <Detail label="White space" value={body.competitive_white_space} />
    </div>
  );
}

function PendingInfluencerBody({ body }: { body: InfluencerOutputBody }) {
  return (
    <ul className="space-y-4">
      {body.suggestions.map((s, i) => (
        <li key={`${s.creator_handle}-${i}`} className="rounded border border-neutral-300 bg-white p-4">
          <p className="text-base font-semibold">{s.creator_handle}</p>
          <p className="mt-2 text-sm text-neutral-800 leading-relaxed">{s.reasoning}</p>
          <p className="mt-3 text-xs text-neutral-500 break-all">
            {s.public_evidence}
          </p>
        </li>
      ))}
    </ul>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-1">{label}</p>
      <p className="text-neutral-800 leading-relaxed">{value}</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Pipeline runs
// ─────────────────────────────────────────────────────────────────────────────

function RunsTab({
  page, pageSize, total, rows,
}: {
  page: number; pageSize: number; total: number; rows: PipelineRunGroup[];
}) {
  return (
    <>
      <header className="mb-6 flex items-baseline justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-semibold">Recent pipeline runs</h2>
          <p className="mt-1 text-sm text-neutral-500">
            Grouped by cron tick (stages within 5 minutes treated as one run).
            Newest first.
          </p>
        </div>
        <TriggerButton />
      </header>
      {rows.length === 0 ? (
        <p className="text-neutral-700">No pipeline runs recorded yet.</p>
      ) : (
        <ol className="space-y-6">
          {rows.map((group, i) => (
            <RunGroupRow key={`${group.started_at}-${i}`} group={group} />
          ))}
        </ol>
      )}
      <Pagination tab="runs" page={page} pageSize={pageSize} total={total} />
    </>
  );
}

function RunGroupRow({ group }: { group: PipelineRunGroup }) {
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

// ─────────────────────────────────────────────────────────────────────────────
// Tab: All moments
// ─────────────────────────────────────────────────────────────────────────────

function MomentsTab({
  page, pageSize, total, rows,
}: {
  page: number; pageSize: number; total: number; rows: AdminMomentEntry[];
}) {
  return (
    <>
      <header className="mb-6">
        <h2 className="text-xl font-semibold">All moments</h2>
        <p className="mt-1 text-sm text-neutral-500">
          Every moment the pipeline has produced — published, pending, or empty.
          Newest first. <span className="text-neutral-700">{total} total.</span>
        </p>
      </header>
      {rows.length === 0 ? (
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
            {rows.map((entry) => (
              <AdminMomentRow key={entry.moment.id} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
      <Pagination tab="moments" page={page} pageSize={pageSize} total={total} />
    </>
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
