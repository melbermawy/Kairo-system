"""
Learning Service.

PR-4: Decisions + Learning Pipeline (Deterministic, No LLM).
PR-6: Added RunContext construction + propagation.

Provides learning summary and execution event processing for brand context (F3_learning flow).

Per PR-map-and-standards §PR-3 4.7, §PR-4, and §PR-6.
"""

import logging
from uuid import UUID

from kairo.hero.dto import LearningEventDTO, LearningSummaryDTO
from kairo.hero.engines import learning_engine
from kairo.hero.run_context import RunContext, create_run_context

logger = logging.getLogger(__name__)


def get_learning_summary(brand_id: UUID) -> LearningSummaryDTO:
    """
    Get learning summary for a brand.

    Calls learning_engine.summarize_learning_for_brand which:
    - Fetches recent LearningEvents from DB (last 30 days)
    - Aggregates performance metrics by pattern, channel
    - Returns a computed LearningSummaryDTO

    Note: This is a read-only operation that doesn't modify state,
    so no RunContext needed (doesn't call engine entrypoint with logging).

    Args:
        brand_id: UUID of the brand

    Returns:
        LearningSummaryDTO with computed learning data
    """
    return learning_engine.summarize_learning_for_brand(brand_id)


def process_recent_execution_events(
    brand_id: UUID,
    hours: int = 24,
    ctx: RunContext | None = None,
) -> dict:
    """
    Process recent execution events for a brand and generate learning events.

    This is the main entry point for the learning pipeline, typically called
    from a management command or scheduled task.

    Per PR-4 requirements:
    - Fetches ExecutionEvents with decision_type set within the time window
    - Aggregates events and applies deterministic weight rules
    - Creates LearningEvent rows in the database
    - Returns summary statistics

    PR-6: Constructs RunContext if not provided (for F3_learning flow).
    The trigger_source defaults to "api" but should be "manual" when called
    from a management command.

    Args:
        brand_id: UUID of the brand to process
        hours: Number of hours to look back (default 24)
        ctx: Optional RunContext. If None, creates one with trigger_source="api"

    Returns:
        Dict with processing statistics:
        - events_processed: Number of ExecutionEvents processed
        - learning_events_created: Number of LearningEvents created
        - learning_events: List of created LearningEventDTOs
    """
    if ctx is None:
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F3_learning",
            trigger_source="api",
        )

    result = learning_engine.process_execution_events(
        ctx=ctx,
        window_hours=hours,
    )

    logger.info(
        "Processed execution events for brand",
        extra={
            "brand_id": str(brand_id),
            "hours": hours,
            "events_processed": result.events_processed,
            "learning_events_created": result.learning_events_created,
        },
    )

    return {
        "events_processed": result.events_processed,
        "learning_events_created": result.learning_events_created,
        "learning_events": result.learning_events,
    }


def get_learning_events(
    brand_id: UUID,
    limit: int = 100,
) -> list[LearningEventDTO]:
    """
    Get recent learning events for a brand.

    Note: This is a read-only operation that doesn't modify state,
    so no RunContext needed.

    Args:
        brand_id: UUID of the brand
        limit: Maximum number of events to return

    Returns:
        List of LearningEventDTOs
    """
    return learning_engine.get_learning_events_for_brand(brand_id, limit)
