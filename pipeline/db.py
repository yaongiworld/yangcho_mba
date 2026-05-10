"""Supabase client — single entry point for every Postgres write/read in the pipeline.

The pipeline always uses the SERVICE-ROLE key (writes need it; reads happen
under the same key for simplicity at portfolio scale). The dashboard uses the
anon key — that path goes through `dashboard/lib/supabase.ts`, not this file.

Lazy-init pattern: the client is constructed on first use, not at import time,
so prompt/schema unit tests can run without env vars set.

Env vars (set in GitHub Actions secrets, mirrored locally in `.env`):
  SUPABASE_URL                — https://<ref>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   — service_role JWT
"""

from __future__ import annotations

import os
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


@cache
def supabase_client() -> Client:
    """Lazy-initialized service-role client. Raises clearly if env is missing."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url:
        raise RuntimeError("SUPABASE_URL not set")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not set")

    # Lazy import keeps the rest of the pipeline importable without supabase-py installed.
    from supabase import create_client

    return create_client(url, key)
