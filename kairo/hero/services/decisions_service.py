"""
Decisions Service.

PR-4: Decisions + Learning Pipeline (Deterministic, No LLM).

Handles recording user decisions on opportunities, packages, and variants.
All state-changing actions are wrapped in transaction.atomic() blocks.

Per PRD-1 §4.1.5 and PR-map-and-standards §PR-4:
- Primary mutation + ExecutionEvent must be in same transaction
- If anything fails, neither is committed
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from django.db import transaction

from kairo.core.enums import (
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    PackageStatus,
    VariantStatus,
)
from kairo.core.models import (
    ContentPackage,
    ExecutionEvent,
    Opportunity,
    Variant,
)
from kairo.hero.dto import DecisionRequestDTO, DecisionResponseDTO

logger = logging.getLogger(__name__)


class DecisionError(Exception):
    """Base exception for decision service errors."""

    pass


class ObjectNotFoundError(DecisionError):
    """Raised when target object is not found."""

    pass


class InvalidDecisionError(DecisionError):
    """Raised when decision is invalid for the object's current state."""

    pass


def record_opportunity_decision(
    brand_id: UUID,
    opportunity_id: UUID,
    decision: DecisionRequestDTO,
) -> DecisionResponseDTO:
    """
    Record a user decision on an opportunity.

    Applies state changes atomically:
    - OPPORTUNITY_PINNED: sets is_pinned=True, is_snoozed=False
    - OPPORTUNITY_SNOOZED: sets is_snoozed=True, is_pinned=False
    - OPPORTUNITY_IGNORED: sets is_snoozed=True (treated as ignore/dismiss)

    NOTE: ExecutionEvent requires a variant FK which opportunities don't have.
    The decision is logged in the opportunity's metadata field instead.
    Full ExecutionEvent support for opportunities requires a schema change
    to make the variant FK nullable or add a polymorphic subject FK.

    Args:
        brand_id: UUID of the brand
        opportunity_id: UUID of the opportunity
        decision: DecisionRequestDTO with decision details

    Returns:
        DecisionResponseDTO with updated state

    Raises:
        ObjectNotFoundError: If opportunity not found or doesn't belong to brand
    """
    now = datetime.now(timezone.utc)

    with transaction.atomic():
        # Load opportunity with select_for_update to prevent concurrent modifications
        try:
            opportunity = Opportunity.objects.select_for_update().get(
                id=opportunity_id,
                brand_id=brand_id,
            )
        except Opportunity.DoesNotExist:
            raise ObjectNotFoundError(
                f"Opportunity {opportunity_id} not found for brand {brand_id}"
            )

        # Apply state change based on decision type
        if decision.decision_type == DecisionType.OPPORTUNITY_PINNED:
            opportunity.is_pinned = True
            opportunity.is_snoozed = False
            opportunity.snoozed_until = None
        elif decision.decision_type == DecisionType.OPPORTUNITY_SNOOZED:
            opportunity.is_snoozed = True
            opportunity.is_pinned = False
            # Could extract snooze_until from decision.metadata if provided
            opportunity.snoozed_until = decision.metadata.get("snoozed_until")
        elif decision.decision_type == DecisionType.OPPORTUNITY_IGNORED:
            opportunity.is_snoozed = True
            opportunity.is_pinned = False

        # Update last_touched_at
        opportunity.last_touched_at = now

        # Log decision in metadata (since we can't create ExecutionEvent without variant)
        decision_log = opportunity.metadata.get("decision_log", [])
        decision_log.append(
            {
                "decision_type": decision.decision_type.value,
                "reason": decision.reason,
                "recorded_at": now.isoformat(),
            }
        )
        opportunity.metadata["decision_log"] = decision_log

        opportunity.save()

        logger.info(
            "Recorded opportunity decision",
            extra={
                "brand_id": str(brand_id),
                "opportunity_id": str(opportunity_id),
                "decision_type": decision.decision_type.value,
            },
        )

    return DecisionResponseDTO(
        status="accepted",
        decision_type=decision.decision_type,
        object_type="opportunity",
        object_id=opportunity_id,
        recorded_at=now,
    )


