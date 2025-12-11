"""
RunContext and Logging tests for PR-6.

Tests verify:
- RunContext construction and field preservation
- Structured logging with kairo.engines logger
- Management command integration with trigger_source="manual"
"""

import logging
from io import StringIO
from uuid import UUID, uuid4

import pytest
from django.core.management import call_command

from kairo.core.models import Brand, Tenant
from kairo.hero.engines import content_engine, learning_engine, opportunities_engine
from kairo.hero.observability import log_engine_event
from kairo.hero.run_context import RunContext, create_run_context


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant-logging",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand for Logging",
        positioning="A test brand for logging tests",
        tone_tags=["professional"],
        taboos=[],
    )


# =============================================================================
# RUNCONTEXT BASICS TESTS
# =============================================================================


class TestRunContextBasics:
    """Tests for RunContext construction and field preservation."""

    def test_create_run_context_preserves_fields(self):
        """create_run_context preserves all provided fields."""
        brand_id = uuid4()
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )

        assert ctx.brand_id == brand_id
        assert ctx.flow == "F1_today"
        assert ctx.trigger_source == "api"
        assert ctx.step is None

    def test_create_run_context_with_step(self):
        """create_run_context preserves optional step field."""
        brand_id = uuid4()
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F2_package",
            trigger_source="cron",
            step="generate_variants",
        )

        assert ctx.step == "generate_variants"

    def test_run_context_generates_run_id(self):
        """RunContext generates a unique run_id."""
        brand_id = uuid4()
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )

        assert ctx.run_id is not None
        assert isinstance(ctx.run_id, UUID)

    def test_run_context_run_ids_unique(self):
        """Each RunContext gets a unique run_id."""
        brand_id = uuid4()
        ctx1 = create_run_context(
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )
        ctx2 = create_run_context(
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )

        assert ctx1.run_id != ctx2.run_id

    def test_run_context_is_not_django_model(self):
        """RunContext is NOT a Django model."""
        ctx = create_run_context(
            brand_id=uuid4(),
            flow="F1_today",
            trigger_source="api",
        )

        # Should not have Django model attributes
        assert not hasattr(ctx, "_meta")
        assert not hasattr(ctx, "pk")
        assert not hasattr(ctx, "save")
        assert not hasattr(ctx, "objects")

    def test_run_context_is_dataclass(self):
        """RunContext is a dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(RunContext)

    def test_run_context_is_frozen(self):
        """RunContext is immutable (frozen dataclass)."""
        ctx = create_run_context(
            brand_id=uuid4(),
            flow="F1_today",
            trigger_source="api",
        )

        with pytest.raises(AttributeError):
            ctx.flow = "F2_package"  # type: ignore

    def test_all_flow_types_valid(self):
        """All flow types can be used."""
        brand_id = uuid4()
        for flow in ["F1_today", "F2_package", "F3_learning"]:
            ctx = create_run_context(
                brand_id=brand_id,
                flow=flow,  # type: ignore
                trigger_source="api",
            )
            assert ctx.flow == flow

    def test_all_trigger_sources_valid(self):
        """All trigger sources can be used."""
        brand_id = uuid4()
        for source in ["api", "cron", "eval", "manual"]:
            ctx = create_run_context(
                brand_id=brand_id,
                flow="F1_today",
                trigger_source=source,  # type: ignore
            )
            assert ctx.trigger_source == source


# =============================================================================
# LOGGING BEHAVIOR TESTS
# =============================================================================


class MockLogHandler(logging.Handler):
    """A custom handler to capture log records for testing."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    def clear(self):
        self.records.clear()


@pytest.fixture
def engine_log_handler():
    """
    Fixture that captures logs from kairo.engines logger.

    This bypasses Django's LOGGING config by adding our own handler directly.
    """
    handler = MockLogHandler()
    handler.setLevel(logging.INFO)

    kairo_engines_logger = logging.getLogger("kairo.engines")
    kairo_engines_logger.addHandler(handler)
    kairo_engines_logger.setLevel(logging.INFO)

    yield handler

    kairo_engines_logger.removeHandler(handler)
    handler.clear()


