/**
 * Home dashboard — page 1.
 *
 * Card grid view of every approved moment. Each card is a self-contained
 * "translation": cultural moment on the outside, marketing post + matched
 * K-Beauty product on the inside, with one influencer pick as a teaser.
 *
 * Why card-grid instead of single-moment-hero:
 *   - MBA reviewers scrolling /llc want "what's the system doing right now?"
 *     not "what's the single best moment today?". Volume = proof of substance.
 *   - The marketing post is the demo screenshot — putting it in every card
 *     means every screenshot of any card lands the thesis.
 *   - Click-through to /brief/[id] preserves the depth view; the home page
 *     is teaser, not destination.
 *
 * Empty-state path preserved from the old hero: if zero moments are
 * approved, surface the "Trend velocity stable today" copy so the
 * dashboard never appears broken.
 */

import Image from "next/image";
import Link from "next/link";

import { getDashboardCards } from "@/lib/queries";
import type {
  DashboardCard,
  InfluencerSuggestionEntry,
  MarketingPostBody,
  PublicMatch,
  PublicMoment,
} from "@/lib/queries";
import { productImageUrl } from "@/lib/storage";

export const dynamic = "force-dynamic";

function formatMomentDate(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString("en-US", {
    timeZone: "Asia/Seoul",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default async function HomeDashboardPage() {
  const cards = await getDashboardCards();

  return (
    <main className="mx-auto max-w-6xl px-6 py-16">
      <header className="border-b border-neutral-200 pb-8 mb-12">
        <p className="text-sm uppercase tracking-widest text-neutral-500">
          The Logic of Life-Care
        </p>
        <h1 className="mt-3 text-4xl font-semibold leading-tight">
          A daily translation from American lifestyle to K-Beauty science.
        </h1>
        <p className="mt-4 text-neutral-600 max-w-2xl leading-relaxed">
          Every card below is one live cultural moment — TikTok trend or cultural
          calendar event — translated into a K-Beauty marketing post and matched
          to a product on the shelf today. {cards.length > 0 && (
            <>Showing <strong>{cards.length}</strong> approved {cards.length === 1 ? "moment" : "moments"}.</>
          )}
        </p>
      </header>

      {cards.length === 0 ? (
        <EmptyHero />
      ) : (
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {cards.map((card) => (
            <MomentCard key={card.moment.id} card={card} />
          ))}
        </section>
      )}

      <footer className="mt-16 border-t border-neutral-200 pt-8 text-sm text-neutral-500">
        <Link href="/methodology" className="underline hover:text-neutral-900">
          How this works
        </Link>
        <span className="mx-3">·</span>
        <Link href="/trends" className="underline hover:text-neutral-900">
          Trend Radar
        </Link>
      </footer>
    </main>
  );
}

function MomentCard({ card }: { card: DashboardCard }) {
  const { moment, friction, top_match, marketing_post, top_influencer } = card;
  return (
    <article className="flex flex-col rounded-xl border border-neutral-200 bg-white overflow-hidden hover:shadow-md transition-shadow">
      <MomentHeader moment={moment} />

      <div className="px-5 pt-4 pb-2 border-b border-neutral-100">
        <p className="text-xs uppercase tracking-wide text-neutral-500 mb-1">
          Friction
          {friction.efficacy_class && (
            <>
              <span className="mx-2">·</span>
              <span>{friction.efficacy_class.replaceAll("-", " ")}</span>
            </>
          )}
        </p>
        <p className="text-sm text-neutral-800 leading-snug line-clamp-2">
          {friction.friction_summary}
        </p>
      </div>

      {/* Marketing post is the centerpiece — the demo screenshot moment. */}
      {marketing_post ? (
        <MarketingPostBlock post={marketing_post} />
      ) : (
        <div className="px-5 py-6 bg-neutral-50 border-b border-neutral-100">
          <p className="text-xs text-neutral-500 italic">
            Marketing post drafting on the next pipeline run.
          </p>
        </div>
      )}

      {top_match ? (
        <ProductStrip match={top_match} />
      ) : (
        <div className="px-5 py-3 text-xs text-neutral-500 italic border-b border-neutral-100">
          Product match queued.
        </div>
      )}

      {top_influencer && <InfluencerStrip influencer={top_influencer} />}

      <Link
        href={`/brief/${moment.id}` as never}
        className="mt-auto px-5 py-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50 border-t border-neutral-100"
      >
        See full brief →
      </Link>
    </article>
  );
}

function MomentHeader({ moment }: { moment: PublicMoment }) {
  const sourceLabel = moment.source === "tiktok" ? "TikTok trend" : "Cultural moment";
  return (
    <header className="px-5 pt-5 pb-4">
      <div className="flex items-center justify-between gap-3 text-xs uppercase tracking-wide text-neutral-500 mb-2">
        <span>{sourceLabel}</span>
        <span>{formatMomentDate(moment.moment_date)}</span>
      </div>
      <h2 className="text-lg font-semibold leading-snug text-neutral-900">
        {moment.name}
      </h2>
      {moment.description && (
        <p className="mt-2 text-sm text-neutral-600 italic line-clamp-2">
          {moment.description}
        </p>
      )}
    </header>
  );
}

function MarketingPostBlock({ post }: { post: MarketingPostBody }) {
  return (
    <section className="px-5 py-5 bg-neutral-50 border-b border-neutral-100">
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        Marketing post
      </p>
      <h3 className="text-base font-semibold leading-snug text-neutral-900 line-clamp-3">
        {post.headline}
      </h3>
      <p className="mt-2 text-sm text-neutral-800 leading-relaxed line-clamp-4 whitespace-pre-line">
        {post.body}
      </p>
      <p className="mt-3 text-xs font-medium uppercase tracking-wide text-neutral-700">
        {post.call_to_action}
      </p>
    </section>
  );
}

function ProductStrip({ match }: { match: PublicMatch }) {
  const { product } = match;
  const imgUrl = productImageUrl(product.image_path);
  const lgBadge = product.is_lg ? "LG H&H" : "competitor";

  return (
    <a
      href={product.public_url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 px-5 py-3 border-b border-neutral-100 hover:bg-neutral-50 group"
    >
      <div className="shrink-0 w-14 h-14 rounded-md bg-neutral-100 overflow-hidden relative">
        {imgUrl ? (
          <Image
            src={imgUrl}
            alt={product.name}
            fill
            sizes="56px"
            className="object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[10px] text-neutral-400 text-center px-1">
            no image
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-semibold text-neutral-900">
            {product.brand}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-neutral-500">
            {lgBadge}
          </span>
        </div>
        <p className="text-sm text-neutral-700 truncate group-hover:underline">
          {product.name}
        </p>
      </div>
      <span className="shrink-0 text-xs text-neutral-400 group-hover:text-neutral-700">↗</span>
    </a>
  );
}

function InfluencerStrip({ influencer }: { influencer: InfluencerSuggestionEntry }) {
  return (
    <div className="px-5 py-3 border-b border-neutral-100">
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-1">
        Suggested creator
      </p>
      <p className="text-sm font-medium text-neutral-900">
        {influencer.creator_handle}
      </p>
      <p className="mt-1 text-xs text-neutral-600 leading-snug line-clamp-2">
        {influencer.reasoning}
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
      <p className="mt-4 text-neutral-700 leading-relaxed max-w-2xl">
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
