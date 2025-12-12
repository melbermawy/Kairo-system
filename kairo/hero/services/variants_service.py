"""
Variants Service.

PR-3: Service Layer + Engines Layer Skeleton.

Handles variant generation, listing, and updates.

Per PR-map-and-standards §PR-3 4.5.
"""

from typing import Any
from uuid import UUID

from kairo.core.enums import VariantStatus
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

    Queries DB for existing variants associated with the package.

    Args:
        package_id: UUID of the package

    Returns:
        VariantListDTO with existing variants
    """
    from kairo.core.models import Variant

    # Query existing variants for this package
    variants = Variant.objects.filter(package_id=package_id).order_by("created_at")
    variant_dtos = [content_engine.variant_to_dto(v) for v in variants]

    return VariantListDTO(
        package_id=package_id,
        variants=variant_dtos,
        count=len(variant_dtos),
    )


def update_variant(variant_id: UUID, payload: dict[str, Any]) -> VariantDTO:
    """
    Update a variant's content or status.

    Queries the variant from DB, applies updates, and returns DTO.

    Args:
        variant_id: UUID of the variant
        payload: Dict with optional keys: body, call_to_action, status

    Returns:
        VariantDTO with updated fields
    """
    from kairo.core.models import Variant

    # Get the variant from DB
    variant = Variant.objects.get(id=variant_id)

    # Apply updates from payload
    if "body" in payload:
        variant.draft_text = payload["body"]

    if "call_to_action" in payload:
        # call_to_action is stored in metadata JSON field
        if variant.metadata is None:
            variant.metadata = {}
        variant.metadata["call_to_action"] = payload["call_to_action"]

    if "status" in payload:
        status = payload["status"]
        if isinstance(status, str):
            status = VariantStatus(status)
        variant.status = status

    variant.save()

    return content_engine.variant_to_dto(variant)
