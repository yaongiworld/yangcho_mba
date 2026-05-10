# TODOS

Deferred work captured during planning. Each entry has enough context that picking it up months later still works.

---

## P3 — Pipeline failure notification system

**What:** Send Yangcho or Tony a Telegram or email notification when `pipeline_runs` records 2+ consecutive failures of any stage.

**Why:** Without this, the only way to know TikTok scraping died is to manually check the dashboard. Tony explicitly asked for failure notifications during /plan-eng-review on 2026-05-09. Daily cron failures during application week could silently kill the demo for 24+ hours.

**Pros:** Catch failures fast, fix before they affect application-week demo.

**Cons:** 30 min of setup. Telegram bot is the simplest (free, instant, reliable). Adds one external secret to manage.

**Context:** Surfaced from /plan-eng-review TODO-1 answer ("notify when TikTok scraping is failing"). Could ship inline in W7 resilience weekend, deferred for revisit.

**Depends on:** `pipeline_runs` table (W3 — already in scope).

**Revisit when:** Application week is approaching and the pipeline has been running for 2+ weeks; OR after a failure goes undetected for >24h.

**Effort:** XS (~30 minutes). Telegram bot via `python-telegram-bot` reading from `pipeline_runs` for 2+ consecutive failures of the same stage.

---

## P3 — Korean methodology page

**What:** Korean-language version of the Methodology Showcase page mirroring the English content (3 hero case studies + scoring formula + framework explainer).

**Why:** Korean-program tracks, alumni interviewers, faculty interviews could include Korean speakers. The Yaongiworld root CLAUDE.md flags bilingual where it matters as a working principle.

**Pros:** Demonstrates respect for bilingual context. Modest signal for international-track admissions.

**Cons:** Translation upkeep. Mismatches the "American mainstream science" pitch on the public dashboard — the front page is deliberately English-only because the audience is US adcom.

**Context:** Originally Open Question #5 in the design doc. Skipped during /plan-eng-review on 2026-05-09 as not on the critical path.

**Revisit when:** After applications submitted; if a specific program/recommender places weight on Korean-language artifacts; or if interview season includes Korean-speaking alumni interviewers.

**Effort:** S (1 day, mostly translation review).

**Depends on:** W6 Hero Story Layer + W5 Methodology page exist.

---

## P4 — Paid TikTok scraping API ($30–60/mo)

**What:** Outsource TikTok scraping fragility to Apify, BrightData, or similar paid service. Pipeline accepts CSV/JSON input from any source per the multi-source design.

**Why:** Eliminates the most fragile component if the multi-source + graceful-degradation pattern proves insufficient.

**Pros:** Removes the most fragile component. Saves engineering time fighting playwright detection.

**Cons:** $30–60/month extra. Tony explicitly preferred no paid services during /plan-eng-review. Requires external account.

**Context:** Skipped during /plan-eng-review on 2026-05-09. The pipeline pivoted to TikTok-only sourcing (cultural calendar always-on as the floor); paid scraping was further deemed unnecessary.

**Revisit when:** TikTok playwright scraping fails 5+ days in a row during the first 4 weeks AND the cultural calendar feels too thin on its own AND budget allows.

**Effort:** XS (account setup + API key + replace playwright module).

**Depends on:** Nothing structurally.
