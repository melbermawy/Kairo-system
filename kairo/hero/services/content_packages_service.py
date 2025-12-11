"""
Content Packages Service.

PR-3: Service Layer + Engines Layer Skeleton.

Handles content package retrieval.

Per PR-map-and-standards §PR-3 4.4.
"""

from datetime import datetime, timezone
from uuid import UUID

from kairo.core.enums import Channel, CreatedVia, PackageStatus
from kairo.hero.dto import ContentPackageDTO


def get_package(package_id: UUID) -> ContentPackageDTO:
    """
    Get a content package by ID.

    For PR-3, creates a fake ContentPackageDTO that matches the stubs
    used in content_engine. Makes it deterministic based on package_id
    so tests can assert something.

    Real implementation (later PRs) will:
    - Query DB for actual package
    - Handle not found errors

    Args:
        package_id: UUID of the package

    Returns:
        ContentPackageDTO with stub data
    """
    now = datetime.now(timezone.utc)

    # Deterministic stub brand ID
    stub_brand_id = UUID("12345678-1234-5678-1234-567812345678")

    return ContentPackageDTO(
        id=package_id,
        brand_id=stub_brand_id,
        title=f"Package {str(package_id)[:8]}",
        status=PackageStatus.DRAFT,
        origin_opportunity_id=UUID("00000000-0000-0000-0000-000000000000"),
        persona_id=None,
        pillar_id=None,
        channels=[Channel.LINKEDIN, Channel.X],
        planned_publish_start=None,
        planned_publish_end=None,
        owner_user_id=None,
        notes="PR-3 stub package",
        created_via=CreatedVia.AI_SUGGESTED,
        created_at=now,
        updated_at=now,
    )