@pytest.mark.django_db
class TestLoggingBehavior:
    """Tests for structured logging with kairo.engines logger."""

    def test_log_engine_event_emits_info_log(self, engine_log_handler):
        """log_engine_event emits an INFO level log."""
        ctx = create_run_context(
            brand_id=uuid4(),
            flow="F1_today",
            trigger_source="api",
        )

        log_engine_event(
            ctx=ctx,
            engine="opportunities_engine",
            operation="generate_today_board",
            status="start",
        )

        assert len(engine_log_handler.records) == 1
        assert engine_log_handler.records[0].levelno == logging.INFO

    def test_log_engine_event_includes_required_fields(self, engine_log_handler):
        """log_engine_event includes all required fields in extra."""
        brand_id = uuid4()
        ctx = create_run_context(
            brand_id=brand_id,
            flow="F2_package",
            trigger_source="cron",
        )

        log_engine_event(
            ctx=ctx,
            engine="content_engine",
            operation="create_package",
            status="success",
        )

        record = engine_log_handler.records[0]
        assert record.run_id == str(ctx.run_id)
        assert record.brand_id == str(brand_id)
        assert record.flow == "F2_package"
        assert record.trigger_source == "cron"
        assert record.engine == "content_engine"
        assert record.operation == "create_package"
        assert record.status == "success"

    def test_log_engine_event_includes_extra_fields(self, engine_log_handler):
        """log_engine_event includes optional extra fields."""
        ctx = create_run_context(
            brand_id=uuid4(),
            flow="F3_learning",
            trigger_source="manual",
        )

        log_engine_event(
            ctx=ctx,
            engine="learning_engine",
            operation="process_events",
            status="success",
            extra={"events_processed": 10, "learning_events_created": 3},
        )

        record = engine_log_handler.records[0]
        assert record.events_processed == 10
        assert record.learning_events_created == 3

    def test_opportunities_engine_logs_start_and_success(self, brand, engine_log_handler):
        """opportunities_engine logs start and success events."""
        ctx = create_run_context(
            brand_id=brand.id,
            flow="F1_today",
            trigger_source="api",
        )

        opportunities_engine.generate_today_board(ctx)

        # Should have at least start and success logs
        assert len(engine_log_handler.records) >= 2

        # Find start and success records
        start_records = [r for r in engine_log_handler.records if getattr(r, "status", None) == "start"]
        success_records = [r for r in engine_log_handler.records if getattr(r, "status", None) == "success"]

        assert len(start_records) >= 1
        assert len(success_records) >= 1

        # Verify start record
        start = start_records[0]
        assert start.engine == "opportunities_engine"
        assert start.operation == "generate_today_board"
        assert start.flow == "F1_today"

        # Verify success record
        success = success_records[0]
        assert success.engine == "opportunities_engine"
        assert success.operation == "generate_today_board"

    def test_content_engine_logs_start_and_success(self, brand, engine_log_handler):
        """content_engine logs start and success events."""
        ctx = create_run_context(
            brand_id=brand.id,
            flow="F2_package",
            trigger_source="api",
        )
        opportunity_id = uuid4()

        content_engine.create_package_from_opportunity(ctx, opportunity_id)

        # Should have at least start and success logs
        assert len(engine_log_handler.records) >= 2

        start_records = [r for r in engine_log_handler.records if getattr(r, "status", None) == "start"]
        success_records = [r for r in engine_log_handler.records if getattr(r, "status", None) == "success"]

        assert len(start_records) >= 1
        assert len(success_records) >= 1

    def test_learning_engine_logs_start_and_success(self, brand, engine_log_handler):
        """learning_engine logs start and success events."""
        ctx = create_run_context(
            brand_id=brand.id,
            flow="F3_learning",
            trigger_source="api",
        )

        learning_engine.process_execution_events(ctx, window_hours=24)

        # Should have at least start and success logs
        assert len(engine_log_handler.records) >= 2

        start_records = [r for r in engine_log_handler.records if getattr(r, "status", None) == "start"]
        success_records = [r for r in engine_log_handler.records if getattr(r, "status", None) == "success"]

        assert len(start_records) >= 1
        assert len(success_records) >= 1

    def test_run_id_consistent_across_logs(self, brand, engine_log_handler):
        """Same run_id is used across all logs in a single operation."""
        ctx = create_run_context(
            brand_id=brand.id,
            flow="F1_today",
            trigger_source="api",
        )

        opportunities_engine.generate_today_board(ctx)

        # All records should have the same run_id
        run_ids = {r.run_id for r in engine_log_handler.records}
        assert len(run_ids) == 1
        assert str(ctx.run_id) in run_ids


