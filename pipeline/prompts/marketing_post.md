# Marketing post generator

PLACEHOLDER. Implementation lands in W4. Voice-checked by Yangcho — zero
K-Beauty cultural phrasing should leak through.

## What this prompt does

Given a matched friction + product, generate 80–120 word English marketing copy
in mainstream-American voice. NO Korean cultural references, NO "glass skin",
NO "K-Beauty secret". The pitch is American mainstream lifestyle science.

## Output schema

JSON:
```json
{
  "headline": "string — 4–8 words",
  "body": "string — 80–120 words",
  "call_to_action": "string — 2–6 words"
}
```

## Voice constraints (NON-NEGOTIABLE)

- ❌ "K-Beauty", "glass skin", "Korean ritual", "Seoul-inspired", "ancient Korean"
- ❌ Cute pastel adjectives ("dreamy", "kawaii", "adorable")
- ✅ Outcome-first ("Your tailgate, weather-engineered")
- ✅ Mechanism-as-feature ("Sebum-resistant film former for 6+ hour wear")
- ✅ Mainstream cultural references the audience already knows

# Variables

- `{{moment_name}}`
- `{{friction_summary}}`
- `{{product_name}}`
- `{{product_brand}}`
- `{{scientific_argument}}`

# Test cases

W4 voice spot-check: 5 generated posts, Yangcho confirms zero cultural-marketing
phrasing leaked. Posts always default to `draft` until she approves — never
auto-publish via the confidence gate.
