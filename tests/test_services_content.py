"""
Content Services tests for PR-3.

Tests verify:
- content_packages_service returns DTOs that pass .model_validate
- variants_service returns DTOs that pass .model_validate
- Stub data is returned correctly
"""

from uuid import uuid4

import pytest

from kairo.core.enums import Channel, VariantStatus
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import (
    ContentPackageDTO,
    GenerateVariantsResponseDTO,
    VariantDTO,
    VariantListDTO,
)
from kairo.hero.services import content_packages_service, variants_service


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
def sample_package_id():
    """A sample package ID for testing."""
    return uuid4()


@pytest.fixture
def sample_variant_id():
    """A sample variant ID for testing."""
    return uuid4()


# =============================================================================
# CONTENT PACKAGES SERVICE TESTS
# =============================================================================


@pytest.mark.django_db
class TestContentPackagesService:
    """Tests for content_packages_service."""

    def test_get_package_returns_dto(self, sample_package_id):
        """Service returns ContentPackageDTO."""
        result = content_packages_service.get_package(sample_package_id)

        assert isinstance(result, ContentPackageDTO)

    def test_get_package_dto_validates(self, sample_package_id):
        """Returned DTO passes model_validate."""
        result = content_packages_service.get_package(sample_package_id)

        # Should not raise
        validated = ContentPackageDTO.model_validate(result.model_dump())
        assert validated.id == sample_package_id

    def test_get_package_has_required_fields(self, sample_package_id):
        """Package DTO has all required fields."""
        result = content_packages_service.get_package(sample_package_id)

        assert result.id is not None
        assert result.brand_id is not None
        assert result.title is not None
        assert result.status is not None
        assert result.channels is not None
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_get_package_id_matches_request(self, sample_package_id):
        """Returned package has the requested ID."""
        result = content_packages_service.get_package(sample_package_id)

        assert result.id == sample_package_id


# =============================================================================
# VARIANTS SERVICE - GENERATE TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantsServiceGenerate:
    """Tests for variants_service.generate_variants_for_package."""

    def test_returns_generate_variants_response_dto(self, sample_package_id):
        """Service returns GenerateVariantsResponseDTO."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        assert isinstance(result, GenerateVariantsResponseDTO)

    def test_dto_validates(self, sample_package_id):
        """Returned DTO passes model_validate."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        # Should not raise
        validated = GenerateVariantsResponseDTO.model_validate(result.model_dump())
        assert validated.status == "generated"

    def test_status_is_generated(self, sample_package_id):
        """Response status is 'generated'."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        assert result.status == "generated"

    def test_package_id_matches(self, sample_package_id):
        """Response has correct package_id."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        assert result.package_id == sample_package_id

    def test_has_variants_list(self, sample_package_id):
        """Response includes variants list."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        assert isinstance(result.variants, list)
        assert len(result.variants) > 0

    def test_count_matches_variants(self, sample_package_id):
        """Count matches actual variants length."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        assert result.count == len(result.variants)

    def test_variants_have_body(self, sample_package_id):
        """All variants have non-empty body."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        for variant in result.variants:
            assert variant.body, "Variant should have body content"

    def test_variants_have_valid_channels(self, sample_package_id):
        """Variants have valid channel values."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        for variant in result.variants:
            assert isinstance(variant.channel, Channel)

    def test_variants_are_draft_status(self, sample_package_id):
        """All variants are in draft status."""
        result = variants_service.generate_variants_for_package(sample_package_id)

        for variant in result.variants:
            assert variant.status == VariantStatus.DRAFT


# =============================================================================
# VARIANTS SERVICE - LIST TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantsServiceList:
    """Tests for variants_service.list_variants_for_package."""

    def test_returns_variant_list_dto(self, sample_package_id):
        """Service returns VariantListDTO."""
        result = variants_service.list_variants_for_package(sample_package_id)

        assert isinstance(result, VariantListDTO)

    def test_dto_validates(self, sample_package_id):
        """Returned DTO passes model_validate."""
        result = variants_service.list_variants_for_package(sample_package_id)

        # Should not raise
        validated = VariantListDTO.model_validate(result.model_dump())
        assert validated.package_id == sample_package_id

    def test_package_id_matches(self, sample_package_id):
        """Response has correct package_id."""
        result = variants_service.list_variants_for_package(sample_package_id)

        assert result.package_id == sample_package_id

    def test_has_variants_list(self, sample_package_id):
        """Response includes variants list."""
        result = variants_service.list_variants_for_package(sample_package_id)

        assert isinstance(result.variants, list)

    def test_count_matches_variants(self, sample_package_id):
        """Count matches actual variants length."""
        result = variants_service.list_variants_for_package(sample_package_id)

        assert result.count == len(result.variants)


# =============================================================================
# VARIANTS SERVICE - UPDATE TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantsServiceUpdate:
    """Tests for variants_service.update_variant."""

    def test_returns_variant_dto(self, sample_variant_id):
        """Service returns VariantDTO."""
        result = variants_service.update_variant(
            sample_variant_id, {"body": "New body"}
        )

        assert isinstance(result, VariantDTO)

    def test_dto_validates(self, sample_variant_id):
        """Returned DTO passes model_validate."""
        result = variants_service.update_variant(
            sample_variant_id, {"body": "New body"}
        )

        # Should not raise
        validated = VariantDTO.model_validate(result.model_dump())
        assert validated.id == sample_variant_id

    def test_body_updated(self, sample_variant_id):
        """Body is updated in response."""
        new_body = "Updated variant body text"

        result = variants_service.update_variant(
            sample_variant_id, {"body": new_body}
        )

        assert result.body == new_body

    def test_status_updated(self, sample_variant_id):
        """Status is updated in response."""
        result = variants_service.update_variant(
            sample_variant_id, {"status": "edited"}
        )

        assert result.status == VariantStatus.EDITED

    def test_call_to_action_updated(self, sample_variant_id):
        """Call to action is updated in response."""
        new_cta = "Click here!"

        result = variants_service.update_variant(
            sample_variant_id, {"call_to_action": new_cta}
        )

        assert result.call_to_action == new_cta

    def test_partial_update(self, sample_variant_id):
        """Partial update only changes specified fields."""
        # Only update body
        result = variants_service.update_variant(
            sample_variant_id, {"body": "Only body changed"}
        )

        assert result.body == "Only body changed"
        # Other fields should still be present
        assert result.id == sample_variant_id
        assert result.channel is not None

    def test_empty_payload_returns_variant(self, sample_variant_id):
        """Empty payload still returns valid variant."""
        result = variants_service.update_variant(sample_variant_id, {})

        assert isinstance(result, VariantDTO)
        assert result.id == sample_variant_id