# =============================================================================
# MANAGEMENT COMMAND INTEGRATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestManagementCommandIntegration:
    """Tests for management command RunContext integration."""

    def test_process_learning_events_uses_manual_trigger(self, brand, engine_log_handler):
        """process_learning_events command uses trigger_source='manual'."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            "--hours=24",
            stdout=out,
        )

        # Should have logs with trigger_source="manual"
        manual_records = [
            r for r in engine_log_handler.records if getattr(r, "trigger_source", None) == "manual"
        ]
        assert len(manual_records) >= 1

    def test_process_learning_events_uses_f3_flow(self, brand, engine_log_handler):
        """process_learning_events command uses flow='F3_learning'."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            "--hours=24",
            stdout=out,
        )

        # Should have logs with flow="F3_learning"
        f3_records = [
            r for r in engine_log_handler.records if getattr(r, "flow", None) == "F3_learning"
        ]
        assert len(f3_records) >= 1

    def test_process_learning_events_logs_learning_engine(self, brand, engine_log_handler):
        """process_learning_events logs learning_engine operations."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            "--hours=24",
            stdout=out,
        )

        # Should have learning_engine logs
        learning_engine_records = [
            r for r in engine_log_handler.records if getattr(r, "engine", None) == "learning_engine"
        ]
        assert len(learning_engine_records) >= 1

    def test_process_learning_events_output(self, brand):
        """process_learning_events produces expected output."""
        out = StringIO()
        call_command(
            "process_learning_events",
            f"--brand-id={brand.id}",
            "--hours=24",
            stdout=out,
        )

        output = out.getvalue()
        # Should mention processing events for the brand
        assert str(brand.id) in output or "execution events" in output.lower()


# =============================================================================
# FAILURE PATH LOGGING TESTS
# =============================================================================


@pytest.mark.django_db
class TestFailurePathLogging:
    """Tests for failure path logging with error_summary."""

    def test_log_engine_event_includes_error_summary(self, engine_log_handler):
        """log_engine_event includes error_summary field on failure status."""
        ctx = create_run_context(
            brand_id=uuid4(),
            flow="F1_today",
            trigger_source="api",
        )

        log_engine_event(
            ctx=ctx,
            engine="opportunities_engine",
            operation="generate_today_board",
            status="failure",
            error_summary="ValueError: Brand not found",
        )

        assert len(engine_log_handler.records) == 1
        record = engine_log_handler.records[0]
        assert record.status == "failure"
        assert record.error_summary == "ValueError: Brand not found"

    def test_opportunities_engine_logs_failure_on_missing_brand(self, db, engine_log_handler):
        """opportunities_engine logs failure with error_summary when brand is missing."""
        fake_brand_id = uuid4()
        ctx = create_run_context(
            brand_id=fake_brand_id,
            flow="F1_today",
            trigger_source="api",
        )

        with pytest.raises(Brand.DoesNotExist):
            opportunities_engine.generate_today_board(ctx)

        # Should have start and failure logs
        failure_records = [
            r for r in engine_log_handler.records
            if getattr(r, "status", None) == "failure"
        ]
        assert len(failure_records) >= 1

        # Verify error_summary is present
        failure = failure_records[0]
        assert hasattr(failure, "error_summary")
        assert "DoesNotExist" in failure.error_summary
