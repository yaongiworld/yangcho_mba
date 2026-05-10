/**
 * Yangcho's Review Queue — admin/queue.
 *
 * Password-gated or URL-only (Supabase Auth — not linked from public dashboard).
 * Confidence-gated entries below the threshold queue here for Yangcho's
 * approve/edit/reject decision (~5–10/day during MBA crunch).
 *
 * Implementation lands in W7. UX optimized for fast keyboard-driven review.
 */

export default function ReviewQueuePage() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <h1 className="text-3xl font-semibold">Review Queue</h1>
      <p className="mt-3 text-neutral-500">
        Confidence-gated entries below threshold. Placeholder — W7.
      </p>
    </main>
  );
}
