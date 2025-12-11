"""
Today Service.

PR-3: Service Layer + Engines Layer Skeleton.

Wraps the hero "Today board" flow.

Per PR-map-and-standards §PR-3 4.2.
"""

from uuid import UUID

from kairo.hero.dto import TodayBoardDTO
from kairo.hero.engines import opportunities_engine


def get_today_board(brand_id: UUID) -> TodayBoardDTO:
    """
    Get the Today board for a brand.

    Calls opportunities_engine.generate_today_board.
    For now, no DB persistence; just passes through the engine's stub output.

    Args:
        brand_id: UUID of the brand

    Returns:
        TodayBoardDTO

    Raises:
        Brand.DoesNotExist: If brand not found (raised by engine)
    """
    return opportunities_engine.generate_today_board(brand_id)


def regenerate_today_board(brand_id: UUID) -> TodayBoardDTO:
    """
    Regenerate the Today board for a brand.

    For PR-3, this behaves identically to get_today_board since we're not
    persisting opportunities yet. In later PRs, this will:
    - Clear existing opportunities
    - Re-run the opportunities graph
    - Persist new opportunities

    Args:
        brand_id: UUID of the brand

    Returns:
        TodayBoardDTO

    Raises:
        Brand.DoesNotExist: If brand not found (raised by engine)
    """
    # PR-3: Same as get_today_board since no persistence yet
    return opportunities_engine.generate_today_board(brand_id)
