"""
Recipe Registry for SourceActivation.

PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section B.3/B.4.

This module provides:
- RecipeSpec dataclass for recipe definitions
- RECIPE_REGISTRY with all platform recipes
- Input builder functions for each recipe type

CRITICAL INVARIANTS (per PRD B.6):
- SA-1: Instagram MUST use 2-stage acquisition
- SA-2: Stage 2 inputs MUST be derived from Stage 1 outputs (no hardcoded URLs)
- SA-4: LLMs do NOT interpret evidence in SourceActivation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from kairo.sourceactivation.types import SeedPack

logger = logging.getLogger(__name__)


# =============================================================================
# TIKTOK FRESHNESS CONSTANTS
# =============================================================================

# Only fetch posts from the last N days (staleness gate requires < 7 days)
TIKTOK_MAX_AGE_DAYS = 5


# =============================================================================
# RECIPE SPEC
# =============================================================================

@dataclass(frozen=True)
class RecipeSpec:
    """
    Deterministic acquisition recipe.

    Per PRD B.3: Given SeedPack, produces the same Apify calls every time.
    Cost is controlled via result_limit caps + USD policy constants (see budget.py).
    """

    recipe_id: str  # e.g., "IG-1"
    platform: str  # instagram, tiktok, linkedin, youtube
    description: str

    # Stage 1 config
    stage1_actor: str
    stage1_input_builder: Callable[["SeedPack"], dict]
    stage1_result_limit: int  # Maps to actor's resultsLimit/limit/maxResults

    # Stage 2 config (None for single-stage platforms)
    stage2_actor: str | None = None
    stage2_input_builder: Callable[[list[str]], dict] | None = None
    stage2_result_limit: int | None = None

    # Filter between stages (None for single-stage)
    stage1_to_stage2_filter: Callable[[list[dict]], list[str]] | None = None


# =============================================================================
# INPUT BUILDERS - Instagram
# =============================================================================

def build_ig_hashtag_input(seed_pack: "SeedPack") -> dict:
    """
    Build Instagram hashtag search input.

    Per PRD B.2.1: Stage 1 discovery (cheap, wide).

    QUERY PLANNER INTEGRATION:
    - Uses seed_pack.instagram_hashtags (LLM-generated semantic probes)
    - Falls back to _extract_primary_keyword if query plan is empty

    Instagram Scraper API:
    - search: The hashtag to search for
    - searchType: "hashtag" for hashtag search
    - resultsLimit: Max posts to return
    - searchLimit: Number of hashtags to search (we use 1 at a time)
    """
    # Use Query Planner output if available
    if seed_pack.instagram_hashtags:
        # Use first hashtag as the search term
        hashtag = seed_pack.instagram_hashtags[0]
        logger.info(
            "IG_INPUT_BUILDER recipe=IG-1 source=QUERY_PLANNER hashtags=%s",
            seed_pack.instagram_hashtags[:3],
        )
    else:
        # Fallback to deterministic builder
        hashtag = _extract_primary_keyword(seed_pack) or "trending"
        logger.warning(
            "IG_INPUT_BUILDER recipe=IG-1 source=FALLBACK hashtag=%s",
            hashtag,
        )

    return {
        "search": hashtag,  # The hashtag to search for
        "searchType": "hashtag",  # Required for hashtag search
        "resultsLimit": 20,  # Max posts to return
        "searchLimit": 1,  # How many hashtags to search
    }


def build_ig_profile_input(seed_pack: "SeedPack") -> dict:
    """
    Build Instagram profile posts input.

    Uses brand name or competitor handle for profile discovery.
    """
    # Use brand name as a fallback profile search
    username = seed_pack.brand_name.lower().replace(" ", "")

    return {
        "usernames": [username],
        "resultsLimit": 15,
    }


def build_ig_search_input(seed_pack: "SeedPack") -> dict:
    """
    Build Instagram search query input.

    QUERY PLANNER INTEGRATION:
    - Uses seed_pack.instagram_queries (LLM-generated semantic probes)
    - Falls back to _extract_search_query if query plan is empty

    Instagram Scraper API:
    - search: Search query
    - searchType: "hashtag" works better for topic discovery than "user"
    - resultsLimit: Max posts to return
    - searchLimit: Number of results to search
    """
    # Use Query Planner output if available
    if seed_pack.instagram_queries:
        query = seed_pack.instagram_queries[0]  # Use first query
        logger.info(
            "IG_INPUT_BUILDER recipe=IG-3 source=QUERY_PLANNER query=%s",
            query,
        )
    else:
        # Fallback to deterministic builder
        query = _extract_search_query(seed_pack)
        logger.warning(
            "IG_INPUT_BUILDER recipe=IG-3 source=FALLBACK query=%s",
            query,
        )

    # Convert query to hashtag-friendly format (remove spaces, lowercase)
    # Instagram search works better with hashtag-style queries
    hashtag_query = query.lower().replace(" ", "")

    return {
        "search": hashtag_query,
        "searchType": "hashtag",  # Required - hashtag search gets better results
        "resultsLimit": 20,
        "searchLimit": 1,
    }


def build_ig_competitor_input(seed_pack: "SeedPack") -> dict:
    """
    Build Instagram competitor watch input.

    Targets competitor accounts for monitoring.
    """
    # Placeholder - would use competitor list from brand config
    return {
        "usernames": [],  # To be populated from brand competitors
        "resultsLimit": 10,
    }


def build_ig_reel_enrichment_input(urls: list[str]) -> dict:
    """
    Build Instagram Reel enrichment input.

    Per PRD B.2.1: Stage 2 enrichment (expensive, winners only).
    INVARIANT: URLs MUST come from Stage 1 filter output (SA-2).
    """
    return {
        "directUrls": urls,
        "resultsLimit": 5,  # Our cap
    }


def filter_ig_reels_by_engagement(stage1_items: list[dict]) -> list[str]:
    """
    Filter Stage 1 items for Stage 2 enrichment.

    Per PRD B.2.1: Stage 1 → Stage 2 derivation.
    INVARIANT: Stage 2 inputs MUST be derived from Stage 1 outputs (SA-2).

    Filter criteria:
    - productType == "clips" (videos only, reels have transcripts)
    - videoViewCount >= 1000
    - Valid URL present
    """
    candidates = []

    for item in stage1_items:
        # Only reels have transcripts
        if item.get("productType") != "clips":
            continue

        # Basic engagement filter
        views = item.get("videoViewCount") or 0
        if views < 1000:
            continue

        url = item.get("url")
        if url:
            candidates.append({
                "url": url,
                "views": views,
                "likes": item.get("likesCount") or 0,
            })

    # Sort by engagement (views * 0.7 + likes * 0.3)
    candidates.sort(
        key=lambda x: x["views"] * 0.7 + x["likes"] * 0.3,
        reverse=True,
    )

    # Take top N
    return [c["url"] for c in candidates[:5]]


# =============================================================================
# INPUT BUILDERS - TikTok
# =============================================================================

def build_tt_hashtag_input(seed_pack: "SeedPack") -> dict:
    """
    Build TikTok hashtag search input.

    Per PRD B.2.2: Single-stage, semantically rich.

    QUERY PLANNER INTEGRATION:
    - Uses seed_pack.tiktok_queries (LLM-generated semantic search probes)
    - Falls back to _build_tiktok_search_queries if query plan is empty

    TikTok Scraper search options (per apify_actor_samples.md):
    - searchQueries: Keywords to search for videos
    - searchSection: "Video" to search videos (not profiles)
    - searchSorting: "0" = Most relevant, "1" = Most liked, "2" = Latest
    - searchDatePosted: Date range filter ("0"=all, "1"=24h, "2"=week, "3"=month, etc.)

    NOTE: Cannot combine searchSorting with leastDiggs (popularity filter).
    We prioritize freshness over engagement because staleness gate is hard requirement.
    """
    # Use Query Planner output if available (preferred - semantic search probes)
    if seed_pack.tiktok_queries:
        search_queries = seed_pack.tiktok_queries[:3]  # Max 3 queries
        logger.info(
            "TIKTOK_INPUT_BUILDER recipe=TT-1 source=QUERY_PLANNER queries=%s",
            search_queries,
        )
    else:
        # Fallback to deterministic builder (legacy - will produce worse results)
        search_queries = _build_tiktok_search_queries(seed_pack)
        logger.warning(
            "TIKTOK_INPUT_BUILDER recipe=TT-1 source=FALLBACK queries=%s (Query Planner not available)",
            search_queries,
        )

    # Calculate freshness cutoff date using the constant (passes staleness gate)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=TIKTOK_MAX_AGE_DAYS)
    oldest_date_str = cutoff_date.strftime("%Y-%m-%d")

    logger.info(
        "TIKTOK_INPUT_BUILDER recipe=TT-1 oldest_date=%s sorting=most_liked",
        oldest_date_str,
    )

    # Strategy: VIRAL content from the LAST N DAYS
    # - oldestPostDateUnified: Hard date filter (only posts after this date)
    # - searchSorting: "1" (Most liked) to get viral/trending content
    # This combination ensures we get HIGH-ENGAGEMENT content that's also FRESH.
    return {
        # Use searchQueries for keyword search
        "searchQueries": search_queries,
        "resultsPerPage": 15,  # Our cap
        # Search in Video section (not profiles) - MUST be "/video" per Apify schema
        "searchSection": "/video",
        # Sort: "0"=Most relevant, "1"=Most liked, "3"=Newest
        # NOTE: "2" is NOT valid - actor only accepts 0, 1, 3
        # Use "1" (Most liked) to get VIRAL content
        "searchSorting": "1",
        # Hard date filter: only posts from last N days (passes staleness gate)
        "oldestPostDateUnified": oldest_date_str,
        # Transcript extraction
        "shouldDownloadSubtitles": True,
    }


def build_tt_profile_input(seed_pack: "SeedPack") -> dict:
    """
    Build TikTok profile videos input.

    For profile scraping:
    - profileSorting: "latest" to get newest content first
    - oldestPostDateUnified: Filter to recent posts (this works for profiles)
    - excludePinnedPosts: Skip pinned posts which may be old
    """
    username = seed_pack.brand_name.lower().replace(" ", "")

    # Calculate freshness cutoff date (7 days to pass staleness gate)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    oldest_date_str = cutoff_date.strftime("%Y-%m-%d")

    logger.info(
        "TIKTOK_INPUT_BUILDER recipe=TT-2 oldest_date=%s profile=%s",
        oldest_date_str,
        username,
    )

    return {
        "profiles": [username],
        "resultsPerPage": 10,
        # Sort by latest to prioritize recent content
        "profileSorting": "latest",
        # Freshness constraint (works for profile scraping)
        "oldestPostDateUnified": oldest_date_str,
        # Skip pinned posts (often old)
        "excludePinnedPosts": True,
        # Transcript extraction
        "shouldDownloadSubtitles": True,
    }


# =============================================================================
# INPUT BUILDERS - LinkedIn
# =============================================================================

def build_li_company_input(seed_pack: "SeedPack") -> dict:
    """
    Build LinkedIn company posts input.

    Per PRD B.2.3: Single-stage, text-heavy.
    """
    # Use brand name or provided company slug
    company_name = seed_pack.brand_name

    return {
        "companyNames": [company_name],
        "limit": 20,  # Our cap
    }


# =============================================================================
# INPUT BUILDERS - YouTube
# =============================================================================

def build_yt_search_input(seed_pack: "SeedPack") -> dict:
    """
    Build YouTube search input.

    Per PRD B.2.4: Single-stage, semantically rich.
    """
    query = _extract_search_query(seed_pack)

    return {
        "searchQueries": [query],
        "maxResults": 10,  # Our cap
        "downloadSubtitles": True,  # Enable transcript retrieval
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _extract_primary_keyword(seed_pack: "SeedPack") -> str:
    """Extract primary keyword from seed pack for hashtag searches."""
    if seed_pack.search_terms:
        # Use first search term
        return seed_pack.search_terms[0].lower().replace(" ", "")

    if seed_pack.pillar_keywords:
        # Fall back to first pillar keyword
        return seed_pack.pillar_keywords[0].lower().replace(" ", "")

    # Last resort: brand name
    return seed_pack.brand_name.lower().replace(" ", "")


def _extract_search_query(seed_pack: "SeedPack") -> str:
    """Extract search query from seed pack for general searches."""
    if seed_pack.positioning:
        # Use first sentence of positioning
        first_sentence = seed_pack.positioning.split(".")[0]
        # Limit to reasonable length
        return first_sentence[:100]

    if seed_pack.search_terms:
        # Join first 3 search terms
        return " ".join(seed_pack.search_terms[:3])

    return seed_pack.brand_name


def _build_tiktok_search_queries(seed_pack: "SeedPack") -> list[str]:
    """
    Build targeted TikTok search queries from seed pack.

    TASK-2: Multiple targeted queries for better relevance:
    - Combine brand context with search terms
    - Add problem-space queries (pain points, workflows)
    - Target trending/recent content patterns

    Returns list of 2-3 targeted search queries.
    """
    queries = []

    # Primary query: brand + key term
    if seed_pack.search_terms:
        primary = seed_pack.search_terms[0]
        queries.append(primary)

        # Secondary query: combine with brand context
        if len(seed_pack.search_terms) > 1:
            queries.append(seed_pack.search_terms[1])

    # Add pillar keywords if available
    if seed_pack.pillar_keywords:
        for kw in seed_pack.pillar_keywords[:2]:
            if kw not in queries:
                queries.append(kw)

    # Fallback to brand name if no queries
    if not queries:
        queries.append(seed_pack.brand_name)

    # Limit to 3 queries to control cost
    return queries[:3]


# =============================================================================
# RECIPE REGISTRY
# =============================================================================

RECIPE_REGISTRY: dict[str, RecipeSpec] = {
    # Instagram recipes (2-stage MANDATORY)
    "IG-1": RecipeSpec(
        recipe_id="IG-1",
        platform="instagram",
        description="Hashtag search → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_hashtag_input,
        stage1_result_limit=20,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=5,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    "IG-2": RecipeSpec(
        recipe_id="IG-2",
        platform="instagram",
        description="Profile posts → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_profile_input,
        stage1_result_limit=15,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=5,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    "IG-3": RecipeSpec(
        recipe_id="IG-3",
        platform="instagram",
        description="Search query → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_search_input,
        stage1_result_limit=20,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=5,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    "IG-4": RecipeSpec(
        recipe_id="IG-4",
        platform="instagram",
        description="Competitor watch → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_competitor_input,
        stage1_result_limit=10,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=3,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    # TikTok recipes (single-stage, semantically rich)
    "TT-1": RecipeSpec(
        recipe_id="TT-1",
        platform="tiktok",
        description="Hashtag search",
        stage1_actor="clockworks/tiktok-scraper",
        stage1_input_builder=build_tt_hashtag_input,
        stage1_result_limit=15,
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),

    "TT-2": RecipeSpec(
        recipe_id="TT-2",
        platform="tiktok",
        description="Profile videos",
        stage1_actor="clockworks/tiktok-scraper",
        stage1_input_builder=build_tt_profile_input,
        stage1_result_limit=10,
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),

    # LinkedIn recipes (single-stage, text-heavy)
    "LI-1": RecipeSpec(
        recipe_id="LI-1",
        platform="linkedin",
        description="Company posts",
        stage1_actor="apimaestro/linkedin-company-posts",
        stage1_input_builder=build_li_company_input,
        stage1_result_limit=20,
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),

    # YouTube recipes (single-stage, semantically rich)
    "YT-1": RecipeSpec(
        recipe_id="YT-1",
        platform="youtube",
        description="Search videos",
        stage1_actor="streamers/youtube-scraper",
        stage1_input_builder=build_yt_search_input,
        stage1_result_limit=10,
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),
}


# Default execution plan for POST /regenerate
# Per PRD G.1.2: Recipe priority order: IG-1 → IG-3 → TT-1
# NOTE: TT-1 temporarily disabled (TikTok scraper requires more Apify credits)
DEFAULT_EXECUTION_PLAN = ["IG-1", "IG-3"]  # Original: ["IG-1", "IG-3", "TT-1"]


def get_recipe(recipe_id: str) -> RecipeSpec | None:
    """Get a recipe by ID."""
    return RECIPE_REGISTRY.get(recipe_id)


def get_execution_plan(seed_pack: "SeedPack") -> list[str]:
    """
    Get execution plan for a seed pack.

    Per PRD G.1.2: Default is IG-1 → IG-3 → TT-1 (Instagram prioritized).

    Future: Could customize based on seed_pack.preferred_platforms.
    """
    # For now, use default plan
    return DEFAULT_EXECUTION_PLAN.copy()
