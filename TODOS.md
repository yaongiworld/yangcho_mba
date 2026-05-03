# TODOS

Deferred work captured during planning. Each entry has enough context that
picking it up months later still works.

---

## P2 — Origin Essay artifact (`essay.md`)

**What:** A first-person personal narrative (600–800 words) explaining the
origin of the White Space Miner project: the moment Yangcho noticed the gap
between US consumer complaints and K-Beauty solutions, why it bothered her
enough to spend her weekends on it, what working cross-functionally with a
CTO partner taught her, and what that revealed about why she now wants an
MBA. Lives at `essay.md` in the repo, surfaced as a "Why I built this" link
from the dashboard footer.

**Why:** The single biggest predictor in MBA admissions is *self-awareness
about why you want this*, not what you built. This artifact addresses that
directly. Reusable: can seed the "why MBA" essay, the "biggest learning"
essay, and interview answers.

**Pros:** High potential differentiation; reusable content; bilingual is a
strength, not a weakness.

**Cons:** Same first-person voice and same beats as her actual MBA
application essays — drafting it is drafting a near-duplicate of work she
has to do anyway. If her application essays are flowing well, this becomes
redundant. If they're struggling, the energy is better spent on the real
essays.

**Context (deferred during /plan-ceo-review on 2026-05-02):** Cherry-pick
ceremony surfaced this as Expansion 2 of 3. Deferred because the writing
energy is *substitutive* with the application essays themselves, not
additive (unlike the Companion White Paper, which has a third-person
project-explainer voice the application essays will not contain).

**Revisit when:**
- Yangcho's MBA essay drafts are flowing easily and she has spare writing
  capacity, OR
- A draft from this artifact would seed (rather than duplicate) an
  application essay, OR
- After the white paper exists and she wants a personal-voice companion
  artifact.

**Effort:** S (1 weekend of Yangcho's writing time, no engineering, no CC
compression — authentic voice can't be tooled).

**Depends on:** Nothing structurally. White paper existence is helpful but
not required.

---

## P3 — Recommender-Friendly One-Pager (`for-recommenders.pdf`)

**What:** A single-sided PDF with the project name, a one-paragraph
non-technical "what it does," 2 hero discoveries with screenshots, a
tools-used line, and the dashboard URL. Designed to be skimmed in 90
seconds. Lives at `for-recommenders.pdf` in the repo.

**Why:** Recommendations are explicitly called out in the Korean strategy
doc as a critical lever ("긴 관찰 기간을 통한 깊은 서사"). If Yangcho chooses
to share this with the 3-year ex-partlead and/or 9-month senior recommender,
they get a concrete artifact that anchors "she's intellectually curious
beyond her day job" — which is the hardest signal to convey from observation
alone.

**Pros:** Cheap to produce — ~95% of content is recycled from the white
paper. Marginal cost is layout time (4–6 hours). Even unshared, it preserves
the option.

**Cons:** **Sharing it is itself a secrecy decision.** Showing it to a
recommender reveals some level of "I'm applying to programs" intent. The
strategy doc explicitly notes she's preparing without employer knowledge
— this is the artifact most likely to break that secrecy if mishandled.
Also: recommenders write what they observe; an artifact she shows them
can be filed mentally as "she lobbied for me to mention this," which
slightly weakens the letter's authenticity.

**Context (deferred during /plan-ceo-review on 2026-05-02):** Cherry-pick
ceremony surfaced this as Expansion 3 of 3. Deferred because the right
moment to *produce* this is after the white paper exists, and the right
moment to *share* it (or not) is after Yangcho has casually mentioned the
project in conversation to each recommender to gauge their reaction.
Producing it now creates a temptation to share before the ground is laid.

**Revisit when:**
- White paper exists (most content recycles from it), AND
- Yangcho has had at least one casual conversation with each recommender
  about her recent side work, AND
- She has decided whether sharing is worth the secrecy risk.

**Effort:** XS (4–6 hours of layout — one half-weekend day).

**Depends on:** White paper (W7) for content reuse.

---

## P3 — Bilingual UI (Korean / English)

**What:** Add Korean translations for the public-facing dashboard pages
(P1 cluster explorer, P2 brief view, P3 hero cases, P4 timeline). Use
Next.js i18n routing. Briefs themselves stay English-first since the
audience is US admissions; only the chrome (nav, labels, empty states)
gets translated.

**Why:** Demonstrates respect for the bilingual context. The
Yaongiworld root CLAUDE.md flags bilingual where it matters as a working
principle. If interview prep includes Korean-speaking faculty contacts
or family demos, this matters.

**Pros:** Free option — Next.js i18n is a one-day add-on, doesn't require
content rework. Modest signal for international-track admissions.

**Cons:** Not on the critical path for admissions. Risk of half-finished
translations that look worse than English-only.

**Context (raised during /plan-ceo-review on 2026-05-04 stack change):**
The stack switch from Streamlit to Next.js made this *feasible*. Not in
scope for the initial build because it adds polish work in a budget
that has zero buffer. Genuinely optional.

**Revisit when:**
- After initial launch, if there's time before applications, OR
- If a specific program or recommender places weight on Korean-context
  framing.

**Effort:** S (1 day, mostly translation review).

**Depends on:** W4 dashboard scaffold.

---

## P3 — Dashboard cold-start splash (only if Vercel/Supabase free tier ever sleeps)

**What:** A static landing page that loads instantly and auto-redirects to
the live dashboard once warm.

**Why:** The original Streamlit Cloud sleep issue (30s wake on first visit)
was a primary motivator for the stack switch. Vercel + Supabase free
tiers do not sleep the public dashboard the same way. If that ever
changes, the splash fix from the original Question 4 plan still applies.

**Context (raised during /plan-ceo-review on 2026-05-02):** Filed as a
contingency, not active work. Revisit only if dashboard cold-start becomes
observable in practice.

**Effort:** XS (~30 minutes).

**Depends on:** Nothing.
