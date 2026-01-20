"""
Apify Output Normalizers.

PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section B.5.

This module provides:
- normalize_actor_output(): Convert raw Apify output to EvidenceItemData
- Platform-specific normalizers for each actor

CRITICAL: Normalization is DETERMINISTIC and makes NO LLM calls (SA-4).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import requests

from kairo.sourceactivation.types import EvidenceItemData

logger = logging.getLogger(__name__)


# =============================================================================
# SUBTITLE FETCHING
# =============================================================================

def _fetch_subtitle_content(url: str, timeout: int = 10) -> str:
    """
    Fetch subtitle content from a URL.

    TikTok subtitle links return WebVTT or SRT format text.
    We parse out the actual text content, stripping timing info.

    Args:
        url: Subtitle file URL (tiktokLink from videoMeta.subtitleLinks)
        timeout: Request timeout in seconds

    Returns:
        Extracted text content, or empty string on failure
    """
    if not url:
        return ""

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        raw_content = response.text

        # Parse VTT/SRT format - extract just the text lines
        # VTT format has timing lines like "00:00:01.000 --> 00:00:04.000"
        # SRT format has timing lines like "00:00:01,000 --> 00:00:04,000"
        lines = raw_content.split("\n")
        text_lines = []

        for line in lines:
            line = line.strip()
            # Skip empty lines
            if not line:
                continue
            # Skip WEBVTT header
            if line.startswith("WEBVTT"):
                continue
            # Skip timing lines (contain -->)
            if "-->" in line:
                continue
            # Skip numeric index lines (SRT format)
            if line.isdigit():
                continue
            # Skip NOTE lines (VTT comments)
            if line.startswith("NOTE"):
                continue
            # Keep actual subtitle text
            text_lines.append(line)

        return " ".join(text_lines)

    except requests.RequestException as e:
        logger.warning("Failed to fetch subtitle from %s: %s", url[:100], str(e))
        return ""
    except Exception as e:
        logger.warning("Error parsing subtitle from %s: %s", url[:100], str(e))
        return ""


# =============================================================================
# MAIN NORMALIZER
# =============================================================================

def normalize_actor_output(
    raw_items: list[dict[str, Any]],
    actor_id: str,
    recipe_id: str,
    stage: int,
    run_id: UUID,
) -> list[EvidenceItemData]:
    """
    Normalize raw Apify actor output to EvidenceItemData.

    Per PRD B.5: Evidence is canonical, deterministic, normalized, uninterpreted.
    NO LLM calls occur here (SA-4).

    Args:
        raw_items: Raw items from Apify dataset
        actor_id: Actor that produced this output
        recipe_id: Recipe this belongs to
        stage: Acquisition stage (1 or 2)
        run_id: ActivationRun ID for correlation

    Returns:
        List of normalized EvidenceItemData
    """
    now = datetime.now(timezone.utc)
    results = []

    # Select normalizer based on actor
    normalizer = _get_normalizer_for_actor(actor_id)

    for raw in raw_items:
        try:
            item = normalizer(
                raw=raw,
                actor_id=actor_id,
                recipe_id=recipe_id,
                stage=stage,
                fetched_at=now,
            )
            if item:
                results.append(item)
        except Exception as e:
            logger.warning(
                "Failed to normalize item from %s: %s",
                actor_id,
                str(e),
            )
            continue

    logger.debug(
        "Normalized %d/%d items from %s",
        len(results),
        len(raw_items),
        actor_id,
    )

    return results


def _get_normalizer_for_actor(actor_id: str):
    """Get the appropriate normalizer function for an actor."""
    normalizers = {
        "apify/instagram-scraper": _normalize_instagram_item,
        "apify/instagram-reel-scraper": _normalize_instagram_reel_item,
        "clockworks/tiktok-scraper": _normalize_tiktok_item,
        "apimaestro/linkedin-company-posts": _normalize_linkedin_item,
        "streamers/youtube-scraper": _normalize_youtube_item,
    }

    return normalizers.get(actor_id, _normalize_generic_item)


# =============================================================================
# INSTAGRAM NORMALIZERS
# =============================================================================

def _normalize_instagram_item(
    raw: dict[str, Any],
    actor_id: str,
    recipe_id: str,
    stage: int,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Normalize Instagram scraper output (Stage 1).

    Expected fields from apify/instagram-scraper:
    - url, shortCode, id
    - ownerUsername, ownerFullName
    - caption
    - likesCount, commentsCount, videoViewCount
    - timestamp
    - productType (clips, feed, etc.)
    """
    url = raw.get("url")
    if not url:
        return None

    # Parse timestamp
    published_at = None
    timestamp = raw.get("timestamp")
    if timestamp:
        try:
            if isinstance(timestamp, str):
                published_at = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )
            elif isinstance(timestamp, (int, float)):
                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, TypeError):
            pass

    return EvidenceItemData(
        platform="instagram",
        actor_id=actor_id,
        acquisition_stage=stage,
        recipe_id=recipe_id,
        canonical_url=url,
        external_id=raw.get("shortCode") or raw.get("id", ""),
        author_ref=raw.get("ownerUsername", ""),
        title="",  # Instagram posts don't have titles
        text_primary=raw.get("caption", "") or "",
        text_secondary="",  # Stage 1 doesn't have transcripts
        hashtags=_extract_hashtags_from_caption(raw.get("caption", "")),
        view_count=raw.get("videoViewCount"),
        like_count=raw.get("likesCount"),
        comment_count=raw.get("commentsCount"),
        share_count=None,  # Not available from this actor
        published_at=published_at,
        fetched_at=fetched_at,
        has_transcript=False,
        raw_json=raw,
    )


