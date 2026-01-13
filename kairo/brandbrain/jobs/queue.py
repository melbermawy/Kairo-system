"""
BrandBrain Job Queue Service.

PR-6: Durable job queue with leasing/locking.

This module provides:
- enqueue_compile_job(): Create a new compile job
- claim_next_job(): Claim the next available job with atomic locking
- complete_job(): Mark a job as succeeded
- fail_job(): Mark a job as failed with retry/backoff logic
- release_stale_jobs(): Release jobs with stale locks
- extend_job_lock(): Extend lock on a running job (heartbeat)

Job leasing ensures no double-execution:
- Worker claims job by atomic update: status=PENDING -> RUNNING
- Sets locked_at and locked_by for stale lock detection
- Stale locks (>10 min) are released and jobs become available
- Workers extend locks periodically via heartbeat to prevent stale release

Retry policy:
- Default max_attempts = 3
- Exponential backoff: 2^attempt * 30 seconds
- After max_attempts, job is marked FAILED permanently
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
from django.db.models import F, Q
from django.utils import timezone

if TYPE_CHECKING:
    from kairo.brandbrain.models import BrandBrainJob

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
    compile_run_id: UUID | None


@dataclass
class ClaimResult:
    """Result of claiming a job."""
    job: "BrandBrainJob | None"
    claimed: bool
    reason: str = ""


# =============================================================================
# JOB QUEUE OPERATIONS
# =============================================================================


def enqueue_compile_job(
    brand_id: UUID,
    compile_run_id: UUID,
    *,
    force_refresh: bool = False,
    prompt_version: str = "v1",
    model: str = "gpt-4",
) -> EnqueueResult:
    """
    Enqueue a compile job for background execution.

    Creates a BrandBrainJob in PENDING status.

    Args:
        brand_id: UUID of the brand
        compile_run_id: UUID of the associated BrandBrainCompileRun
        force_refresh: Whether to force refresh all sources
        prompt_version: Compile prompt version
        model: LLM model identifier

    Returns:
        EnqueueResult with job_id and compile_run_id
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    job = BrandBrainJob.objects.create(
        brand_id=brand_id,
        compile_run_id=compile_run_id,
        job_type="compile",
        status=BrandBrainJobStatus.PENDING,
        params_json={
            "force_refresh": force_refresh,
            "prompt_version": prompt_version,
            "model": model,
        },
    )

    logger.info(
        "Enqueued compile job %s for brand %s (compile_run=%s)",
        job.id,
        brand_id,
        compile_run_id,
    )

    return EnqueueResult(
        job_id=job.id,
        compile_run_id=compile_run_id,
    )


def claim_next_job(
    worker_id: str | None = None,
    job_type: str = "compile",
) -> ClaimResult:
    """
    Claim the next available job with atomic locking.

    Uses optimistic locking pattern:
    1. Find jobs WHERE status=PENDING AND available_at <= now
    2. Update first one to status=RUNNING, set locked_at/locked_by
    3. Return the job if successful

    SQLite compatibility:
    - Uses atomic transaction instead of SELECT FOR UPDATE
    - Single UPDATE with filter ensures no double-claiming

    Args:
        worker_id: Identifier for this worker (defaults to hostname+uuid)
        job_type: Type of job to claim (default: "compile")

    Returns:
        ClaimResult with claimed job or None.
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    if worker_id is None:
        worker_id = f"{socket.gethostname()}-{uuid_module.uuid4().hex[:8]}"

    now = timezone.now()

    with transaction.atomic():
        # Find next available job
        # Ordered by available_at (for backoff) then created_at (FIFO)
        job = (
            BrandBrainJob.objects
            .filter(
                job_type=job_type,
                status=BrandBrainJobStatus.PENDING,
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
        # This prevents race conditions even without SELECT FOR UPDATE
        rows_updated = BrandBrainJob.objects.filter(
            id=job.id,
            status=BrandBrainJobStatus.PENDING,
        ).update(
            status=BrandBrainJobStatus.RUNNING,
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
            "Claimed job %s for brand %s (attempt %d/%d, worker=%s)",
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


def complete_job(job_id: UUID) -> bool:
    """
    Mark a job as succeeded.

    Args:
        job_id: UUID of the job to complete

    Returns:
        True if job was updated, False if not found or already completed.
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    now = timezone.now()

    rows_updated = BrandBrainJob.objects.filter(
        id=job_id,
        status=BrandBrainJobStatus.RUNNING,
    ).update(
        status=BrandBrainJobStatus.SUCCEEDED,
        finished_at=now,
        locked_at=None,
        locked_by=None,
    )

    if rows_updated > 0:
        logger.info("Completed job %s", job_id)
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
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    try:
        job = BrandBrainJob.objects.get(id=job_id)
    except BrandBrainJob.DoesNotExist:
        logger.warning("Job %s not found for fail", job_id)
        return False

    now = timezone.now()

    if job.attempts >= job.max_attempts:
        # Permanent failure
        job.status = BrandBrainJobStatus.FAILED
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

    job.status = BrandBrainJobStatus.PENDING
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


