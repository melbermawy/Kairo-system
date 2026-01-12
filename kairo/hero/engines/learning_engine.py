"""
Learning Engine.

PR-4: Decisions + Learning Pipeline (Deterministic, No LLM).

Ingests ExecutionEvents from platforms, produces LearningEvents, and
pushes updates back into other engines:
- Opportunities engine (opportunity scores)
- Patterns engine (pattern performance stats)
- Content engine (variant eval scores)

Per docs/technical/03-engines-overview.md §8.

NOTE: PR-4 implements deterministic rules-based learning.
Real LLM/graph-based learning comes in future PRs.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from uuid import UUID

from django.db import transaction
from django.db.models import Count

from kairo.core.enums import Channel, DecisionType, LearningSignalType
from kairo.core.models import ExecutionEvent, LearningEvent, Variant
from kairo.hero.dto import LearningEventDTO, LearningSummaryDTO

logger = logging.getLogger(__name__)


# =============================================================================
# DETERMINISTIC LEARNING RULES
# =============================================================================
# Per PRD-1 §5.4 and PR-map-and-standards §PR-4:
# These rules map user decisions (DecisionType) to LearningSignalType and
# weight_delta values. All logic is deterministic with no LLM calls.

# Weight delta values are bounded in [-1.0, +1.0] per scope per run
DECISION_WEIGHT_MAP: dict[DecisionType, tuple[LearningSignalType, float]] = {
    # Variant decisions
    DecisionType.VARIANT_APPROVED: (LearningSignalType.PATTERN_PERFORMANCE_UPDATE, 0.1),
    DecisionType.VARIANT_REJECTED: (LearningSignalType.PATTERN_PERFORMANCE_UPDATE, -0.1),
    DecisionType.VARIANT_EDITED: (LearningSignalType.PATTERN_PERFORMANCE_UPDATE, 0.0),
    # Opportunity decisions
    DecisionType.OPPORTUNITY_PINNED: (LearningSignalType.OPPORTUNITY_SCORE_UPDATE, 0.15),
    DecisionType.OPPORTUNITY_SNOOZED: (LearningSignalType.OPPORTUNITY_SCORE_UPDATE, -0.05),
    DecisionType.OPPORTUNITY_IGNORED: (LearningSignalType.OPPORTUNITY_SCORE_UPDATE, -0.1),
    # Package decisions (affect channel preferences)
    DecisionType.PACKAGE_CREATED: (LearningSignalType.CHANNEL_PREFERENCE_UPDATE, 0.05),
    DecisionType.PACKAGE_APPROVED: (LearningSignalType.CHANNEL_PREFERENCE_UPDATE, 0.1),
}


class ProcessingResult(NamedTuple):
    """Result of processing execution events."""

    events_processed: int
    learning_events_created: int
    learning_events: list[LearningEventDTO]


# =============================================================================
# MAIN PROCESSING FUNCTION
# =============================================================================


def process_execution_events(
    brand_id: UUID,
    window_hours: int = 24,
) -> ProcessingResult:
    """
    Process execution events and generate learning events.

    PR-4 implementation (deterministic rules-based):
    - Fetches ExecutionEvents with decision_type set within the time window
    - Aggregates events by (variant, decision_type)
    - Applies deterministic weight rules from DECISION_WEIGHT_MAP
    - Creates LearningEvent rows in the database
    - Returns list of created LearningEventDTOs

    Per PRD-1 §5.4:
    - Learning never mutates primary tables (Variant, Opportunity, etc.)
    - It only writes to LearningEvent table
    - Weight deltas are bounded in [-1.0, +1.0] per scope per run

    Args:
        brand_id: UUID of the brand to process
        window_hours: Number of hours to look back (default 24)

    Returns:
        ProcessingResult with counts and list of created LearningEventDTOs
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    # Fetch ExecutionEvents with decision_type set within the time window
    # These are the events that represent user decisions
    execution_events = ExecutionEvent.objects.filter(
        brand_id=brand_id,
        decision_type__isnull=False,
        occurred_at__gte=window_start,
        occurred_at__lte=now,
    ).select_related("variant", "variant__package")

    events_list = list(execution_events)
    if not events_list:
        logger.info(
            "No execution events with decisions found",
            extra={
                "brand_id": str(brand_id),
                "window_hours": window_hours,
            },
        )
        return ProcessingResult(
            events_processed=0,
            learning_events_created=0,
            learning_events=[],
        )

    # Aggregate events by (variant_id, decision_type, channel)
    aggregated: dict[tuple, list[ExecutionEvent]] = defaultdict(list)
    for event in events_list:
        key = (event.variant_id, event.decision_type, event.channel)
        aggregated[key].append(event)

    # Create learning events based on aggregated decisions
    learning_events: list[LearningEvent] = []

    with transaction.atomic():
        for (variant_id, decision_type, channel), events in aggregated.items():
            decision_enum = DecisionType(decision_type)

            if decision_enum not in DECISION_WEIGHT_MAP:
                logger.warning(
                    "Unknown decision type in execution event",
                    extra={
                        "decision_type": decision_type,
                        "variant_id": str(variant_id),
                    },
                )
                continue

            signal_type, base_weight_delta = DECISION_WEIGHT_MAP[decision_enum]

            # Scale weight delta by event count (bounded to [-1.0, +1.0])
            event_count = len(events)
            scaled_delta = base_weight_delta * min(event_count, 10)  # Cap multiplier
            bounded_delta = max(-1.0, min(1.0, scaled_delta))

            # Get variant and related IDs for the learning event
            first_event = events[0]
            variant = first_event.variant
            pattern_id = variant.pattern_template_id if variant else None
            opportunity_id = None
            if variant and variant.package:
                opportunity_id = variant.package.origin_opportunity_id

            # Create the learning event
            learning_event = LearningEvent.objects.create(
                brand_id=brand_id,
                signal_type=signal_type.value,
                pattern_id=pattern_id,
                opportunity_id=opportunity_id,
                variant_id=variant_id,
                payload={
                    "decision_type": decision_type,
                    "channel": channel,
                    "weight_delta": bounded_delta,
                    "event_count": event_count,
                    "window_hours": window_hours,
                },
                derived_from=[str(e.id) for e in events],
                effective_at=now,
            )
            learning_events.append(learning_event)

    # Convert to DTOs
    learning_event_dtos = [_learning_event_to_dto(le) for le in learning_events]

    logger.info(
        "Processed execution events",
        extra={
            "brand_id": str(brand_id),
            "events_processed": len(events_list),
            "learning_events_created": len(learning_events),
            "window_hours": window_hours,
        },
    )

    return ProcessingResult(
        events_processed=len(events_list),
        learning_events_created=len(learning_events),
        learning_events=learning_event_dtos,
    )


