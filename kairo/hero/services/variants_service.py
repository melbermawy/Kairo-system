"""
Variants Service.

PR-3: Service Layer + Engines Layer Skeleton.

Handles variant generation, listing, and updates.

Per PR-map-and-standards §PR-3 4.5.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from kairo.core.enums import Channel, VariantStatus
from kairo.hero.dto import (
    GenerateVariantsResponseDTO,
    VariantDTO,
    VariantListDTO,
)
from kairo.hero.engines import content_engine


def generate_variants_for_package(package_id: UUID) -> GenerateVariantsResponseDTO:
    """
    Generate content variants for a package.

    Calls content_engine.generate_variants_for_package and wraps
    the result in GenerateVariantsResponseDTO.

    Args:
        package_id: UUID of the package

    Returns:
        GenerateVariantsResponseDTO with generated variants
    """
    # Call content engine to generate stub variants
    variants = content_engine.generate_variants_for_package(package_id)

    # Convert to DTOs
    variant_dtos = [content_engine.variant_to_dto(v) for v in variants]

    return GenerateVariantsResponseDTO(
        status="generated",
        package_id=package_id,
        variants=variant_dtos,
        count=len(variant_dtos),
    )


def list_variants_for_package(package_id: UUID) -> VariantListDTO:
    """
    List all variants for a package.

    For PR-3, returns a deterministic list of 2 stub variants.

    Real implementation (later PRs) will:
    - Query DB for actual variants

    Args:
        package_id: UUID of the package

    Returns:
        VariantListDTO with stub variants
    """
    # Use content engine to generate consistent stub variants
    variants = content_engine.generate_variants_for_package(package_id)
    variant_dtos = [content_engine.variant_to_dto(v) for v in variants]

    return VariantListDTO(
        package_id=package_id,
        variants=variant_dtos,
        count=len(variant_dtos),
    )


def update_variant(variant_id: UUID, payload: dict[str, Any]) -> VariantDTO:
    """
    Update a variant's content or status.

    For PR-3, ignores most payload fields and returns a stub VariantDTO
    that shows the "updated" variant (echoing back text from payload).

    Real implementation (later PRs) will:
    - Validate variant exists
    - Apply updates to DB
    - Handle workflow transitions

    Args:
        variant_id: UUID of the variant
        payload: Dict with optional keys: body, call_to_action, status

    Returns:
        VariantDTO with updated fields
    """
    now = datetime.now(timezone.utc)

    # Deterministic stub IDs
    stub_brand_id = UUID("12345678-1234-5678-1234-567812345678")
    stub_package_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

    # Build stub variant, applying payload updates
    body = payload.get("body", "Default variant body")
    call_to_action = payload.get("call_to_action")
    status = payload.get("status", VariantStatus.DRAFT)

    # Convert status if it's a string
    if isinstance(status, str):
        status = VariantStatus(status)

    return VariantDTO(
        id=variant_id,
        package_id=stub_package_id,
        brand_id=stub_brand_id,
        channel=Channel.LINKEDIN,
        status=status,
        pattern_template_id=None,
        body=body,
        call_to_action=call_to_action,
        generated_by_model="stub-pr3",
        proposed_at=now,
        scheduled_publish_at=None,
        published_at=None,
        eval_score=None,
        eval_notes=None,
        created_at=now,
        updated_at=now,
    )
