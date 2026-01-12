"""
Caps configuration for BrandBrain actor runs.

PR-2: Two-layer cap enforcement primitives.

=============================================================================
PR-2 IS:
- caps.py: cap_for(), global_max_normalized_items(), apify_run_ttl_hours(), is_dev_mode()
- actors/registry.py: ActorSpec, ACTOR_REGISTRY (7 entries), get_actor_spec(), is_capability_enabled()
- actors/inputs.py: 7 input builders matching Appendix C templates
- freshness.py: check_source_freshness(), any_source_stale(), FreshnessResult

PR-2 IS NOT:
- Dataset-fetch cap enforcement (NOT wired; callers must pass limit to fetch_dataset_items)
- Normalization adapters (PR-3)
- Bundling logic (PR-4)
- Compile orchestration (PR-5)
- API endpoints (PR-7)
=============================================================================

Per spec Section 3.1 and 3.3:
- Dev caps with sane defaults
- Environment variable overrides
- cap_for(platform, capability) helper
- global_max_normalized_items for bundler

Two-layer cap enforcement (per spec §3.1.1):
1. Actor-input caps — passed in actor input JSON (e.g., resultsLimit, maxResults)
   → Implemented in PR-2 via input builders
2. Dataset-fetch caps — ALWAYS pass limit to fetch_dataset_items(limit=N)
   → NOT wired in PR-2; callers must enforce when calling fetch_dataset_items
"""

from __future__ import annotations

import os
from functools import lru_cache


# =============================================================================
# DEFAULT CAPS (Section 3.1)
# =============================================================================

DEFAULT_CAPS = {
    # Instagram
    ("instagram", "posts"): 8,
    ("instagram", "reels"): 6,
    # LinkedIn
    ("linkedin", "company_posts"): 6,
    ("linkedin", "profile_posts"): 6,
    # TikTok
    ("tiktok", "profile_videos"): 6,
    # YouTube
    ("youtube", "channel_videos"): 6,
    # Web
    ("web", "crawl_pages"): 3,
}

# Global max items per BrandBrain compile (normalized input to bundler)
DEFAULT_MAX_NORMALIZED_ITEMS = 40

# TTL for ApifyRun reuse (hours)
DEFAULT_APIFY_RUN_TTL_HOURS = 24

# Dev mode flag (spec §3.3 - currently informational only, no behavior gated on this yet)
DEFAULT_DEV_MODE = True


# =============================================================================
# ENVIRONMENT VARIABLE KEYS (Section 3.3)
# =============================================================================

# Maps (platform, capability) to environment variable name
ENV_VAR_KEYS = {
    ("instagram", "posts"): "BRANDBRAIN_CAP_IG_POSTS",
    ("instagram", "reels"): "BRANDBRAIN_CAP_IG_REELS",
    ("linkedin", "company_posts"): "BRANDBRAIN_CAP_LI",
    ("linkedin", "profile_posts"): "BRANDBRAIN_CAP_LI",  # same cap for both
    ("tiktok", "profile_videos"): "BRANDBRAIN_CAP_TT",
    ("youtube", "channel_videos"): "BRANDBRAIN_CAP_YT",
    ("web", "crawl_pages"): "BRANDBRAIN_CAP_WEB",
}


# =============================================================================
# CAP RESOLUTION
# =============================================================================


def _parse_int_env(key: str, default: int) -> int:
    """Parse an environment variable as an integer, returning default if not set or invalid."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        parsed = int(value)
        # Caps must be positive
        return parsed if parsed > 0 else default
    except ValueError:
        return default


@lru_cache(maxsize=1)
def _load_caps() -> dict[tuple[str, str], int]:
    """
    Load caps from environment variables with defaults.

    Uses lru_cache to avoid repeated os.environ lookups.
    Call _load_caps.cache_clear() if env changes during runtime (tests).
    """
    caps = {}
    for key, default in DEFAULT_CAPS.items():
        env_var = ENV_VAR_KEYS.get(key)
        if env_var:
            caps[key] = _parse_int_env(env_var, default)
        else:
            caps[key] = default
    return caps


def cap_for(platform: str, capability: str) -> int:
    """
    Return the cap for a given platform/capability.

    This is the value to pass to both:
    1. Actor input (e.g., resultsLimit, maxResults)
    2. fetch_dataset_items(limit=...)

    Returns default cap if platform/capability is unknown.

    Args:
        platform: Platform name (instagram, linkedin, tiktok, youtube, web)
        capability: Capability type (posts, reels, company_posts, etc.)

    Returns:
        Cap value as integer.
    """
    caps = _load_caps()
    key = (platform, capability)
    if key in caps:
        return caps[key]
    # Unknown platform/capability - return conservative default
    return 6


def global_max_normalized_items() -> int:
    """
    Return the global max items per BrandBrain compile.

    This is the total items allowed in an EvidenceBundle across all sources.
    Bundler must enforce this limit.
    """
    return _parse_int_env("BRANDBRAIN_MAX_NORMALIZED_ITEMS", DEFAULT_MAX_NORMALIZED_ITEMS)


def apify_run_ttl_hours() -> int:
    """
    Return the TTL in hours for ApifyRun reuse.

    If a cached ApifyRun is within this TTL, it can be reused instead
    of triggering a new actor run.
    """
    return _parse_int_env("BRANDBRAIN_APIFY_RUN_TTL_HOURS", DEFAULT_APIFY_RUN_TTL_HOURS)


def is_dev_mode() -> bool:
    """
    Check if BrandBrain dev mode is enabled.

    Per spec §3.3, BRANDBRAIN_DEV_MODE controls dev-only behavior.
    Currently informational - no specific behavior is gated on this yet.
    Future PRs may use this to enable debug logging, relaxed validation, etc.
    """
    value = os.environ.get("BRANDBRAIN_DEV_MODE", "true").lower()
    return value in ("true", "1", "yes", "on")


def clear_caps_cache() -> None:
    """Clear the caps cache. Call this after changing environment variables in tests."""
    _load_caps.cache_clear()
