/**
 * Trend Radar — page 2.
 *
 * Top 10 moments today, scored by Trend Velocity × Purchase Intent − Brand Risk.
 * Sortable. Recharts is dynamic-imported here only (not on /), so the hero page
 * stays lightweight.
 *
 * Implementation lands in W5.
 */

export default function TrendsPage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="text-3xl font-semibold">Trend Radar</h1>
      <p className="mt-3 text-neutral-500">
        Top 10 lifestyle moments today, scored. Placeholder — W5.
      </p>
    </main>
  );
}
