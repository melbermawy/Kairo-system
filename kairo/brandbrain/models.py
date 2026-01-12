"""
BrandBrain data models.

PR-1: Data Model + Migrations + Indexes.

Models per spec v2.4 Section 2:
- BrandOnboarding (1:1 with Brand)
- SourceConnection (per-platform source config)
- NormalizedEvidenceItem (stable seam between raw and compiled)
- EvidenceBundle (grouped evidence for compile)
- FeatureReport (deterministic stats from bundle)
- BrandBrainCompileRun (compile job tracking)
- BrandBrainOverrides (user overrides/pins, 1:1 with Brand)
- BrandBrainSnapshot (final compiled output)

Note: ApifyRun extension is in kairo/integrations/apify/models.py
"""

from __future__ import annotations

import uuid

from django.db import models

from kairo.core.models import Brand


# =============================================================================
# ONBOARDING
# =============================================================================


class BrandOnboarding(models.Model):
    """
    Tiered onboarding answers for a brand.

    Per spec Section 2.1:
    - 1:1 relationship with Brand
    - tier: 0, 1, or 2
    - answers_json: keyed by stable question_id
    """

    TIER_CHOICES = [
        (0, "Tier 0 - Required"),
        (1, "Tier 1 - Recommended"),
        (2, "Tier 2 - Optional"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.OneToOneField(
        Brand,
        on_delete=models.CASCADE,
        related_name="onboarding",
    )
    tier = models.PositiveSmallIntegerField(choices=TIER_CHOICES, default=0)
    answers_json = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.UUIDField(null=True, blank=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_onboarding"
        verbose_name = "Brand Onboarding"
        verbose_name_plural = "Brand Onboardings"

    def __str__(self) -> str:
        return f"Onboarding for {self.brand.name} (Tier {self.tier})"


# =============================================================================
# SOURCE CONNECTIONS
# =============================================================================


class SourceConnection(models.Model):
    """
    Configuration for a content source connection.

    Per spec Section 2.2:
    - Links a brand to a platform/capability with an identifier
    - settings_json for per-source knobs (e.g., extra_start_urls for web)

    PR-1: Identifier is normalized on save() to ensure uniqueness constraint works.
    """

    PLATFORM_CHOICES = [
        ("instagram", "Instagram"),
        ("linkedin", "LinkedIn"),
        ("tiktok", "TikTok"),
        ("youtube", "YouTube"),
        ("web", "Web"),
    ]

    CAPABILITY_CHOICES = [
        # Instagram
        ("posts", "Posts"),
        ("reels", "Reels"),
        # LinkedIn
        ("company_posts", "Company Posts"),
        ("profile_posts", "Profile Posts"),
        # TikTok
        ("profile_videos", "Profile Videos"),
        # YouTube
        ("channel_videos", "Channel Videos"),
        # Web
        ("crawl_pages", "Crawl Pages"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="source_connections",
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    capability = models.CharField(max_length=30, choices=CAPABILITY_CHOICES)
    identifier = models.CharField(max_length=500)  # handle/url/channel id
    is_enabled = models.BooleanField(default=True)
    settings_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_source_connection"
        indexes = [
            # Required per spec 1.2: enabled sources for brand
            models.Index(
                fields=["brand", "is_enabled"],
                name="idx_source_brand_enabled",
            ),
        ]
        constraints = [
            # Unique source per brand/platform/capability/identifier
            models.UniqueConstraint(
                fields=["brand", "platform", "capability", "identifier"],
                name="uniq_source_brand_platform_cap_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} - {self.platform}/{self.capability}: {self.identifier}"

    def save(self, *args, **kwargs):
        """Normalize identifier before saving to ensure uniqueness constraint works."""
        from kairo.brandbrain.identifiers import normalize_source_identifier

        self.identifier = normalize_source_identifier(
            self.platform, self.capability, self.identifier
        )
        super().save(*args, **kwargs)


# =============================================================================
# NORMALIZED EVIDENCE (Stable Seam)
# =============================================================================


class NormalizedEvidenceItem(models.Model):
    """
    Normalized evidence item from any platform.

    Per spec Section 2.3:
    - Actor-agnostic normalized layer
    - raw_refs points back to ApifyRun + RawApifyItem
    - Uniqueness constraints for dedupe

    Uniqueness:
    - UNIQUE(brand_id, platform, content_type, external_id) WHERE external_id IS NOT NULL
    - UNIQUE(brand_id, platform, content_type, canonical_url) WHERE platform='web'
    """

    PLATFORM_CHOICES = [
        ("instagram", "Instagram"),
        ("linkedin", "LinkedIn"),
        ("tiktok", "TikTok"),
        ("youtube", "YouTube"),
        ("web", "Web"),
    ]

    CONTENT_TYPE_CHOICES = [
        ("post", "Post"),
        ("reel", "Reel"),
        ("text_post", "Text Post"),
        ("short_video", "Short Video"),
        ("video", "Video"),
        ("web_page", "Web Page"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="normalized_evidence",
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    canonical_url = models.URLField(max_length=2000)
    published_at = models.DateTimeField(null=True, blank=True)
    author_ref = models.CharField(max_length=255)
    title = models.CharField(max_length=500, null=True, blank=True)
    text_primary = models.TextField()  # caption/body/title
    text_secondary = models.TextField(null=True, blank=True)  # description
    hashtags = models.JSONField(default=list)
    metrics_json = models.JSONField(default=dict)
    media_json = models.JSONField(default=dict)
    raw_refs = models.JSONField(default=list)  # [{apify_run_uuid, raw_item_id}]
    flags_json = models.JSONField(default=dict)  # {is_collection_page, has_transcript, is_low_value}
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_normalized_evidence_item"
        # =============================================================================
        # Expected Query Patterns (PR-4 Bundler will use these):
        # =============================================================================
        # Pattern A: Filter by (brand_id, platform, content_type), order by created_at
        #   → idx_nei_brand_recency covers this
        # Pattern B: Filter by (brand_id, platform, content_type), order by published_at
        #   → idx_nei_brand_published_ct (RunSQL) covers this
        # Pattern C: Filter by (brand_id, platform) only, order by published_at
        #   → idx_nei_brand_published (RunSQL) covers this - used when selecting
        #     across all content_types for a platform (e.g., "all Instagram content")
        # Pattern D: Filter by (brand_id, platform) for platform-level stats
        #   → idx_nei_brand_platform covers this
        # =============================================================================
        indexes = [
            # Pattern A: bundle selection by recency (created_at)
            models.Index(
                fields=["brand", "platform", "content_type", "-created_at"],
                name="idx_nei_brand_recency",
            ),
            # Pattern D: platform-level filtering/stats
            models.Index(
                fields=["brand", "platform"],
                name="idx_nei_brand_platform",
            ),
            # Note: Pattern B and C indexes are created via RunSQL in migrations
            # because Django ORM doesn't support DESC NULLS LAST natively.
        ]
        # Note: Partial unique constraints require RunSQL migration
        # Standard constraints added here for basic validation
        constraints = []

    def __str__(self) -> str:
        return f"{self.platform}/{self.content_type}: {self.canonical_url[:50]}"


# =============================================================================
# EVIDENCE BUNDLING
# =============================================================================


class EvidenceBundle(models.Model):
    """
    A bundle of evidence items selected for compilation.

    Per spec Section 2.4:
    - criteria_json: limits/heuristics used for selection
    - item_ids: array of NormalizedEvidenceItem.id
    - summary_json: counts per platform, coverage stats
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="evidence_bundles",
    )
    criteria_json = models.JSONField(default=dict)
    item_ids = models.JSONField(default=list)  # array of UUIDs
    summary_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_evidence_bundle"
        indexes = [
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_bundle_brand_created",
            ),
        ]

    def __str__(self) -> str:
        return f"Bundle for {self.brand.name} @ {self.created_at}"


class FeatureReport(models.Model):
    """
    Deterministic feature extraction from a bundle.

    Per spec Section 2.4:
    - stats_json: emoji density, CTA frequency, avg lengths, hook markers
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="feature_reports",
    )
    bundle = models.ForeignKey(
        EvidenceBundle,
        on_delete=models.CASCADE,
        related_name="feature_reports",
    )
    stats_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_feature_report"
        indexes = [
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_feature_brand_created",
            ),
        ]

    def __str__(self) -> str:
        return f"FeatureReport for {self.brand.name} @ {self.created_at}"


# =============================================================================
# COMPILE + OVERRIDES + SNAPSHOTS
# =============================================================================


class BrandBrainCompileRun(models.Model):
    """
    A single compile run for BrandBrain.

    Per spec Section 2.5:
    - Tracks compile job lifecycle: PENDING -> RUNNING -> SUCCEEDED/FAILED
    - evidence_status_json reports source usage (reused/refreshed/skipped/failed)
    """

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="compile_runs",
    )
    bundle = models.ForeignKey(
        EvidenceBundle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compile_runs",
    )
    onboarding_snapshot_json = models.JSONField(default=dict)
    prompt_version = models.CharField(max_length=50, default="v1")
    model = models.CharField(max_length=100, default="gpt-4")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    draft_json = models.JSONField(default=dict)
    qa_report_json = models.JSONField(default=dict)
    evidence_status_json = models.JSONField(default=dict)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_compile_run"
        indexes = [
            # Required per spec 1.2: latest compile run for short-circuit check
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_compile_brand_latest",
            ),
            # Required per spec 1.2: status lookup by PK is automatic
        ]

    def __str__(self) -> str:
        return f"CompileRun {self.id} for {self.brand.name} ({self.status})"


class BrandBrainOverrides(models.Model):
    """
    User overrides and pinned fields for a brand.

    Per spec Section 2.5:
    - 1:1 relationship with Brand
    - overrides_json: field_path -> override_value
    - pinned_paths: array of field_paths that should persist across recompiles
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.OneToOneField(
        Brand,
        on_delete=models.CASCADE,
        related_name="brandbrain_overrides",
    )
    overrides_json = models.JSONField(default=dict)
    pinned_paths = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.UUIDField(null=True, blank=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_overrides"
        verbose_name = "BrandBrain Overrides"
        verbose_name_plural = "BrandBrain Overrides"

    def __str__(self) -> str:
        return f"Overrides for {self.brand.name}"


class BrandBrainSnapshot(models.Model):
    """
    Final compiled BrandBrain snapshot.

    Per spec Section 2.5:
    - snapshot_json: the full BrandBrain schema
    - diff_from_previous_json: what changed from last snapshot
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="brandbrain_snapshots",
    )
    compile_run = models.ForeignKey(
        BrandBrainCompileRun,
        on_delete=models.SET_NULL,
        null=True,
        related_name="snapshots",
    )
    snapshot_json = models.JSONField(default=dict)
    diff_from_previous_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_snapshot"
        indexes = [
            # Required per spec 1.2: latest snapshot lookup
            # Note: INCLUDE columns require RunSQL migration
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_snapshot_brand_latest",
            ),
        ]

    def __str__(self) -> str:
        return f"Snapshot for {self.brand.name} @ {self.created_at}"
