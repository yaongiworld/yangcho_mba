"""Supabase client — single entry point for every Postgres write/read in the pipeline.

The pipeline always uses the SECRET key (writes need it; reads happen under
the same key for simplicity at portfolio scale). The dashboard uses the
publishable key — that path goes through `dashboard/lib/supabase.ts`, not
this file.

Per Supabase's 2025 key model: secret keys (`sb_secret_...`) bypass RLS,
publishable keys (`sb_publishable_...`) respect it. Same RLS semantics as
the legacy service_role / anon pair, just renamed and individually
revocable. Projects created after Nov 1, 2025 get only the new format.

Lazy-init pattern: the client is constructed on first use, not at import time,
so prompt/schema unit tests can run without env vars set.

Env vars (set in GitHub Actions secrets, mirrored locally in `.env`):
  SUPABASE_URL          — https://<ref>.supabase.co
  SUPABASE_SECRET_KEY   — sb_secret_... (bypasses RLS; never ship to client)
"""

from __future__ import annotations

import os
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


@cache
def supabase_client() -> Client:
    """Lazy-initialized secret-key client. Raises clearly if env is missing."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url:
        raise RuntimeError("SUPABASE_URL not set")
    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY not set")

    # Lazy import keeps the rest of the pipeline importable without supabase-py installed.
    from supabase import create_client

    return create_client(url, key)
