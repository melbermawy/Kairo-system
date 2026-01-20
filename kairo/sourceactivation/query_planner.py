"""
Query Planner for SourceActivation.

This module provides LLM-assisted query generation for social media scraping.
It bridges the gap between BrandBrain semantics and platform-specific search inputs.

WHY THIS EXISTS:
---------------
Deterministic recipes cannot invent search intent. Searching "Goodie AI" on TikTok
returns garbage because nobody talks about brands that way on social media.

The Query Planner is a constrained LLM step that:
1. Reads BrandBrainSnapshot (pillars, ICP, positioning)
2. Outputs validated search probes that map to Apify actor inputs
3. Does NOT scrape, gate, or synthesize—only proposes queries

This is the minimum intelligence required to make trend discovery real.

DESIGN PRINCIPLES:
-----------------
- Single LLM call per regenerate (cheap, fast)
- Strict output schema validation
- No fallback to brand names (that's what we're fixing)
- Platform-specific query strategies
- Observable and auditable

SCHEMA CONTRACT:
---------------
The LLM outputs:
{
  "tiktok": {
    "searchQueries": ["ai marketing automation", "saas workflow tips"],
    "hashtags": ["#aitools", "#marketingtech"],
    "rationale": "ICP pain points around workflow automation"
  },
  "instagram": {
    "searchQueries": ["marketing trends 2026", "brand strategy tips"],
    "hashtags": ["marketing", "brandstrategy"],
    "rationale": "Discovery of trending marketing content"
  }
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# OUTPUT SCHEMA
# =============================================================================

@dataclass
class PlatformProbes:
    """Search probes for a single platform."""
    platform: str
    search_queries: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class QueryPlan:
    """Complete query plan across platforms."""
    brand_id: str
    probes: dict[str, PlatformProbes] = field(default_factory=dict)
    raw_llm_output: dict = field(default_factory=dict)
    error: str | None = None

    def get_tiktok_queries(self) -> list[str]:
        """Get TikTok search queries."""
        if "tiktok" in self.probes:
            return self.probes["tiktok"].search_queries
        return []

    def get_tiktok_hashtags(self) -> list[str]:
        """Get TikTok hashtags."""
        if "tiktok" in self.probes:
            return self.probes["tiktok"].hashtags
        return []

    def get_instagram_queries(self) -> list[str]:
        """Get Instagram search queries."""
        if "instagram" in self.probes:
            return self.probes["instagram"].search_queries
        return []

    def get_instagram_hashtags(self) -> list[str]:
        """Get Instagram hashtags."""
        if "instagram" in self.probes:
            return self.probes["instagram"].hashtags
        return []


# =============================================================================
# PROMPT TEMPLATE
# =============================================================================

QUERY_PLANNER_PROMPT = """You are a social media trend discovery expert. Your job is to generate search queries that will find VIRAL, TRENDING content on social platforms.

## Context
Brand: {brand_name}
Positioning: {positioning}
Target Audience: {who_for}

Content Pillars:
{pillars_text}

## Task
Generate search queries for TikTok and Instagram that will surface TRENDING, VIRAL content.

Your queries should fall into TWO categories:

### Category 1: TREND DISCOVERY (2-3 queries)
These are BROAD queries that tap into where viral content naturally lives. These work for ANY brand because they find mainstream trends, hot takes, and cultural moments.

Examples of good trend discovery queries:
- "this is going to change everything"
- "nobody is talking about this"
- "i need to talk about"
- "unpopular opinion"
- "hot take"
- "things that just make sense"
- "pov you finally"

### Category 2: TOPIC-ADJACENT (2-3 queries)
These are related to the brand's TOPICS but NOT hyper-specific phrases. Think: what broader conversations does this brand's audience care about?

For example, if the brand is about AI search:
- BAD: "google ai overviews just told me the wrong answer" (too specific, matches nothing)
- GOOD: "chatgpt recommendations" (broad topic people actually search)
- GOOD: "ai replacing google" (hot topic with lots of content)
- GOOD: "seo is dead" (controversial take people make videos about)

## CRITICAL RULES
1. NEVER use the brand name "{brand_name}" - that returns garbage
2. NEVER use full sentences as queries - use 2-4 word TOPICS
3. Queries should be things people SEARCH FOR, not exact phrases people SAY
4. Hashtags should be POPULAR (millions of views) - check: #fyp #viral #tech #marketing
5. Mix broad trend queries with topic queries for diverse results

## TikTok Query Style
TikTok search is TOPIC-based, not phrase-based:
- BAD: "why does chatgpt keep hallucinating like this" (too specific)
- GOOD: "chatgpt wrong" or "ai hallucination" (searchable topics)
- GOOD: "tech news" or "ai news" (broad discovery)

