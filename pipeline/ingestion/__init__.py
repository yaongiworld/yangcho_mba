"""Data ingestion — Reddit (always-on), cultural calendar (always-on), TikTok (value-add).

Graceful degradation primitive: each source has last-known-good caching with TTLs.
If a source fails, the pipeline produces a daily brief from the remaining sources.
"""
