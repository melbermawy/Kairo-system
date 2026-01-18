"""
Evidence Service: Read-only access to normalized evidence.

PR1: Evidence layer for opportunities v2.
Per opportunities_v1_prd.md §0.1 INV-2 - No Apify Calls on Request Path.

CRITICAL INVARIANTS:
1. This service ONLY reads from NormalizedEvidenceItem table
2. NO Apify calls, NO network calls
3. NO imports from kairo.integrations.apify
4. NO imports from kairo.brandbrain.ingestion

This is the seam between BrandBrain evidence ingestion and opportunities generation.
Evidence must be pre-ingested via BrandBrain compile before this service can access it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from kairo.brandbrain.models import NormalizedEvidenceItem

logger = logging.getLogger("kairo.hero.services.evidence")


# =============================================================================
# EVIDENCE DTO (Internal, not API contract)
# =============================================================================


@dataclass
class EvidenceItem:
    """
    Internal evidence item for generation pipeline.

    This is NOT the API contract (EvidenceDTO from dto.py).
    This is an internal representation for the generation pipeline.
    """

    id: UUID
    brand_id: UUID
    platform: str  # "instagram", "tiktok", "linkedin", "youtube", "web"
    content_type: str  # "post", "reel", "short_video", etc.
    external_id: str | None
    canonical_url: str
    published_at: datetime | None
    author_ref: str
    title: str | None
    text_primary: str
    text_secondary: str | None  # transcript
    hashtags: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)  # {likes, comments, views, ...}
    media: dict = field(default_factory=dict)  # {thumbnail_url, duration, ...}
    has_transcript: bool = False
    is_low_value: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, model: "NormalizedEvidenceItem") -> "EvidenceItem":
        """Create from NormalizedEvidenceItem model instance."""
        flags = model.flags_json or {}
        return cls(
            id=model.id,
            brand_id=model.brand_id,
            platform=model.platform,
            content_type=model.content_type,
            external_id=model.external_id,
            canonical_url=model.canonical_url,
            published_at=model.published_at,
            author_ref=model.author_ref,
            title=model.title,
            text_primary=model.text_primary or "",
            text_secondary=model.text_secondary,
            hashtags=model.hashtags or [],
            metrics=model.metrics_json or {},
            media=model.media_json or {},
            has_transcript=flags.get("has_transcript", False),
            is_low_value=flags.get("is_low_value", False),
            created_at=model.created_at,
        )


@dataclass
class EvidenceSummary:
    """Summary statistics for evidence collection."""

    total_items: int = 0
    platforms: dict[str, int] = field(default_factory=dict)
    items_with_text: int = 0
    items_with_transcript: int = 0
    transcript_coverage: float = 0.0
    oldest_item_age_hours: float | None = None
    newest_item_age_hours: float | None = None


@dataclass
class GetEvidenceResult:
    """Result of get_evidence_for_brand."""

    evidence: list[EvidenceItem]
    summary: EvidenceSummary


# =============================================================================
# EVIDENCE SERVICE
# =============================================================================


def get_evidence_for_brand(
    brand_id: UUID,
    *,
    max_items: int = 50,
    max_age_days: int = 30,
    platforms: list[str] | None = None,
) -> GetEvidenceResult:
    """
    Get normalized evidence items for a brand.

    CRITICAL: This function ONLY reads from NormalizedEvidenceItem table.
    NO Apify calls. NO network calls.

    Args:
        brand_id: UUID of the brand
        max_items: Maximum number of items to return (default 50)
        max_age_days: Maximum age of evidence in days (default 30)
        platforms: Optional list of platforms to filter (default: all)

    Returns:
        GetEvidenceResult with evidence items and summary
    """
    from datetime import timedelta

    from django.utils import timezone as dj_timezone

    from kairo.brandbrain.models import NormalizedEvidenceItem

    now = dj_timezone.now()
    cutoff = now - timedelta(days=max_age_days)

    # Build query
    queryset = (
        NormalizedEvidenceItem.objects
        .filter(
            brand_id=brand_id,
            created_at__gte=cutoff,
        )
        .order_by("-published_at", "-created_at")
    )

    if platforms:
        queryset = queryset.filter(platform__in=platforms)

    # Limit results
    records = list(queryset[:max_items])

    logger.debug(
        "Loaded %d evidence items for brand %s",
        len(records),
        brand_id,
    )

    # Convert to internal representation
    evidence = [EvidenceItem.from_model(r) for r in records]

    # Compute summary
    summary = _compute_summary(evidence, now)

    return GetEvidenceResult(
        evidence=evidence,
        summary=summary,
    )


def _compute_summary(evidence: list[EvidenceItem], now: datetime) -> EvidenceSummary:
    """Compute summary statistics for evidence collection."""
    if not evidence:
        return EvidenceSummary()

    platforms: dict[str, int] = {}
    items_with_text = 0
    items_with_transcript = 0
    oldest_time: datetime | None = None
    newest_time: datetime | None = None

    for e in evidence:
        # Platform counts
        platforms[e.platform] = platforms.get(e.platform, 0) + 1

        # Text counts
        if e.text_primary and len(e.text_primary.strip()) > 0:
            items_with_text += 1

        # Transcript counts
        if e.has_transcript or (e.text_secondary and len(e.text_secondary.strip()) > 0):
            items_with_transcript += 1

        # Age tracking
        if e.published_at:
            if oldest_time is None or e.published_at < oldest_time:
                oldest_time = e.published_at
            if newest_time is None or e.published_at > newest_time:
                newest_time = e.published_at

    # Ensure now is timezone-aware
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Compute ages
    oldest_age_hours = None
    newest_age_hours = None

    if oldest_time:
        if oldest_time.tzinfo is None:
            oldest_time = oldest_time.replace(tzinfo=timezone.utc)
        oldest_age_hours = (now - oldest_time).total_seconds() / 3600

    if newest_time:
        if newest_time.tzinfo is None:
            newest_time = newest_time.replace(tzinfo=timezone.utc)
        newest_age_hours = (now - newest_time).total_seconds() / 3600

    transcript_coverage = items_with_transcript / len(evidence) if evidence else 0.0

    return EvidenceSummary(
        total_items=len(evidence),
        platforms=platforms,
        items_with_text=items_with_text,
        items_with_transcript=items_with_transcript,
        transcript_coverage=transcript_coverage,
        oldest_item_age_hours=oldest_age_hours,
        newest_item_age_hours=newest_age_hours,
    )