# =============================================================================
# SUMMARY GENERATION
# =============================================================================


def summarize_learning_for_brand(brand_id: UUID) -> LearningSummaryDTO:
    """
    Generate a learning summary for a brand.

    PR-4 implementation:
    - Fetches recent LearningEvents from DB (last 30 days)
    - Aggregates performance metrics by pattern, channel, pillar, persona
    - Returns a computed LearningSummaryDTO

    This is still deterministic - it aggregates existing LearningEvents
    rather than making any LLM calls.

    Args:
        brand_id: UUID of the brand

    Returns:
        LearningSummaryDTO with computed learning data
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)

    # Fetch recent learning events
    learning_events = LearningEvent.objects.filter(
        brand_id=brand_id,
        effective_at__gte=window_start,
    ).select_related("pattern", "variant")

    events_list = list(learning_events)

    # If no learning events, return a basic summary
    if not events_list:
        return LearningSummaryDTO(
            brand_id=brand_id,
            generated_at=now,
            top_performing_patterns=[],
            top_performing_channels=[],
            recent_engagement_score=0.0,
            pillar_performance={},
            persona_engagement={},
            notes=["No learning events in the last 30 days"],
        )

    # Aggregate pattern performance
    pattern_scores: dict[UUID, float] = defaultdict(float)
    channel_scores: dict[str, float] = defaultdict(float)

    for event in events_list:
        payload = event.payload or {}
        weight_delta = payload.get("weight_delta", 0.0)
        channel = payload.get("channel")

        if event.pattern_id:
            pattern_scores[event.pattern_id] += weight_delta

        if channel:
            channel_scores[channel] += weight_delta

    # Get top performing patterns (positive scores, sorted descending)
    top_patterns = sorted(
        [(pid, score) for pid, score in pattern_scores.items() if score > 0],
        key=lambda x: x[1],
        reverse=True,
    )[:5]

    # Get top performing channels
    top_channels = sorted(
        [(ch, score) for ch, score in channel_scores.items() if score > 0],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    # Calculate overall engagement score (average of positive deltas)
    positive_deltas = [
        e.payload.get("weight_delta", 0) for e in events_list
        if e.payload.get("weight_delta", 0) > 0
    ]
    avg_engagement = (
        sum(positive_deltas) / len(positive_deltas) * 100
        if positive_deltas
        else 0.0
    )

    # Build notes
    notes = [
        f"Processed {len(events_list)} learning events from the last 30 days",
        f"Found {len(top_patterns)} patterns with positive performance",
    ]

    return LearningSummaryDTO(
        brand_id=brand_id,
        generated_at=now,
        top_performing_patterns=[pid for pid, _ in top_patterns],
        top_performing_channels=[Channel(ch) for ch, _ in top_channels],
        recent_engagement_score=round(avg_engagement, 2),
        pillar_performance={},  # Would require joining to Pillar table
        persona_engagement={},  # Would require joining to Persona table
        notes=notes,
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _learning_event_to_dto(event: LearningEvent) -> LearningEventDTO:
    """Convert a LearningEvent model to LearningEventDTO."""
    return LearningEventDTO(
        id=event.id,
        brand_id=event.brand_id,
        signal_type=LearningSignalType(event.signal_type),
        pattern_id=event.pattern_id,
        opportunity_id=event.opportunity_id,
        variant_id=event.variant_id,
        payload=event.payload or {},
        derived_from=[UUID(uid) for uid in (event.derived_from or [])],
        effective_at=event.effective_at,
        created_at=event.created_at,
    )


def get_learning_events_for_brand(
    brand_id: UUID,
    limit: int = 100,
) -> list[LearningEventDTO]:
    """
    Get recent learning events for a brand.

    Args:
        brand_id: UUID of the brand
        limit: Maximum number of events to return

    Returns:
        List of LearningEventDTOs
    """
    events = LearningEvent.objects.filter(
        brand_id=brand_id,
    ).order_by("-effective_at")[:limit]

    return [_learning_event_to_dto(e) for e in events]
