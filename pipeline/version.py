"""Resolve the prompt_version git SHA to stamp on every AI-generated row.

This is the moat artifact's traceability spine: every friction analysis, every
match, every playbook output carries the git SHA of the pipeline code that
produced it. Lets us correlate output quality against specific commits, and
lets methodology-page reviewers see exactly when a prompt last changed.
"""

from __future__ import annotations

import os
import subprocess
from functools import cache


@cache
def prompt_version() -> str:
    """Return the short git SHA of HEAD, or a sentinel if git is unavailable.

    In CI / GitHub Actions, prefer $GITHUB_SHA when set — it's authoritative even
    if the checkout is shallow. Fall back to local git rev-parse otherwise. If
    nothing works (e.g., running inside a built artifact), return 'unknown'.
    """
    if env_sha := os.environ.get("GITHUB_SHA"):
        return env_sha[:12]

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return out.strip()
