"""
Ingestion Pipeline Models.

Per ingestion_spec_v2.md §4: DB Schema.

Models:
- Surface: Scrape target definition
- CaptureRun: One execution of a capture job
- EvidenceItem: Raw scraped item (immutable)
- Cluster: Grouping key for related content
- NormalizedArtifact: Standardized artifact (no direct FK to cluster)
- ArtifactClusterLink: Join model for many-to-many clustering
- ClusterBucket: Time-windowed aggregation
- TrendCandidate: Cluster that exceeds detection thresholds
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Surface(models.Model):
    """
    Scrape target definition.

    Examples:
    - platform="tiktok", surface_type="discover", surface_key=""
    - platform="instagram", surface_type="hashtag", surface_key="marketing"
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.CharField(max_length=50)  # tiktok, instagram, x, reddit
    surface_type = models.CharField(max_length=100)  # discover, explore_reels, hashtag, trending
    surface_key = models.CharField(max_length=255, blank=True)  # hashtag value if applicable
    is_enabled = models.BooleanField(default=True)
    cadence_minutes = models.PositiveIntegerField(default=60)
    last_capture_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_surface"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "surface_type", "surface_key"],
                name="uniq_surface_identity",
            )
        ]

    def __str__(self) -> str:
        if self.surface_key:
            return f"{self.platform}:{self.surface_type}:{self.surface_key}"
        return f"{self.platform}:{self.surface_type}"


