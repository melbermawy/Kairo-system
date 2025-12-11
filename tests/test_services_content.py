"""
Content Services tests for PR-3 (updated for PR-9).

Tests verify:
- content_packages_service returns DTOs that pass .model_validate
- variants_service returns DTOs that pass .model_validate

PR-9 update: Now requires real DB records and mocks graphs.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from kairo.core.enums import Channel, CreatedVia, OpportunityType, PackageStatus, VariantStatus
from kairo.core.models import Brand, ContentPackage, Opportunity, Tenant, Variant
from kairo.hero.dto import (
    ContentPackageDTO,
    ContentPackageDraftDTO,
    GenerateVariantsResponseDTO,
    VariantDTO,
    VariantDraftDTO,
    VariantListDTO,
)
from kairo.hero.services import content_packages_service, variants_service
from kairo.hero.engines import content_engine


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
        name="Content Service Test Brand",
        positioning="Testing content services",
    )


@pytest.fixture
def opportunity(db, brand):
    """Create a test opportunity."""
    return Opportunity.objects.create(
        brand=brand,
        title="Test Opportunity for Content Services",
        angle="Testing content services",
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=80.0,
        created_via=CreatedVia.AI_SUGGESTED,
    )


@pytest.fixture
def package(db, brand, opportunity):
    """Create a test package."""
    return ContentPackage.objects.create(
        brand=brand,
        title="Test Package for Content Services",
        status=PackageStatus.DRAFT,
        origin_opportunity=opportunity,
        channels=[Channel.LINKEDIN.value, Channel.X.value],
        notes="Test thesis for package",
    )


@pytest.fixture
def sample_variant(db, brand, package):
    """Create a sample variant for testing."""
    return Variant.objects.create(
        brand=brand,
        package=package,
        channel=Channel.LINKEDIN,
        status=VariantStatus.DRAFT,
        draft_text="Test variant body content for LinkedIn.",
    )


@pytest.fixture
def mock_package_draft():
    """Mock package draft for deterministic testing."""
    return ContentPackageDraftDTO(
        title="Test Package from Graph",
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


@pytest.fixture
def mock_variant_drafts():
    """Mock variant drafts for deterministic testing."""
    return [
        VariantDraftDTO(
            channel=Channel.LINKEDIN,
            body="Test content for LinkedIn with multiple paragraphs and insights.",
            call_to_action="Share your thoughts",
            is_valid=True,
            rejection_reasons=[],
            variant_score=10.0,
            quality_band="publish_ready",
        ),
        VariantDraftDTO(
            channel=Channel.X,
            body="Concise X post about marketing strategies. Thread below.",
            call_to_action="Follow for more",
            is_valid=True,
            rejection_reasons=[],
            variant_score=9.0,
            quality_band="publish_ready",
        ),
    ]


# =============================================================================
# CONTENT PACKAGES SERVICE TESTS
# =============================================================================


@pytest.mark.django_db
class TestContentPackagesService:
    """Tests for content_packages_service."""

    def test_get_package_returns_dto(self, package):
        """Service returns ContentPackageDTO."""
        result = content_packages_service.get_package(package.id)

        assert isinstance(result, ContentPackageDTO)

    def test_get_package_dto_validates(self, package):
        """Returned DTO passes model_validate."""
        result = content_packages_service.get_package(package.id)

        # Should not raise
        validated = ContentPackageDTO.model_validate(result.model_dump())
        assert validated.id == package.id

    def test_get_package_has_required_fields(self, package):
        """Package DTO has all required fields."""
        result = content_packages_service.get_package(package.id)

        assert result.id is not None
        assert result.brand_id is not None
        assert result.title is not None
        assert result.status is not None
        assert result.channels is not None
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_get_package_id_matches_request(self, package):
        """Returned package has the requested ID."""
        result = content_packages_service.get_package(package.id)

        assert result.id == package.id


# =============================================================================
# VARIANTS SERVICE - GENERATE TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantsServiceGenerate:
    """Tests for variants_service.generate_variants_for_package."""

    def test_returns_generate_variants_response_dto(self, package, mock_variant_drafts):
        """Service returns GenerateVariantsResponseDTO."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            assert isinstance(result, GenerateVariantsResponseDTO)

    def test_dto_validates(self, package, mock_variant_drafts):
        """Returned DTO passes model_validate."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            # Should not raise
            validated = GenerateVariantsResponseDTO.model_validate(result.model_dump())
            assert validated.status == "generated"

    def test_status_is_generated(self, package, mock_variant_drafts):
        """Response status is 'generated'."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            assert result.status == "generated"

    def test_package_id_matches(self, package, mock_variant_drafts):
        """Response has correct package_id."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            assert result.package_id == package.id

    def test_has_variants_list(self, package, mock_variant_drafts):
        """Response includes variants list."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            assert isinstance(result.variants, list)
            assert len(result.variants) > 0

    def test_count_matches_variants(self, package, mock_variant_drafts):
        """Count matches actual variants length."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            assert result.count == len(result.variants)

    def test_variants_have_body(self, package, mock_variant_drafts):
        """All variants have non-empty body."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            for variant in result.variants:
                assert variant.body, "Variant should have body content"

    def test_variants_have_valid_channels(self, package, mock_variant_drafts):
        """Variants have valid channel values."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            for variant in result.variants:
                assert isinstance(variant.channel, Channel)

    def test_variants_are_draft_status(self, package, mock_variant_drafts):
        """All variants are in draft status."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            result = variants_service.generate_variants_for_package(package.id)

            for variant in result.variants:
                assert variant.status == VariantStatus.DRAFT


