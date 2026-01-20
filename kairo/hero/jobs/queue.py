"""
Opportunities Job Queue Service.

PR1: Durable job queue for opportunities generation.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

This module provides:
- enqueue_opportunities_job(): Create a new generation job
- claim_next_job(): Claim the next available job with atomic locking
- complete_job(): Mark a job as succeeded
- fail_job(): Mark a job as failed with retry/backoff logic
- fail_job_insufficient_evidence(): Mark job as insufficient_evidence (no retry)
- release_stale_jobs(): Release jobs with stale locks
- extend_job_lock(): Extend lock on a running job (heartbeat)

Job leasing ensures no double-execution:
- Worker claims job by atomic update: status=PENDING -> RUNNING
- Sets locked_at and locked_by for stale lock detection
- Stale locks (>10 min) are released and jobs become available
- Workers extend locks periodically via heartbeat

Terminal states:
- SUCCEEDED: Board generated successfully
- FAILED: Error during generation (after max retries)
- INSUFFICIENT_EVIDENCE: Evidence gates blocked generation (no retry)
"""

from __future__ import annotations

import logging
import socket
import uuid as uuid_module
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

if TYPE_CHECKING:
    from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default stale lock threshold (minutes)
DEFAULT_STALE_LOCK_MINUTES = 10

# Base backoff delay (seconds)
BACKOFF_BASE_SECONDS = 30

# Backoff multiplier (exponential)
BACKOFF_MULTIPLIER = 2


# =============================================================================
# RESULT TYPES
# =============================================================================


@dataclass
class EnqueueResult:
    """Result of enqueueing a job."""
    job_id: UUID
    brand_id: UUID


@dataclass
class ClaimResult:
    """Result of claiming a job."""
    job: "OpportunitiesJob | None"
    claimed: bool
    reason: str = ""


# =============================================================================
# JOB QUEUE OPERATIONS
# =============================================================================


def enqueue_opportunities_job(
    brand_id: UUID,
    *,
    force: bool = False,
    first_run: bool = False,
    mode: str | None = None,
) -> EnqueueResult:
    """
    Enqueue an opportunities generation job for background execution.

    Creates an OpportunitiesJob in PENDING status.

    PR-6: Mode selection rule:
    - force=True (POST /regenerate): live_cap_limited (if APIFY_ENABLED)
    - first_run=True (auto-enqueue): fixture_only (always)
    - Default: fixture_only

    Args:
        brand_id: UUID of the brand
        force: Whether this is a force regeneration (from POST /regenerate)
        first_run: Whether this is a first-run auto-enqueue (from GET with evidence)
        mode: Explicit mode override (if None, determined from force/first_run)

    Returns:
        EnqueueResult with job_id and brand_id
    """
    from kairo.core.guardrails import is_apify_enabled
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    # PR-6: Determine mode based on context
    if mode is None:
        if force and is_apify_enabled():
            # POST /regenerate with Apify enabled → live mode
            mode = "live_cap_limited"
        else:
            # First-run auto-enqueue or Apify disabled → fixture mode
            mode = "fixture_only"

    job = OpportunitiesJob.objects.create(
        brand_id=brand_id,
        status=OpportunitiesJobStatus.PENDING,
        params_json={
            "force": force,
            "first_run": first_run,
            "mode": mode,  # PR-6: Store mode in job params
        },
    )

    logger.info(
        "Enqueued opportunities job %s for brand %s (force=%s, first_run=%s, mode=%s)",
        job.id,
        brand_id,
        force,
        first_run,
        mode,
    )

    return EnqueueResult(
        job_id=job.id,
        brand_id=brand_id,
    )


