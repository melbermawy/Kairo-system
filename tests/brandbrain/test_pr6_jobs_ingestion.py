"""
PR-6 Tests: Durable Job Queue + Real Ingestion Wiring.

Tests for:
A) Job queue operations - enqueue, claim, complete, fail, retry
B) Job leasing - atomic claiming, no double-execution
C) Stale lock detection and release
D) Ingestion service - actor run, raw fetch, normalization
E) Cap enforcement - actor input caps and dataset fetch caps
F) Compile worker with real ingestion (mocked Apify)
G) Evidence status tracking - reused/refreshed/skipped/failed
H) Cross-brand security (preserved from PR-5)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from kairo.brandbrain.jobs import (
    claim_next_job,
    complete_job,
    enqueue_compile_job,
    extend_job_lock,
    fail_job,
    get_job_status,
    release_stale_jobs,
)
from kairo.brandbrain.models import (
    BrandBrainJob,
    BrandBrainJobStatus,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="Test Tenant PR6",
        slug="test-tenant-pr6",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand PR6",
        slug="test-brand-pr6",
    )


@pytest.fixture
def brand_with_onboarding(db, brand):
    """Create a brand with complete Tier0 onboarding."""
    from kairo.brandbrain.models import BrandOnboarding

    BrandOnboarding.objects.create(
        brand=brand,
        tier=0,
        answers_json={
            "tier0.what_we_do": "We help businesses grow",
            "tier0.who_for": "Small business owners",
            "tier0.primary_goal": "brand_awareness",
            "tier0.cta_posture": "soft",
        },
    )
    return brand


@pytest.fixture
def source_instagram_posts(db, brand):
    """Create an Instagram posts source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="instagram",
        capability="posts",
        identifier="testbrand",
        is_enabled=True,
    )


@pytest.fixture
def compile_run(db, brand_with_onboarding, source_instagram_posts):
    """Create a pending compile run."""
    from kairo.brandbrain.models import BrandBrainCompileRun

    # Associate source with brand
    source_instagram_posts.brand = brand_with_onboarding
    source_instagram_posts.save()

    return BrandBrainCompileRun.objects.create(
        brand=brand_with_onboarding,
        status="PENDING",
        onboarding_snapshot_json={
            "input_hash": "test-hash",
            "captured_at": timezone.now().isoformat(),
        },
        evidence_status_json={
            "reused": [],
            "refreshed": [],
            "skipped": [],
            "failed": [],
        },
    )


# =============================================================================
# A) JOB QUEUE OPERATIONS
# =============================================================================


@pytest.mark.db
class TestJobEnqueue:
    """Test job enqueueing."""

    def test_enqueue_creates_job(self, db, brand, compile_run):
        """Enqueue creates a job with PENDING status."""
        result = enqueue_compile_job(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            force_refresh=False,
        )

        assert result.job_id is not None
        assert result.compile_run_id == compile_run.id

        job = BrandBrainJob.objects.get(id=result.job_id)
        assert job.status == BrandBrainJobStatus.PENDING
        assert job.brand_id == brand.id
        assert job.compile_run_id == compile_run.id
        assert job.job_type == "compile"
        assert job.attempts == 0
        assert job.max_attempts == 3

    def test_enqueue_stores_params(self, db, brand, compile_run):
        """Enqueue stores job parameters."""
        result = enqueue_compile_job(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            force_refresh=True,
            prompt_version="v2",
            model="gpt-4-turbo",
        )

        job = BrandBrainJob.objects.get(id=result.job_id)
        assert job.params_json["force_refresh"] is True
        assert job.params_json["prompt_version"] == "v2"
        assert job.params_json["model"] == "gpt-4-turbo"


