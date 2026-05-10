# Product matching prompt

PLACEHOLDER. Implementation lands in W3.

## What this prompt does

Given a friction analysis (from `friction.md`) and a candidate product list
retrieved from the scraped catalog (LG H&H + competitors), pick the best match.

Honest competitor-recommendation policy: if the LG match score is within 0.15
of a competitor's, prefer LG. Otherwise recommend the better fit even if it's a
competitor — this signals scientific integrity, not corporate disloyalty.

## Output schema

JSON:
```json
{
  "matches": [
    {
      "product_id": "integer — references products.id",
      "match_score": "float 0–1",
      "scientific_argument": "string — paragraph in R&D voice connecting friction → product"
    }
  ]
}
```

# Variables

- `{{friction_summary}}`
- `{{friction_mechanism}}`
- `{{efficacy_class}}`
- `{{candidate_products}}` — JSON array of products with id, brand, name, claims, key_ingredients
