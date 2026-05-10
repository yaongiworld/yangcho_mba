# Moment scoring prompt

PLACEHOLDER. Implementation lands in W3 with the 10-moment calibration test.

## What this prompt does

Given a clustered lifestyle moment + its raw signals, rate two dimensions 1–5:

- `purchase_intent` — how much commerce-language ("I need", "buying", "where can I get")
  appears in the source posts.
- `brand_risk` — legal / controversy / PR-incident risk. Explicitly NOT cultural risk
  (cultural moments ARE the product, not a risk to filter).

Trend Velocity is computed numerically from signal volume deltas, not by LLM.

## Output schema

JSON:
```json
{
  "purchase_intent": "integer 1–5",
  "brand_risk": "integer 1–5",
  "rationale": "string — one paragraph defending the ratings"
}
```

# Variables

- `{{moment_name}}`
- `{{signal_sample}}` — 10–20 representative posts

# Test cases

W3 calibration test: 10 known moments (5 strong + 5 noise). Verify that the
overall score `(trend_velocity × purchase_intent) − brand_risk` ranks the strong
moments above the noise.
