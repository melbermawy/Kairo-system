"""
Decisions Service tests for PR-4.

Tests verify:
- Services return DecisionResponseDTO that pass .model_validate
- Decision type is echoed correctly
- Object type and ID are correct
- Real DB writes occur (opportunity, package, variant state changes)
- ExecutionEvent rows are created in the same transaction
- Transactionality: if anything fails, nothing is committed
- ObjectNotFoundError is raised for missing objects
"""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError

from kairo.core.enums import (
    Channel,
    CreatedVia,
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    OpportunityType,
    PackageStatus,
    PatternCategory,
    PatternStatus,
    VariantStatus,
)
from kairo.core.models import (
    Brand,
    ContentPackage,
    ExecutionEvent,
    Opportunity,
    PatternTemplate,
    Tenant,
    Variant,
)
from kairo.hero.dto import DecisionRequestDTO, DecisionResponseDTO
from kairo.hero.services import decisions_service
from kairo.hero.services.decisions_service import ObjectNotFoundError


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant():
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug=f"test-tenant-{uuid4().hex[:8]}",
    )


@pytest.fixture
def brand(tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand",
        slug=f"test-brand-{uuid4().hex[:8]}",
        primary_channel=Channel.LINKEDIN,
        channels=[Channel.LINKEDIN.value, Channel.X.value],
    )


@pytest.fixture
def opportunity(brand):
    """Create a test opportunity."""
    return Opportunity.objects.create(
        brand=brand,
        type=OpportunityType.TREND,
        title="Test Opportunity",
        angle="Test angle for the opportunity",
        score=0.75,
        primary_channel=Channel.LINKEDIN,
        created_via=CreatedVia.AI_SUGGESTED,
        is_pinned=False,
        is_snoozed=False,
        metadata={},
    )


@pytest.fixture
def package(brand, opportunity):
    """Create a test content package."""
    return ContentPackage.objects.create(
        brand=brand,
        title="Test Package",
        status=PackageStatus.DRAFT,
        origin_opportunity=opportunity,
        channels=[Channel.LINKEDIN.value, Channel.X.value],
        metrics_snapshot={},
    )


@pytest.fixture
def pattern(brand):
    """Create a test pattern template."""
    return PatternTemplate.objects.create(
        brand=brand,
        name=f"Test Pattern {uuid4().hex[:8]}",
        category=PatternCategory.EVERGREEN,
        status=PatternStatus.ACTIVE,
        beats=["hook", "body", "cta"],
        supported_channels=[Channel.LINKEDIN.value, Channel.X.value],
    )


@pytest.fixture
def variant(brand, package, pattern):
    """Create a test variant."""
    return Variant.objects.create(
        brand=brand,
        package=package,
        channel=Channel.LINKEDIN,
        status=VariantStatus.DRAFT,
        pattern_template=pattern,
        draft_text="This is a test draft.",
        edited_text="",
        approved_text="",
    )


# =============================================================================
# OPPORTUNITY DECISION TESTS
# =============================================================================


