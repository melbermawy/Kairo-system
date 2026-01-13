"""
Engagement scoring for evidence items.

PR-4: Deterministic engagement scoring per platform.

All scoring is deterministic with stable fallbacks for missing metrics.
Missing metrics default to 0 to ensure consistent ordering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kairo.brandbrain.models import NormalizedEvidenceItem


# =============================================================================
# PLATFORM-SPECIFIC ENGAGEMENT WEIGHTS
# =============================================================================

# Weights define relative importance of each metric per platform
# All weights are normalized so scoring is comparable across platforms

ENGAGEMENT_WEIGHTS = {
    "instagram": {
        # Likes and comments are primary engagement signals
        "likes": 1.0,
        "comments": 3.0,  # Comments weighted higher - more engagement
        "views": 0.1,  # Views less significant for IG posts
    },
    "linkedin": {
        # LinkedIn uses reactions as primary metric
        "reactions": 1.0,
        "likes": 1.0,  # Likes often same as reactions
        "comments": 3.0,
        "reposts": 2.0,
    },
    "tiktok": {
        # TikTok: plays are high but less meaningful per unit
        "plays": 0.01,
        "likes": 1.0,
        "comments": 3.0,
        "shares": 4.0,  # Shares very valuable on TikTok
        "saves": 2.0,
    },
    "youtube": {
        # YouTube: views are high volume
        "views": 0.01,
        "likes": 1.0,
        "comments": 3.0,
    },
    "web": {
        # Web pages have no engagement metrics
        # Score defaults to 0, selection is by recency only
    },
}


def compute_engagement_score(item: "NormalizedEvidenceItem") -> float:
    """
    Compute a deterministic engagement score for an evidence item.

    Scoring is platform-specific using weighted sum of metrics.
    Missing metrics default to 0 for determinism.

    Args:
        item: NormalizedEvidenceItem to score

    Returns:
        Float engagement score (always >= 0)
    """
    platform = item.platform
    metrics = item.metrics_json or {}

    weights = ENGAGEMENT_WEIGHTS.get(platform, {})
    if not weights:
        return 0.0

    score = 0.0
    for metric_key, weight in weights.items():
        value = metrics.get(metric_key)
        if value is not None and isinstance(value, (int, float)):
            score += float(value) * weight

    return score


def compute_engagement_score_from_dict(platform: str, metrics: dict) -> float:
    """
    Compute engagement score from raw platform/metrics dict.

    Used when item is not yet a model instance.

    Args:
        platform: Platform name
        metrics: metrics_json dict

    Returns:
        Float engagement score (always >= 0)
    """
    weights = ENGAGEMENT_WEIGHTS.get(platform, {})
    if not weights:
        return 0.0

    score = 0.0
    for metric_key, weight in weights.items():
        value = metrics.get(metric_key)
        if value is not None and isinstance(value, (int, float)):
            score += float(value) * weight

    return score
