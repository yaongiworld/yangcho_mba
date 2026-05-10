# pipeline/analysis/

Stages, in order:

1. **`extract_moments.py`** — clusters raw signals into named lifestyle moments. LLM-driven, snapshot-tested on golden input.
2. **`score.py`** — Trend Velocity × Purchase Intent − Brand Risk. Concrete definitions:
   - Trend Velocity = 7-day rolling volume delta (smooths celebrity-tweet spikes).
   - Purchase Intent = LLM rates 1–5 on commerce-language presence in source posts.
   - Brand Risk = LLM rates 1–5 on legal/controversy/PR-incident risk. Explicitly NOT cultural risk.
3. **`friction.py`** — the moat. Generates friction analysis via `call_llm("friction", ...)`. Includes AI self-rating 1–10 used by the confidence gate.
4. **`match_product.py`** — RAG over scraped catalog. LG primary; competitor recommended honestly when LG lacks fit (within 0.15 score threshold).

All outputs go through `parse_or_default()` in `pipeline/llm.py` — never crash on malformed responses.
