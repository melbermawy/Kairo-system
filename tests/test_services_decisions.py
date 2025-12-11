"""
Decisions Service tests for PR-3.

Tests verify:
- Services return DecisionResponseDTO that pass .model_validate
- Decision type is echoed correctly
- Object type and ID are correct
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from kairo.core.enums import DecisionType
from kairo.hero.dto import DecisionRequestDTO, DecisionResponseDTO
from kairo.hero.services import decisions_service


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_brand_id():
    """A sample brand ID for testing."""
    return uuid4()


@pytest.fixture
def sample_opportunity_id():
    """A sample opportunity ID for testing."""
    return uuid4()


@pytest.fixture
def sample_package_id():
    """A sample package ID for testing."""
    return uuid4()


@pytest.fixture
def sample_variant_id():
    """A sample variant ID for testing."""
    return uuid4()


# =============================================================================
# OPPORTUNITY DECISION TESTS
# =============================================================================


@pytest.mark.django_db
class TestOpportunityDecision:
    """Tests for decisions_service.record_opportunity_decision."""

    def test_returns_decision_response_dto(
        self, sample_brand_id, sample_opportunity_id
    ):
        """Service returns DecisionResponseDTO."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            reason="High priority",
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        assert isinstance(result, DecisionResponseDTO)

    def test_dto_validates(self, sample_brand_id, sample_opportunity_id):
        """Returned DTO passes model_validate."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        # Should not raise
        validated = DecisionResponseDTO.model_validate(result.model_dump())
        assert validated.status == "accepted"

    def test_status_is_accepted(self, sample_brand_id, sample_opportunity_id):
        """Response status is 'accepted'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        assert result.status == "accepted"

    def test_decision_type_echoed(self, sample_brand_id, sample_opportunity_id):
        """Decision type is echoed in response."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_SNOOZED,
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        assert result.decision_type == DecisionType.OPPORTUNITY_SNOOZED

    def test_object_type_is_opportunity(self, sample_brand_id, sample_opportunity_id):
        """Object type is 'opportunity'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        assert result.object_type == "opportunity"

    def test_object_id_matches(self, sample_brand_id, sample_opportunity_id):
        """Object ID matches opportunity ID."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        assert result.object_id == sample_opportunity_id

    def test_has_recorded_at(self, sample_brand_id, sample_opportunity_id):
        """Response has recorded_at timestamp."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            sample_brand_id, sample_opportunity_id, decision
        )

        assert result.recorded_at is not None
        assert isinstance(result.recorded_at, datetime)


# =============================================================================
# PACKAGE DECISION TESTS
# =============================================================================


@pytest.mark.django_db
class TestPackageDecision:
    """Tests for decisions_service.record_package_decision."""

    def test_returns_decision_response_dto(self, sample_brand_id, sample_package_id):
        """Service returns DecisionResponseDTO."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            sample_brand_id, sample_package_id, decision
        )

        assert isinstance(result, DecisionResponseDTO)

    def test_dto_validates(self, sample_brand_id, sample_package_id):
        """Returned DTO passes model_validate."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            sample_brand_id, sample_package_id, decision
        )

        # Should not raise
        validated = DecisionResponseDTO.model_validate(result.model_dump())
        assert validated.object_type == "package"

    def test_decision_type_echoed(self, sample_brand_id, sample_package_id):
        """Decision type is echoed in response."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_CREATED,
        )

        result = decisions_service.record_package_decision(
            sample_brand_id, sample_package_id, decision
        )

        assert result.decision_type == DecisionType.PACKAGE_CREATED

    def test_object_type_is_package(self, sample_brand_id, sample_package_id):
        """Object type is 'package'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            sample_brand_id, sample_package_id, decision
        )

        assert result.object_type == "package"

    def test_object_id_matches(self, sample_brand_id, sample_package_id):
        """Object ID matches package ID."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            sample_brand_id, sample_package_id, decision
        )

        assert result.object_id == sample_package_id


# =============================================================================
# VARIANT DECISION TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantDecision:
    """Tests for decisions_service.record_variant_decision."""

    def test_returns_decision_response_dto(self, sample_brand_id, sample_variant_id):
        """Service returns DecisionResponseDTO."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            sample_brand_id, sample_variant_id, decision
        )

        assert isinstance(result, DecisionResponseDTO)

    def test_dto_validates(self, sample_brand_id, sample_variant_id):
        """Returned DTO passes model_validate."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            sample_brand_id, sample_variant_id, decision
        )

        # Should not raise
        validated = DecisionResponseDTO.model_validate(result.model_dump())
        assert validated.object_type == "variant"

    def test_decision_type_echoed(self, sample_brand_id, sample_variant_id):
        """Decision type is echoed in response."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_EDITED,
            reason="Minor tweaks",
        )

        result = decisions_service.record_variant_decision(
            sample_brand_id, sample_variant_id, decision
        )

        assert result.decision_type == DecisionType.VARIANT_EDITED

    def test_object_type_is_variant(self, sample_brand_id, sample_variant_id):
        """Object type is 'variant'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            sample_brand_id, sample_variant_id, decision
        )

        assert result.object_type == "variant"

    def test_object_id_matches(self, sample_brand_id, sample_variant_id):
        """Object ID matches variant ID."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            sample_brand_id, sample_variant_id, decision
        )

        assert result.object_id == sample_variant_id

    def test_all_variant_decision_types(self, sample_brand_id, sample_variant_id):
        """Test various variant decision types."""
        decision_types = [
            DecisionType.VARIANT_APPROVED,
            DecisionType.VARIANT_EDITED,
            DecisionType.VARIANT_REJECTED,
        ]

        for decision_type in decision_types:
            decision = DecisionRequestDTO(decision_type=decision_type)

            result = decisions_service.record_variant_decision(
                sample_brand_id, sample_variant_id, decision
            )

            assert result.decision_type == decision_type
            assert result.status == "accepted"