# =============================================================================
# VARIANTS SERVICE - LIST TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantsServiceList:
    """Tests for variants_service.list_variants_for_package."""

    def test_returns_variant_list_dto(self, package, sample_variant):
        """Service returns VariantListDTO."""
        result = variants_service.list_variants_for_package(package.id)

        assert isinstance(result, VariantListDTO)

    def test_dto_validates(self, package, sample_variant):
        """Returned DTO passes model_validate."""
        result = variants_service.list_variants_for_package(package.id)

        # Should not raise
        validated = VariantListDTO.model_validate(result.model_dump())
        assert validated.package_id == package.id

    def test_package_id_matches(self, package, sample_variant):
        """Response has correct package_id."""
        result = variants_service.list_variants_for_package(package.id)

        assert result.package_id == package.id

    def test_has_variants_list(self, package, sample_variant):
        """Response includes variants list."""
        result = variants_service.list_variants_for_package(package.id)

        assert isinstance(result.variants, list)

    def test_count_matches_variants(self, package, sample_variant):
        """Count matches actual variants length."""
        result = variants_service.list_variants_for_package(package.id)

        assert result.count == len(result.variants)


# =============================================================================
# VARIANTS SERVICE - UPDATE TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantsServiceUpdate:
    """Tests for variants_service.update_variant."""

    def test_returns_variant_dto(self, sample_variant):
        """Service returns VariantDTO."""
        result = variants_service.update_variant(
            sample_variant.id, {"body": "New body"}
        )

        assert isinstance(result, VariantDTO)

    def test_dto_validates(self, sample_variant):
        """Returned DTO passes model_validate."""
        result = variants_service.update_variant(
            sample_variant.id, {"body": "New body"}
        )

        # Should not raise
        validated = VariantDTO.model_validate(result.model_dump())
        assert validated.id == sample_variant.id

    def test_body_updated(self, sample_variant):
        """Body is updated in response."""
        new_body = "Updated variant body text"

        result = variants_service.update_variant(
            sample_variant.id, {"body": new_body}
        )

        assert result.body == new_body

    def test_status_updated(self, sample_variant):
        """Status is updated in response."""
        result = variants_service.update_variant(
            sample_variant.id, {"status": "edited"}
        )

        assert result.status == VariantStatus.EDITED

    def test_call_to_action_updated(self, sample_variant):
        """Call to action is updated in response."""
        new_cta = "Click here!"

        result = variants_service.update_variant(
            sample_variant.id, {"call_to_action": new_cta}
        )

        assert result.call_to_action == new_cta

    def test_partial_update(self, sample_variant):
        """Partial update only changes specified fields."""
        # Only update body
        result = variants_service.update_variant(
            sample_variant.id, {"body": "Only body changed"}
        )

        assert result.body == "Only body changed"
        # Other fields should still be present
        assert result.id == sample_variant.id
        assert result.channel is not None

    def test_empty_payload_returns_variant(self, sample_variant):
        """Empty payload still returns valid variant."""
        result = variants_service.update_variant(sample_variant.id, {})

        assert isinstance(result, VariantDTO)
        assert result.id == sample_variant.id
