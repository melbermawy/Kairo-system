"""
OpportunitiesJob: Durable job queue for opportunities generation.

PR1: Background execution infrastructure for opportunities v2.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

Job lifecycle: PENDING -> RUNNING -> SUCCEEDED/FAILED/INSUFFICIENT_EVIDENCE

CRITICAL INVARIANTS:
- Jobs are the ONLY place state transitions occur
- Jobs are brand-scoped and idempotent
- Jobs must be safe to re-run

This mirrors the BrandBrainJob pattern from PR-6 but is specific to
opportunities generation.
"""

from __future__ import annotations

import uuid

from django.db import models

from kairo.core.models import Brand


class OpportunitiesJobStatus:
    """
    Status constants for OpportunitiesJob.

    Job lifecycle: PENDING -> RUNNING -> terminal state
    Terminal states: SUCCEEDED, FAILED, INSUFFICIENT_EVIDENCE
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class OpportunitiesJob(models.Model):
    """
    Durable job queue for opportunities generation.

    PR1: DB-backed job queue for production durability.

    Job leasing:
    - Worker claims job by setting status=RUNNING, locked_at, locked_by
    - Atomic update ensures no double-claiming
    - Stale lock detection via locked_at threshold

    Retry policy:
    - max_attempts default 3
    - available_at for exponential backoff
    - last_error for debugging

    Terminal states:
    - SUCCEEDED: Generation completed, board is ready
    - FAILED: Generation failed (error, timeout, etc.)
    - INSUFFICIENT_EVIDENCE: Evidence gates blocked generation
    """

    STATUS_CHOICES = [
        (OpportunitiesJobStatus.PENDING, "Pending"),
        (OpportunitiesJobStatus.RUNNING, "Running"),
        (OpportunitiesJobStatus.SUCCEEDED, "Succeeded"),
        (OpportunitiesJobStatus.FAILED, "Failed"),
        (OpportunitiesJobStatus.INSUFFICIENT_EVIDENCE, "Insufficient Evidence"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="opportunities_jobs",
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=OpportunitiesJobStatus.PENDING,
        db_index=True,
    )

    # Link to resulting board (set on completion)
    board = models.ForeignKey(
        "hero.OpportunitiesBoard",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )

    # Retry tracking
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_error = models.TextField(null=True, blank=True)

    # Job leasing
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=255, null=True, blank=True)  # worker identifier

    # Scheduling
    available_at = models.DateTimeField(auto_now_add=True)  # for backoff scheduling

    # Job parameters
    params_json = models.JSONField(default=dict)  # force, first_run, etc.

    # Result diagnostics (for debugging/observability)
    result_json = models.JSONField(default=dict)  # timing, evidence_stats, etc.

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "hero"
        db_table = "hero_opportunities_job"
        indexes = [
            # Worker query: find next available job
            models.Index(
                fields=["status", "available_at"],
                name="idx_oppjob_status_available",
            ),
            # Brand job history
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_oppjob_brand_created",
            ),
        ]

    def __str__(self) -> str:
        return f"OpportunitiesJob {self.id} for {self.brand_id} [{self.status}]"