@pytest.mark.django_db
class TestOpportunityDecision:
    """Tests for decisions_service.record_opportunity_decision."""

    def test_returns_decision_response_dto(self, brand, opportunity):
        """Service returns DecisionResponseDTO."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            reason="High priority",
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        assert isinstance(result, DecisionResponseDTO)

    def test_dto_validates(self, brand, opportunity):
        """Returned DTO passes model_validate."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        # Should not raise
        validated = DecisionResponseDTO.model_validate(result.model_dump())
        assert validated.status == "accepted"

    def test_status_is_accepted(self, brand, opportunity):
        """Response status is 'accepted'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        assert result.status == "accepted"

    def test_decision_type_echoed(self, brand, opportunity):
        """Decision type is echoed in response."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_SNOOZED,
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        assert result.decision_type == DecisionType.OPPORTUNITY_SNOOZED

    def test_object_type_is_opportunity(self, brand, opportunity):
        """Object type is 'opportunity'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        assert result.object_type == "opportunity"

    def test_object_id_matches(self, brand, opportunity):
        """Object ID matches opportunity ID."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        assert result.object_id == opportunity.id

    def test_has_recorded_at(self, brand, opportunity):
        """Response has recorded_at timestamp."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        result = decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        assert result.recorded_at is not None
        assert isinstance(result.recorded_at, datetime)

    def test_pinned_updates_db_state(self, brand, opportunity):
        """OPPORTUNITY_PINNED sets is_pinned=True, is_snoozed=False."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        opportunity.refresh_from_db()
        assert opportunity.is_pinned is True
        assert opportunity.is_snoozed is False
        assert opportunity.snoozed_until is None

    def test_snoozed_updates_db_state(self, brand, opportunity):
        """OPPORTUNITY_SNOOZED sets is_snoozed=True, is_pinned=False."""
        # First pin it
        opportunity.is_pinned = True
        opportunity.save()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_SNOOZED,
        )

        decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        opportunity.refresh_from_db()
        assert opportunity.is_snoozed is True
        assert opportunity.is_pinned is False

    def test_ignored_updates_db_state(self, brand, opportunity):
        """OPPORTUNITY_IGNORED sets is_snoozed=True."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_IGNORED,
        )

        decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        opportunity.refresh_from_db()
        assert opportunity.is_snoozed is True
        assert opportunity.is_pinned is False

    def test_decision_logged_in_metadata(self, brand, opportunity):
        """Decision is logged in opportunity.metadata.decision_log."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            reason="Test reason",
        )

        decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        opportunity.refresh_from_db()
        assert "decision_log" in opportunity.metadata
        assert len(opportunity.metadata["decision_log"]) == 1
        log_entry = opportunity.metadata["decision_log"][0]
        assert log_entry["decision_type"] == DecisionType.OPPORTUNITY_PINNED.value
        assert log_entry["reason"] == "Test reason"
        assert "recorded_at" in log_entry

    def test_not_found_error_for_missing_opportunity(self, brand):
        """ObjectNotFoundError raised for non-existent opportunity."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        with pytest.raises(ObjectNotFoundError):
            decisions_service.record_opportunity_decision(
                brand.id, uuid4(), decision
            )

    def test_not_found_error_for_wrong_brand(self, brand, opportunity, tenant):
        """ObjectNotFoundError raised when brand doesn't match."""
        other_brand = Brand.objects.create(
            tenant=tenant,
            name="Other Brand",
            slug=f"other-brand-{uuid4().hex[:8]}",
        )
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
        )

        with pytest.raises(ObjectNotFoundError):
            decisions_service.record_opportunity_decision(
                other_brand.id, opportunity.id, decision
            )

    def test_no_execution_event_for_opportunity_decisions(self, brand, opportunity):
        """Opportunity decisions do NOT create ExecutionEvent (Area 3 audit).

        Per decisions_service.py NOTE:
        ExecutionEvent requires a variant FK which opportunities don't have.
        The decision is logged in the opportunity's metadata field instead.
        Full ExecutionEvent support requires schema change (future PR).
        """
        initial_count = ExecutionEvent.objects.filter(brand=brand).count()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            reason="Priority",
        )

        decisions_service.record_opportunity_decision(brand.id, opportunity.id, decision)

        # No ExecutionEvent should be created
        final_count = ExecutionEvent.objects.filter(brand=brand).count()
        assert final_count == initial_count

        # Decision should be logged in metadata instead
        opportunity.refresh_from_db()
        assert "decision_log" in opportunity.metadata
        assert len(opportunity.metadata["decision_log"]) == 1


# =============================================================================
# PACKAGE DECISION TESTS
# =============================================================================


