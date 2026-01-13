"""
Deterministic feature extraction for FeatureReport.

PR-4: Stats computed from evidence bundle with no ML or randomness.

All operations are deterministic - same input always produces same output.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kairo.brandbrain.models import NormalizedEvidenceItem

# =============================================================================
# FEATURE EXTRACTION CONSTANTS
# =============================================================================

# CTA keywords (deterministic list)
# Common call-to-action patterns found in social media content
CTA_KEYWORDS = frozenset([
    # Action CTAs
    "click", "tap", "swipe", "link in bio", "check out", "sign up",
    "subscribe", "follow", "share", "like", "comment", "dm me",
    "book now", "buy now", "shop now", "get started", "learn more",
    "download", "register", "join", "contact", "visit",
    # Question CTAs
    "what do you think", "let me know", "tell me", "drop a comment",
    "agree or disagree", "thoughts?",
])

# Hook marker patterns (deterministic list)
# Phrases that signal hook-style content openings
HOOK_MARKERS = frozenset([
    "here's how", "here is how", "here's why", "here is why",
    "3 ways", "5 ways", "7 ways", "10 ways",  # Common listicle counts
    "stop doing", "stop saying", "start doing",
    "the truth about", "nobody tells you",
    "unpopular opinion", "hot take",
    "secret to", "key to", "trick to",
    "you need to", "you should", "you must",
    "biggest mistake", "common mistake",
    "what i learned", "how i", "how to",
    "never", "always", "finally",
])

# Emoji regex pattern (covers most common emoji ranges)
# Using a simplified pattern that catches most Unicode emojis
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbols & pictographs
    "\U0001F680-\U0001F6FF"  # Transport & map
    "\U0001F1E0-\U0001F1FF"  # Flags
    "\U00002702-\U000027B0"  # Dingbats
    "\U0001F900-\U0001F9FF"  # Supplemental symbols
    "\U0001FA00-\U0001FA6F"  # Chess symbols
    "\U0001FA70-\U0001FAFF"  # Symbols extended-A
    "\U00002600-\U000026FF"  # Misc symbols
    "\U00002300-\U000023FF"  # Misc technical
    "]+",
    flags=re.UNICODE,
)


# =============================================================================
# FEATURE EXTRACTION FUNCTIONS
# =============================================================================


def extract_text_stats(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract text statistics from evidence items.

    Returns:
        Dict with avg_text_primary_length per platform
    """
    # Group by platform
    platform_texts: dict[str, list[int]] = {}

    for item in items:
        platform = item.platform
        text = item.text_primary or ""
        length = len(text)

        if platform not in platform_texts:
            platform_texts[platform] = []
        platform_texts[platform].append(length)

    # Compute averages
    result = {}
    for platform, lengths in platform_texts.items():
        if lengths:
            result[platform] = {
                "avg_text_primary_length": sum(lengths) / len(lengths),
                "min_length": min(lengths),
                "max_length": max(lengths),
                "item_count": len(lengths),
            }

    return result


def compute_emoji_density(text: str) -> float:
    """
    Compute emoji density as emoji_count / char_count.

    Args:
        text: Text to analyze

    Returns:
        Float density (0.0 if no characters)
    """
    if not text:
        return 0.0

    emoji_matches = EMOJI_PATTERN.findall(text)
    emoji_count = sum(len(match) for match in emoji_matches)
    char_count = len(text)

    if char_count == 0:
        return 0.0

    return emoji_count / char_count


