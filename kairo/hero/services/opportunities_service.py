"""
Opportunities Service.

PR-3: Service Layer + Engines Layer Skeleton.

Handles package creation from opportunities.

Per PR-map-and-standards §PR-3 4.3.
"""

from uuid import UUID

from kairo.hero.dto import CreatePackageResponseDTO
from kairo.hero.engines import content_engine


def create_package_for_opportunity(
    brand_id: UUID,
    opportunity_id: UUID,
) -> CreatePackageResponseDTO:
    """
    Create a content package from an opportunity.

    For PR-3, does NOT read real Opportunity rows from DB.
    Just builds a fake response wrapping the stub ContentPackage from content_engine.

    Real implementation (PR-9) will:
    - Validate opportunity exists
    - Check idempotency (existing package for this opportunity?)
    - Persist ContentPackage
    - Return real package data

    Args:
        brand_id: UUID of the brand
        opportunity_id: UUID of the opportunity

    Returns:
        CreatePackageResponseDTO with stub package
    """
    # Call content engine to create stub package
    package = content_engine.create_package_from_opportunity(brand_id, opportunity_id)

    # Convert to DTO
    package_dto = content_engine.package_to_dto(package)

    return CreatePackageResponseDTO(
        status="created",
        package=package_dto,
    )
