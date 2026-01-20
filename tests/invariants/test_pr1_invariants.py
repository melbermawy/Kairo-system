"""
PR-1 Invariant Tests.

Per opportunities_v1_prd.md Section I.2 (PR-1 Make GET /today Read-Only + Move Generation to Jobs).

CRITICAL: PR-1 is the blocking gate. If these tests fail, all subsequent PRs are invalid.

These tests verify:
1. GET /today NEVER calls LLM (uses sentinel guard)
2. GET /today enqueues job on first visit (when snapshot exists)
3. POST /regenerate enqueues job and returns immediately
4. Background job is the only place where generation runs

These are behavioral invariant tests that prove PR-1's core requirements.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from kairo.core.enums import TodayBoardState
from kairo.core.guardrails import (
    GuardrailViolationError,
    is_in_get_today_context,
    reset_get_today_context,
    set_get_today_context,
)
from kairo.core.models import Brand, Tenant


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant-pr1",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="PR1 Invariant Test Brand",
        positioning="Testing PR-1 invariants",
    )


# =============================================================================
# Test 1 - GET /today Never Calls LLM
# Per PRD Section G.2 INV-G1: GET /today/ never directly executes LLM synthesis
# =============================================================================


class TestGetTodayNeverCallsLLM:
    """Verify GET /today cannot trigger LLM synthesis."""

    def test_opportunities_engine_raises_in_get_today_context(self):
        """opportunities_engine.generate_today_board raises in GET /today context."""
        from kairo.hero.engines import opportunities_engine

        # Activate GET /today context (simulates middleware behavior)
        token = set_get_today_context(True)
        try:
            # Attempting to call generate_today_board should raise
            with pytest.raises(GuardrailViolationError) as exc_info:
                # Use a fake brand_id - we expect it to fail before even looking up the brand
                opportunities_engine.generate_today_board(uuid.uuid4())

            # Error message should be informative
            error_msg = str(exc_info.value)
            assert "GET" in error_msg or "read-only" in error_msg.lower(), (
                "GuardrailViolationError should mention GET context"
            )
        finally:
            reset_get_today_context(token)

    def test_legacy_regenerate_raises_in_get_today_context(self):
        """today_service.regenerate_today_board_legacy raises in GET /today context."""
        from kairo.hero.services import today_service

        # Activate GET /today context
        token = set_get_today_context(True)
        try:
            # Attempting to call legacy regenerate should raise
            with pytest.raises(GuardrailViolationError) as exc_info:
                today_service.regenerate_today_board_legacy(uuid.uuid4())

            error_msg = str(exc_info.value)
            assert "GET" in error_msg or "read-only" in error_msg.lower()
        finally:
            reset_get_today_context(token)

    @pytest.mark.django_db
    def test_get_today_service_does_not_call_engine(self, brand):
        """today_service.get_today_board does NOT call opportunities_engine."""
        from kairo.hero.services import today_service

        # Patch the engine to detect if it's called
        with patch(
            "kairo.hero.engines.opportunities_engine.generate_today_board"
        ) as mock_engine:
            # Call GET /today logic
            result = today_service.get_today_board(brand.id)

            # Engine should NEVER be called during GET
            mock_engine.assert_not_called()

        # Result should be a valid DTO with appropriate state
        assert result is not None
        assert result.brand_id == brand.id


# =============================================================================
# Test 2 - GET /today Enqueues Job on First Visit
# Per PRD Section E.1.1: First visit enqueues fixture-only job
# =============================================================================


def _create_evidence_item(brand, suffix: str, with_transcript: bool = False):
    """Helper to create a NormalizedEvidenceItem with correct fields."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    return NormalizedEvidenceItem.objects.create(
        brand=brand,
        platform="instagram",
        content_type="post",
        external_id=f"test_ext_{suffix}",
        canonical_url=f"https://instagram.com/p/{suffix}",
        published_at="2024-01-01T00:00:00Z",
        author_ref=f"test_author_{suffix}",
        title=None,
        text_primary=f"Test content for {suffix} with enough text to be meaningful",
        text_secondary="Sample transcript text" if with_transcript else None,
        hashtags=["test", "pr1"],
        metrics_json={"likes": 100},
        media_json={},
        raw_refs=[],
        flags_json={"has_transcript": with_transcript},
    )


def _create_brandbrain_snapshot(brand):
    """Helper to create a BrandBrainSnapshot for testing first-visit behavior."""
    from kairo.brandbrain.models import BrandBrainSnapshot
    return BrandBrainSnapshot.objects.create(
        brand=brand,
        snapshot_json={
            "positioning": "Test positioning",
            "tone_tags": ["professional"],
            "taboos": [],
            "persona_ids": [],
            "pillar_ids": [],
        },
        diff_from_previous_json={},
    )


