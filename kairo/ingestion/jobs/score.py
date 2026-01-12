"""
Trend scoring and lifecycle job for ingestion pipeline.

Per ingestion_spec_v2.md §5: Stage 4 - Scoring + Lifecycle.
Per ingestion_spec_v2.md §9: Trend Detection + Lifecycle.

Scores clusters and manages TrendCandidate lifecycle:
1. Query recent buckets
2. Select scoring path (A: counter-based or B: sampling-based)
3. Compute trend score for each cluster
4. Promote clusters above threshold to TrendCandidate
5. Transition lifecycle states

Scoring Paths:
- Path A (counter-based): Uses platform counters (views/likes) when available
- Path B (sampling-based): Uses recurrence/breadth/velocity when no counters
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from django.db import transaction

from kairo.ingestion.models import Cluster, ClusterBucket, TrendCandidate

logger = logging.getLogger(__name__)

# Scoring thresholds
DETECTION_THRESHOLD = 50  # Minimum score to become a TrendCandidate
ACTIVE_THRESHOLD = 60     # Score to transition emerging -> active
LOOKBACK_HOURS = 6        # Hours of buckets to consider


def run_score() -> dict:
    """
    Run scoring and lifecycle job.

    Returns:
        Dict with counts
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=LOOKBACK_HOURS)

    # Find clusters with recent activity
    active_clusters = (
        ClusterBucket.objects.filter(bucket_start__gte=lookback)
        .values("cluster_id")
        .distinct()
    )

    candidates_created = 0
    candidates_updated = 0
    transitions = 0

    for cluster_data in active_clusters:
        cluster_id = cluster_data["cluster_id"]
        try:
            result = _score_cluster(cluster_id, now)
            if result == "created":
                candidates_created += 1
            elif result == "updated":
                candidates_updated += 1
            elif result == "transitioned":
                transitions += 1
        except Exception as e:
            logger.warning(
                "Failed to score cluster",
                extra={"cluster_id": str(cluster_id), "error": str(e)},
            )

    # Transition stale candidates
    stale_count = _transition_stale_candidates(now)

    logger.info(
        "Scoring job completed",
        extra={
            "candidates_created": candidates_created,
            "candidates_updated": candidates_updated,
            "transitions": transitions,
            "stale_count": stale_count,
        },
    )

    return {
        "candidates_created": candidates_created,
        "candidates_updated": candidates_updated,
        "transitions": transitions,
        "stale_count": stale_count,
    }


def _score_cluster(cluster_id, now: datetime) -> str:
    """
    Score a cluster and update/create TrendCandidate.

    Returns:
        "created", "updated", "transitioned", or "skipped"
    """
    cluster = Cluster.objects.get(id=cluster_id)
    buckets = list(
        ClusterBucket.objects.filter(
            cluster=cluster,
            bucket_start__gte=now - timedelta(hours=LOOKBACK_HOURS),
        ).order_by("bucket_start")
    )

    if not buckets:
        return "skipped"

    # Compute trend score
    trend_score, components = _compute_trend_score(cluster, buckets, now)

    # Check if passes false trend filters
    if not _passes_filters(cluster, buckets):
        return "skipped"

    # Below threshold: skip
    if trend_score < DETECTION_THRESHOLD:
        return "skipped"

    with transaction.atomic():
        # Get or create TrendCandidate
        candidate, created = TrendCandidate.objects.get_or_create(
            cluster=cluster,
            defaults={
                "detected_at": now,
                "trend_score": trend_score,
                "velocity_score": components.get("velocity", 0),
                "breadth_score": components.get("breadth", 0),
                "novelty_score": components.get("novelty", 0),
            },
        )

        if created:
            return "created"

        # Update scores
        candidate.trend_score = trend_score
        candidate.velocity_score = components.get("velocity", 0)
        candidate.breadth_score = components.get("breadth", 0)
        candidate.novelty_score = components.get("novelty", 0)

        # Lifecycle transitions
        old_status = candidate.status
        new_status = _determine_status(candidate, buckets)

        if new_status != old_status:
            candidate.status = new_status
            if new_status == "peaked":
                candidate.peaked_at = now
            elif new_status == "stale":
                candidate.stale_at = now
            candidate.save()
            return "transitioned"

        candidate.save()
        return "updated"


def select_scoring_path(bucket: ClusterBucket) -> str:
    """
    Select scoring path based on available data.

    Args:
        bucket: The bucket to evaluate

    Returns:
        "counters" for Path A, "sampling" for Path B
    """
    if bucket.total_views > 0 or bucket.total_engagement > 0:
        return "counters"
    return "sampling"