def claim_next_job(
    worker_id: str | None = None,
) -> ClaimResult:
    """
    Claim the next available job with atomic locking.

    Uses optimistic locking pattern:
    1. Find jobs WHERE status=PENDING AND available_at <= now
    2. Update first one to status=RUNNING, set locked_at/locked_by
    3. Return the job if successful

    Args:
        worker_id: Identifier for this worker (defaults to hostname+uuid)

    Returns:
        ClaimResult with claimed job or None.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    if worker_id is None:
        worker_id = f"{socket.gethostname()}-{uuid_module.uuid4().hex[:8]}"

    now = timezone.now()

    with transaction.atomic():
        # Find next available job
        # Ordered by available_at (for backoff) then created_at (FIFO)
        job = (
            OpportunitiesJob.objects
            .filter(
                status=OpportunitiesJobStatus.PENDING,
                available_at__lte=now,
            )
            .order_by("available_at", "created_at")
            .first()
        )

        if not job:
            return ClaimResult(
                job=None,
                claimed=False,
                reason="No available jobs",
            )

        # Atomic claim: only succeeds if still PENDING
        rows_updated = OpportunitiesJob.objects.filter(
            id=job.id,
            status=OpportunitiesJobStatus.PENDING,
        ).update(
            status=OpportunitiesJobStatus.RUNNING,
            locked_at=now,
            locked_by=worker_id,
            attempts=F("attempts") + 1,
        )

        if rows_updated == 0:
            # Another worker claimed it first
            return ClaimResult(
                job=None,
                claimed=False,
                reason="Job claimed by another worker",
            )

        # Refresh the job to get updated values
        job.refresh_from_db()

        logger.info(
            "Claimed opportunities job %s for brand %s (attempt %d/%d, worker=%s)",
            job.id,
            job.brand_id,
            job.attempts,
            job.max_attempts,
            worker_id,
        )

        return ClaimResult(
            job=job,
            claimed=True,
            reason="",
        )


def complete_job(
    job_id: UUID,
    *,
    board_id: UUID | None = None,
    result_json: dict | None = None,
) -> bool:
    """
    Mark a job as succeeded.

    Args:
        job_id: UUID of the job to complete
        board_id: UUID of the resulting OpportunitiesBoard
        result_json: Diagnostics/timing data

    Returns:
        True if job was updated, False if not found or already completed.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    now = timezone.now()

    update_fields = {
        "status": OpportunitiesJobStatus.SUCCEEDED,
        "finished_at": now,
        "locked_at": None,
        "locked_by": None,
    }

    if board_id:
        update_fields["board_id"] = board_id

    if result_json:
        # We need to fetch and update result_json since it might need merging
        try:
            job = OpportunitiesJob.objects.get(id=job_id, status=OpportunitiesJobStatus.RUNNING)
            job.result_json = result_json
            job.status = OpportunitiesJobStatus.SUCCEEDED
            job.finished_at = now
            job.locked_at = None
            job.locked_by = None
            if board_id:
                job.board_id = board_id
            job.save()
            logger.info("Completed opportunities job %s", job_id)
            return True
        except OpportunitiesJob.DoesNotExist:
            logger.warning("Failed to complete job %s (not found or not running)", job_id)
            return False

    rows_updated = OpportunitiesJob.objects.filter(
        id=job_id,
        status=OpportunitiesJobStatus.RUNNING,
    ).update(**update_fields)

    if rows_updated > 0:
        logger.info("Completed opportunities job %s", job_id)
        return True

    logger.warning("Failed to complete job %s (not found or not running)", job_id)
    return False


def fail_job(job_id: UUID, error: str) -> bool:
    """
    Mark a job as failed with retry logic.

    If attempts < max_attempts:
    - Sets status back to PENDING
    - Sets available_at for exponential backoff
    - Stores error in last_error

    If attempts >= max_attempts:
    - Sets status to FAILED permanently
    - Stores error in last_error

    Args:
        job_id: UUID of the job
        error: Error message

    Returns:
        True if job was updated, False if not found.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    try:
        job = OpportunitiesJob.objects.get(id=job_id)
    except OpportunitiesJob.DoesNotExist:
        logger.warning("Job %s not found for fail", job_id)
        return False

    now = timezone.now()

    if job.attempts >= job.max_attempts:
        # Permanent failure
        job.status = OpportunitiesJobStatus.FAILED
        job.finished_at = now
        job.last_error = error
        job.locked_at = None
        job.locked_by = None
        job.save(update_fields=[
            "status", "finished_at", "last_error", "locked_at", "locked_by"
        ])
        logger.warning(
            "Job %s permanently failed after %d attempts: %s",
            job_id,
            job.attempts,
            error[:200],
        )
        return True

    # Retry with exponential backoff
    backoff_seconds = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** job.attempts)
    available_at = now + timedelta(seconds=backoff_seconds)

    job.status = OpportunitiesJobStatus.PENDING
    job.available_at = available_at
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    job.save(update_fields=[
        "status", "available_at", "last_error", "locked_at", "locked_by"
    ])

    logger.info(
        "Job %s scheduled for retry (attempt %d/%d, available at %s): %s",
        job_id,
        job.attempts,
        job.max_attempts,
        available_at.isoformat(),
        error[:200],
    )
    return True


def fail_job_insufficient_evidence(
    job_id: UUID,
    *,
    board_id: UUID | None = None,
    result_json: dict | None = None,
) -> bool:
    """
    Mark a job as insufficient_evidence (no retry).

    This is a terminal state - evidence gates blocked synthesis.
    The job should not retry because evidence won't magically improve.

    Args:
        job_id: UUID of the job
        board_id: UUID of the resulting OpportunitiesBoard (with degraded state)
        result_json: Diagnostics including shortfall details

    Returns:
        True if job was updated, False if not found.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    now = timezone.now()

    try:
        job = OpportunitiesJob.objects.get(id=job_id)
    except OpportunitiesJob.DoesNotExist:
        logger.warning("Job %s not found for insufficient_evidence", job_id)
        return False

    job.status = OpportunitiesJobStatus.INSUFFICIENT_EVIDENCE
    job.finished_at = now
    job.locked_at = None
    job.locked_by = None
    if board_id:
        job.board_id = board_id
    if result_json:
        job.result_json = result_json
    job.save()

    logger.info(
        "Job %s completed with insufficient_evidence",
        job_id,
    )
    return True


