"""
EvidenceItem: Normalized evidence from SourceActivation.

PR-3: Schema additive - new tables for SourceActivation.
Per opportunities_v1_prd.md Section D.3.2.

This model stores:
- Normalized content from Apify actors
- Source identification (platform, actor, recipe)
- Content fields (text, transcript, hashtags)
- Metrics (views, likes, comments, shares)
- Quality flags (has_transcript)
- Raw payload for debugging

IMPORTANT: This is schema-only for PR-3. No Apify execution logic.
EvidenceItems are immutable after creation.
"""

from __future__ import annotations

import uuid

from django.db import models


class EvidenceItem(models.Model):
    """
    Normalized evidence from SourceActivation.

    Immutable after creation. Referenced by Opportunity.evidence_ids (in metadata).

    Per PRD D.3.2 and B.5:
    - id UUID PK
    - activation_run FK -> ActivationRun
    - brand_id UUID
    - platform, actor_id, acquisition_stage, recipe_id
    - canonical_url, external_id, author_ref, title
    - text_primary, text_secondary, hashtags JSON
    - metrics: view_count, like_count, comment_count, share_count
    - published_at, fetched_at, created_at
    - has_transcript bool
    - raw_json JSON
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to activation run that created this item
    activation_run = models.ForeignKey(
        "hero.ActivationRun",
        on_delete=models.CASCADE,
        related_name="items",
    )

    # Brand scope
    brand_id = models.UUIDField()

    # Source identification
    platform = models.CharField(max_length=50)  # instagram, tiktok, youtube, linkedin
    actor_id = models.CharField(max_length=100)  # Apify actor ID
    acquisition_stage = models.PositiveSmallIntegerField()  # 1 or 2
    recipe_id = models.CharField(max_length=20)  # e.g., "IG-1", "TT-1"

    # Content identification
    canonical_url = models.URLField(max_length=2000)
    external_id = models.CharField(max_length=255, blank=True)  # Platform-specific ID
    author_ref = models.CharField(max_length=255)  # Username or handle
    title = models.CharField(max_length=500, blank=True)

    # Content
    text_primary = models.TextField()  # Caption, body, description
    text_secondary = models.TextField(blank=True)  # Transcript (high-value signal)
    hashtags = models.JSONField(default=list)

    # Metrics (all optional - different platforms provide different metrics)
    view_count = models.BigIntegerField(null=True, blank=True)
    like_count = models.BigIntegerField(null=True, blank=True)
    comment_count = models.BigIntegerField(null=True, blank=True)
    share_count = models.BigIntegerField(null=True, blank=True)

    # Timestamps
    published_at = models.DateTimeField(null=True, blank=True)  # When content was published
    fetched_at = models.DateTimeField()  # When we fetched it

    # Quality flags
    has_transcript = models.BooleanField(default=False)

    # Raw payload retention (for debugging)
    raw_json = models.JSONField(default=dict)

    # Record timestamp
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "hero"
        db_table = "hero_evidence_item"
        indexes = [
            # Per PRD D.3.2: (brand_id, created_at)
            models.Index(
                fields=["brand_id", "created_at"],
                name="idx_evidence_brand_created",
            ),
            # Per PRD D.3.2: (platform, fetched_at)
            models.Index(
                fields=["platform", "fetched_at"],
                name="idx_evidence_platform_fetched",
            ),
            # Join-friendly index for "evidence preview by ids" queries
            # Primary key is already indexed, but add composite for brand+id queries
            models.Index(
                fields=["brand_id", "id"],
                name="idx_evidence_brand_id",
            ),
        ]

    def __str__(self) -> str:
        return f"EvidenceItem {self.id} ({self.platform})"