def _normalize_instagram_reel_item(
    raw: dict[str, Any],
    actor_id: str,
    recipe_id: str,
    stage: int,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Normalize Instagram Reel scraper output (Stage 2).

    Expected fields from apify/instagram-reel-scraper:
    - url, shortCode, id
    - ownerUsername
    - caption
    - likesCount, commentsCount, videoViewCount
    - timestamp
    - transcript or transcription (high-value field)
    """
    url = raw.get("url")
    if not url:
        return None

    # Parse timestamp
    published_at = None
    timestamp = raw.get("timestamp")
    if timestamp:
        try:
            if isinstance(timestamp, str):
                published_at = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )
            elif isinstance(timestamp, (int, float)):
                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, TypeError):
            pass

    # Extract transcript (Stage 2 enrichment value)
    transcript = raw.get("transcript") or raw.get("transcription") or ""
    has_transcript = bool(transcript and len(transcript) > 10)

    return EvidenceItemData(
        platform="instagram",
        actor_id=actor_id,
        acquisition_stage=stage,
        recipe_id=recipe_id,
        canonical_url=url,
        external_id=raw.get("shortCode") or raw.get("id", ""),
        author_ref=raw.get("ownerUsername", ""),
        title="",
        text_primary=raw.get("caption", "") or "",
        text_secondary=transcript,  # The high-value enrichment
        hashtags=_extract_hashtags_from_caption(raw.get("caption", "")),
        view_count=raw.get("videoViewCount"),
        like_count=raw.get("likesCount"),
        comment_count=raw.get("commentsCount"),
        share_count=None,
        published_at=published_at,
        fetched_at=fetched_at,
        has_transcript=has_transcript,
        raw_json=raw,
    )


# =============================================================================
# TIKTOK NORMALIZERS
# =============================================================================

def _normalize_tiktok_item(
    raw: dict[str, Any],
    actor_id: str,
    recipe_id: str,
    stage: int,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Normalize TikTok scraper output.

    Expected fields from clockworks/tiktok-scraper:
    - webVideoUrl or video.playAddr
    - id
    - author.uniqueId, author.nickname (or authorMeta)
    - desc or text (description/caption)
    - stats or direct fields: playCount, diggCount (likes), commentCount, shareCount
    - createTime
    - subtitles (when shouldDownloadSubtitles=true) or videoMeta.subtitleLinks
    - hashtags or textExtra
    """
    # Get URL
    url = raw.get("webVideoUrl")
    if not url:
        video_info = raw.get("video", {})
        url = video_info.get("playAddr")
    if not url:
        return None

    # Parse timestamp
    published_at = None
    create_time = raw.get("createTime")
    if create_time:
        try:
            published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
        except (ValueError, TypeError):
            pass

    # Extract author info (two possible formats)
    author = raw.get("author", {}) or raw.get("authorMeta", {})
    author_ref = author.get("uniqueId") or author.get("name") or author.get("nickname", "")

    # Extract stats (two possible formats: nested or flat)
    stats = raw.get("stats", {})
    view_count = stats.get("playCount") or raw.get("playCount")
    like_count = stats.get("diggCount") or raw.get("diggCount")
    comment_count = stats.get("commentCount") or raw.get("commentCount")
    share_count = stats.get("shareCount") or raw.get("shareCount")

    # TASK-2: Extract transcript from downloaded subtitles
    # When shouldDownloadSubtitles=true, subtitles are downloaded and text is extracted
    transcript = ""

    # Option 1: Direct subtitles field (when downloaded)
    subtitles = raw.get("subtitles")
    if subtitles:
        if isinstance(subtitles, str):
            # Plain text subtitles
            transcript = subtitles
        elif isinstance(subtitles, list):
            # List of subtitle objects
            transcript = " ".join(
                sub.get("text", "") if isinstance(sub, dict) else str(sub)
                for sub in subtitles
                if sub
            )

    # Option 2: subtitleInfos field (legacy format)
    if not transcript:
        subtitle_infos = raw.get("subtitleInfos") or []
        if subtitle_infos:
            transcript = " ".join(
                info.get("text", "")
                for info in subtitle_infos
                if info.get("text")
            )

    # Option 3: Fetch subtitles from videoMeta.subtitleLinks URLs
    # TikTok provides subtitle download links but doesn't embed the content
    if not transcript:
        video_meta = raw.get("videoMeta", {})
        subtitle_links = video_meta.get("subtitleLinks") or []
        for link_info in subtitle_links:
            # First check if content was already embedded
            content = link_info.get("content") or link_info.get("text")
            if content:
                transcript = content if isinstance(content, str) else str(content)
                break

            # Otherwise, fetch from tiktokLink URL (English preferred)
            language = link_info.get("language", "")
            tiktok_link = link_info.get("tiktokLink")
            if tiktok_link and ("eng" in language.lower() or "en" in language.lower()):
                transcript = _fetch_subtitle_content(tiktok_link)
                if transcript:
                    break

        # If no English subtitles, try any available subtitle
        if not transcript:
            for link_info in subtitle_links:
                tiktok_link = link_info.get("tiktokLink")
                if tiktok_link:
                    transcript = _fetch_subtitle_content(tiktok_link)
                    if transcript:
                        break

    # Clean up transcript (remove excessive whitespace)
    if transcript:
        transcript = " ".join(transcript.split())

    has_transcript = bool(transcript and len(transcript) > 10)

    # Extract hashtags (two possible formats)
    hashtags = []
    # Format 1: hashtags array with name field
    raw_hashtags = raw.get("hashtags") or []
    for tag in raw_hashtags:
        if isinstance(tag, dict) and tag.get("name"):
            hashtags.append(tag["name"])
        elif isinstance(tag, str):
            hashtags.append(tag)
    # Format 2: textExtra with hashtagName
    if not hashtags:
        text_extras = raw.get("textExtra") or []
        for extra in text_extras:
            if extra.get("hashtagName"):
                hashtags.append(extra["hashtagName"])

    # Get caption/description (two possible field names)
    text_primary = raw.get("desc") or raw.get("text") or ""

    return EvidenceItemData(
        platform="tiktok",
        actor_id=actor_id,
        acquisition_stage=stage,
        recipe_id=recipe_id,
        canonical_url=url,
        external_id=raw.get("id", ""),
        author_ref=author_ref,
        title="",  # TikTok doesn't have titles
        text_primary=text_primary,
        text_secondary=transcript,
        hashtags=hashtags,
        view_count=view_count,
        like_count=like_count,
        comment_count=comment_count,
        share_count=share_count,
        published_at=published_at,
        fetched_at=fetched_at,
        has_transcript=has_transcript,
        raw_json=raw,
    )


# =============================================================================
# LINKEDIN NORMALIZERS
# =============================================================================

def _normalize_linkedin_item(
    raw: dict[str, Any],
    actor_id: str,
    recipe_id: str,
    stage: int,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Normalize LinkedIn company posts output.

    Expected fields from apimaestro/linkedin-company-posts:
    - postUrl
    - text or commentary
    - companyName, companyUrl
    - totalReactions, likes, comments
    - timestamp
    """
    url = raw.get("postUrl")
    if not url:
        return None

    # Parse timestamp
    published_at = None
    timestamp = raw.get("timestamp") or raw.get("postedAt")
    if timestamp:
        try:
            if isinstance(timestamp, str):
                published_at = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )
            elif isinstance(timestamp, (int, float)):
                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, TypeError):
            pass

    # Extract text (LinkedIn is text-heavy, so text_primary is main content)
    text = raw.get("text") or raw.get("commentary") or ""

    return EvidenceItemData(
        platform="linkedin",
        actor_id=actor_id,
        acquisition_stage=stage,
        recipe_id=recipe_id,
        canonical_url=url,
        external_id=raw.get("id", ""),
        author_ref=raw.get("companyName", ""),
        title="",
        text_primary=text,
        text_secondary="",  # LinkedIn posts don't have transcripts
        hashtags=[],  # Would need to parse from text
        view_count=None,  # Not typically available
        like_count=raw.get("likes") or raw.get("totalReactions"),
        comment_count=raw.get("comments"),
        share_count=raw.get("shares"),
        published_at=published_at,
        fetched_at=fetched_at,
        has_transcript=False,
        raw_json=raw,
    )


# =============================================================================
# YOUTUBE NORMALIZERS
# =============================================================================

def _normalize_youtube_item(
    raw: dict[str, Any],
    actor_id: str,
    recipe_id: str,
    stage: int,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Normalize YouTube scraper output.

    Expected fields from streamers/youtube-scraper:
    - url or videoUrl
    - id or videoId
    - channelName, channelUrl
    - title
    - description
    - viewCount, likeCount, commentCount
    - uploadDate or publishedAt
    - subtitles (if downloadSubtitles=true)
    """
    url = raw.get("url") or raw.get("videoUrl")
    if not url:
        video_id = raw.get("id") or raw.get("videoId")
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
    if not url:
        return None

    # Parse timestamp
    published_at = None
    date_str = raw.get("uploadDate") or raw.get("publishedAt")
    if date_str:
        try:
            if isinstance(date_str, str):
                # Handle various date formats
                date_str = date_str.replace("Z", "+00:00")
                published_at = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass

    # Extract transcript from subtitles
    subtitles = raw.get("subtitles") or []
    transcript = ""
    if subtitles:
        # Concatenate subtitle text
        transcript = " ".join(
            sub.get("text", "")
            for sub in subtitles
            if sub.get("text")
        )
    has_transcript = bool(transcript and len(transcript) > 10)

    return EvidenceItemData(
        platform="youtube",
        actor_id=actor_id,
        acquisition_stage=stage,
        recipe_id=recipe_id,
        canonical_url=url,
        external_id=raw.get("id") or raw.get("videoId", ""),
        author_ref=raw.get("channelName", ""),
        title=raw.get("title", ""),
        text_primary=raw.get("description", "") or "",
        text_secondary=transcript,
        hashtags=[],  # YouTube doesn't have hashtags in same way
        view_count=raw.get("viewCount"),
        like_count=raw.get("likeCount"),
        comment_count=raw.get("commentCount"),
        share_count=None,
        published_at=published_at,
        fetched_at=fetched_at,
        has_transcript=has_transcript,
        raw_json=raw,
    )


# =============================================================================
# GENERIC NORMALIZER
# =============================================================================

def _normalize_generic_item(
    raw: dict[str, Any],
    actor_id: str,
    recipe_id: str,
    stage: int,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Generic normalizer for unknown actors.

    Attempts to extract common fields, logs warning about unknown actor.
    """
    logger.warning("Using generic normalizer for unknown actor: %s", actor_id)

    # Try common URL field names
    url = (
        raw.get("url") or
        raw.get("postUrl") or
        raw.get("videoUrl") or
        raw.get("link")
    )
    if not url:
        return None

    return EvidenceItemData(
        platform="unknown",
        actor_id=actor_id,
        acquisition_stage=stage,
        recipe_id=recipe_id,
        canonical_url=url,
        external_id=raw.get("id", ""),
        author_ref=raw.get("author", ""),
        title=raw.get("title", ""),
        text_primary=raw.get("text") or raw.get("description") or "",
        text_secondary="",
        hashtags=[],
        view_count=raw.get("viewCount"),
        like_count=raw.get("likeCount") or raw.get("likes"),
        comment_count=raw.get("commentCount") or raw.get("comments"),
        share_count=raw.get("shareCount") or raw.get("shares"),
        published_at=None,
        fetched_at=fetched_at,
        has_transcript=False,
        raw_json=raw,
    )


# =============================================================================
# HELPERS
# =============================================================================

def _extract_hashtags_from_caption(caption: str) -> list[str]:
    """Extract hashtags from caption text."""
    if not caption:
        return []

    hashtags = []
    import re
    matches = re.findall(r"#(\w+)", caption)
    for match in matches:
        if match and len(match) > 1:
            hashtags.append(match.lower())

    return hashtags[:20]  # Limit to prevent abuse
