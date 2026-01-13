"""
Per-actor normalization adapters.

PR-3: Normalization Adapters per Appendix B mappings.

Each adapter transforms raw Apify JSON into a dict matching NormalizedEvidenceItem fields.
Adapters are pure functions with no database access.

Validated actors (6):
- apify~instagram-scraper → instagram/post
- apify~instagram-reel-scraper → instagram/reel
- apimaestro~linkedin-company-posts → linkedin/text_post
- clockworks~tiktok-scraper → tiktok/short_video
- streamers~youtube-scraper → youtube/video
- apify~website-content-crawler → web/web_page

Unvalidated (1):
- apimaestro~linkedin-profile-posts → linkedin/text_post (BEHIND FEATURE FLAG)
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse


# Type alias for adapter functions
AdapterFunc = Callable[[dict[str, Any]], dict[str, Any]]

# Feature flag for unvalidated LinkedIn profile posts adapter
LINKEDIN_PROFILE_POSTS_FLAG = "BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS"
LINKEDIN_PROFILE_POSTS_ACTOR = "apimaestro~linkedin-profile-posts"


def _is_feature_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled (truthy value in env)."""
    value = os.environ.get(flag_name, "").lower()
    return value in ("true", "1", "yes", "on")


def get_adapter(actor_id: str) -> AdapterFunc | None:
    """
    Get the normalization adapter for an actor_id.

    Args:
        actor_id: Apify actor ID (e.g., "apify~instagram-scraper")

    Returns:
        Adapter function or None if:
        - No adapter exists for this actor
        - The adapter is behind a feature flag that is not enabled
    """
    # Gate unvalidated LinkedIn profile posts adapter behind feature flag
    if actor_id == LINKEDIN_PROFILE_POSTS_ACTOR:
        if not _is_feature_enabled(LINKEDIN_PROFILE_POSTS_FLAG):
            return None

    return ADAPTER_REGISTRY.get(actor_id)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict keys, returning default if any key is missing."""
    result = data
    for key in keys:
        if not isinstance(result, dict):
            return default
        result = result.get(key)
        if result is None:
            return default
    return result


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        # Handle various ISO formats
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except (ValueError, AttributeError):
        return None


def _extract_hashtags_from_text(text: str) -> list[str]:
    """Extract hashtags from text using regex."""
    if not text:
        return []
    # Match #hashtag patterns, excluding trailing punctuation
    matches = re.findall(r"#(\w+)", text)
    return list(dict.fromkeys(matches))  # Dedupe while preserving order


def _is_empty_or_whitespace(value: str | None) -> bool:
    """Check if string is None, empty, or only whitespace."""
    return not value or not value.strip()


def _extract_domain(url: str) -> str:
    """Extract domain from URL for author_ref."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


# =============================================================================
# B1) apify~instagram-scraper (Posts)
# =============================================================================