@pytest.mark.db
class TestJobClaim:
    """Test job claiming."""

    def test_claim_available_job(self, db, brand, compile_run):
        """Claim returns an available job."""
        result = enqueue_compile_job(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
        )

        claim_result = claim_next_job(worker_id="test-worker-1")

        assert claim_result.claimed is True
        assert claim_result.job is not None
        assert claim_result.job.id == result.job_id
        assert claim_result.job.status == BrandBrainJobStatus.RUNNING
        assert claim_result.job.locked_by == "test-worker-1"
        assert claim_result.job.locked_at is not None
        assert claim_result.job.attempts == 1

    def test_claim_returns_none_when_empty(self, db):
        """Claim returns None when no jobs available."""
        claim_result = claim_next_job(worker_id="test-worker-1")

        assert claim_result.claimed is False
        assert claim_result.job is None
        assert "No available jobs" in claim_result.reason

    def test_claim_respects_available_at(self, db, brand, compile_run):
        """Claim skips jobs scheduled for the future."""
        # Create job then update available_at (auto_now_add prevents setting on create)
        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.PENDING,
        )
        # Update to future time after creation
        BrandBrainJob.objects.filter(id=job.id).update(
            available_at=timezone.now() + timedelta(hours=1)
        )

        claim_result = claim_next_job(worker_id="test-worker-1")

        assert claim_result.claimed is False
        assert claim_result.job is None


@pytest.mark.db
class TestJobComplete:
    """Test job completion."""

    def test_complete_running_job(self, db, brand, compile_run):
        """Complete marks job as succeeded."""
        enqueue_compile_job(brand_id=brand.id, compile_run_id=compile_run.id)
        claim_result = claim_next_job()

        success = complete_job(claim_result.job.id)

        assert success is True
        job = BrandBrainJob.objects.get(id=claim_result.job.id)
        assert job.status == BrandBrainJobStatus.SUCCEEDED
        assert job.finished_at is not None
        assert job.locked_at is None
        assert job.locked_by is None

    def test_complete_nonexistent_job(self, db):
        """Complete returns False for nonexistent job."""
        fake_id = uuid.uuid4()
        success = complete_job(fake_id)
        assert success is False


@pytest.mark.db
class TestJobFail:
    """Test job failure and retry."""

    def test_fail_with_retry(self, db, brand, compile_run):
        """Fail schedules retry when attempts < max_attempts."""
        enqueue_compile_job(brand_id=brand.id, compile_run_id=compile_run.id)
        claim_result = claim_next_job()

        success = fail_job(claim_result.job.id, "Test error")

        assert success is True
        job = BrandBrainJob.objects.get(id=claim_result.job.id)
        assert job.status == BrandBrainJobStatus.PENDING  # Scheduled for retry
        assert job.last_error == "Test error"
        assert job.available_at > timezone.now()  # Backoff
        assert job.locked_at is None
        assert job.locked_by is None

    def test_fail_permanent_after_max_attempts(self, db, brand, compile_run):
        """Fail marks job as failed after max_attempts."""
        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
        )

        success = fail_job(job.id, "Final failure")

        assert success is True
        job.refresh_from_db()
        assert job.status == BrandBrainJobStatus.FAILED
        assert job.last_error == "Final failure"
        assert job.finished_at is not None


# =============================================================================
# B) JOB LEASING - NO DOUBLE EXECUTION
# =============================================================================


@pytest.mark.db
class TestJobLeasing:
    """Test that job leasing prevents double-execution."""

    def test_claim_is_atomic(self, db, brand, compile_run):
        """Only one worker can claim a job."""
        enqueue_compile_job(brand_id=brand.id, compile_run_id=compile_run.id)

        # First claim succeeds
        result1 = claim_next_job(worker_id="worker-1")
        assert result1.claimed is True

        # Second claim fails (no more jobs)
        result2 = claim_next_job(worker_id="worker-2")
        assert result2.claimed is False

    def test_running_job_not_claimable(self, db, brand, compile_run):
        """Running jobs cannot be claimed."""
        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            locked_at=timezone.now(),
            locked_by="other-worker",
        )

        claim_result = claim_next_job(worker_id="test-worker")

        assert claim_result.claimed is False


# =============================================================================
# C) STALE LOCK DETECTION
# =============================================================================


