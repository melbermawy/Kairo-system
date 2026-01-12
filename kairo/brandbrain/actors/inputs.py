"""
Input builder functions for BrandBrain actors.

PR-2: Input Builders per Appendix C templates.

Each builder function takes a SourceConnection and cap value,
and returns the actor input JSON.

These templates are validated against actual ApifyRun records
(except linkedin.profile_posts which is unvalidated).

Important: The cap value passed to these builders should already
be resolved via caps.cap_for(platform, capability). The builder
just uses the value as-is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kairo.brandbrain.models import SourceConnection


# =============================================================================
# C1) Instagram Posts (apify~instagram-scraper)
# =============================================================================


def build_instagram_posts_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for apify~instagram-scraper (posts).

    Per Appendix C1:
    - directUrls: Instagram profile URL
    - resultsType: "posts"
    - resultsLimit: cap
    - addParentData: false

    Args:
        source: SourceConnection with identifier (profile URL)
        cap: Max posts to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    return {
        "directUrls": [source.identifier],
        "resultsType": "posts",
        "resultsLimit": cap,
        "addParentData": False,
    }


# =============================================================================
# C2) Instagram Reels (apify~instagram-reel-scraper)
# =============================================================================


def build_instagram_reels_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for apify~instagram-reel-scraper (reels).

    Per Appendix C2:
    - username: array with profile URL or username
    - resultsLimit: cap (only applies to profile scraping)
    - includeTranscript: true (CRITICAL for voice evidence)
    - includeSharesCount: false
    - includeDownloadedVideo: false
    - skipPinnedPosts: true

    Important: resultsLimit does NOT apply when scraping explicit reel URLs.
    Always rely on dataset-fetch cap as backstop.

    Args:
        source: SourceConnection with identifier (profile URL or username)
        cap: Max reels to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    return {
        "username": [source.identifier],
        "resultsLimit": cap,
        "includeTranscript": True,  # CRITICAL: enables transcript field
        "includeSharesCount": False,
        "includeDownloadedVideo": False,
        "skipPinnedPosts": True,
    }


# =============================================================================
# C3) LinkedIn Company Posts (apimaestro~linkedin-company-posts)
# =============================================================================


def build_linkedin_company_posts_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for apimaestro~linkedin-company-posts.

    Per Appendix C3:
    - sort: "recent"
    - limit: cap
    - company_name: company slug

    The identifier normalization (identifiers.py) already extracts the slug
    from URLs, so source.identifier should be the clean slug.

    Args:
        source: SourceConnection with identifier (company slug)
        cap: Max posts to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    return {
        "sort": "recent",
        "limit": cap,
        "company_name": source.identifier,  # Already normalized to slug
    }


# =============================================================================
# C4) LinkedIn Profile Posts (apimaestro~linkedin-profile-posts)
# UNVALIDATED - BEHIND FEATURE FLAG
# =============================================================================


def build_linkedin_profile_posts_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for apimaestro~linkedin-profile-posts.

    ⚠️ UNVALIDATED - This template is assumed, not validated.
    Do not use in production until validated.

    Per Appendix C4 (assumed):
    - sort: "recent"
    - limit: cap
    - profile_url: full LinkedIn profile URL

    Args:
        source: SourceConnection with identifier (profile URL)
        cap: Max posts to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    return {
        "sort": "recent",
        "limit": cap,
        "profile_url": source.identifier,  # Full profile URL
    }


# =============================================================================
# C5) TikTok Profile Videos (clockworks~tiktok-scraper)
# =============================================================================


def build_tiktok_profile_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for clockworks~tiktok-scraper.

    Per Appendix C5:
    - profiles: array of handles WITHOUT @ prefix
    - profileSorting: "latest"
    - resultsPerPage: cap
    - excludePinnedPosts: true
    - profileScrapeSections: ["videos"]

    Note: The identifier normalization (identifiers.py) already strips
    the @ prefix for TikTok handles.

    Args:
        source: SourceConnection with identifier (TikTok handle)
        cap: Max videos to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    # Strip @ just in case (should already be stripped by normalization)
    handle = source.identifier.lstrip("@")
    return {
        "profiles": [handle],
        "profileSorting": "latest",
        "resultsPerPage": cap,
        "excludePinnedPosts": True,
        "profileScrapeSections": ["videos"],
    }


# =============================================================================
# C6) YouTube Channel Videos (streamers~youtube-scraper)
# =============================================================================


def build_youtube_channel_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for streamers~youtube-scraper.

    Per Appendix C6:
    - startUrls: array of URL objects with channel URL
    - maxResults: cap
    - maxResultsShorts: 0 (exclude shorts)
    - maxResultsStreams: 0 (exclude livestreams)

    Args:
        source: SourceConnection with identifier (channel URL)
        cap: Max videos to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    return {
        "startUrls": [{"url": source.identifier}],
        "maxResults": cap,
        "maxResultsShorts": 0,
        "maxResultsStreams": 0,
    }


# =============================================================================
# C7) Web Crawl Pages (apify~website-content-crawler)
# =============================================================================


def build_web_crawl_input(source: "SourceConnection", cap: int) -> dict[str, Any]:
    """
    Build input for apify~website-content-crawler.

    Per Appendix C7:
    - startUrls: homepage URL + optional key pages from settings_json.extra_start_urls
    - maxCrawlDepth: 1 (only crawl one level deep)
    - maxCrawlPages: min(cap, len(startUrls))

    Key pages come from tier1.key_pages onboarding answer, stored in
    SourceConnection.settings_json.extra_start_urls. Clamped to 2 extra URLs.

    Args:
        source: SourceConnection with identifier (homepage URL)
        cap: Max pages to fetch (from caps.cap_for)

    Returns:
        Actor input dictionary.
    """
    # Read key pages from settings_json (clamped to 2)
    settings = source.settings_json or {}
    extra_urls = settings.get("extra_start_urls", [])
    # Filter to valid non-empty strings and clamp to 2
    extra_urls = [u for u in extra_urls if isinstance(u, str) and u.strip()][:2]

    # Build startUrls: homepage + key pages
    start_urls = [{"url": source.identifier}] + [{"url": u} for u in extra_urls]

    return {
        "startUrls": start_urls,
        "maxCrawlDepth": 1,
        # Cap to number of explicit start URLs so we don't crawl discovered links
        "maxCrawlPages": min(cap, len(start_urls)),
    }
