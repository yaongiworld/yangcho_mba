/**
 * Hero Story Layer — page 1.
 *
 * The marquee surface. Renders today's top approved moment end-to-end on a
 * single scroll: trend → friction → mechanism → (eventually: matched product
 * + playbook). Bundle is intentionally tiny (no Recharts here) so this is the
 * fast-loading surface every essay supplement screenshot will use.
 *
 * Empty-state path: when no approved frictions exist yet, we surface the
 * "Trend velocity stable today" copy from the /plan-eng-review design — the
 * dashboard never appears broken.
 */

import Link from "next/link";

import { getLatestApprovedMoment } from "@/lib/queries";

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

export default async function HeroStoryLayerPage() {
  const result = await getLatestApprovedMoment();

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <header className="border-b border-neutral-200 pb-8 mb-12">
        <p className="text-sm uppercase tracking-widest text-neutral-500">
          The Logic of Life-Care
        </p>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">
          A daily translation from American lifestyle to K-Beauty science.
        </h1>
      </header>

      {result ? <BriefHero {...result} /> : <EmptyHero />}

      <footer className="mt-16 border-t border-neutral-200 pt-8 text-sm text-neutral-500">
        <Link href="/methodology" className="underline hover:text-neutral-900">
          How this works
        </Link>
        <span className="mx-3">·</span>
        <Link href="/trends" className="underline hover:text-neutral-900">
          All trending moments
        </Link>
      </footer>
    </main>
  );
}

function BriefHero({
  moment,
  frictions,
}: NonNullable<Awaited<ReturnType<typeof getLatestApprovedMoment>>>) {
  return (
    <article>
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        {formatMomentDate(moment.moment_date)} · {moment.source === "tiktok" ? "TikTok trend" : "Cultural moment"}
      </p>

      <h2 className="text-3xl font-semibold leading-tight">{moment.name}</h2>

      {moment.description && (
        <p className="mt-3 text-neutral-600 italic">{moment.description}</p>
      )}

      <section className="mt-10 space-y-10">
        {frictions.map((f) => (
          <FrictionBlock key={f.id} friction={f} />
        ))}
      </section>

      <div className="mt-12">
        {/* `as never` silences typedRoutes for a dynamic /brief/[id] segment;
            Next 15 typedRoutes generates a stricter type for known routes only. */}
        <Link
          href={`/brief/${moment.id}` as never}
          className="text-sm underline hover:text-neutral-900"
        >
          See the full brief, including matched K-Beauty products →
        </Link>
      </div>
    </article>
  );
}

function FrictionBlock({ friction }: { friction: { friction_summary: string; mechanism: string; efficacy_class: string | null; self_rating: number } }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        Friction
        {friction.efficacy_class && (
          <>
            <span className="mx-2">·</span>
            <span>{friction.efficacy_class.replaceAll("-", " ")}</span>
          </>
        )}
      </p>
      <h3 className="text-xl font-semibold leading-snug">
        {friction.friction_summary}
      </h3>
      <p className="mt-3 text-neutral-800 leading-relaxed">
        {friction.mechanism}
      </p>
    </div>
  );
}

function EmptyHero() {
  return (
    <section>
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        Today
      </p>
      <h2 className="text-2xl font-semibold leading-tight">
        Trend velocity stable today.
      </h2>
      <p className="mt-4 text-neutral-700 leading-relaxed">
        No new high-friction lifestyle moments have crossed the publication
        threshold in the last 24 hours. The pipeline is running on its
        regular daily cadence; check back tomorrow, or browse{" "}
        <Link href="/methodology" className="underline">
          the methodology
        </Link>{" "}
        to see how moments are scored.
      </p>
    </section>
  );
}