@pytest.mark.django_db
class TestPackageDecision:
    """Tests for decisions_service.record_package_decision."""

    def test_returns_decision_response_dto(self, brand, package):
        """Service returns DecisionResponseDTO."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            brand.id, package.id, decision
        )

        assert isinstance(result, DecisionResponseDTO)

    def test_dto_validates(self, brand, package):
        """Returned DTO passes model_validate."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            brand.id, package.id, decision
        )

        # Should not raise
        validated = DecisionResponseDTO.model_validate(result.model_dump())
        assert validated.object_type == "package"

    def test_decision_type_echoed(self, brand, package):
        """Decision type is echoed in response."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_CREATED,
        )

        result = decisions_service.record_package_decision(
            brand.id, package.id, decision
        )

        assert result.decision_type == DecisionType.PACKAGE_CREATED

    def test_object_type_is_package(self, brand, package):
        """Object type is 'package'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            brand.id, package.id, decision
        )

        assert result.object_type == "package"

    def test_object_id_matches(self, brand, package):
        """Object ID matches package ID."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        result = decisions_service.record_package_decision(
            brand.id, package.id, decision
        )

        assert result.object_id == package.id

    def test_approved_from_draft_transitions_to_in_review(self, brand, package):
        """PACKAGE_APPROVED from DRAFT transitions to IN_REVIEW."""
        assert package.status == PackageStatus.DRAFT

        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        decisions_service.record_package_decision(brand.id, package.id, decision)

        package.refresh_from_db()
        assert package.status == PackageStatus.IN_REVIEW

    def test_approved_from_in_review_transitions_to_scheduled(self, brand, package):
        """PACKAGE_APPROVED from IN_REVIEW transitions to SCHEDULED."""
        package.status = PackageStatus.IN_REVIEW
        package.save()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        decisions_service.record_package_decision(brand.id, package.id, decision)

        package.refresh_from_db()
        assert package.status == PackageStatus.SCHEDULED

    def test_execution_event_created_with_variant(self, brand, package, variant):
        """ExecutionEvent created when package has variants."""
        initial_count = ExecutionEvent.objects.filter(brand=brand).count()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        decisions_service.record_package_decision(brand.id, package.id, decision)

        final_count = ExecutionEvent.objects.filter(brand=brand).count()
        assert final_count == initial_count + 1

        event = ExecutionEvent.objects.filter(brand=brand).latest("created_at")
        assert event.decision_type == DecisionType.PACKAGE_APPROVED.value
        assert event.variant == variant
        assert event.source == ExecutionSource.MANUAL_ENTRY.value

    def test_decision_logged_in_metrics_without_variant(self, brand, opportunity):
        """Decision logged in metrics_snapshot when no variants exist."""
        # Create package without variants
        package = ContentPackage.objects.create(
            brand=brand,
            title="Package Without Variants",
            status=PackageStatus.DRAFT,
            origin_opportunity=opportunity,
            metrics_snapshot={},
        )

        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
            reason="Approved for release",
        )

        decisions_service.record_package_decision(brand.id, package.id, decision)

        package.refresh_from_db()
        assert "decision_log" in package.metrics_snapshot
        assert len(package.metrics_snapshot["decision_log"]) == 1

    def test_not_found_error_for_missing_package(self, brand):
        """ObjectNotFoundError raised for non-existent package."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.PACKAGE_APPROVED,
        )

        with pytest.raises(ObjectNotFoundError):
            decisions_service.record_package_decision(
                brand.id, uuid4(), decision
            )


