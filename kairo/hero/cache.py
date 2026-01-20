"""
TodayBoard Cache Module.

PR-7: Hardening (UI reliability) per opportunities_v1_prd.md §D.4.

This module provides:
- Centralized cache key management with exact PRD format
- TTL configuration from settings
- Cache operations for TodayBoard responses
- Cache invalidation on job completion and POST /regenerate

CRITICAL INVARIANTS (per PRD §D.4):
- Cache key format: "today_board:v2:{brand_id}"
- TTL: 6 hours (21600 seconds)
- Invalidation: On job completion OR POST /regenerate

CACHING POLICY:
- ONLY cache state=READY boards
- NEVER cache state=GENERATING (stale immediately)
- NEVER cache state=NOT_GENERATED_YET (may need first-run auto-enqueue)
- Cache includes full DTO with evidence_preview (PR-5 requirement)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

if TYPE_CHECKING:
    from kairo.hero.dto import TodayBoardDTO

logger = logging.getLogger("kairo.hero.cache")


# =============================================================================
# CACHE CONFIGURATION (per PRD §D.4)
# =============================================================================

# Exact key format per PRD: "today_board:v2:{brand_id}"
CACHE_KEY_PREFIX = "today_board:v2"

# Default TTL: 6 hours (21600 seconds) per PRD §D.4
DEFAULT_CACHE_TTL_SECONDS = 21600


def get_cache_ttl() -> int:
    """
    Get cache TTL from settings.

    Returns:
        TTL in seconds (default 21600 = 6 hours per PRD §D.4)
    """
    return getattr(settings, "OPPORTUNITIES_CACHE_TTL_S", DEFAULT_CACHE_TTL_SECONDS)


def get_cache_key(brand_id: UUID) -> str:
    """
    Generate cache key for a brand's TodayBoard.

    Per PRD §D.4: Exact format is "today_board:v2:{brand_id}"

    Args:
        brand_id: UUID of the brand

    Returns:
        Cache key string in exact PRD format
    """
    return f"{CACHE_KEY_PREFIX}:{brand_id}"


# =============================================================================
# CACHE OPERATIONS
# =============================================================================


def get_cached_board(brand_id: UUID) -> "TodayBoardDTO | None":
    """
    Get cached TodayBoard for a brand.

    Args:
        brand_id: UUID of the brand

    Returns:
        TodayBoardDTO if cached and valid, None otherwise
    """
    from kairo.hero.dto import TodayBoardDTO

    cache_key = get_cache_key(brand_id)

    try:
        cached = cache.get(cache_key)
        if cached is None:
            return None

        # Validate and deserialize
        board = TodayBoardDTO.model_validate_json(cached)

        # Mark as cache hit
        board.meta.cache_hit = True
        board.meta.cache_key = cache_key
        board.meta.cache_ttl_seconds = get_cache_ttl()

        logger.debug(
            "Cache hit for brand %s (key=%s)",
            brand_id,
            cache_key,
        )

        return board

    except Exception as e:
        # Cache corruption or deserialization failure - log and return None
        logger.warning(
            "Cache read failed for brand %s: %s",
            brand_id,
            str(e),
        )
        # Optionally delete corrupted cache entry
        try:
            cache.delete(cache_key)
        except Exception:
            pass
        return None


def set_cached_board(brand_id: UUID, board: "TodayBoardDTO") -> bool:
    """
    Cache a TodayBoard response.

    CACHING POLICY (per PRD §D.4):
    - ONLY cache state=READY boards
    - Skip caching for other states (generating, insufficient_evidence, etc.)

    Args:
        brand_id: UUID of the brand
        board: TodayBoardDTO to cache

    Returns:
        True if cached successfully, False otherwise
    """
    from kairo.core.enums import TodayBoardState

    # POLICY: Only cache READY boards
    if board.meta.state != TodayBoardState.READY:
        logger.debug(
            "Skipping cache for brand %s (state=%s, not READY)",
            brand_id,
            board.meta.state,
        )
        return False

    cache_key = get_cache_key(brand_id)
    ttl = get_cache_ttl()

    try:
        # Ensure cache metadata is set
        board.meta.cache_hit = False  # Fresh write, not a hit
        board.meta.cache_key = cache_key
        board.meta.cache_ttl_seconds = ttl

        # Serialize and store
        cache.set(cache_key, board.model_dump_json(), timeout=ttl)

        logger.debug(
            "Cached board for brand %s (key=%s, ttl=%ds)",
            brand_id,
            cache_key,
            ttl,
        )
        return True

    except Exception as e:
        logger.warning(
            "Cache write failed for brand %s: %s",
            brand_id,
            str(e),
        )
        return False


def invalidate_cache(brand_id: UUID) -> bool:
    """
    Invalidate cache for a brand's TodayBoard.

    Called on:
    - POST /regenerate (immediately)
    - Job completion (before/after persisting new board)

    Args:
        brand_id: UUID of the brand

    Returns:
        True if deleted successfully, False otherwise
    """
    cache_key = get_cache_key(brand_id)

    try:
        cache.delete(cache_key)
        logger.debug(
            "Cache invalidated for brand %s (key=%s)",
            brand_id,
            cache_key,
        )
        return True

    except Exception as e:
        logger.warning(
            "Cache invalidation failed for brand %s: %s",
            brand_id,
            str(e),
        )
        return False


# =============================================================================
# JOB TRACKING CACHE
# =============================================================================
# Lightweight cache for tracking running jobs (cheaper than DB queries)

JOB_KEY_PREFIX = "today_job:v2"
JOB_TTL_SECONDS = 600  # 10 minutes max for generation


def get_job_cache_key(brand_id: UUID) -> str:
    """Generate job tracking key for a brand."""
    return f"{JOB_KEY_PREFIX}:{brand_id}"


def get_cached_job_id(brand_id: UUID) -> str | None:
    """
    Get cached running job ID for a brand.

    This is a cheap check before hitting the database.

    Args:
        brand_id: UUID of the brand

    Returns:
        Job ID string if cached, None otherwise
    """
    job_key = get_job_cache_key(brand_id)
    try:
        return cache.get(job_key)
    except Exception:
        return None


def set_cached_job_id(brand_id: UUID, job_id: str) -> bool:
    """
    Cache a running job ID for a brand.

    Args:
        brand_id: UUID of the brand
        job_id: Job ID string

    Returns:
        True if cached successfully, False otherwise
    """
    job_key = get_job_cache_key(brand_id)
    try:
        cache.set(job_key, job_id, timeout=JOB_TTL_SECONDS)
        return True
    except Exception:
        return False


def clear_cached_job_id(brand_id: UUID) -> bool:
    """
    Clear cached job ID for a brand (on job completion).

    Args:
        brand_id: UUID of the brand

    Returns:
        True if deleted successfully, False otherwise
    """
    job_key = get_job_cache_key(brand_id)
    try:
        cache.delete(job_key)
        return True
    except Exception:
        return False
