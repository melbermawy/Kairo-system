"""
Today Service.

PR-3: Service Layer + Engines Layer Skeleton.
PR-6: Added RunContext construction + propagation.

Wraps the hero "Today board" flow (F1_today).

Per PR-map-and-standards §PR-3 4.2 and §PR-6.
"""

from uuid import UUID

from kairo.hero.dto import TodayBoardDTO
from kairo.hero.engines import opportunities_engine
from kairo.hero.run_context import RunContext, create_run_context


def get_today_board(
    brand_id: UUID,
    ctx: RunContext | None = None,
) -> TodayBoardDTO:
    """
    Get the Today board for a brand.

    Calls opportunities_engine.generate_today_board.
    For now, no DB persistence; just passes through the engine's stub output.

    PR-6: Constructs RunContext if not provided (for F1_today flow, api trigger).

    Args:
        brand_id: UUID of the brand
        ctx: Optional RunContext. If None, creates one with trigger_source="api"

    Returns:
        TodayBoardDTO

    Raises:
        Brand.DoesNotExist: If brand not found (raised by engine)
    """
    if ctx is None:
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )

    return opportunities_engine.generate_today_board(ctx)


def regenerate_today_board(
    brand_id: UUID,
    ctx: RunContext | None = None,
) -> TodayBoardDTO:
    """
    Regenerate the Today board for a brand.

    For PR-3, this behaves identically to get_today_board since we're not
    persisting opportunities yet. In later PRs, this will:
    - Clear existing opportunities
    - Re-run the opportunities graph
    - Persist new opportunities

    PR-6: Constructs RunContext if not provided (for F1_today flow, api trigger).

    Args:
        brand_id: UUID of the brand
        ctx: Optional RunContext. If None, creates one with trigger_source="api"

    Returns:
        TodayBoardDTO

    Raises:
        Brand.DoesNotExist: If brand not found (raised by engine)
    """
    if ctx is None:
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )

    # PR-3: Same as get_today_board since no persistence yet
    return opportunities_engine.generate_today_board(ctx)