def _create_error_board_for_stuck_job(
    job: "OpportunitiesJob",
    prev_locked_by: str | None,
) -> "OpportunitiesBoard | None":
    """
    PR1.1: Create an error board when a stuck job permanently fails.

    This ensures GET /today returns state=error with remediation instructions
    instead of staying in a limbo state.

    Args:
        job: The stuck job that is being marked as failed
        prev_locked_by: The worker that had the lock before it went stale

    Returns:
        The created OpportunitiesBoard or None if creation fails
    """
    from kairo.core.enums import TodayBoardState
    from kairo.hero.models import OpportunitiesBoard

    try:
        board = OpportunitiesBoard.objects.create(
            brand_id=job.brand_id,
            state=TodayBoardState.ERROR,
            ready_reason=None,  # Not applicable for error state
            opportunity_ids=[],
            evidence_summary_json={},
            evidence_shortfall_json={},
            remediation=(
                "Generation job failed after maximum retries. "
                "Try again by clicking Regenerate, or contact support if the issue persists."
            ),
            diagnostics_json={
                "error": "stuck_job_timeout",
                "job_id": str(job.id),
                "attempts": job.attempts,
                "last_worker": prev_locked_by,
            },
        )
        logger.info(
            "Created error board %s for stuck job %s (brand=%s)",
            board.id,
            job.id,
            job.brand_id,
        )
        return board
    except Exception as e:
        logger.error(
            "Failed to create error board for stuck job %s: %s",
            job.id,
            str(e),
        )
        return None


def release_stale_jobs(
    stale_threshold_minutes: int = DEFAULT_STALE_LOCK_MINUTES,
) -> int:
    """
    Release jobs with stale locks.

    Jobs with locked_at older than threshold are reset to PENDING
    for re-execution (if attempts < max_attempts).

    PR1.1: When a job permanently fails (max attempts reached), an error board
    is created so GET /today returns state=error with remediation instructions.

    This handles workers that crash or become unresponsive.

    Args:
        stale_threshold_minutes: Lock age threshold in minutes

    Returns:
        Number of jobs released.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    now = timezone.now()
    threshold = now - timedelta(minutes=stale_threshold_minutes)

    # Find stale running jobs
    stale_jobs = OpportunitiesJob.objects.filter(
        status=OpportunitiesJobStatus.RUNNING,
        locked_at__lt=threshold,
    )

    released_count = 0
    for job in stale_jobs:
        prev_locked_at = job.locked_at
        prev_locked_by = job.locked_by

        if job.attempts >= job.max_attempts:
            # Permanent failure due to stale lock
            # PR1.1: Create error board so GET /today returns error state
            error_board = _create_error_board_for_stuck_job(job, prev_locked_by)

            job.status = OpportunitiesJobStatus.FAILED
            job.finished_at = now
            job.last_error = f"Stale lock after {job.attempts} attempts"
            job.locked_at = None
            job.locked_by = None
            if error_board:
                job.board_id = error_board.id
            job.save(update_fields=[
                "status", "finished_at", "last_error", "locked_at", "locked_by", "board_id"
            ])
            logger.warning(
                "Job %s failed due to stale lock after max attempts "
                "(was locked since %s by %s, board=%s)",
                job.id,
                prev_locked_at,
                prev_locked_by,
                error_board.id if error_board else None,
            )
        else:
            # Release for retry
            job.status = OpportunitiesJobStatus.PENDING
            job.available_at = now
            job.last_error = f"Released from stale lock (was locked by {prev_locked_by})"
            job.locked_at = None
            job.locked_by = None
            job.save(update_fields=[
                "status", "available_at", "last_error", "locked_at", "locked_by"
            ])
            logger.info(
                "Released stale job %s for retry (was locked since %s by %s)",
                job.id,
                prev_locked_at,
                prev_locked_by,
            )
        released_count += 1

    return released_count


def extend_job_lock(
    job_id: UUID,
    worker_id: str,
) -> bool:
    """
    Extend the lock on a running job (heartbeat).

    Updates locked_at timestamp ONLY if:
    - Job exists with given job_id
    - Job status is RUNNING
    - Job is locked by the given worker_id

    Args:
        job_id: UUID of the job
        worker_id: Worker identifier (must match locked_by)

    Returns:
        True if lock was extended, False if job not found/not owned/not running.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    now = timezone.now()

    rows_updated = OpportunitiesJob.objects.filter(
        id=job_id,
        status=OpportunitiesJobStatus.RUNNING,
        locked_by=worker_id,
    ).update(locked_at=now)

    if rows_updated > 0:
        logger.debug(
            "Extended lock for job %s (worker=%s, locked_at=%s)",
            job_id,
            worker_id,
            now.isoformat(),
        )
        return True

    return False


def get_running_job_for_brand(brand_id: UUID) -> "OpportunitiesJob | None":
    """
    Get the currently running job for a brand.

    Args:
        brand_id: UUID of the brand

    Returns:
        OpportunitiesJob if a job is running, None otherwise.
    """
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    return (
        OpportunitiesJob.objects
        .filter(
            brand_id=brand_id,
            status__in=[OpportunitiesJobStatus.PENDING, OpportunitiesJobStatus.RUNNING],
        )
        .order_by("-created_at")
        .first()
    )
