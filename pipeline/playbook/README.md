# pipeline/playbook/

Three generators, each one LLM call via `call_llm()`:

1. **`influencer.py`** — matches a moment against `data/influencers.yaml` (~50 curated US creators with public moment-fit tags). No private DM scraping, no follower-count harvesting, no PII.
2. **`marketing_post.py`** — 80–120 word English copy in mainstream-American voice. Voice-check spot-tested in W4 to confirm zero K-Beauty cultural phrasing leaks.
3. **`product_idea.py`** — triggered only when match score < threshold. One-page brief with target friction, hero mechanism, and competitive white space.

All outputs land in `playbook_outputs` table with `approved_by_yangcho: bool`. Marketing posts always default to `draft` until Yangcho approves; the confidence gate doesn't auto-approve marketing copy (different bar than friction analysis).
