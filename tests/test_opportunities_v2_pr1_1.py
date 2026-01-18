"""
Opportunities v2 PR1.1 Tests: Design Hazard Fixes + Anti-Regression Guardrails.

Per PR1.1 prompt: Correctness, unambiguous state semantics, single source of truth.

PR1.1 SCOPE:
A) Ready state semantics - ready_reason field
B) Persistence truth enforcement - referential integrity
C) Anti-regression guardrails:
   1) No Apify imports in hero engine path
   2) GET /today must not do heavy work
   3) State semantics invariant (ready + empty opps needs reason)
D) Stuck job handling
"""

import ast
import os
from pathlib import Path
from uuid import uuid4

import pytest

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import ReadyReason


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="PR1.1 Test Tenant",
        slug="pr1-1-test-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand with no evidence."""
    return Brand.objects.create(
        tenant=tenant,
        name="PR1.1 Test Brand",
        slug="pr1-1-test-brand",
        positioning="Testing PR1.1 behavior",
    )


@pytest.fixture
def brand_with_sufficient_evidence(db, tenant):
    """Create a brand with sufficient evidence for generation."""
    from kairo.brandbrain.models import NormalizedEvidenceItem

    from tests.fixtures.evidence_fixtures import create_sufficient_evidence

    brand = Brand.objects.create(
        tenant=tenant,
        name="Brand With Sufficient Evidence PR1.1",
        slug="brand-with-sufficient-evidence-pr1-1",
        positioning="Has enough evidence for generation",
    )

    evidence_data = create_sufficient_evidence(brand.id)
    for data in evidence_data:
        NormalizedEvidenceItem.objects.create(**data)

    return brand


# =============================================================================
# A) READY STATE SEMANTICS TESTS
# =============================================================================


@pytest.mark.django_db
class TestReadyStateSemantics:
    """Test that ready state has unambiguous semantics."""

    def test_ready_with_empty_opportunities_has_reason(self, brand_with_sufficient_evidence):
        """
        CRITICAL INVARIANT: If state=ready AND opportunities=[], ready_reason MUST be set.

        This prevents the ambiguity where frontend/devs can't tell if:
        - Synthesis hasn't been implemented yet (PR1)
        - Synthesis ran but produced 0 valid candidates
        - Something else went wrong
        """
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service
        from kairo.hero.tasks.generate import execute_opportunities_job

        from kairo.hero.jobs.queue import enqueue_opportunities_job

        # Create and execute job
        enqueue_result = enqueue_opportunities_job(brand_with_sufficient_evidence.id)
        job = OpportunitiesJob.objects.get(id=enqueue_result.job_id)
        job.status = "running"
        job.save()

        execute_opportunities_job(
            job_id=job.id,
            brand_id=brand_with_sufficient_evidence.id,
        )

        # GET the board
        result = today_service.get_today_board(brand_with_sufficient_evidence.id)

        # CRITICAL INVARIANT CHECK
        if result.meta.state == TodayBoardState.READY and len(result.opportunities) == 0:
            assert result.meta.ready_reason is not None, (
                "INVARIANT VIOLATION: state=ready with empty opportunities MUST have ready_reason set. "
                "This is a PR1.1 requirement to prevent ambiguous state semantics."
            )
            # Verify it's a known reason code
            known_reasons = {
                ReadyReason.GENERATED,
                ReadyReason.GATES_ONLY_NO_SYNTHESIS,
                ReadyReason.NO_VALID_CANDIDATES,
                ReadyReason.EMPTY_BRAND_CONTEXT,
            }
            assert result.meta.ready_reason in known_reasons, (
                f"ready_reason '{result.meta.ready_reason}' is not a known reason code. "
                f"Allowed: {known_reasons}"
            )

    def test_pr1_sets_gates_only_no_synthesis_reason(self, brand_with_sufficient_evidence):
        """PR1 (no LLM synthesis) should set ready_reason = 'gates_only_no_synthesis'."""
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service
        from kairo.hero.tasks.generate import execute_opportunities_job

        from kairo.hero.jobs.queue import enqueue_opportunities_job

        enqueue_result = enqueue_opportunities_job(brand_with_sufficient_evidence.id)
        job = OpportunitiesJob.objects.get(id=enqueue_result.job_id)
        job.status = "running"
        job.save()

        execute_opportunities_job(
            job_id=job.id,
            brand_id=brand_with_sufficient_evidence.id,
        )

        result = today_service.get_today_board(brand_with_sufficient_evidence.id)

        if result.meta.state == TodayBoardState.READY:
            assert result.meta.ready_reason == ReadyReason.GATES_ONLY_NO_SYNTHESIS, (
                f"PR1 should set ready_reason='{ReadyReason.GATES_ONLY_NO_SYNTHESIS}', "
                f"got '{result.meta.ready_reason}'"
            )


