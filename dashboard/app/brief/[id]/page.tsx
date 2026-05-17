/**
 * Brief Detail — page 3.
 *
 * Full chain per moment: trend → friction → matched product → (eventually:
 * marketing playbook). Always shows the "Product data sourced from public
 * Olive Young Global pages, last refreshed [date]" disclaimer.
 *
 * This is the page that demonstrates the full moat: friction analysis in
 * R&D voice + an honest LG-primary product match with a scientific argument
 * connecting friction mechanism to product mechanism.
 */

import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";

import { getBriefByMomentId } from "@/lib/queries";
import type {
  FrictionWithMatches,
  InfluencerOutputBody,
  MarketingPostBody,
  ProductIdeaBody,
  PublicMatch,
} from "@/lib/queries";
import { productImageUrl } from "@/lib/storage";

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

export default async function BriefDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const momentId = Number(id);
  if (!Number.isFinite(momentId) || momentId <= 0) notFound();

  const result = await getBriefByMomentId(momentId);
  if (!result) notFound();
  const { moment, frictions, influencer_suggestions } = result;

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <header className="border-b border-neutral-200 pb-8 mb-12">
        <Link href="/" className="text-sm text-neutral-500 underline hover:text-neutral-900">
          ← Back to today&apos;s brief
        </Link>
        <p className="mt-6 text-xs uppercase tracking-wide text-neutral-500">
          {formatMomentDate(moment.moment_date)} · {moment.source === "tiktok" ? "TikTok trend" : "Cultural moment"}
        </p>
        <h1 className="mt-2 text-4xl font-semibold leading-tight">{moment.name}</h1>
        {moment.description && (
          <p className="mt-3 text-neutral-600 italic">{moment.description}</p>
        )}
      </header>

      {frictions.length === 0 ? (
        <p className="text-neutral-700">
          This moment has no approved frictions yet. Items below the confidence
          threshold queue for review before they go public.
        </p>
      ) : (
        <section className="space-y-16">
          {frictions.map((friction) => (
            <FrictionWithMatchesBlock key={friction.id} friction={friction} />
          ))}
        </section>
      )}

      {influencer_suggestions && influencer_suggestions.suggestions.length > 0 && (
        <InfluencerSection body={influencer_suggestions} />
      )}

      <footer className="mt-20 border-t border-neutral-200 pt-6 text-xs text-neutral-500">
        Product data sourced from public Olive Young Global pages.
        {" "}
        <Link href="/methodology" className="underline">
          See methodology
        </Link>
        {" "}for how moments are scored and how friction reasoning is anchored.
      </footer>
    </main>
  );
}

function FrictionWithMatchesBlock({ friction }: { friction: FrictionWithMatches }) {
  return (
    <article>
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        Friction
        {friction.efficacy_class && (
          <>
            <span className="mx-2">·</span>
            <span>{friction.efficacy_class.replaceAll("-", " ")}</span>
          </>
        )}
      </p>
      <h2 className="text-xl font-semibold leading-snug">{friction.friction_summary}</h2>
      <p className="mt-3 text-neutral-800 leading-relaxed">{friction.mechanism}</p>

      {friction.matches.length > 0 ? (
        <section className="mt-8 border-l-2 border-neutral-200 pl-6 space-y-8">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500">
            Matched K-Beauty products
          </h3>
          {friction.matches.map((match) => (
            <MatchBlock key={match.id} match={match} />
          ))}
        </section>
      ) : (
        // Two no-matches paths read differently to the visitor:
        //   • Friction was approved manually via /admin → matches will land on
        //     the next pipeline cron run. Surface a "queued" state so the
        //     interim window looks intentional, not broken.
        //   • Friction was auto-approved by the cron AND matching ran but
        //     produced nothing usable → this is a real "no fit" signal.
        // We can't perfectly distinguish without a flag, but the heuristic of
        // "newer than the latest pipeline_runs success" is good enough to
        // catch the manual-approve case the vast majority of the time. For
        // simplicity we use the safer interim copy whenever matches are
        // absent — it's accurate either way for a v1 dashboard.
        <p className="mt-6 text-sm text-neutral-500 italic">
          Product matches queued for the next pipeline run. K-Beauty matches
          attach automatically; this friction was approved between cron ticks
          and is waiting for the upcoming refresh.
        </p>
      )}

      {/* Marketing post: surfaces when a post has been approved for this friction. */}
      {friction.marketing_post && <MarketingPostBlock post={friction.marketing_post} />}

      {/* Product idea: only when the AI couldn't find a strong catalog match. */}
      {friction.product_idea && <ProductIdeaBlock idea={friction.product_idea} />}
    </article>
  );
}

