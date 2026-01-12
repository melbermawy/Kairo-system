"""
Bucket aggregation job for ingestion pipeline.

Per ingestion_spec_v2.md §5: Stage 3 - Bucket Aggregation.

Aggregates NormalizedArtifacts into ClusterBuckets:
1. Determine current bucket window (aligned to hour)
2. Group artifacts by cluster (via ArtifactClusterLink)
3. Compute metrics: counts, velocity, acceleration
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from django.db.models import Avg, Count, Sum

from kairo.ingestion.models import ArtifactClusterLink, Cluster, ClusterBucket, NormalizedArtifact

logger = logging.getLogger(__name__)

# Bucket window size in minutes
BUCKET_WINDOW_MINUTES = 60


def run_aggregate(
    window_minutes: int = BUCKET_WINDOW_MINUTES,
    reference_time: datetime | None = None,
) -> dict:
    """
    Run bucket aggregation job.

    Args:
        window_minutes: Bucket window size (default 60)
        reference_time: Reference time for bucket alignment (default now)

    Returns:
        Dict with counts: {"buckets_updated": N, "clusters_processed": N}
    """
    now = reference_time or datetime.now(timezone.utc)
    bucket_start = _align_to_bucket(now, window_minutes)
    bucket_end = bucket_start + timedelta(minutes=window_minutes)

    # Find clusters with activity in current window via ArtifactClusterLink
    # Only consider primary links for aggregation
    active_clusters = (
        ArtifactClusterLink.objects.filter(
            role="primary",
            artifact__created_at__gte=bucket_start,
            artifact__created_at__lt=bucket_end,
        )
        .values("cluster_id")
        .distinct()
    )

    buckets_updated = 0
    clusters_processed = 0

    for cluster_data in active_clusters:
        cluster_id = cluster_data["cluster_id"]
        try:
            _aggregate_cluster_bucket(cluster_id, bucket_start, bucket_end)
            buckets_updated += 1
        except Exception as e:
            logger.warning(
                "Failed to aggregate bucket",
                extra={"cluster_id": str(cluster_id), "error": str(e)},
            )
        clusters_processed += 1

    logger.info(
        "Aggregation job completed",
        extra={
            "bucket_start": bucket_start.isoformat(),
            "buckets_updated": buckets_updated,
            "clusters_processed": clusters_processed,
        },
    )

    return {"buckets_updated": buckets_updated, "clusters_processed": clusters_processed}


def _align_to_bucket(dt: datetime, window_minutes: int) -> datetime:
    """
    Align datetime to bucket boundary.

    Example: 14:23 with 60-min window -> 14:00
    """
    minutes = dt.minute
    aligned_minutes = (minutes // window_minutes) * window_minutes
    return dt.replace(minute=aligned_minutes, second=0, microsecond=0)


def _aggregate_cluster_bucket(
    cluster_id,
    bucket_start: datetime,
    bucket_end: datetime,
) -> ClusterBucket:
    """
    Aggregate metrics for a cluster bucket.

    Uses ArtifactClusterLink to find artifacts linked to this cluster.
    """
    # Get artifact links for this cluster in this window (primary links only)
    links = ArtifactClusterLink.objects.filter(
        cluster_id=cluster_id,
        role="primary",
        artifact__created_at__gte=bucket_start,
        artifact__created_at__lt=bucket_end,
    ).select_related("artifact__evidence_item")

    # Compute metrics via links
    metrics = links.aggregate(
        artifact_count=Count("artifact_id", distinct=True),
        unique_authors=Count("artifact__evidence_item__author_id", distinct=True),
        total_views=Sum("artifact__evidence_item__view_count"),
        total_engagement=Sum("artifact__evidence_item__like_count"),
        avg_engagement_score=Avg("artifact__engagement_score"),
    )

    # Get previous bucket for velocity calculation
    prev_bucket_start = bucket_start - timedelta(minutes=BUCKET_WINDOW_MINUTES)
    try:
        prev_bucket = ClusterBucket.objects.get(
            cluster_id=cluster_id,
            bucket_start=prev_bucket_start,
        )
        prev_count = prev_bucket.artifact_count
        prev_velocity = prev_bucket.velocity
    except ClusterBucket.DoesNotExist:
        prev_count = 0
        prev_velocity = 0

    # Compute velocity and acceleration
    hours = BUCKET_WINDOW_MINUTES / 60
    velocity = (metrics["artifact_count"] - prev_count) / hours
    acceleration = (velocity - prev_velocity) / hours

    # Upsert bucket
    bucket, created = ClusterBucket.objects.update_or_create(
        cluster_id=cluster_id,
        bucket_start=bucket_start,
        defaults={
            "bucket_end": bucket_end,
            "artifact_count": metrics["artifact_count"] or 0,
            "unique_authors": metrics["unique_authors"] or 0,
            "total_views": metrics["total_views"] or 0,
            "total_engagement": metrics["total_engagement"] or 0,
            "avg_engagement_score": metrics["avg_engagement_score"] or 0,
            "velocity": velocity,
            "acceleration": acceleration,
        },
    )

    return bucket
