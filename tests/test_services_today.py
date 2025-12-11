"""
Today Service tests for PR-3.

Tests verify:
- Services return DTOs that pass .model_validate
- Services call the appropriate engines
- Brand.DoesNotExist is properly raised
"""

from uuid import uuid4

import pytest

from kairo.core.models import Brand, Tenant
from kairo.hero.dto import TodayBoardDTO
from kairo.hero.services import today_service


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="Today Service Test Brand",
        positioning="Testing today service",
    )


# =============================================================================
# GET TODAY BOARD TESTS
# =============================================================================


@pytest.mark.django_db
class TestGetTodayBoard:
    """Tests for today_service.get_today_board."""

    def test_returns_today_board_dto(self, brand):
        """Service returns a valid TodayBoardDTO."""
        result = today_service.get_today_board(brand.id)

        assert isinstance(result, TodayBoardDTO)

    def test_dto_validates(self, brand):
        """Returned DTO passes model_validate."""
        result = today_service.get_today_board(brand.id)

        # Should not raise
        validated = TodayBoardDTO.model_validate(result.model_dump())
        assert validated.brand_id == brand.id

    def test_brand_id_matches(self, brand):
        """Returned board has correct brand_id."""
        result = today_service.get_today_board(brand.id)

        assert result.brand_id == brand.id

    def test_has_snapshot(self, brand):
        """Board includes brand snapshot."""
        result = today_service.get_today_board(brand.id)

        assert result.snapshot is not None
        assert result.snapshot.brand_id == brand.id
        assert result.snapshot.brand_name == brand.name

    def test_has_opportunities(self, brand):
        """Board includes opportunities list."""
        result = today_service.get_today_board(brand.id)

        assert isinstance(result.opportunities, list)
        assert len(result.opportunities) > 0

    def test_has_meta(self, brand):
        """Board includes metadata."""
        result = today_service.get_today_board(brand.id)

        assert result.meta is not None
        assert result.meta.generated_at is not None
        assert result.meta.source == "hero_f1"

    def test_raises_on_missing_brand(self, db):
        """Raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.get_today_board(fake_id)


# =============================================================================
# REGENERATE TODAY BOARD TESTS
# =============================================================================


@pytest.mark.django_db
class TestRegenerateTodayBoard:
    """Tests for today_service.regenerate_today_board."""

    def test_returns_today_board_dto(self, brand):
        """Service returns a valid TodayBoardDTO."""
        result = today_service.regenerate_today_board(brand.id)

        assert isinstance(result, TodayBoardDTO)

    def test_dto_validates(self, brand):
        """Returned DTO passes model_validate."""
        result = today_service.regenerate_today_board(brand.id)

        # Should not raise
        validated = TodayBoardDTO.model_validate(result.model_dump())
        assert validated.brand_id == brand.id

    def test_brand_id_matches(self, brand):
        """Returned board has correct brand_id."""
        result = today_service.regenerate_today_board(brand.id)

        assert result.brand_id == brand.id

    def test_raises_on_missing_brand(self, db):
        """Raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.regenerate_today_board(fake_id)

    def test_same_as_get_for_pr3(self, brand):
        """PR-3: regenerate behaves same as get (no persistence)."""
        get_result = today_service.get_today_board(brand.id)
        regenerate_result = today_service.regenerate_today_board(brand.id)

        # Same number of opportunities
        assert len(get_result.opportunities) == len(regenerate_result.opportunities)

        # Same opportunity IDs (deterministic stubs)
        get_ids = {opp.id for opp in get_result.opportunities}
        regen_ids = {opp.id for opp in regenerate_result.opportunities}
        assert get_ids == regen_ids
