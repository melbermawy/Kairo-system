"""
Opportunities Service tests for PR-3.

Tests verify:
- Services return DTOs that pass .model_validate
- Package creation from opportunity works correctly
"""

from uuid import uuid4

import pytest

from kairo.core.models import Brand, Tenant
from kairo.hero.dto import CreatePackageResponseDTO
from kairo.hero.services import opportunities_service


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
        name="Opportunities Service Test Brand",
        positioning="Testing opportunities service",
    )


# =============================================================================
# CREATE PACKAGE FOR OPPORTUNITY TESTS
# =============================================================================


@pytest.mark.django_db
class TestCreatePackageForOpportunity:
    """Tests for opportunities_service.create_package_for_opportunity."""

    def test_returns_create_package_response_dto(self, brand):
        """Service returns CreatePackageResponseDTO."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert isinstance(result, CreatePackageResponseDTO)

    def test_dto_validates(self, brand):
        """Returned DTO passes model_validate."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        # Should not raise
        validated = CreatePackageResponseDTO.model_validate(result.model_dump())
        assert validated.status == "created"

    def test_status_is_created(self, brand):
        """Response status is 'created'."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result.status == "created"

    def test_package_has_correct_brand_id(self, brand):
        """Package in response has correct brand_id."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result.package.brand_id == brand.id

    def test_package_has_origin_opportunity_id(self, brand):
        """Package references source opportunity."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result.package.origin_opportunity_id == opportunity_id

    def test_package_has_title(self, brand):
        """Package has a title."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result.package.title is not None
        assert len(result.package.title) > 0

    def test_package_has_draft_status(self, brand):
        """Package starts in draft status."""
        from kairo.core.enums import PackageStatus

        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result.package.status == PackageStatus.DRAFT

    def test_package_has_channels(self, brand):
        """Package has target channels."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert len(result.package.channels) >= 1

    def test_package_has_timestamps(self, brand):
        """Package has created_at and updated_at."""
        opportunity_id = uuid4()

        result = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result.package.created_at is not None
        assert result.package.updated_at is not None

    def test_deterministic_package_id(self, brand):
        """Same inputs produce same package ID."""
        opportunity_id = uuid4()

        result1 = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )
        result2 = opportunities_service.create_package_for_opportunity(
            brand.id, opportunity_id
        )

        assert result1.package.id == result2.package.id

    def test_different_opportunities_different_packages(self, brand):
        """Different opportunities produce different package IDs."""
        opp1 = uuid4()
        opp2 = uuid4()

        result1 = opportunities_service.create_package_for_opportunity(brand.id, opp1)
        result2 = opportunities_service.create_package_for_opportunity(brand.id, opp2)

        assert result1.package.id != result2.package.id
