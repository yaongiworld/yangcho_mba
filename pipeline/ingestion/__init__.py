"""Data ingestion — cultural calendar (always-on) + TikTok (value-add).

Graceful degradation primitive: each source has last-known-good caching with TTLs.
If TikTok fails, the cultural calendar still produces a daily brief.
"""
