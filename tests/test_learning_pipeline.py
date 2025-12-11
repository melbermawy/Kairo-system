"""
Learning Pipeline tests for PR-4.

Tests verify:
- learning_engine.process_execution_events processes ExecutionEvents correctly
- LearningEvents are created with correct signal_type and payload
- DECISION_WEIGHT_MAP is applied correctly
- Weight deltas are bounded in [-1.0, +1.0]
- learning_service.process_recent_execution_events works end-to-end
- summarize_learning_for_brand aggregates LearningEvents correctly
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from kairo.core.enums import (
    Channel,
    CreatedVia,
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    LearningSignalType,
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
    LearningEvent,
    Opportunity,
    PatternTemplate,
    Tenant,
    Variant,
)
from kairo.hero.engines import learning_engine
from kairo.hero.run_context import create_run_context
from kairo.hero.services import learning_service


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
        angle="Test angle",
        score=0.75,
        primary_channel=Channel.LINKEDIN,
        created_via=CreatedVia.AI_SUGGESTED,
    )


@pytest.fixture
def package(brand, opportunity):
    """Create a test content package."""
    return ContentPackage.objects.create(
        brand=brand,
        title="Test Package",
        status=PackageStatus.DRAFT,
        origin_opportunity=opportunity,
        channels=[Channel.LINKEDIN.value],
    )


@pytest.fixture
def pattern(brand):
    """Create a test pattern template."""
    return PatternTemplate.objects.create(
        brand=brand,
        name=f"Test Pattern {uuid4().hex[:8]}",
        category=PatternCategory.EVERGREEN,
        status=PatternStatus.ACTIVE,
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


@pytest.fixture
def f3_context(brand):
    """Create a RunContext for F3_learning flow."""
    return create_run_context(
        brand_id=brand.id,
        flow="F3_learning",
        trigger_source="api",
    )


# =============================================================================
# LEARNING ENGINE TESTS
# =============================================================================


@pytest.mark.django_db
class TestLearningEngineProcessing:
    """Tests for learning_engine.process_execution_events."""

    def test_processes_execution_events_with_decisions(
        self, brand, variant, execution_event_with_decision, f3_context
    ):
        """ExecutionEvents with decision_type are processed."""
        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        assert result.events_processed == 1
        assert result.learning_events_created == 1
        assert len(result.learning_events) == 1

    def test_creates_learning_event_with_correct_signal_type(
        self, brand, variant, execution_event_with_decision, f3_context
    ):
        """LearningEvent has correct signal_type for VARIANT_APPROVED."""
        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        learning_event = result.learning_events[0]
        # VARIANT_APPROVED maps to PATTERN_PERFORMANCE_UPDATE
        assert learning_event.signal_type == LearningSignalType.PATTERN_PERFORMANCE_UPDATE

    def test_learning_event_has_correct_payload(
        self, brand, variant, execution_event_with_decision, f3_context
    ):
        """LearningEvent payload contains expected fields."""
        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        learning_event = result.learning_events[0]
        payload = learning_event.payload

        assert "decision_type" in payload
        assert "channel" in payload
        assert "weight_delta" in payload
        assert "event_count" in payload

    def test_weight_delta_is_positive_for_approved(
        self, brand, variant, execution_event_with_decision, f3_context
    ):
        """VARIANT_APPROVED has positive weight_delta."""
        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        learning_event = result.learning_events[0]
        assert learning_event.payload["weight_delta"] > 0

    def test_weight_delta_is_negative_for_rejected(self, brand, variant, f3_context):
        """VARIANT_REJECTED has negative weight_delta."""
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_REJECTED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=datetime.now(timezone.utc),
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        learning_event = result.learning_events[0]
        assert learning_event.payload["weight_delta"] < 0

    def test_weight_delta_is_bounded(self, brand, variant, f3_context):
        """Weight delta is bounded to [-1.0, +1.0] even with many events."""
        now = datetime.now(timezone.utc)
        # Create 20 events to try to exceed bounds
        for i in range(20):
            ExecutionEvent.objects.create(
                brand=brand,
                variant=variant,
                channel=Channel.LINKEDIN,
                event_type=ExecutionEventType.CLICK,
                decision_type=DecisionType.VARIANT_APPROVED,
                source=ExecutionSource.MANUAL_ENTRY,
                occurred_at=now - timedelta(minutes=i),
            )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        learning_event = result.learning_events[0]
        assert -1.0 <= learning_event.payload["weight_delta"] <= 1.0

    def test_returns_empty_when_no_events(self, brand, f3_context):
        """Returns empty result when no ExecutionEvents exist."""
        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        assert result.events_processed == 0
        assert result.learning_events_created == 0
        assert len(result.learning_events) == 0

    def test_ignores_events_without_decision_type(self, brand, variant, f3_context):
        """ExecutionEvents without decision_type are ignored."""
        # Create event without decision_type
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.IMPRESSION,
            decision_type=None,
            source=ExecutionSource.PLATFORM_WEBHOOK,
            occurred_at=datetime.now(timezone.utc),
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        assert result.events_processed == 0
        assert result.learning_events_created == 0

    def test_ignores_events_outside_window(self, brand, variant, f3_context):
        """ExecutionEvents outside the time window are ignored."""
        # Create event from 48 hours ago
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=datetime.now(timezone.utc) - timedelta(hours=48),
        )

        # Process with 24 hour window
        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        assert result.events_processed == 0
        assert result.learning_events_created == 0

    def test_aggregates_events_by_variant_and_decision(self, brand, variant, f3_context):
        """Multiple events with same variant and decision are aggregated."""
        now = datetime.now(timezone.utc)
        # Create 3 VARIANT_APPROVED events for same variant
        for i in range(3):
            ExecutionEvent.objects.create(
                brand=brand,
                variant=variant,
                channel=Channel.LINKEDIN,
                event_type=ExecutionEventType.CLICK,
                decision_type=DecisionType.VARIANT_APPROVED,
                source=ExecutionSource.MANUAL_ENTRY,
                occurred_at=now - timedelta(minutes=i),
            )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        # Should create only 1 LearningEvent (aggregated)
        assert result.events_processed == 3
        assert result.learning_events_created == 1
        assert result.learning_events[0].payload["event_count"] == 3

    def test_different_decision_types_create_separate_events(self, brand, variant, f3_context):
        """Different decision types create separate LearningEvents."""
        now = datetime.now(timezone.utc)

        # VARIANT_APPROVED
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=now,
        )

        # VARIANT_EDITED
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_EDITED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=now,
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)

        assert result.events_processed == 2
        assert result.learning_events_created == 2

    def test_learning_event_persisted_to_db(
        self, brand, variant, execution_event_with_decision, f3_context
    ):
        """LearningEvents are persisted to the database."""
        initial_count = LearningEvent.objects.filter(brand=brand).count()

        learning_engine.process_execution_events(f3_context, window_hours=24)

        final_count = LearningEvent.objects.filter(brand=brand).count()
        assert final_count == initial_count + 1


# =============================================================================
# DECISION TYPE MAPPING TESTS
# =============================================================================


@pytest.mark.django_db
class TestDecisionTypeMapping:
    """Tests for DECISION_WEIGHT_MAP correctness."""

    def test_variant_approved_maps_to_pattern_performance(self, brand, variant, f3_context):
        """VARIANT_APPROVED maps to PATTERN_PERFORMANCE_UPDATE."""
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=datetime.now(timezone.utc),
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)
        assert result.learning_events[0].signal_type == LearningSignalType.PATTERN_PERFORMANCE_UPDATE

    def test_variant_rejected_maps_to_pattern_performance(self, brand, variant, f3_context):
        """VARIANT_REJECTED maps to PATTERN_PERFORMANCE_UPDATE."""
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_REJECTED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=datetime.now(timezone.utc),
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)
        assert result.learning_events[0].signal_type == LearningSignalType.PATTERN_PERFORMANCE_UPDATE

    def test_opportunity_pinned_maps_to_opportunity_score(self, brand, variant, f3_context):
        """OPPORTUNITY_PINNED maps to OPPORTUNITY_SCORE_UPDATE."""
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=datetime.now(timezone.utc),
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)
        assert result.learning_events[0].signal_type == LearningSignalType.OPPORTUNITY_SCORE_UPDATE

    def test_package_approved_maps_to_channel_preference(self, brand, variant, f3_context):
        """PACKAGE_APPROVED maps to CHANNEL_PREFERENCE_UPDATE."""
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.PACKAGE_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=datetime.now(timezone.utc),
        )

        result = learning_engine.process_execution_events(f3_context, window_hours=24)
        assert result.learning_events[0].signal_type == LearningSignalType.CHANNEL_PREFERENCE_UPDATE


# =============================================================================
# LEARNING SUMMARY TESTS
# =============================================================================


@pytest.mark.django_db
class TestLearningSummary:
    """Tests for learning_engine.summarize_learning_for_brand."""

    def test_returns_summary_dto(self, brand):
        """summarize_learning_for_brand returns LearningSummaryDTO."""
        summary = learning_engine.summarize_learning_for_brand(brand.id)

        assert summary.brand_id == brand.id
        assert summary.generated_at is not None

    def test_empty_summary_when_no_events(self, brand):
        """Returns empty summary when no LearningEvents exist."""
        summary = learning_engine.summarize_learning_for_brand(brand.id)

        assert len(summary.top_performing_patterns) == 0
        assert len(summary.top_performing_channels) == 0
        assert "No learning events" in summary.notes[0]

    def test_aggregates_pattern_performance(self, brand, pattern):
        """Aggregates pattern performance from LearningEvents."""
        # Create LearningEvent with positive weight for pattern
        LearningEvent.objects.create(
            brand=brand,
            signal_type=LearningSignalType.PATTERN_PERFORMANCE_UPDATE,
            pattern=pattern,
            payload={"weight_delta": 0.5, "channel": "linkedin"},
            effective_at=datetime.now(timezone.utc),
        )

        summary = learning_engine.summarize_learning_for_brand(brand.id)

        assert pattern.id in summary.top_performing_patterns

    def test_aggregates_channel_performance(self, brand):
        """Aggregates channel performance from LearningEvents."""
        # Create LearningEvent with positive weight for channel
        LearningEvent.objects.create(
            brand=brand,
            signal_type=LearningSignalType.CHANNEL_PREFERENCE_UPDATE,
            payload={"weight_delta": 0.5, "channel": Channel.LINKEDIN.value},
            effective_at=datetime.now(timezone.utc),
        )

        summary = learning_engine.summarize_learning_for_brand(brand.id)

        assert Channel.LINKEDIN in summary.top_performing_channels


# =============================================================================
# BRAND ISOLATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestBrandIsolation:
    """Tests for brand-scoped learning (Area 2 audit requirement)."""

    def test_brand_a_events_not_processed_for_brand_b(self, tenant, brand, variant):
        """Events for brand A are completely ignored when processing brand B."""
        # Create brand B
        brand_b = Brand.objects.create(
            tenant=tenant,
            name="Brand B",
            slug=f"brand-b-{uuid4().hex[:8]}",
            primary_channel=Channel.LINKEDIN,
        )

        # Create events for brand A (the original brand fixture)
        now = datetime.now(timezone.utc)
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=now,
        )

        # Create context for brand B
        ctx_b = create_run_context(
            brand_id=brand_b.id,
            flow="F3_learning",
            trigger_source="api",
        )

        # Process for brand B
        result = learning_engine.process_execution_events(ctx_b, window_hours=24)

        # Brand B should have zero events processed
        assert result.events_processed == 0
        assert result.learning_events_created == 0
        assert len(result.learning_events) == 0

        # Verify no LearningEvents created for brand B
        assert LearningEvent.objects.filter(brand=brand_b).count() == 0

    def test_learning_events_scoped_to_brand(self, tenant, brand, variant, f3_context):
        """LearningEvents are created with correct brand_id."""
        # Create brand B with its own variant
        brand_b = Brand.objects.create(
            tenant=tenant,
            name="Brand B",
            slug=f"brand-b-{uuid4().hex[:8]}",
            primary_channel=Channel.LINKEDIN,
        )
        package_b = ContentPackage.objects.create(
            brand=brand_b,
            title="Package B",
            status=PackageStatus.DRAFT,
        )
        variant_b = Variant.objects.create(
            brand=brand_b,
            package=package_b,
            channel=Channel.LINKEDIN,
            status=VariantStatus.DRAFT,
            draft_text="Test",
        )

        # Create events for both brands
        now = datetime.now(timezone.utc)
        ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=now,
        )
        ExecutionEvent.objects.create(
            brand=brand_b,
            variant=variant_b,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_REJECTED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=now,
        )

        # Create context for brand B
        ctx_b = create_run_context(
            brand_id=brand_b.id,
            flow="F3_learning",
            trigger_source="api",
        )

        # Process brand A (using f3_context fixture)
        result_a = learning_engine.process_execution_events(f3_context, window_hours=24)
        # Process brand B
        result_b = learning_engine.process_execution_events(ctx_b, window_hours=24)

        # Each brand should have exactly 1 event processed
        assert result_a.events_processed == 1
        assert result_b.events_processed == 1

        # Verify LearningEvents have correct brand_id
        learning_a = LearningEvent.objects.filter(brand=brand)
        learning_b = LearningEvent.objects.filter(brand=brand_b)
        assert learning_a.count() == 1
        assert learning_b.count() == 1

        # Verify cross-contamination didn't happen
        assert learning_a.first().brand_id == brand.id
        assert learning_b.first().brand_id == brand_b.id


# =============================================================================
# LEARNING SERVICE TESTS
# =============================================================================


@pytest.mark.django_db
class TestLearningService:
    """Tests for learning_service functions."""

    def test_process_recent_execution_events(
        self, brand, variant, execution_event_with_decision
    ):
        """process_recent_execution_events calls engine and returns result."""
        result = learning_service.process_recent_execution_events(
            brand_id=brand.id,
            hours=24,
        )

        assert result["events_processed"] == 1
        assert result["learning_events_created"] == 1
        assert len(result["learning_events"]) == 1

    def test_get_learning_summary(self, brand):
        """get_learning_summary returns summary from engine."""
        summary = learning_service.get_learning_summary(brand.id)

        assert summary.brand_id == brand.id

    def test_get_learning_events(self, brand):
        """get_learning_events returns learning events for brand."""
        # Create some learning events
        LearningEvent.objects.create(
            brand=brand,
            signal_type=LearningSignalType.PATTERN_PERFORMANCE_UPDATE,
            payload={"test": True},
            effective_at=datetime.now(timezone.utc),
        )

        events = learning_service.get_learning_events(brand.id, limit=10)

        assert len(events) == 1