@pytest.mark.db
class TestStaleLocks:
    """Test stale lock detection and release."""

    def test_release_stale_jobs(self, db, brand, compile_run):
        """Stale running jobs are released for retry."""
        # Create job with old lock
        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            attempts=1,
            max_attempts=3,
            locked_at=timezone.now() - timedelta(minutes=15),
            locked_by="dead-worker",
        )

        released_count = release_stale_jobs(stale_threshold_minutes=10)

        assert released_count == 1
        job.refresh_from_db()
        assert job.status == BrandBrainJobStatus.PENDING
        assert job.locked_at is None
        assert job.locked_by is None
        assert "stale lock" in job.last_error.lower()

    def test_stale_job_fails_after_max_attempts(self, db, brand, compile_run):
        """Stale job with max attempts fails permanently."""
        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            attempts=3,
            max_attempts=3,
            locked_at=timezone.now() - timedelta(minutes=15),
            locked_by="dead-worker",
        )

        released_count = release_stale_jobs(stale_threshold_minutes=10)

        assert released_count == 1
        job.refresh_from_db()
        assert job.status == BrandBrainJobStatus.FAILED


# =============================================================================
# C2) JOB LOCK EXTENSION (HEARTBEAT)
# =============================================================================


@pytest.mark.db
class TestJobLockExtension:
    """Test job lock extension (heartbeat) functionality."""

    def test_extend_job_lock_updates_locked_at_for_owned_running_job(
        self, db, brand, compile_run
    ):
        """extend_job_lock updates locked_at for a job owned by the worker."""
        old_time = timezone.now() - timedelta(minutes=5)
        new_time = timezone.now()

        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            locked_at=old_time,
            locked_by="worker-1",
            attempts=1,
        )

        result = extend_job_lock(job.id, "worker-1", now=new_time)

        assert result is True
        job.refresh_from_db()
        assert job.locked_at == new_time
        # Status and locked_by should remain unchanged
        assert job.status == BrandBrainJobStatus.RUNNING
        assert job.locked_by == "worker-1"

    def test_extend_job_lock_noop_for_wrong_worker(self, db, brand, compile_run):
        """extend_job_lock returns False and doesn't change lock for wrong worker."""
        old_time = timezone.now() - timedelta(minutes=5)
        new_time = timezone.now()

        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            locked_at=old_time,
            locked_by="worker-1",
            attempts=1,
        )

        # Try to extend with different worker
        result = extend_job_lock(job.id, "worker-2", now=new_time)

        assert result is False
        job.refresh_from_db()
        # locked_at should be unchanged
        assert job.locked_at == old_time
        assert job.locked_by == "worker-1"

    def test_extend_job_lock_noop_for_non_running_status(self, db, brand, compile_run):
        """extend_job_lock returns False for jobs not in RUNNING status."""
        old_time = timezone.now() - timedelta(minutes=5)
        new_time = timezone.now()

        # Test with PENDING status
        job_pending = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.PENDING,
            locked_at=old_time,
            locked_by="worker-1",
        )

        result = extend_job_lock(job_pending.id, "worker-1", now=new_time)

        assert result is False
        job_pending.refresh_from_db()
        assert job_pending.locked_at == old_time

    def test_extend_job_lock_noop_for_nonexistent_job(self, db):
        """extend_job_lock returns False for nonexistent job."""
        fake_id = uuid.uuid4()
        result = extend_job_lock(fake_id, "worker-1")
        assert result is False


# =============================================================================
# D) INGESTION SERVICE (MOCKED APIFY)
# =============================================================================