# =============================================================================
# VARIANT DECISION TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantDecision:
    """Tests for decisions_service.record_variant_decision."""

    def test_returns_decision_response_dto(self, brand, variant):
        """Service returns DecisionResponseDTO."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            brand.id, variant.id, decision
        )

        assert isinstance(result, DecisionResponseDTO)

    def test_dto_validates(self, brand, variant):
        """Returned DTO passes model_validate."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            brand.id, variant.id, decision
        )

        # Should not raise
        validated = DecisionResponseDTO.model_validate(result.model_dump())
        assert validated.object_type == "variant"

    def test_decision_type_echoed(self, brand, variant):
        """Decision type is echoed in response."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_EDITED,
            reason="Minor tweaks",
        )

        result = decisions_service.record_variant_decision(
            brand.id, variant.id, decision
        )

        assert result.decision_type == DecisionType.VARIANT_EDITED

    def test_object_type_is_variant(self, brand, variant):
        """Object type is 'variant'."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            brand.id, variant.id, decision
        )

        assert result.object_type == "variant"

    def test_object_id_matches(self, brand, variant):
        """Object ID matches variant ID."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        result = decisions_service.record_variant_decision(
            brand.id, variant.id, decision
        )

        assert result.object_id == variant.id

    def test_all_variant_decision_types(self, brand, variant):
        """Test various variant decision types."""
        decision_types = [
            DecisionType.VARIANT_EDITED,
            DecisionType.VARIANT_APPROVED,
            DecisionType.VARIANT_REJECTED,
        ]

        for decision_type in decision_types:
            # Reset variant status
            variant.status = VariantStatus.DRAFT
            variant.save()

            decision = DecisionRequestDTO(decision_type=decision_type)

            result = decisions_service.record_variant_decision(
                brand.id, variant.id, decision
            )

            assert result.decision_type == decision_type
            assert result.status == "accepted"

    def test_edited_updates_status(self, brand, variant):
        """VARIANT_EDITED sets status to EDITED."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_EDITED,
            metadata={"body": "New edited text"},
        )

        decisions_service.record_variant_decision(brand.id, variant.id, decision)

        variant.refresh_from_db()
        assert variant.status == VariantStatus.EDITED
        assert variant.edited_text == "New edited text"

    def test_approved_updates_status_and_text(self, brand, variant):
        """VARIANT_APPROVED sets status to APPROVED and copies text."""
        # First edit the variant
        variant.edited_text = "Edited version"
        variant.save()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        decisions_service.record_variant_decision(brand.id, variant.id, decision)

        variant.refresh_from_db()
        assert variant.status == VariantStatus.APPROVED
        assert variant.approved_text == "Edited version"

    def test_approved_uses_draft_if_no_edited(self, brand, variant):
        """VARIANT_APPROVED uses draft_text if edited_text is empty."""
        variant.edited_text = ""
        variant.draft_text = "Original draft"
        variant.save()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        decisions_service.record_variant_decision(brand.id, variant.id, decision)

        variant.refresh_from_db()
        assert variant.approved_text == "Original draft"

    def test_rejected_updates_status(self, brand, variant):
        """VARIANT_REJECTED sets status to REJECTED."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_REJECTED,
            reason="Not aligned with brand voice",
        )

        decisions_service.record_variant_decision(brand.id, variant.id, decision)

        variant.refresh_from_db()
        assert variant.status == VariantStatus.REJECTED

    def test_execution_event_created(self, brand, variant):
        """ExecutionEvent is created for variant decisions."""
        initial_count = ExecutionEvent.objects.filter(brand=brand).count()

        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
            reason="Looks good",
        )

        decisions_service.record_variant_decision(brand.id, variant.id, decision)

        final_count = ExecutionEvent.objects.filter(brand=brand).count()
        assert final_count == initial_count + 1

        event = ExecutionEvent.objects.filter(brand=brand).latest("created_at")
        assert event.variant == variant
        assert event.decision_type == DecisionType.VARIANT_APPROVED.value
        assert event.source == ExecutionSource.MANUAL_ENTRY.value
        assert event.channel == variant.channel

    def test_execution_event_has_all_required_fields(self, brand, variant):
        """ExecutionEvent created has all required fields per Area 3 audit.

        Required fields:
        - brand: FK to Brand
        - variant: FK to Variant (required due to schema constraint)
        - decision_type: Uses DecisionType enum, not raw strings
        - event_type: ExecutionEventType enum
        - source: ExecutionSource enum
        - channel: Channel from variant
        - occurred_at/received_at: Timestamps
        - metadata: Optional dict with context
        """
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_REJECTED,
            reason="Off-brand tone",
        )

        decisions_service.record_variant_decision(brand.id, variant.id, decision)

        event = ExecutionEvent.objects.filter(brand=brand).latest("created_at")

        # Verify all required fields
        assert event.brand_id == brand.id
        assert event.variant_id == variant.id
        assert event.decision_type == DecisionType.VARIANT_REJECTED.value
        assert event.event_type == ExecutionEventType.CLICK.value
        assert event.source == ExecutionSource.MANUAL_ENTRY.value
        assert event.channel == variant.channel
        assert event.occurred_at is not None
        assert event.received_at is not None

        # Verify metadata contains context
        assert event.metadata is not None
        assert event.metadata.get("object_type") == "variant"
        assert event.metadata.get("reason") == "Off-brand tone"

    def test_not_found_error_for_missing_variant(self, brand):
        """ObjectNotFoundError raised for non-existent variant."""
        decision = DecisionRequestDTO(
            decision_type=DecisionType.VARIANT_APPROVED,
        )

        with pytest.raises(ObjectNotFoundError):
            decisions_service.record_variant_decision(
                brand.id, uuid4(), decision
            )


# =============================================================================
# TRANSACTIONALITY TESTS
# =============================================================================


@pytest.mark.django_db(transaction=True)
class TestDecisionTransactionality:
    """Tests for transactional behavior of decision recording."""

    def test_variant_decision_rolls_back_on_execution_event_failure(
        self, brand, variant
    ):
        """If ExecutionEvent creation fails, variant changes are rolled back."""
        original_status = variant.status

        # Mock ExecutionEvent.objects.create to raise an error
        with patch.object(
            ExecutionEvent.objects, "create", side_effect=IntegrityError("Simulated")
        ):
            with pytest.raises(IntegrityError):
                decision = DecisionRequestDTO(
                    decision_type=DecisionType.VARIANT_APPROVED,
                )
                decisions_service.record_variant_decision(
                    brand.id, variant.id, decision
                )

        # Variant should be unchanged
        variant.refresh_from_db()
        assert variant.status == original_status

    def test_opportunity_decision_atomic(self, brand, opportunity):
        """Opportunity decision changes are atomic."""
        # Verify the happy path - both state change and metadata update occur
        decision = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            reason="Test",
        )

        decisions_service.record_opportunity_decision(
            brand.id, opportunity.id, decision
        )

        # Verify both the state change and metadata update occurred
        opportunity.refresh_from_db()
        assert opportunity.is_pinned is True
        assert "decision_log" in opportunity.metadata