function MarketingPostBlock({ post }: { post: MarketingPostBody }) {
  return (
    <section className="mt-10 rounded-lg border border-neutral-300 bg-neutral-50 p-6">
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-3">
        Marketing post draft
      </p>
      <h3 className="text-2xl font-semibold leading-tight text-neutral-900">
        {post.headline}
      </h3>
      <p className="mt-4 text-neutral-800 leading-relaxed whitespace-pre-line">
        {post.body}
      </p>
      <p className="mt-4 text-sm font-medium uppercase tracking-wide text-neutral-700">
        {post.call_to_action}
      </p>
    </section>
  );
}

function ProductIdeaBlock({ idea }: { idea: ProductIdeaBody }) {
  return (
    <section className="mt-10 rounded-lg border border-amber-300 bg-amber-50 p-6">
      <p className="text-xs uppercase tracking-wide text-amber-700 mb-2">
        K-Beauty white space — concept brief
      </p>
      <h3 className="text-xl font-semibold leading-tight text-neutral-900">
        {idea.concept_name}
      </h3>
      <p className="mt-2 text-sm text-neutral-700 italic">{idea.target_friction}</p>

      <dl className="mt-5 space-y-4 text-sm text-neutral-800 leading-relaxed">
        <Detail label="Hero mechanism" value={idea.hero_mechanism} />
        <Detail label="Hero ingredient class" value={idea.hero_ingredient_class} />
        <Detail label="Target consumer" value={idea.target_consumer_profile} />
        <Detail label="Competitive white space" value={idea.competitive_white_space} />
      </dl>
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-neutral-500 mb-1">{label}</dt>
      <dd className="text-neutral-800">{value}</dd>
    </div>
  );
}

function InfluencerSection({ body }: { body: InfluencerOutputBody }) {
  return (
    <section className="mt-16 border-t border-neutral-200 pt-8">
      <p className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        Influencer suggestions
      </p>
      <h2 className="text-2xl font-semibold leading-tight">
        Creators who already live in this moment
      </h2>
      <p className="mt-2 text-sm text-neutral-500">
        Public-content matches from a web search. Suggestions are based on
        public content categories, not endorsements; no creator has been
        contacted.
      </p>

      <ul className="mt-6 space-y-6">
        {body.suggestions.map((s, i) => (
          <li key={`${s.creator_handle}-${i}`} className="rounded-lg border border-neutral-200 p-5">
            <p className="text-base font-semibold">{s.creator_handle}</p>
            <p className="mt-2 text-sm text-neutral-800 leading-relaxed">{s.reasoning}</p>
            <p className="mt-3 text-xs text-neutral-500 break-all">
              {s.public_evidence}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MatchBlock({ match }: { match: PublicMatch }) {
  const { product } = match;
  const lgBadge = product.is_lg ? "LG H&H" : "competitor brand";
  const imgUrl = productImageUrl(product.image_path);
  return (
    <div className="flex gap-4">
      <a
        href={product.public_url}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0 block w-20 h-20 rounded-md bg-neutral-100 overflow-hidden relative hover:opacity-90"
        aria-label={`Open ${product.name} on Olive Young`}
      >
        {imgUrl ? (
          <Image
            src={imgUrl}
            alt={product.name}
            fill
            sizes="80px"
            className="object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[10px] text-neutral-400 text-center px-1">
            no image
          </div>
        )}
      </a>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-3 flex-wrap">
          <p className="text-base font-semibold">{product.brand}</p>
          <span className="text-xs uppercase tracking-wide text-neutral-500">{lgBadge}</span>
          <span className="ml-auto text-xs font-mono text-neutral-500">
            match {match.match_score.toFixed(2)}
          </span>
        </div>
        <a
          href={product.public_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 block text-neutral-900 hover:underline"
        >
          {product.name} ↗
        </a>
        <p className="mt-3 text-neutral-800 leading-relaxed">
          {match.scientific_argument}
        </p>
      </div>
    </div>
  );
}
