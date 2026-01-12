"""
Normalization job for ingestion pipeline.

Per ingestion_spec_v2.md §5: Stage 2 - Normalize.

Processes EvidenceItems without artifacts:
1. Extract cluster key(s) based on platform/item_type
2. Upsert Cluster for each key (primary + secondary)
3. Create NormalizedArtifact linking to primary cluster
4. Create ArtifactClusterLink rows for all clusters
5. Compute engagement_score
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.db import transaction

from kairo.ingestion.models import (
    ArtifactClusterLink,
    Cluster,
    EvidenceItem,
    NormalizedArtifact,
)

logger = logging.getLogger(__name__)


def run_normalize() -> dict:
    """
    Run normalization job.

    Processes all EvidenceItems that don't have a NormalizedArtifact yet.

    Returns:
        Dict with counts: {"processed": N, "skipped": N, "errors": N}
    """
    items = EvidenceItem.objects.filter(artifact__isnull=True)
    processed = 0
    skipped = 0
    errors = 0

    for item in items:
        try:
            _normalize_item(item)
            processed += 1
        except Exception as e:
            logger.warning(
                "Failed to normalize item",
                extra={"item_id": str(item.id), "error": str(e)},
            )
            errors += 1

    logger.info(
        "Normalization job completed",
        extra={"processed": processed, "skipped": skipped, "errors": errors},
    )

    return {"processed": processed, "skipped": skipped, "errors": errors}


def _normalize_item(item: EvidenceItem) -> NormalizedArtifact:
    """
    Normalize a single EvidenceItem.

    Args:
        item: EvidenceItem to normalize

    Returns:
        Created NormalizedArtifact
    """
    with transaction.atomic():
        # Extract all cluster keys (primary + secondary)
        cluster_keys = _extract_all_cluster_keys(item)

        if not cluster_keys:
            raise ValueError(f"No cluster keys extracted for item {item.id}")

        # First key is primary, rest are secondary
        primary_key = cluster_keys[0]
        secondary_keys = cluster_keys[1:]

        now = datetime.now(timezone.utc)

        # Upsert primary cluster
        primary_cluster = _upsert_cluster(
            key_type=primary_key["key_type"],
            key=primary_key["key"],
            display_name=primary_key["display_name"],
            platform=item.platform,
            now=now,
        )

        # Compute engagement score
        engagement_score = _compute_engagement_score(item)

        # Create artifact (no direct FK to cluster)
        artifact = NormalizedArtifact.objects.create(
            evidence_item=item,
            normalized_text=item.text_content[:1000] if item.text_content else "",
            engagement_score=engagement_score,
        )

        # Create primary link
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=primary_cluster,
            role="primary",
            key_type=primary_key["key_type"],
            key_value=primary_key["raw_value"],
        )

        # Upsert secondary clusters and create links
        for rank, sec_key in enumerate(secondary_keys):
            sec_cluster = _upsert_cluster(
                key_type=sec_key["key_type"],
                key=sec_key["key"],
                display_name=sec_key["display_name"],
                platform=item.platform,
                now=now,
            )
            ArtifactClusterLink.objects.create(
                artifact=artifact,
                cluster=sec_cluster,
                role="secondary",
                key_type=sec_key["key_type"],
                key_value=sec_key["raw_value"],
                rank=rank,
            )

        return artifact


def _upsert_cluster(
    key_type: str,
    key: str,
    display_name: str,
    platform: str,
    now: datetime,
) -> Cluster:
    """Upsert a cluster and update its platforms list."""
    cluster, created = Cluster.objects.update_or_create(
        cluster_key_type=key_type,
        cluster_key=key,
        defaults={
            "display_name": display_name,
            "last_seen_at": now,
        },
    )

    # Update platforms list if needed
    if platform not in cluster.platforms:
        cluster.platforms = list(set(cluster.platforms + [platform]))
        cluster.save(update_fields=["platforms"])

    return cluster


def _extract_all_cluster_keys(item: EvidenceItem) -> list[dict]:
    """
    Extract all cluster keys from EvidenceItem.

    Returns list of dicts with keys:
    - key_type: audio_id, hashtag, phrase
    - key: formatted cluster key
    - display_name: human-readable name
    - raw_value: original extracted value

    First item is primary, rest are secondary.
    Priority for primary: audio_id > first hashtag > phrase
    """
    keys = []

    # Audio ID (primary if present)
    if item.audio_id:
        keys.append({
            "key_type": "audio_id",
            "key": f"{item.platform}:{item.audio_id}",
            "display_name": item.audio_title or f"Audio {item.audio_id[:8]}",
            "raw_value": item.audio_id,
        })

    # Hashtags (first one is primary if no audio_id, rest are secondary)
    if item.hashtags:
        for hashtag in item.hashtags:
            keys.append({
                "key_type": "hashtag",
                "key": f"{item.platform}:#{hashtag}",
                "display_name": f"#{hashtag}",
                "raw_value": f"#{hashtag}",
            })

    # Phrase fallback (only if nothing else available)
    if not keys and item.text_content:
        words = item.text_content.split()[:5]
        phrase = "_".join(words).lower()
        keys.append({
            "key_type": "phrase",
            "key": f"phrase:{phrase}",
            "display_name": " ".join(words),
            "raw_value": " ".join(words),
        })

    if not keys:
        raise ValueError("Cannot extract cluster key: no audio, hashtags, or text")

    return keys


def _compute_engagement_score(item: EvidenceItem) -> float:
    """
    Compute normalized engagement score 0-100.

    Simple heuristic based on available metrics.
    """
    import math

    # Normalize view count (log scale)
    views = item.view_count or 0
    if views > 0:
        view_score = min(math.log10(views) / 7 * 50, 50)  # 10M views = 50 points
    else:
        view_score = 0

    # Normalize like ratio
    likes = item.like_count or 0
    if views > 0 and likes > 0:
        ratio = likes / views
        ratio_score = min(ratio * 1000, 30)  # 3% ratio = 30 points
    else:
        ratio_score = 0

    # Comment bonus
    comments = item.comment_count or 0
    if comments > 100:
        comment_score = 20
    elif comments > 10:
        comment_score = 10
    else:
        comment_score = 0

    return min(view_score + ratio_score + comment_score, 100)
