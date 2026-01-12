"""Django admin configuration for ingestion models."""

from django.contrib import admin

from .models import (
    ArtifactClusterLink,
    CaptureRun,
    Cluster,
    ClusterBucket,
    EvidenceItem,
    NormalizedArtifact,
    Surface,
    TrendCandidate,
)


@admin.register(Surface)
class SurfaceAdmin(admin.ModelAdmin):
    """Admin for Surface model."""

    list_display = ["__str__", "platform", "surface_type", "is_enabled", "cadence_minutes", "last_capture_at"]
    list_filter = ["platform", "surface_type", "is_enabled"]
    search_fields = ["platform", "surface_type", "surface_key"]


@admin.register(CaptureRun)
class CaptureRunAdmin(admin.ModelAdmin):
    """Admin for CaptureRun model."""

    list_display = ["id", "surface", "status", "item_count", "started_at", "ended_at"]
    list_filter = ["status", "surface__platform"]
    ordering = ["-started_at"]


@admin.register(EvidenceItem)
class EvidenceItemAdmin(admin.ModelAdmin):
    """Admin for EvidenceItem model."""

    list_display = ["__str__", "platform", "item_type", "author_handle", "captured_at"]
    list_filter = ["platform", "item_type"]
    search_fields = ["platform_item_id", "author_handle", "text_content"]
    ordering = ["-captured_at"]


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    """Admin for Cluster model."""

    list_display = ["__str__", "cluster_key_type", "display_name", "first_seen_at", "last_seen_at"]
    list_filter = ["cluster_key_type"]
    search_fields = ["cluster_key", "display_name"]
    ordering = ["-last_seen_at"]


@admin.register(NormalizedArtifact)
class NormalizedArtifactAdmin(admin.ModelAdmin):
    """Admin for NormalizedArtifact model."""

    list_display = ["id", "evidence_item", "engagement_score", "created_at"]
    ordering = ["-created_at"]


@admin.register(ArtifactClusterLink)
class ArtifactClusterLinkAdmin(admin.ModelAdmin):
    """Admin for ArtifactClusterLink model."""

    list_display = ["id", "artifact", "cluster", "role", "key_type", "created_at"]
    list_filter = ["role", "key_type"]
    ordering = ["-created_at"]


@admin.register(ClusterBucket)
class ClusterBucketAdmin(admin.ModelAdmin):
    """Admin for ClusterBucket model."""

    list_display = ["cluster", "bucket_start", "artifact_count", "velocity", "acceleration"]
    list_filter = ["bucket_start"]
    ordering = ["-bucket_start"]


@admin.register(TrendCandidate)
class TrendCandidateAdmin(admin.ModelAdmin):
    """Admin for TrendCandidate model."""

    list_display = ["cluster", "status", "trend_score", "detected_at", "emit_count"]
    list_filter = ["status"]
    search_fields = ["cluster__display_name"]
    ordering = ["-trend_score"]
