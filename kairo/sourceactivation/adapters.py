"""
SourceActivation Adapters.

PR-4: Convert EvidenceBundle to signals for opportunities graph.
Per PR-4 requirements: Engine splice via convert_evidence_bundle_to_signals().

This adapter converts EvidenceBundle items into the signal format
expected by the opportunities graph (ExternalSignalBundleDTO).

IMPORTANT:
- This is a pure transformation, no LLM calls
- Signals feed into the existing graph execution path
- Evidence items with transcripts are treated as high-value signals
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from kairo.hero.dto import (
    CompetitorPostSignalDTO,
    ExternalSignalBundleDTO,
    SocialMomentSignalDTO,
    TrendSignalDTO,
    WebMentionSignalDTO,
)
from kairo.sourceactivation.types import EvidenceBundle, EvidenceItemData

logger = logging.getLogger(__name__)


def convert_evidence_bundle_to_signals(
    evidence_bundle: EvidenceBundle,
) -> ExternalSignalBundleDTO:
    """
    Convert EvidenceBundle to ExternalSignalBundleDTO for graph consumption.

    PR-4: Engine splice - adapts evidence items to signal format.
    This allows the existing graph to consume evidence without changes.

    Mapping strategy:
    - High-engagement content -> TrendSignalDTO (trending topic)
    - Content with transcripts -> WebMentionSignalDTO (detailed content)
    - Regular content -> SocialMomentSignalDTO (social activity)

    Args:
        evidence_bundle: EvidenceBundle from SourceActivation

    Returns:
        ExternalSignalBundleDTO compatible with opportunities graph
    """
    now = datetime.now(timezone.utc)

    trends: list[TrendSignalDTO] = []
    web_mentions: list[WebMentionSignalDTO] = []
    competitor_posts: list[CompetitorPostSignalDTO] = []
    social_moments: list[SocialMomentSignalDTO] = []

    for item in evidence_bundle.items:
        # Calculate relevance score based on engagement
        relevance_score = _compute_relevance_score(item)

        # Route based on content characteristics
        if item.has_transcript:
            # Transcript content is high-value -> WebMention
            web_mentions.append(
                _item_to_web_mention(item, relevance_score)
            )
        elif relevance_score >= 70:
            # High engagement -> Trend
            trends.append(
                _item_to_trend(item, relevance_score)
            )
        else:
            # Regular content -> SocialMoment
            social_moments.append(
                _item_to_social_moment(item, relevance_score)
            )

    logger.info(
        "Converted %d evidence items to signals: trends=%d, mentions=%d, moments=%d",
        len(evidence_bundle.items),
        len(trends),
        len(web_mentions),
        len(social_moments),
    )

    return ExternalSignalBundleDTO(
        brand_id=evidence_bundle.brand_id,
        fetched_at=evidence_bundle.fetched_at or now,
        trends=trends,
        web_mentions=web_mentions,
        competitor_posts=competitor_posts,  # Not populated from own content
        social_moments=social_moments,
    )


def _compute_relevance_score(item: EvidenceItemData) -> float:
    """
    Compute relevance score (0-100) for an evidence item.

    Scoring factors:
    - Engagement metrics (views, likes, comments, shares)
    - Transcript presence (high-value signal)
    - Content length (more content = more signal)

    Args:
        item: EvidenceItemData

    Returns:
        Relevance score 0-100
    """
    score = 50.0  # Base score

    # Engagement boost
    if item.view_count:
        if item.view_count > 100000:
            score += 20
        elif item.view_count > 10000:
            score += 10
        elif item.view_count > 1000:
            score += 5

    if item.like_count:
        if item.like_count > 10000:
            score += 15
        elif item.like_count > 1000:
            score += 8
        elif item.like_count > 100:
            score += 3

    if item.comment_count:
        if item.comment_count > 500:
            score += 10
        elif item.comment_count > 100:
            score += 5
        elif item.comment_count > 10:
            score += 2

    # Transcript boost
    if item.has_transcript:
        score += 15

    # Content length boost
    text_len = len(item.text_primary or "")
    if text_len > 500:
        score += 5
    elif text_len > 200:
        score += 3

    return min(100.0, max(0.0, score))


def _item_to_trend(item: EvidenceItemData, relevance_score: float) -> TrendSignalDTO:
    """Convert evidence item to TrendSignalDTO."""
    # Extract topic from title or first sentence of text
    topic = item.title or (item.text_primary or "")[:100].split(".")[0]
    if not topic:
        topic = f"{item.platform} content from {item.author_ref}"

    # Compute recency
    recency_days = 0
    if item.published_at:
        delta = datetime.now(timezone.utc) - item.published_at
        recency_days = max(0, delta.days)

    return TrendSignalDTO(
        id=f"evidence:{item.platform}:{item.external_id or item.canonical_url[-20:]}",
        topic=topic[:200],  # Truncate
        source=f"sourceactivation_{item.platform}",
        relevance_score=relevance_score,
        recency_days=recency_days,
        url=item.canonical_url,
        snippet=(item.text_primary or "")[:200],
    )


def _item_to_web_mention(
    item: EvidenceItemData,
    relevance_score: float,
) -> WebMentionSignalDTO:
    """Convert evidence item to WebMentionSignalDTO."""
    title = item.title or f"Content from {item.author_ref}"

    # For items with transcripts, include transcript snippet
    snippet = item.text_secondary if item.has_transcript else (item.text_primary or "")
    snippet = snippet[:300] if snippet else ""

    return WebMentionSignalDTO(
        id=f"evidence:{item.platform}:{item.external_id or item.canonical_url[-20:]}",
        title=title[:200],
        source=f"{item.platform}:{item.author_ref}",
        url=item.canonical_url,
        snippet=snippet,
        published_at=item.published_at,
        relevance_score=relevance_score,
    )


def _item_to_social_moment(
    item: EvidenceItemData,
    relevance_score: float,
) -> SocialMomentSignalDTO:
    """Convert evidence item to SocialMomentSignalDTO."""
    # Build description from available content
    description = item.text_primary or item.title or f"Activity from {item.author_ref}"
    description = description[:200]

    # Compute recency in hours
    recency_hours = 0
    if item.published_at:
        delta = datetime.now(timezone.utc) - item.published_at
        recency_hours = max(0, int(delta.total_seconds() / 3600))

    # Map platform to Channel enum value
    from kairo.core.enums import Channel

    channel_map = {
        "instagram": Channel.INSTAGRAM,
        "tiktok": Channel.TIKTOK,
        "linkedin": Channel.LINKEDIN,
        "youtube": Channel.YOUTUBE,
    }
    channel = channel_map.get(item.platform.lower(), Channel.LINKEDIN)

    return SocialMomentSignalDTO(
        id=f"evidence:{item.platform}:{item.external_id or item.canonical_url[-20:]}",
        description=description,
        channel=channel,
        relevance_hint=f"Score: {relevance_score:.0f}",
        recency_hours=recency_hours,
        url=item.canonical_url,
    )


def select_evidence_for_opportunity(
    evidence_bundle: EvidenceBundle,
    max_items: int = 3,
) -> list[UUID]:
    """
    Select top evidence items for an opportunity.

    PR-4 requirement: Deterministic selection of evidence for opportunities.

    Selection strategy (per PR-4 prompt):
    1. Prefer items with transcript (high-value signal)
    2. Prefer higher view_count/like_count
    3. Stable fallback order (by canonical_url for determinism)

    Args:
        evidence_bundle: EvidenceBundle to select from
        max_items: Maximum number of items to select (default 3)

    Returns:
        List of EvidenceItem UUIDs (deterministic IDs)
    """
    from kairo.sourceactivation.fixtures.loader import generate_evidence_id

    if not evidence_bundle.items:
        return []

    # Score and sort items
    scored_items = []
    for item in evidence_bundle.items:
        score = 0

        # Prefer transcript items
        if item.has_transcript:
            score += 1000

        # Prefer higher engagement
        if item.view_count:
            score += min(item.view_count / 1000, 100)  # Cap at 100 points
        if item.like_count:
            score += min(item.like_count / 100, 50)  # Cap at 50 points

        # Stable tiebreaker: canonical_url (deterministic)
        scored_items.append((score, item.canonical_url, item))

    # Sort by score descending, then URL ascending for determinism
    scored_items.sort(key=lambda x: (-x[0], x[1]))

    # Select top items and generate deterministic IDs
    selected_ids = []
    for _, _, item in scored_items[:max_items]:
        evidence_id = generate_evidence_id(
            brand_id=evidence_bundle.brand_id,
            platform=item.platform,
            canonical_url=item.canonical_url,
        )
        selected_ids.append(evidence_id)

    return selected_ids
