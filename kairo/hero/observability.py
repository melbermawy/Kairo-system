"""
Observability utilities for Hero engines.

PR-6: Minimal Observability + Run IDs (Before Any LLM).

Provides structured logging for engine operations. Every engine entry point
logs at least start and end events with run_id, brand_id, flow, trigger_source,
engine name, operation name, and status.

Per PR-map-and-standards §PR-6.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Mapping

from .run_context import RunContext

logger = logging.getLogger("kairo.engines")

Status = Literal["start", "success", "partial", "failure"]


def log_engine_event(
    ctx: RunContext,
    engine: str,
    operation: str,
    status: Status,
    extra: Mapping[str, Any] | None = None,
    error_summary: str | None = None,
) -> None:
    """
    Log a structured engine event.

    All engine operations should log at least:
    - One "start" event at the beginning
    - One "success", "partial", or "failure" event at the end

    The log payload always includes:
    - run_id, brand_id, flow, trigger_source (from RunContext)
    - engine, operation, status (from arguments)
    - error_summary (if status is "failure" and error_summary is provided)
    - Any additional fields from extra

    Args:
        ctx: RunContext for this run
        engine: Name of the engine (e.g., "opportunities_engine")
        operation: Name of the operation (e.g., "generate_today_board")
        status: Current status ("start", "success", "partial", "failure")
        extra: Optional additional fields to include in the log
        error_summary: Short error description for failure status (e.g., "Brand.DoesNotExist")
    """
    payload: dict[str, Any] = {
        "run_id": str(ctx.run_id),
        "brand_id": str(ctx.brand_id),
        "flow": ctx.flow,
        "trigger_source": ctx.trigger_source,
        "engine": engine,
        "operation": operation,
        "status": status,
    }

    if ctx.step:
        payload["step"] = ctx.step

    if error_summary:
        payload["error_summary"] = error_summary

    if extra:
        payload.update(extra)

    logger.info("engine_event", extra=payload)