@pytest.mark.db
class TestIngestionService:
    """Test ingestion service with mocked Apify."""

    def test_ingest_source_success(self, db, brand, source_instagram_posts):
        """Successful ingestion creates ApifyRun, raw items, and normalizes."""
        from kairo.brandbrain.ingestion import ingest_source
        from kairo.integrations.apify.client import ApifyClient, RunInfo
        from kairo.integrations.apify.models import ApifyRun, RawApifyItem

        # Mock Apify client
        mock_client = MagicMock(spec=ApifyClient)
        mock_client.start_actor_run.return_value = RunInfo(
            run_id="test-run-123",
            actor_id="apify~instagram-scraper",
            status="RUNNING",
            dataset_id="test-dataset-123",
            started_at=timezone.now(),
            finished_at=None,
        )
        mock_client.poll_run.return_value = RunInfo(
            run_id="test-run-123",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="test-dataset-123",
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        mock_client.fetch_dataset_items.return_value = [
            {
                "id": "12345",
                "url": "https://instagram.com/p/ABC123",
                "timestamp": "2024-01-15T10:00:00Z",
                "ownerUsername": "testbrand",
                "caption": "Test caption #hashtag",
                "likesCount": 100,
                "commentsCount": 10,
            },
            {
                "id": "67890",
                "url": "https://instagram.com/p/DEF456",
                "timestamp": "2024-01-16T10:00:00Z",
                "ownerUsername": "testbrand",
                "caption": "Another test",
                "likesCount": 50,
                "commentsCount": 5,
            },
        ]

        source_instagram_posts.brand_id = brand.id
        source_instagram_posts.save()

        result = ingest_source(source_instagram_posts, apify_client=mock_client)

        assert result.success is True
        assert result.apify_run_id is not None
        assert result.apify_run_status == "SUCCEEDED"
        assert result.raw_items_count == 2
        assert result.normalized_items_created + result.normalized_items_updated >= 0

        # Verify ApifyRun was created
        apify_run = ApifyRun.objects.get(id=result.apify_run_id)
        assert apify_run.status == "succeeded"
        assert apify_run.source_connection_id == source_instagram_posts.id
        assert apify_run.brand_id == brand.id

        # Verify raw items were stored
        raw_items = RawApifyItem.objects.filter(apify_run=apify_run)
        assert raw_items.count() == 2

    def test_ingest_source_disabled_capability(self, db, brand):
        """Ingestion fails for disabled capability."""
        from kairo.brandbrain.ingestion import ingest_source
        from kairo.brandbrain.models import SourceConnection

        # Create LinkedIn profile posts source (disabled by default)
        source = SourceConnection.objects.create(
            brand=brand,
            platform="linkedin",
            capability="profile_posts",
            identifier="testprofile",
            is_enabled=True,
        )

        result = ingest_source(source)

        assert result.success is False
        assert "disabled" in result.error.lower()

    def test_ingest_source_poll_timeout(self, db, brand, source_instagram_posts):
        """Ingestion handles poll timeout gracefully."""
        from kairo.brandbrain.ingestion import ingest_source
        from kairo.integrations.apify.client import ApifyClient, ApifyTimeoutError, RunInfo

        mock_client = MagicMock(spec=ApifyClient)
        mock_client.start_actor_run.return_value = RunInfo(
            run_id="test-run-timeout",
            actor_id="apify~instagram-scraper",
            status="RUNNING",
            dataset_id=None,
            started_at=timezone.now(),
            finished_at=None,
        )
        mock_client.poll_run.side_effect = ApifyTimeoutError("Polling timed out")

        source_instagram_posts.brand_id = brand.id
        source_instagram_posts.save()

        result = ingest_source(source_instagram_posts, apify_client=mock_client)

        assert result.success is False
        assert "timed out" in result.error.lower()
        assert result.apify_run_status == "timed_out"


# =============================================================================
# E) CAP ENFORCEMENT
# =============================================================================


@pytest.mark.db
class TestCapEnforcement:
    """Test that caps are enforced at actor input and dataset fetch."""

    def test_actor_input_uses_cap(self, db, brand, source_instagram_posts):
        """Actor input includes cap from cap_for()."""
        from kairo.brandbrain.ingestion import ingest_source
        from kairo.brandbrain.caps import cap_for
        from kairo.integrations.apify.client import ApifyClient, RunInfo

        mock_client = MagicMock(spec=ApifyClient)
        mock_client.start_actor_run.return_value = RunInfo(
            run_id="test-run",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="test-dataset",
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        mock_client.poll_run.return_value = mock_client.start_actor_run.return_value
        mock_client.fetch_dataset_items.return_value = []

        source_instagram_posts.brand_id = brand.id
        source_instagram_posts.save()

        expected_cap = cap_for("instagram", "posts")

        ingest_source(source_instagram_posts, apify_client=mock_client)

        # Verify actor input contains cap
        call_args = mock_client.start_actor_run.call_args
        input_json = call_args[0][1]  # Second positional arg
        assert "resultsLimit" in input_json
        assert input_json["resultsLimit"] == expected_cap

    def test_dataset_fetch_uses_cap(self, db, brand, source_instagram_posts):
        """Dataset fetch passes cap as limit."""
        from kairo.brandbrain.ingestion import ingest_source
        from kairo.brandbrain.caps import cap_for
        from kairo.integrations.apify.client import ApifyClient, RunInfo

        mock_client = MagicMock(spec=ApifyClient)
        mock_client.start_actor_run.return_value = RunInfo(
            run_id="test-run",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="test-dataset",
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        mock_client.poll_run.return_value = mock_client.start_actor_run.return_value
        mock_client.fetch_dataset_items.return_value = []

        source_instagram_posts.brand_id = brand.id
        source_instagram_posts.save()

        expected_cap = cap_for("instagram", "posts")

        ingest_source(source_instagram_posts, apify_client=mock_client)

        # Verify fetch used cap as limit
        mock_client.fetch_dataset_items.assert_called_once()
        call_kwargs = mock_client.fetch_dataset_items.call_args[1]
        assert call_kwargs["limit"] == expected_cap


# =============================================================================
# F) COMPILE WORKER WITH REAL INGESTION
# =============================================================================


@pytest.mark.db
class TestCompileWorkerIngestion:
    """Test compile worker with real ingestion (mocked Apify)."""

    def test_compile_triggers_ingestion_when_stale(
        self, db, brand_with_onboarding, source_instagram_posts
    ):
        """Compile triggers ingestion for stale sources."""
        from kairo.brandbrain.compile import compile_brandbrain
        from kairo.brandbrain.models import BrandBrainCompileRun

        # Associate source with brand
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Mock the ingest_source function
        with patch("kairo.brandbrain.compile.worker.ingest_source") as mock_ingest:
            from kairo.brandbrain.ingestion import IngestionResult

            mock_ingest.return_value = IngestionResult(
                source_connection_id=source_instagram_posts.id,
                success=True,
                apify_run_id=uuid.uuid4(),
                apify_run_status="SUCCEEDED",
                raw_items_count=5,
                normalized_items_created=5,
                normalized_items_updated=0,
            )

            result = compile_brandbrain(brand_with_onboarding.id, sync=True)

            # Verify compile succeeded
            assert result.status == "SUCCEEDED"

            # Verify ingestion was called
            mock_ingest.assert_called()

    def test_compile_reuses_fresh_source(
        self, db, brand_with_onboarding, source_instagram_posts
    ):
        """Compile reuses cached run for fresh sources."""
        from kairo.brandbrain.compile import compile_brandbrain
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus

        # Associate source with brand
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Create a fresh ApifyRun
        ApifyRun.objects.create(
            brand_id=brand_with_onboarding.id,
            source_connection_id=source_instagram_posts.id,
            actor_id="apify~instagram-scraper",
            apify_run_id="fresh-run-123",
            status=ApifyRunStatus.SUCCEEDED,
            input_json={},
            raw_item_count=5,
            normalized_item_count=5,
        )

        # Mock the ingest_source function to verify it's NOT called
        with patch("kairo.brandbrain.compile.worker.ingest_source") as mock_ingest:
            result = compile_brandbrain(brand_with_onboarding.id, sync=True)

            # Compile should succeed
            assert result.status == "SUCCEEDED"

            # Ingestion should NOT be called (fresh source)
            mock_ingest.assert_not_called()


# =============================================================================
# G) EVIDENCE STATUS TRACKING
# =============================================================================


@pytest.mark.db
class TestEvidenceStatusTracking:
    """Test evidence status tracking during compile."""

    def test_evidence_status_refreshed(self, db, brand_with_onboarding, source_instagram_posts):
        """Evidence status records refreshed sources."""
        from kairo.brandbrain.compile import compile_brandbrain
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        with patch("kairo.brandbrain.compile.worker.ingest_source") as mock_ingest:
            from kairo.brandbrain.ingestion import IngestionResult

            mock_ingest.return_value = IngestionResult(
                source_connection_id=source_instagram_posts.id,
                success=True,
                apify_run_id=uuid.uuid4(),
                apify_run_status="SUCCEEDED",
                raw_items_count=5,
                normalized_items_created=5,
                normalized_items_updated=0,
            )

            result = compile_brandbrain(brand_with_onboarding.id, sync=True)

        compile_run = BrandBrainCompileRun.objects.get(id=result.compile_run_id)
        evidence = compile_run.evidence_status_json

        assert len(evidence["refreshed"]) > 0
        refreshed_sources = [s["source"] for s in evidence["refreshed"]]
        assert "instagram.posts" in refreshed_sources

    def test_evidence_status_reused(self, db, brand_with_onboarding, source_instagram_posts):
        """Evidence status records reused sources."""
        from kairo.brandbrain.compile import compile_brandbrain
        from kairo.brandbrain.models import BrandBrainCompileRun
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Create fresh run
        ApifyRun.objects.create(
            brand_id=brand_with_onboarding.id,
            source_connection_id=source_instagram_posts.id,
            actor_id="apify~instagram-scraper",
            apify_run_id="fresh-run",
            status=ApifyRunStatus.SUCCEEDED,
            input_json={},
        )

        result = compile_brandbrain(brand_with_onboarding.id, sync=True)

        compile_run = BrandBrainCompileRun.objects.get(id=result.compile_run_id)
        evidence = compile_run.evidence_status_json

        assert len(evidence["reused"]) > 0
        reused_sources = [s["source"] for s in evidence["reused"]]
        assert "instagram.posts" in reused_sources

    def test_evidence_status_skipped_disabled(self, db, brand_with_onboarding):
        """Evidence status records skipped disabled sources."""
        from kairo.brandbrain.compile import compile_brandbrain
        from kairo.brandbrain.models import BrandBrainCompileRun, SourceConnection

        # Create LinkedIn profile posts source (disabled by default)
        SourceConnection.objects.create(
            brand=brand_with_onboarding,
            platform="linkedin",
            capability="profile_posts",
            identifier="testprofile",
            is_enabled=True,
        )

        # Also create an enabled source so compile can proceed
        SourceConnection.objects.create(
            brand=brand_with_onboarding,
            platform="instagram",
            capability="posts",
            identifier="testbrand",
            is_enabled=True,
        )

        with patch("kairo.brandbrain.compile.worker.ingest_source") as mock_ingest:
            from kairo.brandbrain.ingestion import IngestionResult

            mock_ingest.return_value = IngestionResult(
                source_connection_id=uuid.uuid4(),
                success=True,
                apify_run_id=uuid.uuid4(),
                apify_run_status="SUCCEEDED",
                raw_items_count=0,
            )

            result = compile_brandbrain(brand_with_onboarding.id, sync=True)

        compile_run = BrandBrainCompileRun.objects.get(id=result.compile_run_id)
        evidence = compile_run.evidence_status_json

        skipped_sources = [s["source"] for s in evidence["skipped"]]
        assert "linkedin.profile_posts" in skipped_sources


# =============================================================================
# H) CROSS-BRAND SECURITY
# =============================================================================


@pytest.fixture
def brand_b(db, tenant):
    """Create a second test brand for cross-brand tests."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand B",
        slug="test-brand-b",
    )


@pytest.mark.db
class TestCrossBrandSecurity:
    """Test that cross-brand security is preserved."""

    def test_get_job_status_respects_brand(self, db, brand, brand_b, compile_run):
        """Jobs are associated with specific brands."""
        result = enqueue_compile_job(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
        )

        job = get_job_status(result.job_id)
        assert job is not None
        assert job.brand_id == brand.id
        assert job.brand_id != brand_b.id

    def test_compile_status_requires_brand_match(
        self, db, brand_with_onboarding, brand_b, source_instagram_posts
    ):
        """Compile status enforces brand ownership."""
        from kairo.brandbrain.compile import compile_brandbrain, get_compile_status
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Create fresh run
        ApifyRun.objects.create(
            brand_id=brand_with_onboarding.id,
            source_connection_id=source_instagram_posts.id,
            actor_id="apify~instagram-scraper",
            apify_run_id="test-run",
            status=ApifyRunStatus.SUCCEEDED,
            input_json={},
        )

        result = compile_brandbrain(brand_with_onboarding.id, sync=True)

        # Correct brand can access
        status = get_compile_status(result.compile_run_id, brand_with_onboarding.id)
        assert status is not None

        # Wrong brand cannot access
        status_wrong = get_compile_status(result.compile_run_id, brand_b.id)
        assert status_wrong is None
