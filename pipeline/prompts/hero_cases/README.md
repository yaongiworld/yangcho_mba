# Hero case studies — the moat artifact

This directory holds Yangcho's 3 hero case studies, used in two places:

1. **In-context exemplars** in `pipeline/prompts/friction.md`. The friction analyzer
   reasons by analogy — it sees these 3 cases and writes new ones in the same voice
   and structure.
2. **Public Methodology Showcase page** (W5). Rendered long-form on `/methodology`
   so any technical interviewer can read Yangcho's actual reasoning.

## Current status

**All three cases are PLACEHOLDERS** written by Tony on 2026-05-10. They demonstrate
the right shape — first-person voice, friction observation → mechanism → ingredient
class → product/concept — but the technical claims are illustrative, not Yangcho's
actual R&D depth. Adcom-defensibility comes from Yangcho's replacement work in W1.

## How to replace

Each file is a markdown document with a fixed structure (see any of the three for
the template). Replace the body in-place. Do not change the filename or the
top-level structure — `pipeline/analysis/friction.py` reads them by filename.

The friction prompt loads the FULL content of each file as `{{hero_case_1}}`,
`{{hero_case_2}}`, `{{hero_case_3}}` exemplars. Length: 250–400 words per case.

## Quality bar

When you replace a placeholder, the new case must:

- Be defensible cold in any interview ("why is hard-water chelation the right
  mechanism for this friction, and not just better surfactant choice?").
- Use specific ingredient names (e.g., "Acrylates/C10-30 Alkyl Acrylate Crosspolymer"
  not "a film-forming polymer").
- Stay first-person ("I noticed", "in my experience", "the reason I reach for X").
- Not name LG H&H internal projects, codenames, or proprietary information.
  Editorial review at commit time is the safeguard — when in doubt, leave it out.

## The three categories

| File | Friction category | Demonstrates |
|------|-------------------|--------------|
| `1_long_outdoor_uv_sweat.md` | Long outdoor + UV + sweat | Rheology + film-former interaction |
| `2_hard_water_film.md` | US municipal hard water + cleansing | Chelation + surfactant chemistry |
| `3_post_microneedling_repair.md` | At-home microneedling recovery (#SkinTok trend) | Barrier biology + inflammation cascade |

These three were chosen during /plan-eng-review (2026-05-09) as covering the widest
span of Yangcho's R&D depth: rheology, environmental chemistry, and barrier biology.
Replace them in any order.
