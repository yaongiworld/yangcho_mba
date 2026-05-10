# pipeline/ingestion/

Three sources, ranked by reliability:

1. **`calendar.py`** — reads `data/calendar.yaml`. Always-on, deterministic, zero failure modes. Returns the lifestyle moments tied to today's date.
2. **`reddit.py`** — PRAW client over public subreddits (r/SkincareAddiction, r/AsianBeauty, r/MakeupAddiction, r/30PlusSkinCare, r/Sephora). Always-on; graceful empty + logged on PRAW auth failure.
3. **`tiktok.py`** — Creative Center API + playwright fallback. Value-add; expected to be the most fragile. On failure, the pipeline keeps running with calendar + Reddit.

Every source returns the same `RawSignal` schema (see `pipeline/schemas.py`). Last-known-good cache lives in Supabase `signals_cache` (TTL: 24h). On a fresh failure, the orchestrator reads the cache and surfaces a "Data refresh delayed" banner via `pipeline_runs.last_success`.
