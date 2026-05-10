/**
 * Methodology Showcase — page 4.
 *
 * Yangcho's 3 hand-written hero case studies in first person, plus the scoring
 * formula, data sources, and the framework explainer. Surfaces "Last successful
 * pipeline run: [timestamp]" as transparency signal.
 *
 * Hero case studies render long-form (essay-quality typography). This page is
 * what survives any technical interview challenge — it shows Yangcho's reasoning,
 * not the AI's.
 */

import { createServerClient } from "@/lib/supabase";
import { loadHeroCases } from "@/lib/hero_cases";

// Force dynamic rendering — we want the latest pipeline_run timestamp on every
// load, not a stale cached value from build time.
export const dynamic = "force-dynamic";

async function getLastSuccessfulRun(): Promise<Date | null> {
  const supabase = createServerClient();
  const { data, error } = await supabase
    .from("pipeline_runs")
    .select("finished_at")
    .eq("status", "success")
    .order("finished_at", { ascending: false })
    .limit(1);
  if (error || !data || data.length === 0) return null;
  // Supabase's typed client narrows projection rows to `never` in some
  // postgrest-version combinations; the runtime row shape is correct so we
  // cast at the boundary.
  const row = data[0] as { finished_at: string | null } | undefined;
  if (!row?.finished_at) return null;
  return new Date(row.finished_at);
}

function formatTimestamp(d: Date): string {
  return d.toLocaleString("en-US", {
    timeZone: "Asia/Seoul",
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }) + " KST";
}

export default async function MethodologyPage() {
  const heroCases = loadHeroCases();
  const lastRun = await getLastSuccessfulRun();

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <header className="border-b border-neutral-200 pb-8 mb-12">
        <p className="text-sm uppercase tracking-widest text-neutral-500">
          The Logic of Life-Care
        </p>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">
          Methodology
        </h1>
        <p className="mt-4 text-neutral-600 leading-relaxed">
          Three hero case studies showing how I reason from a US lifestyle moment
          to a K-Beauty product match. The dashboard&apos;s daily auto-generated
          briefs are the AI extending this reasoning to new trends, with me
          reviewing every entry before it goes live.
        </p>
      </header>

      {/* The 3 hero case studies, rendered long-form. */}
      <section className="space-y-16">
        {heroCases.map((hero) => (
          <article key={hero.slug} id={hero.slug} className="scroll-mt-24">
            <h2 className="text-2xl font-semibold mb-1">{hero.title}</h2>
            {hero.isPlaceholder && (
              <p className="text-xs uppercase tracking-wide text-amber-700 mb-6">
                Placeholder — to be replaced with Yangcho&apos;s R&amp;D writeup
              </p>
            )}
            <div
              className="prose prose-neutral max-w-none mt-6 prose-headings:font-semibold prose-headings:text-neutral-900 prose-p:leading-relaxed prose-p:text-neutral-800"
              dangerouslySetInnerHTML={{ __html: hero.html }}
            />
          </article>
        ))}
      </section>

      {/* Scoring formula + how it works. */}
      <section className="mt-20 border-t border-neutral-200 pt-12">
        <h2 className="text-2xl font-semibold mb-6">How moments are scored</h2>
        <div className="bg-neutral-100 rounded-lg p-6 font-mono text-sm leading-relaxed">
          score = (Trend Velocity × Purchase Intent) − Brand Risk
        </div>
        <ul className="mt-6 space-y-3 text-neutral-700 leading-relaxed">
          <li>
            <strong>Trend Velocity</strong> — 7-day rolling volume delta on TikTok
            hashtag mentions. Smooths celebrity-tweet spikes; rewards sustained
            attention.
          </li>
          <li>
            <strong>Purchase Intent</strong> — LLM-rated 1–5 on commerce-language
            density in source posts (&quot;I need&quot;, &quot;buying&quot;, &quot;where can I&quot;).
          </li>
          <li>
            <strong>Brand Risk</strong> — LLM-rated 1–5 on legal / controversy /
            PR-incident exposure. Explicitly NOT cultural risk; cultural moments
            are the product, not a hazard to filter.
          </li>
        </ul>
      </section>

      {/* Data sources. */}
      <section className="mt-16">
        <h2 className="text-2xl font-semibold mb-6">Data sources</h2>
        <ul className="space-y-3 text-neutral-700 leading-relaxed">
          <li>
            <strong>TikTok Creative Center</strong> — trending US hashtags,
            7-day volume, weekly. Public; respects robots.txt.
          </li>
          <li>
            <strong>Cultural calendar</strong> — NFL game-day, marathons,
            festivals, Bama Rush, sorority recruitment. Hand-curated to
            anchor the dashboard on real American lifestyle moments.
          </li>
          <li>
            <strong>Olive Young Global product catalog</strong> — public
            JSON API, K-Beauty product names, brands, categories, images.
            Filtered to LG H&amp;H brands (PHYSIOGEL, CAREPLUS, BEYOND) with
            12 indie K-Beauty brands as the competitive landscape.
          </li>
        </ul>
      </section>

      {/* Pipeline transparency. */}
      <section className="mt-16 mb-8">
        <h2 className="text-2xl font-semibold mb-4">Pipeline transparency</h2>
        {lastRun ? (
          <p className="text-neutral-700">
            Last successful pipeline run:{" "}
            <span className="font-mono text-sm">{formatTimestamp(lastRun)}</span>
          </p>
        ) : (
          <p className="text-amber-700">
            No successful pipeline runs recorded yet. The dashboard surfaces
            content from the cultural calendar even when the cron has not run.
          </p>
        )}
      </section>
    </main>
  );
}
