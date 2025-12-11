"""
Learning Service.

PR-3: Service Layer + Engines Layer Skeleton.

Provides learning summary for brand context.

Per PR-map-and-standards §PR-3 4.7.
"""

from uuid import UUID

from kairo.hero.dto import LearningSummaryDTO
from kairo.hero.engines import learning_engine


def get_learning_summary(brand_id: UUID) -> LearningSummaryDTO:
    """
    Get learning summary for a brand.

    Just calls learning_engine.summarize_learning_for_brand and returns
    that stub.

    Real implementation (PR-4) will:
    - Aggregate actual learning data from DB
    - Compute real performance metrics

    Args:
        brand_id: UUID of the brand

    Returns:
        LearningSummaryDTO with stub learning data
    """
    return learning_engine.summarize_learning_for_brand(brand_id)