class CaptureRun(models.Model):
    """
    One execution of a capture job.

    Tracks status, timing, and item count for observability.
    """

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("partial", "Partial"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    surface = models.ForeignKey(Surface, on_delete=models.PROTECT, related_name="runs")
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="running")
    item_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ingestion_capture_run"
        indexes = [
            models.Index(fields=["surface", "started_at"]),
            models.Index(fields=["status", "started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.surface} @ {self.started_at.isoformat()}"


class EvidenceItem(models.Model):
    """
    Raw scraped item. Immutable after creation.

    Contains platform-native fields preserved from scrape.
    Unique constraint on (platform, platform_item_id) ensures idempotency.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture_run = models.ForeignKey(CaptureRun, on_delete=models.CASCADE, related_name="items")
    platform = models.CharField(max_length=50)  # tiktok, instagram, x, reddit
    platform_item_id = models.CharField(max_length=255)  # video_id, post_id, etc.
    item_type = models.CharField(max_length=50)  # video, post, audio, comment

    # Platform-native fields (nullable, platform-dependent)
    author_id = models.CharField(max_length=255, blank=True)
    author_handle = models.CharField(max_length=255, blank=True)
    text_content = models.TextField(blank=True)
    audio_id = models.CharField(max_length=255, blank=True)
    audio_title = models.CharField(max_length=500, blank=True)
    hashtags = models.JSONField(default=list, blank=True)  # list of strings
    view_count = models.BigIntegerField(null=True, blank=True)
    like_count = models.BigIntegerField(null=True, blank=True)
    comment_count = models.BigIntegerField(null=True, blank=True)
    share_count = models.BigIntegerField(null=True, blank=True)

    # Timestamps
    item_created_at = models.DateTimeField(null=True, blank=True)  # when posted on platform
    captured_at = models.DateTimeField(default=timezone.now)

    # Raw storage
    raw_json = models.JSONField(default=dict, blank=True)  # full platform response
    canonical_url = models.URLField(max_length=2000, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_evidence_item"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "platform_item_id"],
                name="uniq_platform_item",
            )
        ]
        indexes = [
            models.Index(fields=["platform", "audio_id"]),
            models.Index(fields=["platform", "captured_at"]),
            models.Index(fields=["capture_run", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.platform}:{self.platform_item_id}"


class Cluster(models.Model):
    """
    Grouping key for related content.

    Examples:
    - cluster_key_type="audio_id", cluster_key="tiktok:6851234567890123456"
    - cluster_key_type="hashtag", cluster_key="instagram:#marketing"
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster_key_type = models.CharField(max_length=50)  # audio_id, hashtag, phrase, entity
    cluster_key = models.CharField(max_length=500)  # the actual key value
    display_name = models.CharField(max_length=500)  # human-readable name
    platforms = models.JSONField(default=list, blank=True)  # platforms where this appears
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_cluster"
        constraints = [
            models.UniqueConstraint(
                fields=["cluster_key_type", "cluster_key"],
                name="uniq_cluster_key",
            )
        ]
        indexes = [
            models.Index(fields=["cluster_key_type", "last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.cluster_key_type}:{self.cluster_key}"


class NormalizedArtifact(models.Model):
    """
    Standardized artifact. Linked to clusters via ArtifactClusterLink.

    One-to-one with EvidenceItem. Contains normalized fields
    and engagement scores for aggregation.

    Note: No direct FK to Cluster. All cluster associations via ArtifactClusterLink.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_item = models.OneToOneField(
        EvidenceItem, on_delete=models.CASCADE, related_name="artifact"
    )

    # Normalized fields
    normalized_text = models.TextField(blank=True)
    engagement_score = models.FloatField(default=0)  # normalized 0-100

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_normalized_artifact"

    def __str__(self) -> str:
        return f"Artifact for {self.evidence_item}"

    def get_primary_cluster(self) -> "Cluster | None":
        """Return the primary cluster for this artifact."""
        link = self.cluster_links.filter(role="primary").first()
        return link.cluster if link else None


class ArtifactClusterLink(models.Model):
    """
    Join model linking NormalizedArtifact ↔ Cluster.

    Supports many-to-many clustering: each artifact has exactly 1 primary
    cluster and any number of secondary cluster links.

    Constraints:
    - Conditional unique on (artifact) where role="primary" ensures exactly one primary
    - Unique on (artifact, cluster, role) prevents duplicate links
    """

    ROLE_CHOICES = [
        ("primary", "Primary"),
        ("secondary", "Secondary"),
    ]
    KEY_TYPE_CHOICES = [
        ("audio_id", "Audio ID"),
        ("hashtag", "Hashtag"),
        ("phrase", "Phrase"),
        ("entity", "Entity"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(
        NormalizedArtifact, on_delete=models.CASCADE, related_name="cluster_links"
    )
    cluster = models.ForeignKey(
        Cluster, on_delete=models.PROTECT, related_name="artifact_links"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    key_type = models.CharField(max_length=50, choices=KEY_TYPE_CHOICES)
    key_value = models.CharField(max_length=500, blank=True)  # original extracted value
    rank = models.PositiveIntegerField(null=True, blank=True)  # ordering for secondary links
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_artifact_cluster_link"
        constraints = [
            # Each artifact can only have one primary role
            models.UniqueConstraint(
                fields=["artifact"],
                condition=models.Q(role="primary"),
                name="uniq_artifact_primary_role",
            ),
            # Prevent duplicate (artifact, cluster, role) combinations
            models.UniqueConstraint(
                fields=["artifact", "cluster", "role"],
                name="uniq_artifact_cluster_role",
            ),
        ]
        indexes = [
            models.Index(fields=["cluster", "created_at"]),
            models.Index(fields=["artifact", "role"]),
        ]

    def __str__(self) -> str:
        return f"{self.artifact} -> {self.cluster} ({self.role})"


class ClusterBucket(models.Model):
    """
    Time-windowed aggregation for a cluster.

    Contains metrics for velocity, breadth, and engagement
    within a specific time window (typically 60 minutes).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name="buckets")
    bucket_start = models.DateTimeField()
    bucket_end = models.DateTimeField()

    # Metrics
    artifact_count = models.PositiveIntegerField(default=0)
    unique_authors = models.PositiveIntegerField(default=0)
    total_views = models.BigIntegerField(default=0)
    total_engagement = models.BigIntegerField(default=0)
    avg_engagement_score = models.FloatField(default=0)

    # Velocity (calculated from previous bucket)
    velocity = models.FloatField(default=0)  # artifacts/hour change
    acceleration = models.FloatField(default=0)  # velocity change

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_cluster_bucket"
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "bucket_start"],
                name="uniq_cluster_bucket",
            )
        ]
        indexes = [
            models.Index(fields=["bucket_start", "velocity"]),
        ]

    def __str__(self) -> str:
        return f"{self.cluster} @ {self.bucket_start.isoformat()}"


class TrendCandidate(models.Model):
    """
    A cluster that exceeds detection thresholds.

    Eligible to become a trend signal for the hero loop.
    """

    STATUS_CHOICES = [
        ("emerging", "Emerging"),
        ("active", "Active"),
        ("peaked", "Peaked"),
        ("stale", "Stale"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name="trend_candidates")

    # Lifecycle
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="emerging")
    detected_at = models.DateTimeField(default=timezone.now)
    peaked_at = models.DateTimeField(null=True, blank=True)
    stale_at = models.DateTimeField(null=True, blank=True)

    # Scoring
    trend_score = models.FloatField(default=0)  # 0-100
    velocity_score = models.FloatField(default=0)
    breadth_score = models.FloatField(default=0)
    novelty_score = models.FloatField(default=0)

    # For hero integration
    last_emitted_at = models.DateTimeField(null=True, blank=True)
    emit_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_trend_candidate"
        indexes = [
            models.Index(fields=["status", "trend_score"]),
            models.Index(fields=["detected_at"]),
        ]

    def __str__(self) -> str:
        return f"Trend: {self.cluster.display_name} ({self.status})"
