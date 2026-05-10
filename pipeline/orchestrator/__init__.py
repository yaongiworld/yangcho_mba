"""Orchestrator — daily cron entrypoint.

Runs LLM calls in parallel via asyncio.gather() across moments. Pipeline wall time
~2 min instead of 5–10 min serial. Every stage records to pipeline_runs table.
"""
