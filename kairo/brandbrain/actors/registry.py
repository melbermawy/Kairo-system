"""
Actor Registry for BrandBrain.

PR-2: ActorSpec + Registry.

Per spec Section 4:
- Maps (platform, capability) to ActorSpec
- ActorSpec contains actor_id, build_input callable, cap_fields, notes
- Feature flag support for unvalidated actors (linkedin.profile_posts)

V1 Registry Entries (7 total, 6 validated):
1. instagram.posts (validated)
2. instagram.reels (validated)
3. linkedin.company_posts (validated)
4. linkedin.profile_posts (UNVALIDATED - behind feature flag)
5. tiktok.profile_videos (validated)
6. youtube.channel_videos (validated)
7. web.crawl_pages (validated)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from kairo.brandbrain.models import SourceConnection


@dataclass(frozen=True)
class ActorSpec:
    """
    Specification for an Apify actor.

    Attributes:
        platform: Platform name (instagram, linkedin, tiktok, youtube, web)
        capability: Capability type (posts, reels, company_posts, etc.)
        actor_id: Apify actor ID (e.g., "apify~instagram-scraper")
        build_input: Callable that builds actor input from SourceConnection and cap
        cap_fields: List of input JSON keys that are limit-like (for documentation)
        notes: Known limitations or gotchas
        validated: Whether this actor has been validated against real data
        feature_flag: Environment variable that must be truthy to enable (None = always enabled)
    """

    platform: str
    capability: str
    actor_id: str
    build_input: Callable[["SourceConnection", int], dict]
    cap_fields: list[str]
    notes: str
    validated: bool = True
    feature_flag: str | None = None


def _is_feature_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled (truthy value in env)."""
    value = os.environ.get(flag_name, "").lower()
    return value in ("true", "1", "yes", "on")


def is_capability_enabled(platform: str, capability: str) -> bool:
    """
    Check if a capability is enabled.

    Validated actors are always enabled.
    Unvalidated actors require their feature flag to be set.

    Args:
        platform: Platform name
        capability: Capability type

    Returns:
        True if the capability is enabled, False otherwise.
    """
    key = (platform, capability)
    spec = ACTOR_REGISTRY.get(key)
    if spec is None:
        return False
    if spec.feature_flag is None:
        return True
    return _is_feature_enabled(spec.feature_flag)


def get_actor_spec(platform: str, capability: str) -> ActorSpec | None:
    """
    Get the ActorSpec for a platform/capability.

    Returns None if:
    - The capability is not registered
    - The capability is behind a feature flag that is not enabled

    Args:
        platform: Platform name
        capability: Capability type

    Returns:
        ActorSpec if available and enabled, None otherwise.
    """
    key = (platform, capability)
    spec = ACTOR_REGISTRY.get(key)
    if spec is None:
        return None
    if spec.feature_flag and not _is_feature_enabled(spec.feature_flag):
        return None
    return spec


# =============================================================================
# ACTOR REGISTRY
# =============================================================================

# Import builders here to avoid circular imports
# (inputs.py is simple and doesn't import from registry)
from kairo.brandbrain.actors.inputs import (
    build_instagram_posts_input,
    build_instagram_reels_input,
    build_linkedin_company_posts_input,
    build_linkedin_profile_posts_input,
    build_tiktok_profile_input,
    build_youtube_channel_input,
    build_web_crawl_input,
)


ACTOR_REGISTRY: dict[tuple[str, str], ActorSpec] = {
    # -------------------------------------------------------------------------
    # Instagram: Posts
    # -------------------------------------------------------------------------
    ("instagram", "posts"): ActorSpec(
        platform="instagram",
        capability="posts",
        actor_id="apify~instagram-scraper",
        build_input=build_instagram_posts_input,
        cap_fields=["resultsLimit"],
        notes="Validated. addParentData=false to avoid bloating output.",
        validated=True,
    ),
    # -------------------------------------------------------------------------
    # Instagram: Reels
    # -------------------------------------------------------------------------
    ("instagram", "reels"): ActorSpec(
        platform="instagram",
        capability="reels",
        actor_id="apify~instagram-reel-scraper",
        build_input=build_instagram_reels_input,
        cap_fields=["resultsLimit"],
        notes=(
            "Validated. resultsLimit only applies to profile scraping, not explicit reel URLs. "
            "includeTranscript=true is CRITICAL for voice evidence."
        ),
        validated=True,
    ),
    # -------------------------------------------------------------------------
    # LinkedIn: Company Posts
    # -------------------------------------------------------------------------
    ("linkedin", "company_posts"): ActorSpec(
        platform="linkedin",
        capability="company_posts",
        actor_id="apimaestro~linkedin-company-posts",
        build_input=build_linkedin_company_posts_input,
        cap_fields=["limit"],
        notes="Validated. Identifier should be company slug (extracted from URL if needed).",
        validated=True,
    ),
    # -------------------------------------------------------------------------
    # LinkedIn: Profile Posts (UNVALIDATED - BEHIND FEATURE FLAG)
    # -------------------------------------------------------------------------
    ("linkedin", "profile_posts"): ActorSpec(
        platform="linkedin",
        capability="profile_posts",
        actor_id="apimaestro~linkedin-profile-posts",
        build_input=build_linkedin_profile_posts_input,
        cap_fields=["limit"],
        notes=(
            "⚠️ UNVALIDATED - Input template and normalization are assumed, not proven. "
            "Must NOT be enabled in production until validated. "
            "Requires BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS=true."
        ),
        validated=False,
        feature_flag="BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS",
    ),
    # -------------------------------------------------------------------------
    # TikTok: Profile Videos
    # -------------------------------------------------------------------------
    ("tiktok", "profile_videos"): ActorSpec(
        platform="tiktok",
        capability="profile_videos",
        actor_id="clockworks~tiktok-scraper",
        build_input=build_tiktok_profile_input,
        cap_fields=["resultsPerPage"],
        notes="Validated. Handle should NOT have @ prefix (stripped by builder).",
        validated=True,
    ),
    # -------------------------------------------------------------------------
    # YouTube: Channel Videos
    # -------------------------------------------------------------------------
    ("youtube", "channel_videos"): ActorSpec(
        platform="youtube",
        capability="channel_videos",
        actor_id="streamers~youtube-scraper",
        build_input=build_youtube_channel_input,
        cap_fields=["maxResults"],
        notes="Validated. Shorts and streams excluded (maxResultsShorts=0, maxResultsStreams=0).",
        validated=True,
    ),
    # -------------------------------------------------------------------------
    # Web: Crawl Pages
    # -------------------------------------------------------------------------
    ("web", "crawl_pages"): ActorSpec(
        platform="web",
        capability="crawl_pages",
        actor_id="apify~website-content-crawler",
        build_input=build_web_crawl_input,
        cap_fields=["maxCrawlPages"],
        notes=(
            "Validated. Cap is total pages (homepage + up to 2 key pages from settings_json.extra_start_urls). "
            "maxCrawlDepth=1 to only crawl one level deep."
        ),
        validated=True,
    ),
}
