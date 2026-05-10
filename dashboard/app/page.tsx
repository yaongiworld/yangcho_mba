/**
 * Hero Story Layer — page 1.
 *
 * The marquee surface. Visitor lands here, sees today's top moment translated
 * end-to-end on a single scroll: trend → friction → product → pitch → influencer.
 *
 * This is the screenshot every essay supplement uses and the thumbnail of the
 * 2-minute application video. Bundle is intentionally tiny (no Recharts here).
 *
 * Implementation lands in W6, after the data layer and methodology page exist.
 */

export default function HeroStoryLayerPage() {
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

      <section className="prose prose-neutral max-w-none">
        <p className="text-neutral-500">
          Hero Story Layer placeholder — wires to today&apos;s top moment in W6.
        </p>
      </section>
    </main>
  );
}