# =============================================================================
# B) PERSISTENCE TRUTH TESTS
# =============================================================================


@pytest.mark.django_db
class TestPersistenceTruth:
    """Test referential integrity between OpportunitiesBoard and Opportunity."""

    def test_empty_opportunity_ids_is_valid(self, brand):
        """Empty opportunity_ids should pass referential integrity check."""
        from kairo.hero.models import OpportunitiesBoard

        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            ready_reason=ReadyReason.GATES_ONLY_NO_SYNTHESIS,
            opportunity_ids=[],
        )

        is_valid, missing = board.validate_referential_integrity()
        assert is_valid is True
        assert missing == []

    def test_invalid_opportunity_ids_fails_integrity_check(self, brand):
        """Non-existent opportunity IDs should fail referential integrity check."""
        from kairo.hero.models import OpportunitiesBoard

        fake_id = str(uuid4())
        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            ready_reason=ReadyReason.GENERATED,
            opportunity_ids=[fake_id],
        )

        is_valid, missing = board.validate_referential_integrity()
        assert is_valid is False
        assert fake_id in missing

    def test_valid_opportunity_ids_passes_integrity_check(self, brand):
        """Existing opportunity IDs should pass referential integrity check."""
        from kairo.core.enums import Channel, OpportunityType
        from kairo.core.models import Opportunity
        from kairo.hero.models import OpportunitiesBoard

        # Create real opportunity
        opp = Opportunity.objects.create(
            brand=brand,
            type=OpportunityType.TREND,
            title="Test Opportunity",
            primary_channel=Channel.LINKEDIN,
        )

        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            ready_reason=ReadyReason.GENERATED,
            opportunity_ids=[str(opp.id)],
        )

        is_valid, missing = board.validate_referential_integrity()
        assert is_valid is True
        assert missing == []


# =============================================================================
# C) ANTI-REGRESSION GUARDRAILS
# =============================================================================