def extract_emoji_stats(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract emoji usage statistics.

    Returns:
        Dict with emoji density stats per platform and overall
    """
    platform_densities: dict[str, list[float]] = {}
    all_densities: list[float] = []

    for item in items:
        platform = item.platform
        text = item.text_primary or ""
        density = compute_emoji_density(text)

        if platform not in platform_densities:
            platform_densities[platform] = []
        platform_densities[platform].append(density)
        all_densities.append(density)

    result = {
        "by_platform": {},
        "overall_avg_density": sum(all_densities) / len(all_densities) if all_densities else 0.0,
    }

    for platform, densities in platform_densities.items():
        result["by_platform"][platform] = {
            "avg_density": sum(densities) / len(densities) if densities else 0.0,
            "max_density": max(densities) if densities else 0.0,
            "items_with_emoji": sum(1 for d in densities if d > 0),
        }

    return result


def count_cta_occurrences(text: str) -> int:
    """
    Count CTA keyword occurrences in text.

    Args:
        text: Text to analyze

    Returns:
        Count of CTA matches
    """
    if not text:
        return 0

    text_lower = text.lower()
    count = 0
    for keyword in CTA_KEYWORDS:
        # Count non-overlapping occurrences
        count += text_lower.count(keyword)

    return count


def extract_cta_stats(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract CTA (call-to-action) frequency statistics.

    Returns:
        Dict with CTA counts and frequencies
    """
    platform_cta_counts: dict[str, list[int]] = {}
    all_counts: list[int] = []
    cta_keyword_freq: Counter = Counter()

    for item in items:
        platform = item.platform
        text = item.text_primary or ""
        count = count_cta_occurrences(text)

        if platform not in platform_cta_counts:
            platform_cta_counts[platform] = []
        platform_cta_counts[platform].append(count)
        all_counts.append(count)

        # Track which CTAs appear
        text_lower = text.lower()
        for keyword in CTA_KEYWORDS:
            if keyword in text_lower:
                cta_keyword_freq[keyword] += 1

    result = {
        "by_platform": {},
        "overall_avg_cta_count": sum(all_counts) / len(all_counts) if all_counts else 0.0,
        "items_with_cta": sum(1 for c in all_counts if c > 0),
        "total_items": len(all_counts),
        "top_ctas": dict(cta_keyword_freq.most_common(10)),
    }

    for platform, counts in platform_cta_counts.items():
        result["by_platform"][platform] = {
            "avg_cta_count": sum(counts) / len(counts) if counts else 0.0,
            "items_with_cta": sum(1 for c in counts if c > 0),
            "total_items": len(counts),
        }

    return result


def count_hashtags(hashtags: list) -> int:
    """Count hashtags in list."""
    if not hashtags:
        return 0
    return len(hashtags)


def extract_hashtag_stats(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract hashtag usage statistics.

    Returns:
        Dict with hashtag count distribution
    """
    platform_hashtag_counts: dict[str, list[int]] = {}
    all_counts: list[int] = []

    for item in items:
        platform = item.platform
        hashtags = item.hashtags or []
        count = count_hashtags(hashtags)

        if platform not in platform_hashtag_counts:
            platform_hashtag_counts[platform] = []
        platform_hashtag_counts[platform].append(count)
        all_counts.append(count)

    result = {
        "by_platform": {},
        "overall_avg_count": sum(all_counts) / len(all_counts) if all_counts else 0.0,
        "items_with_hashtags": sum(1 for c in all_counts if c > 0),
        "total_items": len(all_counts),
    }

    for platform, counts in platform_hashtag_counts.items():
        result["by_platform"][platform] = {
            "avg_count": sum(counts) / len(counts) if counts else 0.0,
            "max_count": max(counts) if counts else 0,
            "items_with_hashtags": sum(1 for c in counts if c > 0),
            "total_items": len(counts),
        }

    return result


def count_hook_markers(text: str) -> int:
    """
    Count hook marker occurrences in text.

    Args:
        text: Text to analyze

    Returns:
        Count of hook marker matches
    """
    if not text:
        return 0

    text_lower = text.lower()
    count = 0
    for marker in HOOK_MARKERS:
        if marker in text_lower:
            count += 1

    return count


def extract_hook_marker_stats(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract hook marker frequency statistics.

    Hook markers are phrases that signal hook-style content openings
    like "here's how", "3 ways", "stop doing", etc.

    Returns:
        Dict with hook marker counts and frequencies
    """
    platform_hook_counts: dict[str, list[int]] = {}
    all_counts: list[int] = []
    hook_marker_freq: Counter = Counter()

    for item in items:
        platform = item.platform
        text = item.text_primary or ""
        count = count_hook_markers(text)

        if platform not in platform_hook_counts:
            platform_hook_counts[platform] = []
        platform_hook_counts[platform].append(count)
        all_counts.append(count)

        # Track which hooks appear
        text_lower = text.lower()
        for marker in HOOK_MARKERS:
            if marker in text_lower:
                hook_marker_freq[marker] += 1

    result = {
        "by_platform": {},
        "overall_avg_hook_count": sum(all_counts) / len(all_counts) if all_counts else 0.0,
        "items_with_hooks": sum(1 for c in all_counts if c > 0),
        "total_items": len(all_counts),
        "top_hooks": dict(hook_marker_freq.most_common(10)),
    }

    for platform, counts in platform_hook_counts.items():
        result["by_platform"][platform] = {
            "avg_hook_count": sum(counts) / len(counts) if counts else 0.0,
            "items_with_hooks": sum(1 for c in counts if c > 0),
            "total_items": len(counts),
        }

    return result


def extract_transcript_coverage(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract transcript coverage statistics.

    Checks flags_json.has_transcript for each item.

    Returns:
        Dict with transcript coverage stats
    """
    platform_transcript: dict[str, dict] = {}
    total_with_transcript = 0
    total_items = len(items)

    for item in items:
        platform = item.platform
        flags = item.flags_json or {}
        has_transcript = flags.get("has_transcript", False)

        if platform not in platform_transcript:
            platform_transcript[platform] = {"with_transcript": 0, "total": 0}

        platform_transcript[platform]["total"] += 1
        if has_transcript:
            platform_transcript[platform]["with_transcript"] += 1
            total_with_transcript += 1

    result = {
        "by_platform": {},
        "overall_with_transcript": total_with_transcript,
        "overall_total": total_items,
        "overall_coverage": total_with_transcript / total_items if total_items > 0 else 0.0,
    }

    for platform, stats in platform_transcript.items():
        total = stats["total"]
        with_trans = stats["with_transcript"]
        result["by_platform"][platform] = {
            "with_transcript": with_trans,
            "total": total,
            "coverage": with_trans / total if total > 0 else 0.0,
        }

    return result


def extract_all_features(items: list["NormalizedEvidenceItem"]) -> dict:
    """
    Extract all feature statistics from evidence items.

    This is the main entry point for FeatureReport generation.
    All operations are deterministic.

    Args:
        items: List of NormalizedEvidenceItem to analyze

    Returns:
        Dict with all feature statistics
    """
    return {
        "text_stats": extract_text_stats(items),
        "emoji_stats": extract_emoji_stats(items),
        "cta_stats": extract_cta_stats(items),
        "hashtag_stats": extract_hashtag_stats(items),
        "hook_marker_stats": extract_hook_marker_stats(items),
        "transcript_coverage": extract_transcript_coverage(items),
    }
