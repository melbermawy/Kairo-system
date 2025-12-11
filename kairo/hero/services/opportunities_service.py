"""
Opportunities Service.

PR-3: Service Layer + Engines Layer Skeleton.
PR-6: Added RunContext construction + propagation.

Handles package creation from opportunities (F2_package flow).

Per PR-map-and-standards §PR-3 4.3 and §PR-6.
"""

from uuid import UUID

from kairo.hero.dto import CreatePackageResponseDTO
from kairo.hero.engines import content_engine
from kairo.hero.run_context import RunContext, create_run_context


def create_package_for_opportunity(
    brand_id: UUID,
    opportunity_id: UUID,
    ctx: RunContext | None = None,
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

    PR-6: Constructs RunContext if not provided (for F2_package flow, api trigger).

    Args:
        brand_id: UUID of the brand
        opportunity_id: UUID of the opportunity
        ctx: Optional RunContext. If None, creates one with trigger_source="api"

    Returns:
        CreatePackageResponseDTO with stub package
    """
    if ctx is None:
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F2_package",
            trigger_source="api",
        )

    # Call content engine to create stub package
    package = content_engine.create_package_from_opportunity(ctx, opportunity_id)

    # Convert to DTO
    package_dto = content_engine.package_to_dto(package)

    return CreatePackageResponseDTO(
        status="created",
        package=package_dto,
    )