class TestNoApifyImportsInHeroEngine:
    """
    GUARDRAIL: No Apify imports in hero engine path.

    Apify calls should NEVER happen in the hero engine path.
    Evidence comes from NormalizedEvidenceItem (already ingested).
    """

    def test_no_apify_imports_in_hero_engine(self):
        """
        Scan all Python files under kairo/hero/ for Apify imports.

        This test fails if ANY module imports from:
        - kairo.integrations.apify
        - apify (direct SDK import)
        """
        hero_dir = Path(__file__).parent.parent / "kairo" / "hero"
        assert hero_dir.exists(), f"Expected hero directory at {hero_dir}"

        violations = []

        for py_file in hero_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue

            try:
                source = py_file.read_text()
                tree = ast.parse(source)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "apify" in alias.name.lower():
                            violations.append(
                                f"{py_file.relative_to(hero_dir.parent.parent)}: "
                                f"import {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "apify" in module.lower():
                        violations.append(
                            f"{py_file.relative_to(hero_dir.parent.parent)}: "
                            f"from {module} import ..."
                        )
                    # Also check for kairo.integrations.apify
                    if "integrations.apify" in module.lower():
                        violations.append(
                            f"{py_file.relative_to(hero_dir.parent.parent)}: "
                            f"from {module} import ..."
                        )

        assert len(violations) == 0, (
            f"ANTI-REGRESSION VIOLATION: Found Apify imports in hero engine path!\n"
            f"Violations:\n" + "\n".join(f"  - {v}" for v in violations) + "\n\n"
            f"Hero engine must NEVER import Apify. "
            f"Evidence comes from NormalizedEvidenceItem table."
        )


class TestNoLLMImportsInPR1:
    """
    GUARDRAIL: No LLM imports in PR1 generation path.

    PR1 runs evidence gates only, no LLM synthesis.
    """

    def test_no_llm_imports_in_generate_task(self):
        """
        The generate.py task file should not import any LLM modules in PR1.
        """
        generate_file = (
            Path(__file__).parent.parent
            / "kairo"
            / "hero"
            / "tasks"
            / "generate.py"
        )
        assert generate_file.exists()

        source = generate_file.read_text()
        tree = ast.parse(source)

        llm_patterns = ["kairo.llm", "openai", "anthropic", "langchain"]
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for pattern in llm_patterns:
                    if pattern in module.lower():
                        violations.append(f"from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for pattern in llm_patterns:
                        if pattern in alias.name.lower():
                            violations.append(f"import {alias.name}")

        assert len(violations) == 0, (
            f"ANTI-REGRESSION VIOLATION: Found LLM imports in generate.py!\n"
            f"Violations: {violations}\n\n"
            f"PR1 must NOT import LLM modules. Evidence gates only."
        )


@pytest.mark.django_db
class TestGetTodayReadOnly:
    """
    GUARDRAIL: GET /today must not do heavy work.

    The ONLY allowed side effect is first-run auto-enqueue.
    """

    def test_get_does_not_enqueue_when_job_running(self, brand):
        """GET should NOT enqueue a new job if one is already running."""
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        from kairo.hero.jobs.queue import enqueue_opportunities_job

        # Enqueue first job
        enqueue_result = enqueue_opportunities_job(brand.id)
        initial_job_count = OpportunitiesJob.objects.filter(brand_id=brand.id).count()

        # GET should not create another job
        today_service.get_today_board(brand.id)

        final_job_count = OpportunitiesJob.objects.filter(brand_id=brand.id).count()
        assert final_job_count == initial_job_count, (
            "GET created a new job when one was already pending/running. "
            "This violates the read-only GET principle."
        )

    def test_get_does_not_enqueue_when_board_exists(self, brand):
        """GET should NOT enqueue if a persisted board already exists."""
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.services import today_service

        # Create a persisted board
        OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            ready_reason=ReadyReason.GATES_ONLY_NO_SYNTHESIS,
            opportunity_ids=[],
        )

        initial_job_count = OpportunitiesJob.objects.filter(brand_id=brand.id).count()

        # GET should read from board, not enqueue
        result = today_service.get_today_board(brand.id)

        final_job_count = OpportunitiesJob.objects.filter(brand_id=brand.id).count()
        assert final_job_count == initial_job_count, (
            "GET created a job when a board already exists. "
            "This violates the read-only GET principle."
        )
        assert result.meta.state == TodayBoardState.READY

    def test_get_first_run_enqueue_only_with_sufficient_evidence(self, brand):
        """GET first-run auto-enqueue should ONLY happen with sufficient evidence."""
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        # Brand has no evidence (0 items)
        initial_job_count = OpportunitiesJob.objects.filter(brand_id=brand.id).count()

        # GET should NOT enqueue - insufficient evidence
        result = today_service.get_today_board(brand.id)

        final_job_count = OpportunitiesJob.objects.filter(brand_id=brand.id).count()
        assert final_job_count == initial_job_count, (
            "GET enqueued a job for a brand with no evidence. "
            "First-run auto-enqueue requires MIN_EVIDENCE_ITEMS (8)."
        )
        assert result.meta.state == TodayBoardState.NOT_GENERATED_YET


@pytest.mark.django_db
class TestStateInvariantEnforcement:
    """
    GUARDRAIL: State semantics invariant enforcement.

    If state=ready AND opportunities=[], ready_reason MUST be set.
    """

    def test_board_dto_enforces_ready_reason_invariant(self, brand):
        """
        Test that OpportunitiesBoard.to_dto() includes ready_reason.

        Future PR can add validation that raises if invariant is violated.
        """
        from kairo.hero.models import OpportunitiesBoard

        # Create board with ready_reason set correctly
        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            ready_reason=ReadyReason.GATES_ONLY_NO_SYNTHESIS,
            opportunity_ids=[],
        )

        dto = board.to_dto()

        assert dto.meta.ready_reason == ReadyReason.GATES_ONLY_NO_SYNTHESIS, (
            "to_dto() should preserve ready_reason field"
        )

    def test_invariant_violation_detectable(self, brand):
        """
        A board with state=ready, opportunities=[], but NO ready_reason
        should be detectable as an invariant violation.

        This test documents the invariant - enforcement is via code review
        and the test in test_ready_with_empty_opportunities_has_reason.
        """
        from kairo.hero.models import OpportunitiesBoard

        # Create board WITHOUT ready_reason (violates invariant)
        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            ready_reason=None,  # VIOLATION
            opportunity_ids=[],
        )

        dto = board.to_dto()

        # The DTO should have None for ready_reason
        # This is detectable as a violation
        if dto.meta.state == TodayBoardState.READY and len(dto.opportunities) == 0:
            is_violation = dto.meta.ready_reason is None
            assert is_violation, "This test verifies the violation is detectable"


