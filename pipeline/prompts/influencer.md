# Influencer suggestion

PLACEHOLDER. Implementation lands in W4.

## What this prompt does

Given a lifestyle moment, suggest one creator from the curated list in
`data/influencers.yaml` whose public content categories overlap with the
moment.

NEVER scrape private DMs, follower counts, or PII. The curated list ONLY
contains public content categories the creator has voluntarily posted in
public. The prompt reasons over the list; it does not generate creator names
freely (which would risk hallucinating non-existent people).

## Output schema

JSON:
```json
{
  "creator_handle": "string — must exactly match an entry in influencers.yaml",
  "reasoning": "string — one paragraph on the moment-fit",
  "public_evidence": "string — 1–2 sample post references showing the fit"
}
```

# Variables

- `{{moment_name}}`
- `{{moment_description}}`
- `{{influencer_list}}` — full curated list as YAML/JSON

# Disclaimer

The dashboard surfaces these suggestions with copy: "Suggestions are based on
public content categories, not endorsements. Creators have not been contacted."
