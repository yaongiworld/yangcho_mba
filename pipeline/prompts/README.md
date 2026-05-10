# pipeline/prompts/

One markdown file per LLM call site. The `call_llm()` helper in `pipeline/llm.py` reads these files and substitutes `{{handlebars}}` variables before calling Claude.

Every entry the pipeline generates is stamped with `prompt_version` (the git SHA at the time of generation), so we can always trace which prompt produced which output.

| File | Purpose | Owner |
|------|---------|-------|
| `friction.md` | The moat. Generates friction analysis from a lifestyle moment. Anchored by Yangcho's 3 hero case studies as in-context exemplars. | Yangcho writes the hero cases; Tony scaffolds the prompt structure. |
| `scoring.md` | LLM-driven scoring of Purchase Intent (1–5) and Brand Risk (1–5) for a moment. Trend Velocity is computed numerically, not by LLM. | Tony |
| `product_match.md` | Matches a friction analysis to a K-Beauty product from the scraped catalog. LG primary; competitor honest. | Tony |
| `marketing_post.md` | 80–120 word English copy, mainstream-American voice. Zero K-Beauty cultural phrasing. | Tony, voice-checked by Yangcho |
| `product_idea.md` | One-page new-product brief, triggered when match score < threshold. | Yangcho voice |
| `influencer.md` | Reasoning over `data/influencers.yaml` to suggest a moment-fit creator. | Tony |
| `self_rating.md` | After friction analysis, AI self-rates 1–10. Drives the confidence gate. | Tony |

## Convention

- Markdown body is the prompt itself.
- A `# Variables` section at the bottom lists `{{var_name}}` substitutions and what they should contain.
- A `# Test cases` section lists 1–3 hand-rated examples for the W1 quality gate.
- No prompt is checked in with secrets or employer-specific terms (the pre-commit hook enforces this).