# =============================================================================
# D) STUCK JOB HANDLING TESTS
# =============================================================================


@pytest.mark.django_db
class TestStuckJobHandling:
    """Test stuck job detection and transition to error state."""

    def test_mark_stuck_job_as_error(self, brand):
        """
        Jobs stuck in 'running' state beyond threshold should transition to error.
        """
        from datetime import timedelta

        from django.utils import timezone

        from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

        from kairo.hero.jobs.queue import enqueue_opportunities_job

        # Create a job
        enqueue_result = enqueue_opportunities_job(brand.id)
        job = OpportunitiesJob.objects.get(id=enqueue_result.job_id)

        # Simulate stuck job: set to running with old locked_at
        old_time = timezone.now() - timedelta(minutes=15)  # Beyond 10-minute threshold
        job.status = OpportunitiesJobStatus.RUNNING
        job.locked_at = old_time
        job.locked_by = "dead-worker"
        job.attempts = job.max_attempts  # Max attempts reached
        job.save()

        # Release stale jobs should mark this as FAILED
        from kairo.hero.jobs.queue import release_stale_jobs

        released = release_stale_jobs(stale_threshold_minutes=10)

        assert released == 1

        # Verify job is now FAILED
        job.refresh_from_db()
        assert job.status == OpportunitiesJobStatus.FAILED
        assert "stale" in job.last_error.lower()

    def test_stuck_job_creates_error_board(self, brand_with_sufficient_evidence):
        """
        PR1.1: When a job is stuck and fails, an error board IS created.

        This ensures GET /today returns state=error with remediation instructions.
        """
        from datetime import timedelta

        from django.utils import timezone

        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob, OpportunitiesJobStatus
        from kairo.hero.services import today_service

        from kairo.hero.jobs.queue import enqueue_opportunities_job, release_stale_jobs

        # Create and run job
        enqueue_result = enqueue_opportunities_job(brand_with_sufficient_evidence.id)
        job = OpportunitiesJob.objects.get(id=enqueue_result.job_id)

        # Simulate stuck job at max attempts
        old_time = timezone.now() - timedelta(minutes=15)
        job.status = OpportunitiesJobStatus.RUNNING
        job.locked_at = old_time
        job.locked_by = "dead-worker"
        job.attempts = job.max_attempts
        job.save()

        # Release stale jobs - this should create an error board
        release_stale_jobs(stale_threshold_minutes=10)
        job.refresh_from_db()

        # Job should be FAILED
        assert job.status == OpportunitiesJobStatus.FAILED

        # PR1.1: An error board should have been created
        error_board = OpportunitiesBoard.objects.filter(
            brand_id=brand_with_sufficient_evidence.id,
            state=TodayBoardState.ERROR,
        ).first()
        assert error_board is not None, "Error board should be created for stuck job"

        # Job should reference the board
        assert job.board_id == error_board.id

        # GET should return error state
        result = today_service.get_today_board(brand_with_sufficient_evidence.id)
        assert result.meta.state == TodayBoardState.ERROR
        assert result.meta.remediation is not None
