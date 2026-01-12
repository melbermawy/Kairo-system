"""
Management Command tests for PR-4.

Tests verify:
- process_learning_events command works end-to-end
- Validates brand_id UUID format
- Validates brand exists
- Validates hours is positive
- Processes events and outputs summary
- Failure propagation behavior (Area 5 audit requirement)
"""

from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from kairo.core.enums import (
    Channel,
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    VariantStatus,
)
from kairo.core.models import (
    Brand,
    ContentPackage,
    ExecutionEvent,
    LearningEvent,
    Tenant,
    Variant,
)


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
    )


@pytest.fixture
def package(brand):
    """Create a test content package."""
    return ContentPackage.objects.create(
        brand=brand,
        title="Test Package",
    )


@pytest.fixture
def variant(brand, package):
    """Create a test variant."""
    return Variant.objects.create(
        brand=brand,
        package=package,
        channel=Channel.LINKEDIN,
        status=VariantStatus.DRAFT,
        draft_text="Test draft",
    )


@pytest.fixture
def execution_event_with_decision(brand, variant):
    """Create an ExecutionEvent with a decision_type."""
    return ExecutionEvent.objects.create(
        brand=brand,
        variant=variant,
        channel=Channel.LINKEDIN,
        event_type=ExecutionEventType.CLICK,
        decision_type=DecisionType.VARIANT_APPROVED,
        source=ExecutionSource.MANUAL_ENTRY,
        occurred_at=datetime.now(timezone.utc),
    )


# =============================================================================
# COMMAND TESTS
# =============================================================================


@pytest.mark.django_db
class TestProcessLearningEventsCommand:
    """Tests for process_learning_events management command."""

    def test_command_succeeds_with_valid_brand(self, brand):
        """Command succeeds with valid brand_id."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            stdout=out,
        )

        output = out.getvalue()
        assert "Processing execution events" in output or "No execution events" in output

    def test_command_processes_events(
        self, brand, variant, execution_event_with_decision
    ):
        """Command processes execution events and creates learning events."""
        initial_count = LearningEvent.objects.filter(brand=brand).count()

        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            "--hours=24",
            stdout=out,
        )

        final_count = LearningEvent.objects.filter(brand=brand).count()
        assert final_count > initial_count

        output = out.getvalue()
        assert "Processed" in output
        assert "learning event" in output

    def test_command_reports_no_events(self, brand):
        """Command reports when no events found."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            stdout=out,
        )

        output = out.getvalue()
        assert "No execution events found" in output

    def test_command_fails_with_invalid_uuid(self):
        """Command fails with invalid UUID format."""
        out = StringIO()
        err = StringIO()

        with pytest.raises(CommandError) as exc_info:
            call_command(
                "process_learning_events",
                "--brand-id=not-a-uuid",
                stdout=out,
                stderr=err,
            )

        assert "Invalid UUID format" in str(exc_info.value)

    def test_command_fails_with_nonexistent_brand(self):
        """Command fails when brand doesn't exist."""
        fake_brand_id = uuid4()

        with pytest.raises(CommandError) as exc_info:
            call_command(
                "process_learning_events",
                f"--brand-id={fake_brand_id}",
            )

        assert "Brand not found" in str(exc_info.value)

    def test_command_fails_with_negative_hours(self, brand):
        """Command fails with negative hours value."""
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "process_learning_events",
                f"--brand-id={brand.id}",
                "--hours=-1",
            )

        assert "Hours must be positive" in str(exc_info.value)

    def test_command_fails_with_zero_hours(self, brand):
        """Command fails with zero hours value."""
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "process_learning_events",
                f"--brand-id={brand.id}",
                "--hours=0",
            )

        assert "Hours must be positive" in str(exc_info.value)

    def test_command_uses_default_hours(self, brand):
        """Command uses default 24 hours when not specified."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            stdout=out,
        )

        output = out.getvalue()
        assert "24 hours" in output

    def test_command_respects_custom_hours(self, brand):
        """Command respects custom hours value."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            "--hours=48",
            stdout=out,
        )

        output = out.getvalue()
        assert "48 hours" in output

    def test_command_propagates_learning_service_exception(self, brand):
        """Command propagates exceptions from learning_service (Area 5 audit).

        Per PR-4 Failure Behavior documentation:
        - Exceptions propagate and abort the entire run
        - Django management framework catches and exits non-zero
        """
        with patch(
            "kairo.hero.services.learning_service.process_recent_execution_events",
            side_effect=RuntimeError("Simulated processing failure"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                call_command(
                    "process_learning_events",
                    f"--brand-id={brand.id}",
                )

            assert "Simulated processing failure" in str(exc_info.value)