def release_stale_jobs(
    stale_threshold_minutes: int = DEFAULT_STALE_LOCK_MINUTES,
) -> int:
    """
    Release jobs with stale locks.

    Jobs with locked_at older than threshold are reset to PENDING
    for re-execution (if attempts < max_attempts).

    This handles workers that crash or become unresponsive.

    Args:
        stale_threshold_minutes: Lock age threshold in minutes

    Returns:
        Number of jobs released.
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    now = timezone.now()
    threshold = now - timedelta(minutes=stale_threshold_minutes)

    # Find stale running jobs that can be retried
    stale_jobs = BrandBrainJob.objects.filter(
        status=BrandBrainJobStatus.RUNNING,
        locked_at__lt=threshold,
    )

    released_count = 0
    for job in stale_jobs:
        # Capture lock info before clearing for logging
        prev_locked_at = job.locked_at
        prev_locked_by = job.locked_by

        if job.attempts >= job.max_attempts:
            # Permanent failure due to stale lock
            job.status = BrandBrainJobStatus.FAILED
            job.finished_at = now
            job.last_error = f"Stale lock after {job.attempts} attempts"
            job.locked_at = None
            job.locked_by = None
            job.save(update_fields=[
                "status", "finished_at", "last_error", "locked_at", "locked_by"
            ])
            logger.warning(
                "Job %s failed due to stale lock after max attempts "
                "(was locked since %s by %s)",
                job.id,
                prev_locked_at,
                prev_locked_by,
            )
        else:
            # Release for retry
            job.status = BrandBrainJobStatus.PENDING
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
    *,
    now: "datetime | None" = None,
) -> bool:
    """
    Extend the lock on a running job (heartbeat).

    Updates locked_at timestamp ONLY if:
    - Job exists with given job_id
    - Job status is RUNNING
    - Job is locked by the given worker_id

    This prevents stale lock detection from releasing jobs that are
    still actively being processed by a worker.

    Args:
        job_id: UUID of the job
        worker_id: Worker identifier (must match locked_by)
        now: Optional timestamp override (for testing)

    Returns:
        True if lock was extended, False if job not found/not owned/not running.
    """
    from datetime import datetime as dt
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    if now is None:
        now = timezone.now()

    rows_updated = BrandBrainJob.objects.filter(
        id=job_id,
        status=BrandBrainJobStatus.RUNNING,
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


def get_job_status(job_id: UUID) -> "BrandBrainJob | None":
    """
    Get job status by ID.

    Args:
        job_id: UUID of the job

    Returns:
        BrandBrainJob or None if not found.
    """
    from kairo.brandbrain.models import BrandBrainJob

    try:
        return BrandBrainJob.objects.get(id=job_id)
    except BrandBrainJob.DoesNotExist:
        return None
