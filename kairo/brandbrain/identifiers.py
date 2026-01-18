"""
Identifier normalization for SourceConnection.

PR-1: Normalize identifiers before save to ensure uniqueness constraint works correctly.
PR-7: Enhanced normalization - strip query params, canonicalize handles.

Platform-specific rules:
- instagram/tiktok: strip leading '@' from handles, extract username from URLs
- linkedin company_posts: if URL, extract slug; if slug, lowercase
- youtube: extract channel ID or handle from URLs
- web: strip query params and fragments, normalize to canonical URL
- ALL URLs: lowercase scheme+host, strip trailing slash
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


def normalize_source_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize a source identifier for deduplication.

    Args:
        platform: Platform name (instagram, linkedin, tiktok, youtube, web)
        capability: Capability type (posts, reels, company_posts, etc.)
        identifier: Raw identifier (URL, handle, slug)

    Returns:
        Normalized identifier string.

    Normalization rules (PR-7 enhanced):
    - Strip leading/trailing whitespace (all)
    - URLs: lowercase scheme+host
    - URLs: strip trailing slash from path
    - URLs: strip query params and fragments for social platforms
    - instagram: extract username from profile URLs, strip '@'
    - tiktok: extract username from profile URLs, strip '@'
    - linkedin company_posts: extract slug from URLs, lowercase
    - youtube: extract channel ID or handle from URLs
    - web: preserve query params (they may be significant)
    """
    if not identifier:
        return identifier

    # Strip whitespace
    identifier = identifier.strip()

    if not identifier:
        return identifier

    # Check if it looks like a URL (case-insensitive check)
    lower = identifier.lower()
    is_url = lower.startswith(("http://", "https://", "//"))

    if is_url:
        identifier = _normalize_url_identifier(platform, capability, identifier)
    else:
        identifier = _normalize_handle_identifier(platform, capability, identifier)

    return identifier


def _normalize_url_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize URL-based identifiers.

    Rules (PR-7 enhanced):
    - Lowercase scheme and host
    - Strip trailing slash from path
    - Strip query params and fragments for social platforms (idempotency)
    - Extract username/slug from social profile URLs
    - Preserve query params for web crawl (they may be significant)
    """
    try:
        parsed = urlparse(identifier)

        # Lowercase scheme and host
        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        host = parsed.netloc.lower() if parsed.netloc else ""

        # Path: strip trailing slash
        path = parsed.path.rstrip("/")

        # Platform-specific extraction
        if platform == "instagram":
            # Extract username from instagram.com/username URLs
            match = re.search(r"instagram\.com/([^/?#]+)", host + path, re.IGNORECASE)
            if match:
                username = match.group(1).lower()
                # Skip non-profile paths like /p/, /reel/, /stories/
                if username not in ("p", "reel", "reels", "stories", "explore", "tv"):
                    return username

        elif platform == "tiktok":
            # Extract username from tiktok.com/@username URLs
            match = re.search(r"tiktok\.com/@?([^/?#]+)", host + path, re.IGNORECASE)
            if match:
                return match.group(1).lower().lstrip("@")

        elif platform == "linkedin" and capability == "company_posts":
            # Extract slug from linkedin.com/company/slug URLs
            match = re.search(r"/company/([^/?#]+)", path, re.IGNORECASE)
            if match:
                return match.group(1).lower()

        elif platform == "youtube":
            # Extract channel ID or handle from various YouTube URL formats
            # youtube.com/channel/UC... or youtube.com/@handle or youtube.com/c/name
            if "/channel/" in path:
                match = re.search(r"/channel/([^/?#]+)", path)
                if match:
                    return match.group(1)  # Channel IDs are case-sensitive
            elif "/@" in path:
                match = re.search(r"/@([^/?#]+)", path)
                if match:
                    return "@" + match.group(1).lower()
            elif "/c/" in path:
                match = re.search(r"/c/([^/?#]+)", path)
                if match:
                    return match.group(1).lower()

        elif platform == "web":
            # For web crawl, preserve query params (they may be significant)
            # But still normalize scheme/host and strip fragment
            normalized = urlunparse((
                scheme,
                host,
                path,
                parsed.params,
                parsed.query,
                "",  # Strip fragment
            ))
            return normalized

        # Default for social platforms: strip query params and fragment
        # (tracking params like ?utm_source shouldn't create duplicates)
        normalized = urlunparse((
            scheme,
            host,
            path,
            "",  # Strip params
            "",  # Strip query
            "",  # Strip fragment
        ))

        return normalized

    except Exception:
        # If parsing fails, just strip trailing slash
        return identifier.rstrip("/")


def _normalize_handle_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize handle-based identifiers (non-URL).

    Rules:
    - instagram/tiktok: strip leading '@'
    - linkedin company_posts: lowercase slug
    - web/youtube: no handle rules (shouldn't have handles anyway)
    """
    # Strip leading '@' for social handles only
    if platform in ("instagram", "tiktok") and identifier.startswith("@"):
        identifier = identifier[1:]

    # LinkedIn company slug: lowercase
    if platform == "linkedin" and capability == "company_posts":
        identifier = identifier.lower()

    return identifier
