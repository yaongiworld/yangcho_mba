# pipeline/ingestion/

Two sources, ranked by reliability:

1. **`calendar.py`** — reads `data/calendar.yaml`. Always-on, deterministic, zero failure modes. Returns the lifestyle moments tied to today's date.
2. **`tiktok.py`** — playwright + XHR interception against TikTok Creative Center. Value-add, the most fragile source. On failure, the pipeline keeps running with calendar moments only.

Every source returns the same `RawSignal` schema (see `pipeline/schemas.py`). Last-known-good cache lives in Supabase `signals_cache` (TTL: 24h). On a fresh failure, the orchestrator reads the cache and surfaces a "Data refresh delayed" banner via `pipeline_runs.last_success`.
