"""
BrandBrain actor registry and input builders.

PR-2: Actor Registry + Input Builders.

This package provides:
- ActorSpec dataclass for actor configuration
- ACTOR_REGISTRY mapping (platform, capability) to ActorSpec
- Input builder functions for each actor (Appendix C templates)
- Feature flag support for unvalidated actors
"""

from kairo.brandbrain.actors.registry import (
    ActorSpec,
    ACTOR_REGISTRY,
    get_actor_spec,
    is_capability_enabled,
)
from kairo.brandbrain.actors.inputs import (
    build_instagram_posts_input,
    build_instagram_reels_input,
    build_linkedin_company_posts_input,
    build_linkedin_profile_posts_input,
    build_tiktok_profile_input,
    build_youtube_channel_input,
    build_web_crawl_input,
)

__all__ = [
    # Registry
    "ActorSpec",
    "ACTOR_REGISTRY",
    "get_actor_spec",
    "is_capability_enabled",
    # Input builders
    "build_instagram_posts_input",
    "build_instagram_reels_input",
    "build_linkedin_company_posts_input",
    "build_linkedin_profile_posts_input",
    "build_tiktok_profile_input",
    "build_youtube_channel_input",
    "build_web_crawl_input",
]