def normalize_instagram_post(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize Instagram post from apify~instagram-scraper.

    Per Appendix B1 - validated against var/apify_samples/apify_instagram-scraper/
    """
    caption = raw.get("caption") or ""

    return {
        "platform": "instagram",
        "content_type": "post",
        "external_id": raw.get("id"),
        "canonical_url": raw.get("url", ""),
        "published_at": _parse_iso_datetime(raw.get("timestamp")),
        "author_ref": raw.get("ownerUsername", ""),
        "title": None,  # Posts don't have titles
        "text_primary": caption,
        "text_secondary": None,
        "hashtags": raw.get("hashtags") or [],
        "metrics_json": {
            "likes": raw.get("likesCount"),
            "comments": raw.get("commentsCount"),
            "views": raw.get("videoViewCount"),  # Video posts only
        },
        "media_json": {
            "type": raw.get("type"),
            "shortcode": raw.get("shortCode"),
            "owner_id": raw.get("ownerId"),
            "music_id": _safe_get(raw, "musicInfo", "audio_id"),
            "duration": raw.get("videoDuration"),
        },
        "flags_json": {
            "has_transcript": False,
            "is_low_value": _is_empty_or_whitespace(caption),
            "is_collection_page": False,
        },
    }


# =============================================================================
# B2) apify~instagram-reel-scraper (Reels)
# =============================================================================


def normalize_instagram_reel(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize Instagram reel from apify~instagram-reel-scraper.

    Per Appendix B2 - validated against var/apify_samples/apify_instagram-reel-scraper/

    Important: transcript field is the key voice evidence when present.
    """
    caption = raw.get("caption") or ""
    transcript = raw.get("transcript") or ""
    has_transcript = not _is_empty_or_whitespace(transcript)

    return {
        "platform": "instagram",
        "content_type": "reel",
        "external_id": raw.get("id"),
        "canonical_url": raw.get("url", ""),
        "published_at": _parse_iso_datetime(raw.get("timestamp")),
        "author_ref": raw.get("ownerUsername", ""),
        "title": None,  # Reels don't have titles
        "text_primary": caption,
        "text_secondary": transcript if has_transcript else None,
        "hashtags": raw.get("hashtags", []),
        "metrics_json": {
            "likes": raw.get("likesCount"),
            "comments": raw.get("commentsCount"),
            "views": raw.get("videoViewCount"),
        },
        "media_json": {
            "type": raw.get("type"),
            "shortcode": raw.get("shortCode"),
            "owner_id": raw.get("ownerId"),
            "duration": raw.get("videoDuration"),
        },
        "flags_json": {
            "has_transcript": has_transcript,
            "is_low_value": _is_empty_or_whitespace(caption) and not has_transcript,
            "is_collection_page": False,
        },
    }


# =============================================================================
# B3) clockworks~tiktok-scraper (Profile Videos)
# =============================================================================


def normalize_tiktok_video(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize TikTok video from clockworks~tiktok-scraper.

    Per Appendix B3 - validated against var/apify_samples/clockworks_tiktok-scraper/

    Note: subtitleLinks contains URLs to subtitle files, not actual transcript text.
    """
    text = raw.get("text") or ""

    # Extract hashtag names from hashtag objects
    hashtags_raw = raw.get("hashtags", [])
    hashtags = [h.get("name") for h in hashtags_raw if isinstance(h, dict) and h.get("name")]

    return {
        "platform": "tiktok",
        "content_type": "short_video",
        "external_id": raw.get("id"),
        "canonical_url": raw.get("webVideoUrl", ""),
        "published_at": _parse_iso_datetime(raw.get("createTimeISO")),
        "author_ref": _safe_get(raw, "authorMeta", "name", default=""),
        "title": None,  # TikToks don't have titles
        "text_primary": text,
        "text_secondary": None,
        "hashtags": hashtags,
        "metrics_json": {
            "plays": raw.get("playCount"),
            "likes": raw.get("diggCount"),
            "comments": raw.get("commentCount"),
            "shares": raw.get("shareCount"),
            "saves": raw.get("collectCount"),
        },
        "media_json": {
            "duration": _safe_get(raw, "videoMeta", "duration"),
            "width": _safe_get(raw, "videoMeta", "width"),
            "height": _safe_get(raw, "videoMeta", "height"),
            "cover_url": _safe_get(raw, "videoMeta", "coverUrl"),
            "author_fans": _safe_get(raw, "authorMeta", "fans"),
        },
        "flags_json": {
            "has_transcript": False,  # subtitleLinks are download URLs, not text
            "is_sponsored": raw.get("isSponsored", False),
            "is_ad": raw.get("isAd", False),
            "is_low_value": _is_empty_or_whitespace(text),
            "is_collection_page": False,
        },
    }


# =============================================================================
# B4) streamers~youtube-scraper (Channel Videos)
# =============================================================================


def normalize_youtube_video(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize YouTube video from streamers~youtube-scraper.

    Per Appendix B4 - validated against var/apify_samples/streamers_youtube-scraper/
    """
    title = raw.get("title") or ""
    description = raw.get("text") or ""

    return {
        "platform": "youtube",
        "content_type": "video",
        "external_id": raw.get("id"),
        "canonical_url": raw.get("url", ""),
        "published_at": _parse_iso_datetime(raw.get("date")),
        "author_ref": raw.get("channelId", ""),
        "title": title,
        "text_primary": title,  # Per spec: title is text_primary
        "text_secondary": description,
        "hashtags": raw.get("hashtags", []),
        "metrics_json": {
            "views": raw.get("viewCount"),
            "likes": raw.get("likes"),
            "comments": raw.get("commentsCount"),
        },
        "media_json": {
            "duration": raw.get("duration"),
            "thumbnail_url": raw.get("thumbnailUrl"),
            "channel_name": raw.get("channelName"),
            "channel_url": raw.get("channelUrl"),
            "channel_subscribers": raw.get("numberOfSubscribers"),
        },
        "flags_json": {
            "has_transcript": False,  # This actor doesn't provide transcripts
            "is_members_only": raw.get("isMembersOnly", False),
            "is_monetized": raw.get("isMonetized"),
            "comments_off": raw.get("commentsTurnedOff", False),
            "is_low_value": _is_empty_or_whitespace(title) and _is_empty_or_whitespace(description),
            "is_collection_page": False,
        },
    }


# =============================================================================
# B5) apimaestro~linkedin-company-posts
# =============================================================================


def normalize_linkedin_company_post(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize LinkedIn company post from apimaestro~linkedin-company-posts.

    Per Appendix B5 - validated against var/apify_samples/apimaestro_linkedin-company-posts/
    """
    text = raw.get("text") or ""

    # Parse hashtags from text
    hashtags = _extract_hashtags_from_text(text)

    # Get external_id: prefer activity_urn, fallback to full_urn
    external_id = raw.get("activity_urn") or raw.get("full_urn")

    # Parse published_at from nested posted_at object
    posted_at_obj = raw.get("posted_at", {})
    published_at = None
    if isinstance(posted_at_obj, dict):
        # Try parsing the date string format: "2026-01-07 20:00:09"
        date_str = posted_at_obj.get("date")
        if date_str:
            try:
                published_at = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

    # Get stats
    stats = raw.get("stats", {})

    # Get media info
    media = raw.get("media", {})
    media_items = media.get("items", []) if isinstance(media, dict) else []

    return {
        "platform": "linkedin",
        "content_type": "text_post",
        "external_id": external_id,
        "canonical_url": raw.get("post_url", ""),
        "published_at": published_at,
        "author_ref": _safe_get(raw, "author", "company_url", default=""),
        "title": None,  # LinkedIn posts don't have titles
        "text_primary": text,
        "text_secondary": None,
        "hashtags": hashtags,
        "metrics_json": {
            "reactions": stats.get("total_reactions") if isinstance(stats, dict) else None,
            "likes": stats.get("like") if isinstance(stats, dict) else None,
            "comments": stats.get("total_comments") if isinstance(stats, dict) else None,
            "reposts": stats.get("reposts") if isinstance(stats, dict) else None,
        },
        "media_json": {
            "has_media": bool(media_items),
            "media_type": media.get("type") if isinstance(media, dict) else None,
            "author_name": _safe_get(raw, "author", "name"),
        },
        "flags_json": {
            "has_transcript": False,
            "is_low_value": _is_empty_or_whitespace(text),
            "is_collection_page": False,
        },
    }


# =============================================================================
# B6) apimaestro~linkedin-profile-posts (UNVALIDATED)
# =============================================================================


def normalize_linkedin_profile_post(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize LinkedIn profile post from apimaestro~linkedin-profile-posts.

    ⚠️ UNVALIDATED - This mapping is assumed, not proven.
    Per Appendix B6 - no sample files exist to validate against.

    Assumed to have same structure as company posts.
    """
    # Reuse company post adapter since structure is assumed to be similar
    result = normalize_linkedin_company_post(raw)

    # Override author_ref to use profile URL if available
    profile_url = _safe_get(raw, "author", "profile_url")
    if profile_url:
        result["author_ref"] = profile_url

    return result


# =============================================================================
# B7) apify~website-content-crawler (Web Pages)
# =============================================================================


def _is_collection_page(jsonld: list[dict] | None) -> bool:
    """
    Detect if page is a collection page from JSON-LD.

    Per Appendix B7:
    - CollectionPage type = collection
    - BreadcrumbList with multiple items = possibly collection (but not definitive)
    """
    if not jsonld or not isinstance(jsonld, list):
        return False

    for item in jsonld:
        if not isinstance(item, dict):
            continue

        # Check top-level @type
        if item.get("@type") == "CollectionPage":
            return True

        # Check @graph array
        graph = item.get("@graph", [])
        if not isinstance(graph, list):
            continue

        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "CollectionPage":
                return True

    return False


def _extract_jsonld_date(jsonld: list[dict] | None) -> datetime | None:
    """Extract datePublished from JSON-LD."""
    if not jsonld or not isinstance(jsonld, list):
        return None

    for item in jsonld:
        if not isinstance(item, dict):
            continue

        # Check top-level
        if item.get("datePublished"):
            return _parse_iso_datetime(item["datePublished"])

        # Check @graph array
        graph = item.get("@graph", [])
        if not isinstance(graph, list):
            continue

        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("datePublished"):
                return _parse_iso_datetime(node["datePublished"])

    return None


def _extract_og_image(open_graph: list[dict] | None) -> str | None:
    """Extract og:image from OpenGraph metadata."""
    if not open_graph or not isinstance(open_graph, list):
        return None

    for item in open_graph:
        if isinstance(item, dict) and item.get("property") == "og:image":
            return item.get("content")

    return None


def _extract_org_info(jsonld: list[dict] | None) -> tuple[str | None, str | None]:
    """Extract organization name and logo from JSON-LD."""
    if not jsonld or not isinstance(jsonld, list):
        return None, None

    for item in jsonld:
        if not isinstance(item, dict):
            continue

        # Check @graph array for Organization
        graph = item.get("@graph", [])
        if not isinstance(graph, list):
            continue

        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "Organization":
                name = node.get("name")
                logo_obj = node.get("logo", {})
                logo_url = logo_obj.get("url") if isinstance(logo_obj, dict) else None
                return name, logo_url

    return None, None


def normalize_web_page(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize web page from apify~website-content-crawler.

    Per Appendix B7 - validated against var/apify_samples/apify_website-content-crawler/
    """
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    text = raw.get("text") or ""
    jsonld = metadata.get("jsonLd")
    open_graph = metadata.get("openGraph")

    # Get canonical URL with fallback
    canonical_url = metadata.get("canonicalUrl") or raw.get("url", "")

    # Detect collection page
    is_collection = _is_collection_page(jsonld)

    # Extract org info
    org_name, org_logo = _extract_org_info(jsonld)

    return {
        "platform": "web",
        "content_type": "web_page",
        "external_id": None,  # Web pages use URL for dedupe
        "canonical_url": canonical_url,
        "published_at": _extract_jsonld_date(jsonld),
        "author_ref": _extract_domain(raw.get("url", "")),
        "title": metadata.get("title"),
        "text_primary": text,
        "text_secondary": metadata.get("description"),
        "hashtags": [],  # Web pages don't have hashtags
        "metrics_json": {},  # No metrics for web pages
        "media_json": {
            "og_image": _extract_og_image(open_graph),
            "org_name": org_name,
            "org_logo": org_logo,
        },
        "flags_json": {
            "has_transcript": False,
            "is_collection_page": is_collection,
            "is_low_value": is_collection or len(text) < 200,
            "http_status": _safe_get(raw, "crawl", "httpStatusCode"),
        },
    }


# =============================================================================
# ADAPTER REGISTRY
# =============================================================================


ADAPTER_REGISTRY: dict[str, AdapterFunc] = {
    # Instagram
    "apify~instagram-scraper": normalize_instagram_post,
    "apify~instagram-reel-scraper": normalize_instagram_reel,
    # LinkedIn
    "apimaestro~linkedin-company-posts": normalize_linkedin_company_post,
    "apimaestro~linkedin-profile-posts": normalize_linkedin_profile_post,  # UNVALIDATED
    # TikTok
    "clockworks~tiktok-scraper": normalize_tiktok_video,
    # YouTube
    "streamers~youtube-scraper": normalize_youtube_video,
    # Web
    "apify~website-content-crawler": normalize_web_page,
}
