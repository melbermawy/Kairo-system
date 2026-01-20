"""
ActivationRun: Tracks one SourceActivation execution.

PR-3: Schema additive - new tables for SourceActivation.
Per opportunities_v1_prd.md Section D.3.2.

This model tracks:
- Which job triggered the activation
- Input snapshot and seed pack
- Recipes selected and executed
- Timing and outcome metrics
- Budget tracking via estimated_cost_usd

IMPORTANT: This is schema-only for PR-3. No Apify execution logic.
"""

from __future__ import annotations

import uuid

from django.db import models


class ActivationRun(models.Model):
    """
    One execution of SourceActivation.

    Links to OpportunitiesJob. Tracks recipes executed, result counts,
    and estimated cost.

    Per PRD D.3.2:
    - id UUID PK
    - job FK -> OpportunitiesJob
    - brand_id UUID
    - snapshot_id UUID
    - seed_pack_json JSON
    - recipes_selected JSON list
    - recipes_executed JSON list
    - started_at, ended_at
    - item_count, items_with_transcript
    - estimated_cost_usd Decimal
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to job that triggered this activation
    # PR-4b: Per PRD §D.3.2 - Required FK for ledger traceability
    # SourceActivation must ONLY be invoked from job execution context
    job = models.ForeignKey(
        "hero.OpportunitiesJob",
        on_delete=models.CASCADE,
        related_name="activation_runs",
    )

    # Brand scope
    brand_id = models.UUIDField(db_index=True)

    # Input snapshot reference (BrandBrainSnapshot.id)
    snapshot_id = models.UUIDField()

    # Seed pack used for this run (deterministic derivation from snapshot)
    seed_pack_json = models.JSONField(default=dict)

    # Recipe tracking
    recipes_selected = models.JSONField(default=list)  # ["IG-1", "IG-2", ...]
    recipes_executed = models.JSONField(default=list)  # ["IG-1", ...]

    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Outcome metrics
    item_count = models.PositiveIntegerField(default=0)
    items_with_transcript = models.PositiveIntegerField(default=0)

    # Budget tracking (per PRD G.1.3)
    # Stores estimated Apify cost for this run
    # max_digits=6, decimal_places=4 allows up to $99.9999
    estimated_cost_usd = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=0,
    )

    class Meta:
        app_label = "hero"
        db_table = "hero_activation_run"
        indexes = [
            # Query by brand for history
            models.Index(
                fields=["brand_id", "-started_at"],
                name="idx_actrun_brand_started",
            ),
            # Query by job for related runs
            models.Index(
                fields=["job", "-started_at"],
                name="idx_actrun_job_started",
            ),
        ]

    def __str__(self) -> str:
        return f"ActivationRun {self.id} for brand {self.brand_id}"