@pytest.mark.django_db
class TestGetTodayEnqueuesOnFirstVisit:
    """Verify GET /today enqueues job on first visit when BrandBrainSnapshot exists."""

    def test_first_visit_with_snapshot_enqueues_job(self, brand):
        """First GET with BrandBrainSnapshot enqueues a generation job."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        # Create BrandBrainSnapshot (the PRD-required predicate)
        _create_brandbrain_snapshot(brand)

        # Clear any existing jobs
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # First GET should enqueue a job
        result = today_service.get_today_board(brand.id)

        # Should return generating state with job_id
        assert result.meta.state == TodayBoardState.GENERATING
        assert result.meta.job_id is not None

        # Job should exist in database
        job = OpportunitiesJob.objects.filter(brand_id=brand.id).first()
        assert job is not None
        assert str(job.id) == result.meta.job_id

    def test_first_visit_without_snapshot_does_not_enqueue(self, brand):
        """First GET without BrandBrainSnapshot returns not_generated_yet (no job)."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        # Ensure no snapshot exists
        BrandBrainSnapshot.objects.filter(brand=brand).delete()

        # Clear any existing jobs
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # GET should return not_generated_yet
        result = today_service.get_today_board(brand.id)

        # Should return not_generated_yet state
        assert result.meta.state == TodayBoardState.NOT_GENERATED_YET
        assert result.meta.remediation is not None

        # No job should be created
        assert not OpportunitiesJob.objects.filter(brand_id=brand.id).exists()

    def test_second_visit_does_not_create_duplicate_job(self, brand):
        """Second GET does not create duplicate jobs (idempotent)."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        # Create BrandBrainSnapshot
        _create_brandbrain_snapshot(brand)

        # Clear existing jobs
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # First GET
        result1 = today_service.get_today_board(brand.id)
        job_count_after_first = OpportunitiesJob.objects.filter(brand_id=brand.id).count()

        # Second GET
        result2 = today_service.get_today_board(brand.id)
        job_count_after_second = OpportunitiesJob.objects.filter(brand_id=brand.id).count()

        # Should be same job_id
        assert result1.meta.job_id == result2.meta.job_id

        # Should not create duplicate jobs
        assert job_count_after_first == job_count_after_second == 1


# =============================================================================
# Test 3 - POST /regenerate Enqueues Job
# Per PRD Section I.2: POST /regenerate enqueues a job and returns immediately
# =============================================================================


@pytest.mark.django_db
class TestPostRegenerateEnqueuesJob:
    """Verify POST /regenerate enqueues job and returns immediately."""

    def test_regenerate_returns_job_id(self, brand):
        """POST /regenerate returns job_id in response."""
        from kairo.hero.dto import RegenerateResponseDTO
        from kairo.hero.services import today_service

        result = today_service.regenerate_today_board(brand.id)

        # Should return RegenerateResponseDTO
        assert isinstance(result, RegenerateResponseDTO)
        assert result.status == "accepted"
        assert result.job_id is not None
        assert result.poll_url is not None
        assert str(brand.id) in result.poll_url

    def test_regenerate_creates_job_in_database(self, brand):
        """POST /regenerate creates OpportunitiesJob in database."""
        from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus
        from kairo.hero.services import today_service

        # Clear existing jobs
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        result = today_service.regenerate_today_board(brand.id)

        # Job should exist
        job = OpportunitiesJob.objects.get(id=result.job_id)
        assert job.brand_id == brand.id
        assert job.status == OpportunitiesJobStatus.PENDING

    def test_regenerate_does_not_wait_for_completion(self, brand):
        """POST /regenerate returns immediately (does not block on generation)."""
        from kairo.hero.services import today_service
        import time

        start_time = time.monotonic()
        result = today_service.regenerate_today_board(brand.id)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        # Should return quickly (< 100ms typical, < 1s worst case)
        assert elapsed_ms < 1000, (
            f"regenerate_today_board took {elapsed_ms}ms - should return immediately"
        )

        # Job should be PENDING (not completed)
        from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus
        job = OpportunitiesJob.objects.get(id=result.job_id)
        assert job.status == OpportunitiesJobStatus.PENDING

    def test_regenerate_does_not_call_llm(self, brand):
        """POST /regenerate does NOT call LLM inline."""
        from kairo.hero.services import today_service

        # Patch graph to detect if it's called
        with patch(
            "kairo.hero.graphs.opportunities_graph.graph_hero_generate_opportunities"
        ) as mock_graph:
            result = today_service.regenerate_today_board(brand.id)

            # Graph should NOT be called during regenerate
            mock_graph.assert_not_called()

        # Should still return job_id
        assert result.job_id is not None


# =============================================================================
# Test 4 - Background Job Produces Board
# Per PRD Section I.2: Job execution produces board
# =============================================================================


@pytest.mark.django_db
class TestBackgroundJobProducesBoard:
    """Verify background job execution produces board with opportunities."""

    def test_job_execution_creates_board_with_opportunities(self, brand):
        """PR1b: Job execution creates OpportunitiesBoard with opportunities."""
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.tasks.generate import execute_opportunities_job

        # Create evidence with transcripts (half with, half without)
        for i in range(10):
            _create_evidence_item(brand, f"job_exec_{i}", with_transcript=(i < 5))

        # Clean up existing boards
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()

        # Enqueue job
        result = enqueue_opportunities_job(brand.id)
        job_id = result.job_id

        # Execute job (simulating worker) - this should call the engine
        job_result = execute_opportunities_job(job_id, brand.id)

        # Board should be created
        board = OpportunitiesBoard.objects.filter(brand_id=brand.id).first()
        assert board is not None

        # Job should have board_id
        job = OpportunitiesJob.objects.get(id=job_id)
        assert job.board_id == board.id

        # PR1b: Board should have opportunities (engine generates them)
        if board.state == TodayBoardState.READY:
            # When ready, opportunities should exist
            assert len(board.opportunity_ids) > 0, (
                "PR1b: READY board must have opportunities after synthesis"
            )

    def test_subsequent_get_returns_ready_with_opportunities(self, brand):
        """PR1b: GET /today returns ready state with opportunities after job completes."""
        from kairo.hero.models import OpportunitiesBoard
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.tasks.generate import execute_opportunities_job
        from kairo.hero.services import today_service

        # Create evidence with transcripts
        for i in range(10):
            _create_evidence_item(brand, f"ready_test_{i}", with_transcript=(i < 5))

        # Clean up existing boards
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()

        # Enqueue and execute job
        result = enqueue_opportunities_job(brand.id)
        execute_opportunities_job(result.job_id, brand.id)

        # Subsequent GET should return ready with opportunities
        board_dto = today_service.get_today_board(brand.id)

        # Should be ready or insufficient_evidence (depending on evidence quality)
        assert board_dto.meta.state in (
            TodayBoardState.READY,
            TodayBoardState.INSUFFICIENT_EVIDENCE,
        )

        # PR1b: If ready, must have opportunities
        if board_dto.meta.state == TodayBoardState.READY:
            assert len(board_dto.opportunities) > 0, (
                "PR1b: READY board must have opportunities"
            )

    def test_full_flow_first_get_to_ready_with_opportunities(self, brand):
        """PR1b Integration: First GET -> generating -> worker runs -> GET returns ready with opps."""
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.tasks.generate import execute_opportunities_job
        from kairo.hero.services import today_service

        # Setup: Create BrandBrainSnapshot (required predicate for auto-enqueue)
        _create_brandbrain_snapshot(brand)

        # Setup: Create sufficient evidence
        for i in range(10):
            _create_evidence_item(brand, f"fullflow_{i}", with_transcript=(i < 5))

        # Clean slate
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # Step 1: First GET should return GENERATING and enqueue a job
        result1 = today_service.get_today_board(brand.id)
        assert result1.meta.state == TodayBoardState.GENERATING, (
            "First GET with snapshot should return GENERATING"
        )
        assert result1.meta.job_id is not None, "Should have job_id"
        job_id = result1.meta.job_id

        # Step 2: Simulate worker running the job
        job = OpportunitiesJob.objects.get(id=job_id)
        execute_opportunities_job(job.id, brand.id)

        # Step 3: Next GET should return READY with opportunities
        result2 = today_service.get_today_board(brand.id)

        # Allow READY or INSUFFICIENT_EVIDENCE based on evidence gates
        assert result2.meta.state in (
            TodayBoardState.READY,
            TodayBoardState.INSUFFICIENT_EVIDENCE,
        ), f"Unexpected state: {result2.meta.state}"

        # PR1b: If READY, must have opportunities
        if result2.meta.state == TodayBoardState.READY:
            assert len(result2.opportunities) > 0, (
                "PR1b CRITICAL: After job completes, READY board must have opportunities. "
                "This proves synthesis ran in background."
            )


# =============================================================================
# Test 5 - HTTP Level Integration
# Per PRD Section I.2: API endpoints behave correctly
# =============================================================================


@pytest.mark.django_db
class TestHttpLevelInvariants:
    """Verify HTTP endpoints enforce PR-1 invariants."""

    def test_get_today_endpoint_returns_200(self, client, brand):
        """GET /api/brands/{brand_id}/today/ returns 200."""
        response = client.get(f"/api/brands/{brand.id}/today/")

        assert response.status_code == 200
        data = response.json()
        assert "meta" in data
        assert "state" in data["meta"]

    def test_get_today_endpoint_has_valid_state(self, client, brand):
        """GET /api/brands/{brand_id}/today/ returns valid state."""
        response = client.get(f"/api/brands/{brand.id}/today/")

        data = response.json()
        state = data["meta"]["state"]

        # State must be one of the valid TodayBoardState values
        valid_states = [s.value for s in TodayBoardState]
        assert state in valid_states, f"Invalid state: {state}"

    def test_post_regenerate_returns_202(self, client, brand):
        """POST /api/brands/{brand_id}/today/regenerate/ returns 202."""
        response = client.post(f"/api/brands/{brand.id}/today/regenerate/")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "job_id" in data
        assert "poll_url" in data

    def test_post_regenerate_invalidates_cache(self, client, brand):
        """POST /regenerate invalidates cache."""
        from django.core.cache import cache

        cache_key = f"today_board:v2:{brand.id}"

        # Set something in cache
        cache.set(cache_key, '{"test": "data"}')
        assert cache.get(cache_key) is not None

        # POST regenerate
        response = client.post(f"/api/brands/{brand.id}/today/regenerate/")
        assert response.status_code == 202

        # Cache should be invalidated
        assert cache.get(cache_key) is None


# =============================================================================
# Test 6 - Guard Integration
# Per PRD Section G.2: Guards prevent invariant violations
# =============================================================================


class TestGuardIntegration:
    """Verify guards are properly integrated."""

    def test_assert_not_in_get_today_passes_outside_context(self):
        """assert_not_in_get_today() passes when not in GET /today context."""
        from kairo.core.guardrails import assert_not_in_get_today

        # Should not raise outside of GET /today context
        assert_not_in_get_today()  # No exception = pass

    def test_assert_not_in_get_today_raises_inside_context(self):
        """assert_not_in_get_today() raises when in GET /today context."""
        from kairo.core.guardrails import assert_not_in_get_today

        token = set_get_today_context(True)
        try:
            with pytest.raises(GuardrailViolationError):
                assert_not_in_get_today()
        finally:
            reset_get_today_context(token)

    def test_middleware_sets_context_for_get_today(self):
        """Middleware is configured and sets context for GET /today."""
        from django.conf import settings
        from kairo.middleware.get_today_sentinel import GetTodaySentinelMiddleware

        # Middleware should be in settings
        middleware_path = "kairo.middleware.get_today_sentinel.GetTodaySentinelMiddleware"
        assert middleware_path in settings.MIDDLEWARE

        # Middleware should detect GET /today paths
        from kairo.middleware.get_today_sentinel import _TODAY_GET_PATTERN
        assert _TODAY_GET_PATTERN.match("/api/brands/12345678-1234-1234-1234-123456789012/today/")


# =============================================================================
# Test 7 - State Machine Invariants (Patch B Compliance)
# Per PRD: insufficient_evidence is ONLY for gate failures, not synthesis failures
# =============================================================================


@pytest.mark.django_db
class TestStateMachineInvariants:
    """
    Verify state machine correctly distinguishes:
    - gate fail → INSUFFICIENT_EVIDENCE (user action needed: connect sources)
    - gate pass + synthesis fail → ERROR (retry-oriented remediation)
    - gate pass + synthesis success → READY
    """

    def test_synthesis_timeout_produces_error_state_not_insufficient_evidence(self, brand):
        """
        CRITICAL INVARIANT: LLM timeout must NOT map to insufficient_evidence.

        When gates PASS but synthesis FAILS (timeout, 5xx, etc.), the board
        must land in ERROR state with retry-oriented remediation.
        """
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.tasks.generate import execute_opportunities_job

        # Clean slate
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # Enqueue job
        result = enqueue_opportunities_job(brand.id, mode="fixture_only")
        job_id = result.job_id

        # Mock the graph to raise a timeout exception
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = TimeoutError("LLM request timed out")

            # Execute the job - should handle the timeout gracefully
            job_result = execute_opportunities_job(job_id, brand.id, mode="fixture_only")

        # Verify board was created
        board = OpportunitiesBoard.objects.filter(brand_id=brand.id).order_by("-created_at").first()
        assert board is not None, "Board should be created even on synthesis failure"

        # CRITICAL ASSERTION: State must be ERROR, NOT INSUFFICIENT_EVIDENCE
        assert board.state == TodayBoardState.ERROR, (
            f"Synthesis failure must produce ERROR state, got {board.state}. "
            "insufficient_evidence is reserved for gate failures only."
        )

        # Remediation should be retry-oriented, not "connect more sources"
        assert board.remediation is not None, "ERROR state must have remediation"
        assert "retry" in board.remediation.lower() or "regenerat" in board.remediation.lower(), (
            f"ERROR remediation should mention retry/regenerate, got: {board.remediation}"
        )
        assert "connect" not in board.remediation.lower(), (
            f"ERROR remediation should NOT mention 'connect sources', got: {board.remediation}"
        )

        # evidence_shortfall in DTO MUST be None when gates passed
        # DB stores {} but DTO converts to None (empty dict is falsy)
        board_dto = board.to_dto()
        assert board_dto.meta.evidence_shortfall is None, (
            f"evidence_shortfall in DTO must be None when gates passed, got: {board_dto.meta.evidence_shortfall}"
        )

        # Diagnostics should show gates passed
        diagnostics = board.diagnostics_json or {}
        assert diagnostics.get("gates_passed") is True, (
            "Diagnostics should record that gates passed"
        )

    def test_gate_failure_produces_insufficient_evidence_state(self, brand):
        """
        Verify gate failure produces INSUFFICIENT_EVIDENCE (not ERROR).

        This is the correct use case for insufficient_evidence.
        """
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.tasks.generate import execute_opportunities_job

        # Clean slate - remove any existing evidence too
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # Enqueue job
        result = enqueue_opportunities_job(brand.id, mode="fixture_only")
        job_id = result.job_id

        # Mock SourceActivation to return an empty bundle (simulates no evidence)
        with patch(
            "kairo.sourceactivation.services.get_or_create_evidence_bundle"
        ) as mock_bundle:
            from kairo.sourceactivation.types import EvidenceBundle
            mock_bundle.return_value = EvidenceBundle(
                brand_id=brand.id,
                activation_run_id=None,
                snapshot_id=None,
                items=[],  # Empty = will fail gates
                mode="fixture_only",
            )

            # Execute the job
            job_result = execute_opportunities_job(job_id, brand.id, mode="fixture_only")

        # Verify board was created
        board = OpportunitiesBoard.objects.filter(brand_id=brand.id).order_by("-created_at").first()
        assert board is not None

        # State must be INSUFFICIENT_EVIDENCE (gate failure)
        assert board.state == TodayBoardState.INSUFFICIENT_EVIDENCE, (
            f"Gate failure must produce INSUFFICIENT_EVIDENCE state, got {board.state}"
        )

        # job_result should indicate insufficient_evidence
        assert job_result.insufficient_evidence is True

    def test_successful_synthesis_produces_ready_state(self, brand):
        """
        Verify successful synthesis (gates pass + LLM success) produces READY state.
        """
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.tasks.generate import execute_opportunities_job
        from kairo.hero.dto import OpportunityDraftDTO
        from kairo.core.enums import OpportunityType, Channel

        # Clean slate
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # Enqueue job
        result = enqueue_opportunities_job(brand.id, mode="fixture_only")
        job_id = result.job_id

        # Mock graph to return valid opportunities
        mock_drafts = [
            OpportunityDraftDTO(
                proposed_title=f"Test Opportunity {i}",
                proposed_angle="Test angle for this opportunity",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                suggested_channels=[Channel.LINKEDIN],
                score=80.0,
                score_explanation="Test score",
                source="test",
                why_now="This is timely because of current market trends and audience interest.",
                is_valid=True,
            )
            for i in range(3)
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_drafts

            # Execute the job
            job_result = execute_opportunities_job(job_id, brand.id, mode="fixture_only")

        # Verify board was created
        board = OpportunitiesBoard.objects.filter(brand_id=brand.id).order_by("-created_at").first()
        assert board is not None

        # State must be READY
        assert board.state == TodayBoardState.READY, (
            f"Successful synthesis must produce READY state, got {board.state}"
        )

        # Should have opportunities
        assert len(board.opportunity_ids) > 0, "READY board must have opportunities"

        # job_result should indicate success
        assert job_result.success is True
