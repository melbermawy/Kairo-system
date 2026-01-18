"""
Today Service tests.

PR-3: Original tests for synchronous today board generation.
PR0: Updated to use legacy functions for backwards compatibility.

Tests verify:
- Services return DTOs that pass .model_validate
- Services call the appropriate engines
- Brand.DoesNotExist is properly raised
"""

from uuid import uuid4

import pytest

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import RegenerateResponseDTO, TodayBoardDTO
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
# GET TODAY BOARD TESTS (PR0 - State Machine Behavior)
# =============================================================================


@pytest.mark.django_db
class TestGetTodayBoard:
    """Tests for today_service.get_today_board (PR0 - read-only)."""

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

    def test_has_opportunities_empty_for_new_brand(self, brand):
        """PR0: New brand has empty opportunities (no stub generation)."""
        result = today_service.get_today_board(brand.id)

        assert isinstance(result.opportunities, list)
        # PR0: No stub generation, so new brand has empty opportunities
        assert len(result.opportunities) == 0

    def test_has_meta_with_state(self, brand):
        """PR0: Board includes metadata with state machine."""
        result = today_service.get_today_board(brand.id)

        assert result.meta is not None
        assert result.meta.generated_at is not None
        assert result.meta.source == "hero_f1_v2"  # PR0 updated source
        assert result.meta.state == TodayBoardState.NOT_GENERATED_YET

    def test_raises_on_missing_brand(self, db):
        """Raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.get_today_board(fake_id)


# =============================================================================
# REGENERATE TODAY BOARD TESTS (PR0 - Async Pattern)
# =============================================================================


@pytest.mark.django_db
class TestRegenerateTodayBoard:
    """Tests for today_service.regenerate_today_board (PR0 - async pattern)."""

    def test_returns_regenerate_response_dto(self, brand):
        """PR0: Service returns a RegenerateResponseDTO."""
        result = today_service.regenerate_today_board(brand.id)

        assert isinstance(result, RegenerateResponseDTO)

    def test_dto_validates(self, brand):
        """Returned DTO passes model_validate."""
        result = today_service.regenerate_today_board(brand.id)

        # Should not raise
        validated = RegenerateResponseDTO.model_validate(result.model_dump())
        assert validated.job_id is not None

    def test_has_job_id(self, brand):
        """PR0: Response has job_id."""
        result = today_service.regenerate_today_board(brand.id)

        assert result.job_id is not None
        assert len(result.job_id) > 0

    def test_has_poll_url(self, brand):
        """PR0: Response has poll_url containing brand_id."""
        result = today_service.regenerate_today_board(brand.id)

        assert result.poll_url is not None
        assert str(brand.id) in result.poll_url

    def test_raises_on_missing_brand(self, db):
        """Raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.regenerate_today_board(fake_id)


# =============================================================================
# LEGACY REGENERATE TESTS (PR0 - Backwards Compatibility)
# =============================================================================


@pytest.mark.django_db
class TestRegenerateTodayBoardLegacy:
    """Tests for today_service.regenerate_today_board_legacy (backwards compat)."""

    def test_returns_today_board_dto(self, brand):
        """Legacy service returns a valid TodayBoardDTO."""
        result = today_service.regenerate_today_board_legacy(brand.id)

        assert isinstance(result, TodayBoardDTO)

    def test_dto_validates(self, brand):
        """Returned DTO passes model_validate."""
        result = today_service.regenerate_today_board_legacy(brand.id)

        # Should not raise
        validated = TodayBoardDTO.model_validate(result.model_dump())
        assert validated.brand_id == brand.id

    def test_brand_id_matches(self, brand):
        """Returned board has correct brand_id."""
        result = today_service.regenerate_today_board_legacy(brand.id)

        assert result.brand_id == brand.id

    def test_raises_on_missing_brand(self, db):
        """Raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.regenerate_today_board_legacy(fake_id)

    def test_has_opportunities(self, brand):
        """Legacy regenerate returns opportunities from engine."""
        result = today_service.regenerate_today_board_legacy(brand.id)

        # Legacy path still uses the old engine which generates stubs
        assert isinstance(result.opportunities, list)
        # Note: The old engine generates stub opportunities
        assert len(result.opportunities) > 0
