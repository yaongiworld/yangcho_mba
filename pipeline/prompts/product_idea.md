# New-product-idea generator

PLACEHOLDER. Implementation lands in W4. Triggered ONLY when the best product
match score is below threshold (currently 0.5 — tunable).

## What this prompt does

Given a friction analysis + the failure of any existing product to match well,
generate a one-page product brief: target friction, hero mechanism, hero
ingredient class, target consumer profile, competitive white space note.

This is the previous project's killer feature, preserved. Yangcho's voice;
defendable in any interview as "the system told me K-Beauty doesn't have this
yet, here's what it should be."

## Output schema

JSON:
```json
{
  "concept_name": "string — short codename",
  "target_friction": "string",
  "hero_mechanism": "string — R&D voice",
  "hero_ingredient_class": "string",
  "target_consumer_profile": "string — 2–3 sentences",
  "competitive_white_space": "string — why no current K-Beauty product fills this"
}
```

# Variables

- `{{friction_summary}}`
- `{{friction_mechanism}}`
- `{{best_existing_match}}` — the product + score that didn't quite fit
- `{{efficacy_class}}`