def record_package_decision(
    brand_id: UUID,
    package_id: UUID,
    decision: DecisionRequestDTO,
) -> DecisionResponseDTO:
    """
    Record a user decision on a package.

    Applies state changes atomically:
    - PACKAGE_CREATED: no state change (just logs creation event)
    - PACKAGE_APPROVED: sets status to IN_REVIEW or SCHEDULED based on context

    Creates an ExecutionEvent using the first variant of the package (if exists).
    If no variants exist, logs the decision in package metadata.

    Args:
        brand_id: UUID of the brand
        package_id: UUID of the package
        decision: DecisionRequestDTO with decision details

    Returns:
        DecisionResponseDTO with updated state

    Raises:
        ObjectNotFoundError: If package not found or doesn't belong to brand
    """
    now = datetime.now(timezone.utc)

    with transaction.atomic():
        # Load package with select_for_update
        try:
            package = ContentPackage.objects.select_for_update().get(
                id=package_id,
                brand_id=brand_id,
            )
        except ContentPackage.DoesNotExist:
            raise ObjectNotFoundError(
                f"Package {package_id} not found for brand {brand_id}"
            )

        # Apply state change based on decision type
        if decision.decision_type == DecisionType.PACKAGE_APPROVED:
            # Move from draft to in_review (or scheduled if ready)
            if package.status == PackageStatus.DRAFT:
                package.status = PackageStatus.IN_REVIEW
            elif package.status == PackageStatus.IN_REVIEW:
                package.status = PackageStatus.SCHEDULED
        # PACKAGE_CREATED doesn't change state, just logs the event

        package.save()

        # Try to create ExecutionEvent using first variant
        first_variant = package.variants.first()
        if first_variant:
            ExecutionEvent.objects.create(
                brand_id=brand_id,
                variant=first_variant,
                channel=first_variant.channel,
                event_type=ExecutionEventType.CLICK,  # Using CLICK as proxy for user action
                decision_type=decision.decision_type,
                event_value=decision.reason or "",
                source=ExecutionSource.MANUAL_ENTRY,
                occurred_at=now,
                received_at=now,
                metadata={
                    "object_type": "package",
                    "object_id": str(package_id),
                    "reason": decision.reason,
                },
            )
        else:
            # Log in package metadata if no variants
            decision_log = package.metrics_snapshot.get("decision_log", [])
            decision_log.append(
                {
                    "decision_type": decision.decision_type.value,
                    "reason": decision.reason,
                    "recorded_at": now.isoformat(),
                }
            )
            package.metrics_snapshot["decision_log"] = decision_log
            package.save()

        logger.info(
            "Recorded package decision",
            extra={
                "brand_id": str(brand_id),
                "package_id": str(package_id),
                "decision_type": decision.decision_type.value,
                "has_execution_event": first_variant is not None,
            },
        )

    return DecisionResponseDTO(
        status="accepted",
        decision_type=decision.decision_type,
        object_type="package",
        object_id=package_id,
        recorded_at=now,
    )


def record_variant_decision(
    brand_id: UUID,
    variant_id: UUID,
    decision: DecisionRequestDTO,
) -> DecisionResponseDTO:
    """
    Record a user decision on a variant.

    Applies state changes atomically:
    - VARIANT_EDITED: sets status to EDITED
    - VARIANT_APPROVED: sets status to APPROVED
    - VARIANT_REJECTED: sets status to REJECTED

    Creates an ExecutionEvent for learning pipeline consumption.

    Args:
        brand_id: UUID of the brand
        variant_id: UUID of the variant
        decision: DecisionRequestDTO with decision details

    Returns:
        DecisionResponseDTO with updated state

    Raises:
        ObjectNotFoundError: If variant not found or doesn't belong to brand
    """
    now = datetime.now(timezone.utc)

    with transaction.atomic():
        # Load variant with select_for_update
        try:
            variant = Variant.objects.select_for_update().get(
                id=variant_id,
                brand_id=brand_id,
            )
        except Variant.DoesNotExist:
            raise ObjectNotFoundError(
                f"Variant {variant_id} not found for brand {brand_id}"
            )

        # Apply state change based on decision type
        if decision.decision_type == DecisionType.VARIANT_EDITED:
            variant.status = VariantStatus.EDITED
            # If new body is provided in metadata, update it
            if decision.metadata.get("body"):
                variant.edited_text = decision.metadata["body"]
        elif decision.decision_type == DecisionType.VARIANT_APPROVED:
            variant.status = VariantStatus.APPROVED
            # Set approved_text from edited_text or draft_text
            if variant.edited_text:
                variant.approved_text = variant.edited_text
            else:
                variant.approved_text = variant.draft_text
        elif decision.decision_type == DecisionType.VARIANT_REJECTED:
            variant.status = VariantStatus.REJECTED

        variant.save()

        # Create ExecutionEvent for learning pipeline
        ExecutionEvent.objects.create(
            brand_id=brand_id,
            variant=variant,
            channel=variant.channel,
            event_type=ExecutionEventType.CLICK,  # Using CLICK as proxy for user action
            decision_type=decision.decision_type,
            event_value=decision.reason or "",
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=now,
            received_at=now,
            metadata={
                "object_type": "variant",
                "reason": decision.reason,
            },
        )

        logger.info(
            "Recorded variant decision",
            extra={
                "brand_id": str(brand_id),
                "variant_id": str(variant_id),
                "decision_type": decision.decision_type.value,
                "new_status": variant.status,
            },
        )

    return DecisionResponseDTO(
        status="accepted",
        decision_type=decision.decision_type,
        object_type="variant",
        object_id=variant_id,
        recorded_at=now,
    )
