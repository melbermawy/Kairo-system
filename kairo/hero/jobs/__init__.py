"""
Kairo Hero Jobs.

PR1: Background execution infrastructure for opportunities v2.
"""

from .queue import (
    ClaimResult,
    EnqueueResult,
    claim_next_job,
    complete_job,
    extend_job_lock,
    fail_job,
    fail_job_insufficient_evidence,
    enqueue_opportunities_job,
    release_stale_jobs,
)

__all__ = [
    "ClaimResult",
    "EnqueueResult",
    "claim_next_job",
    "complete_job",
    "extend_job_lock",
    "fail_job",
    "fail_job_insufficient_evidence",
    "enqueue_opportunities_job",
    "release_stale_jobs",
]
