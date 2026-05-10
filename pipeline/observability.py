"""pipeline_runs observability — every stage opens and closes a row.

Implements the /plan-eng-review Issue 7 decision: SDK retries handle transient
LLM failures, parse_or_default handles malformed responses, and this module
records what actually happened at every stage so we can answer "is the
pipeline healthy?" from the dashboard.

Usage:

    from pipeline.observability import record_stage
    from pipeline.schemas import PipelineStage

    with record_stage(PipelineStage.INGEST_REDDIT) as run:
        items = fetch_reddit()
        run.items_processed = len(items)
        run.items_succeeded = len(items)

The context manager:
  - On enter: inserts a row with status='running', returns a mutable handle.
  - On clean exit: updates status='success' (or 'partial' if items_succeeded < items_processed).
  - On exception (default): updates status='failure' with error_message, then RE-RAISES.
  - With swallow=True: same as failure path but the exception is logged and consumed.
    Used for non-critical stages where one failure shouldn't crash the whole run.

Failures of THIS module never propagate. If the pipeline_runs table itself is
unreachable, we log and continue — observability outage must not break the pipeline.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from pipeline.db import supabase_client
from pipeline.schemas import PipelineStage, PipelineStatus
from pipeline.version import prompt_version

logger = logging.getLogger(__name__)


@dataclass
class StageHandle:
    """Mutable handle yielded by record_stage(). Set fields during the stage."""

    stage: PipelineStage
    started_at: datetime
    items_processed: int | None = None
    items_succeeded: int | None = None
    # Internal: row id assigned by Supabase, None if insert failed.
    _row_id: int | None = None


def _open_run(stage: PipelineStage) -> StageHandle:
    """Insert a 'running' row. Returns a handle even if the insert failed."""
    started_at = datetime.now(timezone.utc)
    handle = StageHandle(stage=stage, started_at=started_at)
    try:
        client = supabase_client()
        result = (
            client.table("pipeline_runs")
            .insert({
                "started_at": started_at.isoformat(),
                "stage": stage.value,
                "status": PipelineStatus.RUNNING.value,
                "code_version": prompt_version(),
            })
            .execute()
        )
        if result.data:
            handle._row_id = result.data[0]["id"]
    except Exception as exc:
        logger.warning("observability: could not open pipeline_runs row: %s", exc)
    return handle


def _close_run(
    handle: StageHandle,
    status: PipelineStatus,
    error_message: str | None = None,
) -> None:
    """Update the row to terminal status. Never raises."""
    if handle._row_id is None:
        return  # row never opened; nothing to close
    try:
        client = supabase_client()
        update: dict[str, str | int | None] = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": status.value,
        }
        if error_message:
            # Cap error message length so a giant traceback doesn't bloat the row.
            update["error_message"] = error_message[:2000]
        if handle.items_processed is not None:
            update["items_processed"] = handle.items_processed
        if handle.items_succeeded is not None:
            update["items_succeeded"] = handle.items_succeeded
        client.table("pipeline_runs").update(update).eq("id", handle._row_id).execute()
    except Exception as exc:
        logger.warning("observability: could not close pipeline_runs row: %s", exc)


@contextmanager
def record_stage(
    stage: PipelineStage,
    *,
    swallow: bool = False,
) -> Iterator[StageHandle]:
    """Track a pipeline stage. Default re-raises on exception; swallow=True consumes it.

    Use swallow=True for non-critical stages (e.g., one ingestion source failing
    when others succeed). Use the default for critical stages where failure
    should abort the run.
    """
    handle = _open_run(stage)
    try:
        yield handle
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        _close_run(handle, PipelineStatus.FAILURE, error_message=error_message)
        if swallow:
            logger.exception("stage %s failed (swallowed)", stage.value)
            return
        raise
    else:
        # Compute success vs partial based on items_succeeded / items_processed.
        if (
            handle.items_processed is not None
            and handle.items_succeeded is not None
            and handle.items_succeeded < handle.items_processed
        ):
            status = PipelineStatus.PARTIAL
        else:
            status = PipelineStatus.SUCCESS
        _close_run(handle, status)


def last_successful_run_at(stage: PipelineStage | None = None) -> datetime | None:
    """Return the latest successful pipeline_runs row's finished_at.

    Used by the dashboard's "Last successful pipeline run: …" methodology
    callout and by the (deferred TODO P3) failure notification system.

    If `stage` is None, returns the latest success across ALL stages — useful
    for the top-level "is the pipeline alive?" signal.
    """
    try:
        client = supabase_client()
        q = (
            client.table("pipeline_runs")
            .select("finished_at")
            .eq("status", PipelineStatus.SUCCESS.value)
            .order("finished_at", desc=True)
            .limit(1)
        )
        if stage is not None:
            q = q.eq("stage", stage.value)
        result = q.execute()
        if not result.data:
            return None
        return datetime.fromisoformat(result.data[0]["finished_at"])
    except Exception as exc:
        logger.warning("last_successful_run_at failed: %s", exc)
        return None
