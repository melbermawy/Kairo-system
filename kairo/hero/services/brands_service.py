"""
Brands Service.

PR-3: Service Layer + Engines Layer Skeleton.

Basic helpers to resolve a brand.

Per PR-map-and-standards §PR-3 4.1.
"""

from uuid import UUID

from kairo.core.models import Brand


def get_brand(brand_id: UUID) -> Brand:
    """
    Get a brand by ID.

    Args:
        brand_id: UUID of the brand

    Returns:
        Brand instance

    Raises:
        Brand.DoesNotExist: If brand not found
    """
    return Brand.objects.get(id=brand_id)
