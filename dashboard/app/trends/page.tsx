/**
 * Trend Radar — public archive of every approved brief.
 *
 * Grouped by date, newest first. Each row: source badge, friction count,
 * matched-product count, click-through to /brief/[id].
 *
 * Bundle policy: static markup, no Recharts here. Chart-driven trend
 * visualization lands later (W5+) when there's enough history to make
 * a sparkline meaningful.
 */

import Link from "next/link";

import { getAllApprovedMoments, momentSourceLabel } from "@/lib/queries";
import type { ArchiveEntry } from "@/lib/queries";

export const dynamic = "force-dynamic";

function formatMomentDate(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString("en-US", {
    timeZone: "Asia/Seoul",
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function groupByDate(entries: ArchiveEntry[]): Map<string, ArchiveEntry[]> {
  const out = new Map<string, ArchiveEntry[]>();
  for (const e of entries) {
    const key = e.moment.moment_date;
    const arr = out.get(key) ?? [];
    arr.push(e);
    out.set(key, arr);
  }
  return out;
}

export default async function TrendsPage() {
  const entries = await getAllApprovedMoments();
  const byDate = groupByDate(entries);
  const dates = Array.from(byDate.keys()); // already sorted (query returned newest first)

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <header className="border-b border-neutral-200 pb-8 mb-12">
        <p className="text-sm uppercase tracking-widest text-neutral-500">
          The Logic of Life-Care
        </p>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">
          Every brief we&apos;ve published
        </h1>
        <p className="mt-4 text-neutral-600">
          {entries.length === 0
            ? "No briefs published yet — check back tomorrow."
            : `${entries.length} brief${entries.length === 1 ? "" : "s"} across ${dates.length} day${dates.length === 1 ? "" : "s"}.`}
        </p>
      </header>

      {entries.length === 0 ? (
        <EmptyArchive />
      ) : (
        <section className="space-y-12">
          {dates.map((date) => (
            <DateGroup key={date} date={date} entries={byDate.get(date) ?? []} />
          ))}
        </section>
      )}

      <footer className="mt-16 border-t border-neutral-200 pt-8 text-sm text-neutral-500">
        <Link href="/" className="underline hover:text-neutral-900">
          ← Today&apos;s brief
        </Link>
        <span className="mx-3">·</span>
        <Link href="/methodology" className="underline hover:text-neutral-900">
          How this works
        </Link>
      </footer>
    </main>
  );
}

function DateGroup({ date, entries }: { date: string; entries: ArchiveEntry[] }) {
  return (
    <section>
      <h2 className="text-sm uppercase tracking-widest text-neutral-500 mb-4">
        {formatMomentDate(date)}
      </h2>
      <ul className="space-y-4">
        {entries.map((entry) => (
          <ArchiveRow key={entry.moment.id} entry={entry} />
        ))}
      </ul>
    </section>
  );
}

function ArchiveRow({ entry }: { entry: ArchiveEntry }) {
  const { moment, friction_count, match_count } = entry;
  return (
    <li>
      <Link
        href={`/brief/${moment.id}` as never}
        className="block group rounded-lg border border-neutral-200 p-5 hover:border-neutral-400 hover:bg-neutral-50 transition-colors"
      >
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="text-xs uppercase tracking-wide text-neutral-500">
            {momentSourceLabel(moment.source)}
          </span>
          <span className="ml-auto text-xs text-neutral-500">
            {friction_count} friction{friction_count === 1 ? "" : "s"}
            {" · "}
            {match_count} match{match_count === 1 ? "" : "es"}
          </span>
        </div>
        <p className="mt-2 text-lg font-semibold leading-snug group-hover:underline">
          {moment.name}
        </p>
        {(moment.event_details || moment.description) && (
          <p className="mt-1 text-sm text-neutral-600 leading-snug line-clamp-2">
            {moment.event_details || moment.description}
          </p>
        )}
      </Link>
    </li>
  );
}

function EmptyArchive() {
  return (
    <section className="text-neutral-700 leading-relaxed">
      <p>
        Trend velocity stable. When a lifestyle moment clears the confidence
        gate, its brief lands here. New briefs publish on a daily cadence —
        most days yield 1–2 approved moments.
      </p>
      <p className="mt-3">
        See{" "}
        <Link href="/methodology" className="underline">
          the methodology
        </Link>{" "}
        for how moments are scored and how the confidence gate works.
      </p>
    </section>
  );
}