## Output Format
Return ONLY valid JSON:
{{
  "tiktok": {{
    "searchQueries": ["broad trend query", "topic query 1", "topic query 2", "another trend query", "topic query 3"],
    "hashtags": ["popular hashtag", "niche hashtag", "trending hashtag"],
    "rationale": "Brief explanation"
  }},
  "instagram": {{
    "searchQueries": ["topic 1", "topic 2", "topic 3"],
    "hashtags": ["popular", "niche", "trending"],
    "rationale": "Brief explanation"
  }}
}}

Generate 5 search queries and 3-5 hashtags per platform. Mix trend discovery with topic queries.
"""


# =============================================================================
# TREND DISCOVERY BANK
# =============================================================================
# These queries are UNIVERSALLY good at finding viral/trending content.
# They work for ANY brand because they tap into viral content patterns,
# NOT specific topics. Topic-specific queries come from the LLM which has brand context.

TIKTOK_TREND_BANK = [
    # Viral content hooks - these patterns have massive content volume
    "this changed everything",
    "nobody talks about this",
    "unpopular opinion",
    "hot take",
    "finally someone said it",
    "things that just make sense",
    "pov you realize",
    "wait for it",
    "let me explain",
    # Cultural/generational moments - universal engagement
    "millennials vs gen z",
    "adulting be like",
    "main character energy",
]

INSTAGRAM_TREND_BANK = [
    # Discovery hashtags that always have content - truly universal
    "trending",
    "viral",
    "fyp",
    "explorepage",
    "reels",
    "trending2026",
]


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def generate_query_plan(
    brand_id: str,
    snapshot_json: dict,
    *,
    model: str = "fast",
) -> QueryPlan:
    """
    Generate a query plan from BrandBrainSnapshot.

    Args:
        brand_id: The brand UUID
        snapshot_json: The BrandBrainSnapshot.snapshot_json
        model: LLM model to use ("fast" or "heavy")

    Returns:
        QueryPlan with platform-specific search probes
    """
    logger.info(
        "QUERY_PLANNER_START brand_id=%s",
        brand_id,
    )

    # Extract relevant fields from snapshot
    brand_name = _extract_brand_name(snapshot_json)
    positioning = _extract_positioning(snapshot_json)
    who_for = _extract_who_for(snapshot_json)
    pillars = _extract_pillars(snapshot_json)

    # Format pillars for prompt
    pillars_text = _format_pillars(pillars)

    # Build prompt
    prompt = QUERY_PLANNER_PROMPT.format(
        brand_name=brand_name,
        positioning=positioning,
        who_for=who_for,
        pillars_text=pillars_text,
    )

    logger.info(
        "QUERY_PLANNER_PROMPT brand_name=%s pillars_count=%d",
        brand_name,
        len(pillars),
    )

    # Call LLM using the standard client
    try:
        from kairo.hero.llm_client import LLMClient

        client = LLMClient()
        role = "fast" if model == "fast" else "heavy"

        llm_response = client.call(
            brand_id=UUID(brand_id),
            flow="query_planner",
            prompt=prompt,
            role=role,
            temperature=0.7,  # Some creativity for query diversity
            max_output_tokens=1000,
        )

        response = llm_response.raw_text

        logger.info(
            "QUERY_PLANNER_LLM_RESPONSE length=%d",
            len(response),
        )

        # Parse and validate response
        plan = _parse_llm_response(brand_id, response)

        # Mix in trend bank queries for guaranteed discovery
        plan = _mix_trend_bank_queries(plan)

        logger.info(
            "QUERY_PLANNER_SUCCESS brand_id=%s tiktok_queries=%d instagram_queries=%d",
            brand_id,
            len(plan.get_tiktok_queries()),
            len(plan.get_instagram_queries()),
        )

        return plan

    except Exception as e:
        logger.error(
            "QUERY_PLANNER_FAILED brand_id=%s error=%s",
            brand_id,
            str(e),
        )
        return QueryPlan(
            brand_id=brand_id,
            error=str(e),
        )


def _parse_llm_response(brand_id: str, response: str) -> QueryPlan:
    """Parse and validate LLM response into QueryPlan."""
    # Try to extract JSON from response
    try:
        # Handle markdown code blocks
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            response = response[start:end].strip()

        data = json.loads(response)
    except json.JSONDecodeError as e:
        logger.warning(
            "QUERY_PLANNER_JSON_PARSE_FAILED response=%s error=%s",
            response[:200],
            str(e),
        )
        raise ValueError(f"Invalid JSON in LLM response: {e}")

    # Validate and extract probes
    probes = {}

    for platform in ["tiktok", "instagram"]:
        if platform in data:
            platform_data = data[platform]
            probes[platform] = PlatformProbes(
                platform=platform,
                search_queries=_validate_queries(platform_data.get("searchQueries", [])),
                hashtags=_validate_hashtags(platform_data.get("hashtags", [])),
                rationale=platform_data.get("rationale", ""),
            )

    return QueryPlan(
        brand_id=brand_id,
        probes=probes,
        raw_llm_output=data,
    )


def _validate_queries(queries: list) -> list[str]:
    """Validate and clean search queries."""
    validated = []
    for q in queries:
        if isinstance(q, str) and len(q.strip()) > 2:
            validated.append(q.strip()[:100])  # Cap length
    return validated[:5]  # Max 5 queries


def _validate_hashtags(hashtags: list) -> list[str]:
    """Validate and clean hashtags."""
    validated = []
    for h in hashtags:
        if isinstance(h, str):
            # Remove # prefix if present
            h = h.strip().lstrip("#")
            if len(h) > 1:
                validated.append(h[:50])  # Cap length
    return validated[:5]  # Max 5 hashtags


def _mix_trend_bank_queries(plan: QueryPlan) -> QueryPlan:
    """
    Mix trend bank queries into the query plan for guaranteed discovery.

    This ensures we always have some broad queries that return viral content,
    even if the LLM-generated queries are too specific.

    Strategy:
    - Take first 3 LLM-generated queries (topic-specific)
    - Add 2 queries from trend bank (guaranteed discovery)
    - Total: 5 queries per platform
    """
    import random

    # Mix TikTok queries
    if "tiktok" in plan.probes:
        llm_queries = plan.probes["tiktok"].search_queries[:3]  # Keep top 3 from LLM
        # Pick 2 random trend bank queries
        trend_queries = random.sample(TIKTOK_TREND_BANK, min(2, len(TIKTOK_TREND_BANK)))
        # Combine: LLM first (more specific), then trend bank (broader)
        combined = llm_queries + [q for q in trend_queries if q not in llm_queries]
        plan.probes["tiktok"].search_queries = combined[:5]

        logger.info(
            "QUERY_PLANNER_TREND_MIX platform=tiktok llm_queries=%d trend_queries=%d total=%d",
            len(llm_queries),
            len(trend_queries),
            len(plan.probes["tiktok"].search_queries),
        )

    # Mix Instagram hashtags (use trend bank as fallback hashtags)
    if "instagram" in plan.probes:
        llm_hashtags = plan.probes["instagram"].hashtags[:3]
        trend_hashtags = random.sample(INSTAGRAM_TREND_BANK, min(2, len(INSTAGRAM_TREND_BANK)))
        combined = llm_hashtags + [h for h in trend_hashtags if h not in llm_hashtags]
        plan.probes["instagram"].hashtags = combined[:5]

        logger.info(
            "QUERY_PLANNER_TREND_MIX platform=instagram llm_hashtags=%d trend_hashtags=%d total=%d",
            len(llm_hashtags),
            len(trend_hashtags),
            len(plan.probes["instagram"].hashtags),
        )

    return plan


# =============================================================================
# SNAPSHOT EXTRACTION HELPERS
# =============================================================================

def _extract_brand_name(snapshot: dict) -> str:
    """Extract brand name from snapshot."""
    # Try positioning.brand_name first
    positioning = snapshot.get("positioning", {})
    if isinstance(positioning, dict):
        brand_name = positioning.get("brand_name")
        if isinstance(brand_name, dict):
            return brand_name.get("value", "Unknown Brand")
        elif isinstance(brand_name, str):
            return brand_name

    # Fallback
    return "Unknown Brand"


def _extract_positioning(snapshot: dict) -> str:
    """Extract positioning statement from snapshot."""
    positioning = snapshot.get("positioning", {})
    if isinstance(positioning, dict):
        # Try one_liner first
        one_liner = positioning.get("one_liner", {})
        if isinstance(one_liner, dict):
            return one_liner.get("value", "")

        # Try positioning_statement
        statement = positioning.get("positioning_statement", {})
        if isinstance(statement, dict):
            return statement.get("value", "")

    return ""


def _extract_who_for(snapshot: dict) -> str:
    """Extract target audience from snapshot."""
    positioning = snapshot.get("positioning", {})
    if isinstance(positioning, dict):
        who_for = positioning.get("who_for", {})
        if isinstance(who_for, dict):
            return who_for.get("value", "")
        elif isinstance(who_for, str):
            return who_for

    return ""


def _extract_pillars(snapshot: dict) -> list[dict]:
    """Extract content pillars from snapshot."""
    content = snapshot.get("content", {})
    if isinstance(content, dict):
        pillars = content.get("content_pillars", [])
        if isinstance(pillars, list):
            return pillars

    return []


def _format_pillars(pillars: list[dict]) -> str:
    """Format pillars for prompt."""
    if not pillars:
        return "No pillars defined"

    lines = []
    for i, pillar in enumerate(pillars, 1):
        name = pillar.get("name", f"Pillar {i}")
        desc = pillar.get("description", "")
        lines.append(f"{i}. {name}: {desc}")

    return "\n".join(lines)
