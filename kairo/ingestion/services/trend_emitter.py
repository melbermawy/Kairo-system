"""
Trend emitter service for hero loop integration.

Per ingestion_spec_v2.md §11: Hero Integration.

Converts TrendCandidates to TrendSignalDTOs for consumption
by the opportunities graph (F1).

Uses ArtifactClusterLink to find artifacts associated with clusters.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from kairo.hero.dto import ExternalSignalBundleDTO, TrendSignalDTO
from kairo.ingestion.models import ArtifactClusterLink, TrendCandidate

logger = logging.getLogger(__name__)


def get_trend_signals_for_brand(brand_id: str) -> list[TrendSignalDTO]:
    """
    Get trend signals relevant to a brand.

    Args:
        brand_id: Brand UUID to filter signals for

    Returns:
        List of TrendSignalDTO for active/emerging trends
    """
    # Query active trend candidates
    candidates = TrendCandidate.objects.filter(
        status__in=["emerging", "active"],
    ).select_related("cluster").order_by("-trend_score")[:20]

    signals = []
    for candidate in candidates:
        signal = _candidate_to_signal(candidate)
        signals.append(signal)

    return signals


def get_external_signal_bundle(brand_id: str) -> ExternalSignalBundleDTO:
    """
    Get complete external signal bundle for hero loop.

    This replaces the fixture-based implementation in
    kairo.hero.services.external_signals_service when mode="ingestion".

    IMPORTANT: Returns empty bundle if no candidates exist.
    NEVER falls back to fixtures.

    Args:
        brand_id: Brand UUID

    Returns:
        ExternalSignalBundleDTO with trend signals
    """
    trends = get_trend_signals_for_brand(brand_id)
    now = datetime.now(timezone.utc)

    # Parse brand_id to UUID, handle string input
    try:
        brand_uuid = UUID(brand_id) if isinstance(brand_id, str) else brand_id
    except ValueError:
        # Generate deterministic UUID for invalid input (testing only)
        brand_uuid = UUID(hashlib.md5(brand_id.encode()).hexdigest())

    return ExternalSignalBundleDTO(
        brand_id=brand_uuid,
        fetched_at=now,
        trends=trends,
        web_mentions=[],
        competitor_posts=[],
        social_moments=[],
    )


def _candidate_to_signal(candidate: TrendCandidate) -> TrendSignalDTO:
    """
    Convert TrendCandidate to TrendSignalDTO.

    Maps ingestion domain objects to hero loop DTOs.
    Uses ArtifactClusterLink to find best evidence item.
    """
    cluster = candidate.cluster
    now = datetime.now(timezone.utc)

    # Compute recency in days
    recency_days = (now - candidate.detected_at).days

    # Build URL from best evidence item via ArtifactClusterLink
    url = None
    snippet = f"Trending on {', '.join(cluster.platforms)}: {cluster.display_name}"

    # Find artifacts linked to this cluster (any role) and get best evidence
    best_link = (
        ArtifactClusterLink.objects
        .filter(cluster=cluster)
        .select_related("artifact__evidence_item")
        .order_by("-artifact__engagement_score")
        .first()
    )

    if best_link and best_link.artifact and best_link.artifact.evidence_item:
        evidence = best_link.artifact.evidence_item
        url = evidence.canonical_url or None
        if evidence.text_content:
            snippet = evidence.text_content[:200]

    return TrendSignalDTO(
        id=str(candidate.id),
        topic=cluster.display_name,
        source=cluster.platforms[0] if cluster.platforms else "unknown",
        relevance_score=candidate.trend_score / 100,  # Normalize to 0-1
        recency_days=recency_days,
        url=url,
        snippet=snippet,
    )
