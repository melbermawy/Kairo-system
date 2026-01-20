"""
Opportunities Service tests for PR-3 (updated for PR-9).

Tests verify:
- Services return DTOs that pass .model_validate
- Package creation from opportunity works correctly

PR-9 update: Now requires real opportunity records and mocks the package graph.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from kairo.core.enums import Channel, CreatedVia, OpportunityType
from kairo.core.models import Brand, Opportunity, Tenant
from kairo.hero.dto import ContentPackageDraftDTO, CreatePackageResponseDTO
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


@pytest.fixture
def opportunity(db, brand):
    """Create a test opportunity."""
    return Opportunity.objects.create(
        brand=brand,
        title="Test Opportunity for Service",
        angle="Testing service functionality",
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=80.0,
        created_via=CreatedVia.AI_SUGGESTED,
        metadata={
            "why_now": "Current market trends show high engagement with this topic. Testing service functionality.",
            "evidence_ids": [],
        },
    )


@pytest.fixture
def mock_package_draft():
    """Mock package draft for deterministic testing."""
    return ContentPackageDraftDTO(
        title="Test Package from Service",
        thesis="A comprehensive test thesis about marketing strategies and best practices.",
        summary="This package covers various marketing topics with practical examples.",
        primary_channel=Channel.LINKEDIN,
        channels=[Channel.LINKEDIN, Channel.X],
        cta="Learn more",
        is_valid=True,
        rejection_reasons=[],
        package_score=12.0,
        quality_band="board_ready",
    )


# =============================================================================
# CREATE PACKAGE FOR OPPORTUNITY TESTS
# =============================================================================


@pytest.mark.django_db
class TestCreatePackageForOpportunity:
    """Tests for opportunities_service.create_package_for_opportunity."""

    def test_returns_create_package_response_dto(self, brand, opportunity, mock_package_draft):
        """Service returns CreatePackageResponseDTO."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert isinstance(result, CreatePackageResponseDTO)

    def test_dto_validates(self, brand, opportunity, mock_package_draft):
        """Returned DTO passes model_validate."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            # Should not raise
            validated = CreatePackageResponseDTO.model_validate(result.model_dump())
            assert validated.status == "created"

    def test_status_is_created(self, brand, opportunity, mock_package_draft):
        """Response status is 'created'."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result.status == "created"

    def test_package_has_correct_brand_id(self, brand, opportunity, mock_package_draft):
        """Package in response has correct brand_id."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result.package.brand_id == brand.id

    def test_package_has_origin_opportunity_id(self, brand, opportunity, mock_package_draft):
        """Package references source opportunity."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result.package.origin_opportunity_id == opportunity.id

    def test_package_has_title(self, brand, opportunity, mock_package_draft):
        """Package has a title."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result.package.title is not None
            assert len(result.package.title) > 0

    def test_package_has_draft_status(self, brand, opportunity, mock_package_draft):
        """Package starts in draft status."""
        from kairo.core.enums import PackageStatus

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result.package.status == PackageStatus.DRAFT

    def test_package_has_channels(self, brand, opportunity, mock_package_draft):
        """Package has target channels."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert len(result.package.channels) >= 1

    def test_package_has_timestamps(self, brand, opportunity, mock_package_draft):
        """Package has created_at and updated_at."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result.package.created_at is not None
            assert result.package.updated_at is not None

    def test_idempotent_package_id(self, brand, opportunity, mock_package_draft):
        """Same inputs produce same package ID (idempotency)."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result1 = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )
            result2 = opportunities_service.create_package_for_opportunity(
                brand.id, opportunity.id
            )

            assert result1.package.id == result2.package.id

    def test_different_opportunities_different_packages(self, db, brand, mock_package_draft):
        """Different opportunities produce different package IDs."""
        # Create two opportunities
        opp1 = Opportunity.objects.create(
            brand=brand,
            title="First Opportunity",
            angle="Testing first",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_via=CreatedVia.AI_SUGGESTED,
            metadata={
                "why_now": "First opportunity testing why_now field is required for package creation.",
                "evidence_ids": [],
            },
        )
        opp2 = Opportunity.objects.create(
            brand=brand,
            title="Second Opportunity",
            angle="Testing second",
            type=OpportunityType.TREND,
            primary_channel=Channel.X,
            score=75.0,
            created_via=CreatedVia.AI_SUGGESTED,
            metadata={
                "why_now": "Second opportunity testing why_now field is required for package creation.",
                "evidence_ids": [],
            },
        )

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result1 = opportunities_service.create_package_for_opportunity(brand.id, opp1.id)
            result2 = opportunities_service.create_package_for_opportunity(brand.id, opp2.id)

            assert result1.package.id != result2.package.id