def _compute_trend_score(
    cluster: Cluster,
    buckets: list[ClusterBucket],
    now: datetime,
) -> tuple[float, dict]:
    """
    Compute trend score 0-100 using appropriate path.

    Path A (counter-based): When platform counters are available
    Path B (sampling-based): When no counters available
    """
    if not buckets:
        return 0, {"path": "none"}

    latest = buckets[-1]
    path = select_scoring_path(latest)

    if path == "counters":
        score, components = _compute_score_path_a(cluster, buckets, now)
    else:
        score, components = _compute_score_path_b(cluster, buckets, now)

    components["path"] = path
    return score, components


def _compute_score_path_a(
    cluster: Cluster,
    buckets: list[ClusterBucket],
    now: datetime,
) -> tuple[float, dict]:
    """
    Counter-based scoring (Path A).

    Used when platform counters are available (views, likes, etc.).
    Weights: engagement (35%) + velocity (25%) + breadth (20%) + novelty (20%)
    """
    latest = buckets[-1]

    # Engagement component (35%) - from platform counters
    views_norm = min(latest.total_views / 1_000_000, 1.0)  # 1M views = max
    engagement_norm = min(latest.total_engagement / 100_000, 1.0)  # 100K engagement = max
    engagement_score = ((views_norm + engagement_norm) / 2) * 35

    # Velocity component (25%)
    velocity_norm = min(max(latest.velocity, 0) / 10, 1.0)  # 10 artifacts/hr = max
    velocity_score = velocity_norm * 25

    # Breadth component (20%)
    breadth = latest.unique_authors / max(latest.artifact_count, 1)
    breadth_score = breadth * 20

    # Novelty component (20%)
    hours_since_first = (now - cluster.first_seen_at).total_seconds() / 3600
    novelty = max(0, 1 - hours_since_first / 168)  # 1 week = 168 hours
    novelty_score = novelty * 20

    total = engagement_score + velocity_score + breadth_score + novelty_score

    return total, {
        "engagement": engagement_score,
        "velocity": velocity_score,
        "breadth": breadth_score,
        "novelty": novelty_score,
    }


def _compute_score_path_b(
    cluster: Cluster,
    buckets: list[ClusterBucket],
    now: datetime,
) -> tuple[float, dict]:
    """
    Sampling-based scoring (Path B).

    Used when no counters available (Reddit, some scraped sources).
    Weights: velocity (40%) + breadth (30%) + novelty (20%) + volume (10%)
    """
    latest = buckets[-1]

    # Velocity component (40%) - primary signal when no counters
    velocity_norm = min(max(latest.velocity, 0) / 10, 1.0)  # 10 artifacts/hr = max
    velocity_score = velocity_norm * 40

    # Breadth component (30%) - author diversity
    breadth = latest.unique_authors / max(latest.artifact_count, 1)
    breadth_score = breadth * 30

    # Novelty component (20%)
    hours_since_first = (now - cluster.first_seen_at).total_seconds() / 3600
    novelty = max(0, 1 - hours_since_first / 168)  # 1 week = 168 hours
    novelty_score = novelty * 20

    # Volume/concentration component (10%)
    volume_norm = min(latest.artifact_count / 50, 1.0)  # 50 artifacts = max
    volume_score = volume_norm * 10

    total = velocity_score + breadth_score + novelty_score + volume_score

    return total, {
        "velocity": velocity_score,
        "breadth": breadth_score,
        "novelty": novelty_score,
        "volume": volume_score,
    }


def _passes_filters(cluster: Cluster, buckets: list[ClusterBucket]) -> bool:
    """
    Check if cluster passes false trend filters.

    Per spec §9: single-author, bot pattern, old trend, too small
    """
    if not buckets:
        return False

    latest = buckets[-1]

    # Too small
    if latest.artifact_count < 3:
        return False

    # Single-author (breadth < 0.2)
    breadth = latest.unique_authors / max(latest.artifact_count, 1)
    if breadth < 0.2 and latest.artifact_count > 5:
        return False

    return True


def _determine_status(
    candidate: TrendCandidate,
    buckets: list[ClusterBucket],
) -> str:
    """
    Determine lifecycle status based on velocity patterns.
    """
    if not buckets:
        return "stale"

    # Check for negative velocity streak
    negative_streak = 0
    for bucket in reversed(buckets[-3:]):
        if bucket.velocity < 0:
            negative_streak += 1
        else:
            break

    if negative_streak >= 2:
        if candidate.status in ("emerging", "active"):
            return "peaked"
        return candidate.status

    # Check for active threshold
    if candidate.trend_score >= ACTIVE_THRESHOLD:
        if candidate.status == "emerging":
            return "active"

    return candidate.status


def _transition_stale_candidates(now: datetime) -> int:
    """
    Transition candidates with no recent activity to stale.
    """
    stale_threshold = now - timedelta(hours=LOOKBACK_HOURS)

    stale_candidates = TrendCandidate.objects.filter(
        status__in=["emerging", "active", "peaked"],
        cluster__last_seen_at__lt=stale_threshold,
    )

    count = stale_candidates.update(status="stale", stale_at=now)
    return count
