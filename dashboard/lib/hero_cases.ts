/**
 * Read the 3 hero case study markdown files from disk and render them as HTML.
 *
 * The cases live in `../pipeline/prompts/hero_cases/` — outside the dashboard
 * directory because they're also consumed by the Python friction analyzer as
 * in-context exemplars. Single source of truth across pipeline and dashboard.
 *
 * fs reads happen at request time (Node runtime, server component). Next.js
 * caches by default; revalidate when needed via revalidateTag or revalidatePath.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { marked } from "marked";

// Configure marked for static rendering (no client-side JS needed).
marked.setOptions({
  gfm: true,
  breaks: false,
});

const HERO_CASES_DIR = join(process.cwd(), "..", "pipeline", "prompts", "hero_cases");

export interface HeroCase {
  slug: string;
  title: string;
  /** Full markdown rendered to HTML. */
  html: string;
  /** Whether the case is still the placeholder Tony wrote (vs Yangcho's real version). */
  isPlaceholder: boolean;
}

const HERO_CASE_FILES: { slug: string; filename: string; title: string }[] = [
  {
    slug: "long-outdoor-uv-sweat",
    filename: "1_long_outdoor_uv_sweat.md",
    title: "Long outdoor moments — UV, sweat, and film-former failure",
  },
  {
    slug: "hard-water-film",
    filename: "2_hard_water_film.md",
    title: "US municipal hard water and the chelation gap",
  },
  {
    slug: "post-microneedling-repair",
    filename: "3_post_microneedling_repair.md",
    title: "At-home microneedling recovery — barrier biology meets #SkinTok",
  },
];

export function loadHeroCases(): HeroCase[] {
  return HERO_CASE_FILES.map(({ slug, filename, title }) => {
    const raw = readFileSync(join(HERO_CASES_DIR, filename), "utf-8");
    const isPlaceholder = raw.includes("PLACEHOLDER");
    return {
      slug,
      title,
      html: marked.parse(raw, { async: false }) as string,
      isPlaceholder,
    };
  });
}
