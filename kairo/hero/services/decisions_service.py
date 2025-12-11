"""
Decisions Service.

PR-3: Service Layer + Engines Layer Skeleton.

Handles recording user decisions on opportunities, packages, and variants.

Per PR-map-and-standards §PR-3 4.6.

NOTE: PR-3 has NO DB writes. Real side effects (ExecutionEvent, LearningEvent)
land in PR-4.
"""

from datetime import datetime, timezone
from uuid import UUID

from kairo.hero.dto import DecisionRequestDTO, DecisionResponseDTO


def record_opportunity_decision(
    brand_id: UUID,
    opportunity_id: UUID,
    decision: DecisionRequestDTO,
) -> DecisionResponseDTO:
    """
    Record a user decision on an opportunity.

    For PR-3:
    - No DB writes yet
    - Returns deterministic DecisionResponseDTO that echoes back the decision

    Real implementation (PR-4) will:
    - Create ExecutionEvent record
    - Update opportunity state (pin, snooze, etc.)
    - Trigger learning event creation

    Args:
        brand_id: UUID of the brand
        opportunity_id: UUID of the opportunity
        decision: DecisionRequestDTO with decision details

    Returns:
        DecisionResponseDTO with echoed decision
    """
    return DecisionResponseDTO(
        status="accepted",
        decision_type=decision.decision_type,
        object_type="opportunity",
        object_id=opportunity_id,
        recorded_at=datetime.now(timezone.utc),
    )


def record_package_decision(
    brand_id: UUID,
    package_id: UUID,
    decision: DecisionRequestDTO,
) -> DecisionResponseDTO:
    """
    Record a user decision on a package.

    For PR-3:
    - No DB writes yet
    - Returns deterministic DecisionResponseDTO that echoes back the decision

    Real implementation (PR-4) will:
    - Create ExecutionEvent record
    - Update package status
    - Trigger learning event creation

    Args:
        brand_id: UUID of the brand
        package_id: UUID of the package
        decision: DecisionRequestDTO with decision details

    Returns:
        DecisionResponseDTO with echoed decision
    """
    return DecisionResponseDTO(
        status="accepted",
        decision_type=decision.decision_type,
        object_type="package",
        object_id=package_id,
        recorded_at=datetime.now(timezone.utc),
    )


def record_variant_decision(
    brand_id: UUID,
    variant_id: UUID,
    decision: DecisionRequestDTO,
) -> DecisionResponseDTO:
    """
    Record a user decision on a variant.

    For PR-3:
    - No DB writes yet
    - Returns deterministic DecisionResponseDTO that echoes back the decision

    Real implementation (PR-4) will:
    - Create ExecutionEvent record
    - Update variant status
    - Trigger learning event creation

    Args:
        brand_id: UUID of the brand
        variant_id: UUID of the variant
        decision: DecisionRequestDTO with decision details

    Returns:
        DecisionResponseDTO with echoed decision
    """
    return DecisionResponseDTO(
        status="accepted",
        decision_type=decision.decision_type,
        object_type="variant",
        object_id=variant_id,
        recorded_at=datetime.now(timezone.utc),
    )
