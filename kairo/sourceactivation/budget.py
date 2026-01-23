"""
Budget Policy for SourceActivation.

PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section G.1.

This module provides:
- Budget policy constants (env-configurable)
- Result cap constants for each actor
- Daily spend tracking via ActivationRun ledger
- Budget enforcement functions

CRITICAL: These are HARD guards, not suggestions. Budget violations block runs.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from django.conf import settings

logger = logging.getLogger(__name__)


# =============================================================================
# BUDGET POLICY CONSTANTS (Per PRD G.1.1)
# =============================================================================
# Phase 3: Budget restrictions are now DISABLED by default for BYOK users.
# Users pay for their own API usage, so we remove artificial caps.
# These constants are kept for backwards compatibility but set to None/False.

def _get_decimal_env(name: str, default: str) -> Decimal:
    """Get decimal value from environment or settings."""
    # Try environment first
    env_val = os.environ.get(name)
    if env_val is not None:
        return Decimal(env_val)
    # Try Django settings
    settings_val = getattr(settings, name, None)
    if settings_val is not None:
        return Decimal(str(settings_val))
    return Decimal(default)


def _get_bool_env(name: str, default: bool) -> bool:
    """Get boolean value from environment or settings."""
    env_val = os.environ.get(name)
    if env_val is not None:
        return env_val.lower() in ("true", "1", "yes")
    return getattr(settings, name, default)


# Total project budget (fixed, for reference) - not enforced
APIFY_BUDGET_TOTAL_USD = _get_decimal_env("APIFY_BUDGET_TOTAL_USD", "5.00")

# Remaining budget as of PRD date (operator-managed constant) - not enforced
APIFY_BUDGET_REMAINING_USD = _get_decimal_env("APIFY_BUDGET_REMAINING_USD", "2.77")

# Maximum spend per calendar day - Phase 3: REMOVED (set very high)
# Users with BYOK pay their own way, no need to cap
APIFY_DAILY_SPEND_CAP_USD = _get_decimal_env("APIFY_DAILY_SPEND_CAP_USD", "999999.00")

# Maximum spend per POST /regenerate/ execution - Phase 3: REMOVED (set very high)
# Users with BYOK pay their own way, no need to cap
APIFY_PER_REGENERATE_CAP_USD = _get_decimal_env("APIFY_PER_REGENERATE_CAP_USD", "999999.00")

# If budget exhausted, block all Apify runs - Phase 3: DISABLED
# With BYOK, users manage their own Apify account limits
APIFY_HARD_STOP_ON_EXHAUSTION = _get_bool_env("APIFY_HARD_STOP_ON_EXHAUSTION", False)


# =============================================================================
# RESULT CAP CONSTANTS (Per PRD G.1 Table)
# =============================================================================

@dataclass(frozen=True)
class ActorCaps:
    """Result caps for an Apify actor."""
    actor_id: str
    cap_field: str  # The input field name for limiting results
    our_limit: int  # Our enforced limit
    actor_max: int  # Actor's maximum (for reference)
    estimated_cost_per_result: Decimal  # Rough estimate


# Actor caps per PRD G.1 table
# Phase 3: Limits DOUBLED for more evidence collection
# More evidence = better opportunities. Users with BYOK pay their own usage.
ACTOR_CAPS = {
    "apify/instagram-scraper": ActorCaps(
        actor_id="apify/instagram-scraper",
        cap_field="resultsLimit",
        our_limit=40,  # Phase 3: 2x from 20 to 40
        actor_max=200,
        estimated_cost_per_result=Decimal("0.002"),
    ),
    "apify/instagram-reel-scraper": ActorCaps(
        actor_id="apify/instagram-reel-scraper",
        cap_field="resultsLimit",
        our_limit=10,  # Phase 3: 2x from 5 to 10
        actor_max=200,
        estimated_cost_per_result=Decimal("0.008"),
    ),
    "clockworks/tiktok-scraper": ActorCaps(
        actor_id="clockworks/tiktok-scraper",
        cap_field="resultsPerPage",
        our_limit=30,  # Phase 3: 2x from 15 to 30
        actor_max=1_000_000,
        estimated_cost_per_result=Decimal("0.003"),
    ),
    # Phase 3: TikTok Trends Scraper for trend discovery
    "clockworks/tiktok-trends-scraper": ActorCaps(
        actor_id="clockworks/tiktok-trends-scraper",
        cap_field="maxResults",
        our_limit=30,  # 30 trending hashtags per run
        actor_max=100,
        estimated_cost_per_result=Decimal("0.002"),
    ),
    "apimaestro/linkedin-company-posts": ActorCaps(
        actor_id="apimaestro/linkedin-company-posts",
        cap_field="limit",
        our_limit=40,  # Phase 3: 2x from 20 to 40
        actor_max=100,
        estimated_cost_per_result=Decimal("0.002"),
    ),
    "streamers/youtube-scraper": ActorCaps(
        actor_id="streamers/youtube-scraper",
        cap_field="maxResults",
        our_limit=20,  # Phase 3: 2x from 10 to 20
        actor_max=999_999,
        estimated_cost_per_result=Decimal("0.003"),
    ),
}


# =============================================================================
# COST ESTIMATION
# =============================================================================

@dataclass
class RecipeCostEstimate:
    """Estimated cost for executing a recipe."""
    recipe_id: str
    stage1_cost: Decimal
    stage2_cost: Decimal  # 0 for single-stage
    total_cost: Decimal


# Pre-computed cost estimates per recipe (per PRD G.1.2)
RECIPE_COST_ESTIMATES = {
    # Instagram 2-stage recipes
    "IG-1": RecipeCostEstimate(
        recipe_id="IG-1",
        stage1_cost=Decimal("0.04"),
        stage2_cost=Decimal("0.04"),
        total_cost=Decimal("0.08"),
    ),
    "IG-2": RecipeCostEstimate(
        recipe_id="IG-2",
        stage1_cost=Decimal("0.03"),
        stage2_cost=Decimal("0.04"),
        total_cost=Decimal("0.07"),
    ),
    "IG-3": RecipeCostEstimate(
        recipe_id="IG-3",
        stage1_cost=Decimal("0.04"),
        stage2_cost=Decimal("0.04"),
        total_cost=Decimal("0.08"),
    ),
    "IG-4": RecipeCostEstimate(
        recipe_id="IG-4",
        stage1_cost=Decimal("0.02"),
        stage2_cost=Decimal("0.024"),
        total_cost=Decimal("0.044"),
    ),
    # TikTok single-stage
    "TT-1": RecipeCostEstimate(
        recipe_id="TT-1",
        stage1_cost=Decimal("0.05"),
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0.05"),
    ),
    "TT-2": RecipeCostEstimate(
        recipe_id="TT-2",
        stage1_cost=Decimal("0.03"),
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0.03"),
    ),
    # Phase 3: TikTok Trends Discovery (two queries: general + industry)
    "TT-TRENDS-GENERAL": RecipeCostEstimate(
        recipe_id="TT-TRENDS-GENERAL",
        stage1_cost=Decimal("0.04"),  # ~20 results at $0.002 each
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0.04"),
    ),
    "TT-TRENDS-INDUSTRY": RecipeCostEstimate(
        recipe_id="TT-TRENDS-INDUSTRY",
        stage1_cost=Decimal("0.03"),  # ~15 results at $0.002 each
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0.03"),
    ),
    # LinkedIn single-stage
    "LI-1": RecipeCostEstimate(
        recipe_id="LI-1",
        stage1_cost=Decimal("0.04"),
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0.04"),
    ),
    # YouTube single-stage
    "YT-1": RecipeCostEstimate(
        recipe_id="YT-1",
        stage1_cost=Decimal("0.03"),
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0.03"),
    ),
    # Fixtures (no cost)
    "FIXTURE": RecipeCostEstimate(
        recipe_id="FIXTURE",
        stage1_cost=Decimal("0"),
        stage2_cost=Decimal("0"),
        total_cost=Decimal("0"),
    ),
}


def estimate_recipe_cost(recipe_id: str) -> Decimal:
    """Get estimated cost for a recipe."""
    estimate = RECIPE_COST_ESTIMATES.get(recipe_id)
    if estimate:
        return estimate.total_cost
    # Unknown recipe - use conservative estimate
    return Decimal("0.10")


def estimate_execution_plan_cost(recipe_ids: list[str]) -> Decimal:
    """Estimate total cost for an execution plan."""
    return sum(estimate_recipe_cost(rid) for rid in recipe_ids)


# =============================================================================
# BUDGET ENFORCEMENT
# =============================================================================

class BudgetStatus(Enum):
    """Budget check result."""
    OK = "ok"
    DAILY_CAP_REACHED = "daily_cap_reached"
    PER_RUN_CAP_EXCEEDED = "per_run_cap_exceeded"
    TOTAL_BUDGET_EXHAUSTED = "total_budget_exhausted"


@dataclass
class BudgetCheckResult:
    """Result of budget check."""
    status: BudgetStatus
    can_proceed: bool
    message: str
    daily_spend: Decimal = Decimal("0")
    daily_remaining: Decimal = Decimal("0")
    estimated_cost: Decimal = Decimal("0")


def get_daily_spend() -> Decimal:
    """
    Sum estimated_cost_usd for all ActivationRuns today.

    Per PRD G.1.3: Minimal ledger approach using ActivationRun rows.
    """
    from django.db.models import Sum
    from django.utils import timezone

    from kairo.hero.models import ActivationRun

    today = timezone.now().date()

    result = (
        ActivationRun.objects
        .filter(started_at__date=today)
        .aggregate(total=Sum("estimated_cost_usd"))
    )

    return result["total"] or Decimal("0")


def is_daily_cap_reached() -> bool:
    """Check if daily spend cap has been reached."""
    return get_daily_spend() >= APIFY_DAILY_SPEND_CAP_USD


def check_budget_for_run(estimated_cost: Decimal) -> BudgetCheckResult:
    """
    Check if a run with the given estimated cost is allowed.

    Per PRD G.1:
    - Check daily cap first
    - Then check per-run cap
    - Check remaining total budget if APIFY_HARD_STOP_ON_EXHAUSTION is true

    Args:
        estimated_cost: Estimated cost for the run

    Returns:
        BudgetCheckResult with status and details
    """
    daily_spend = get_daily_spend()
    daily_remaining = APIFY_DAILY_SPEND_CAP_USD - daily_spend

    # Check 1: Daily cap
    if daily_spend >= APIFY_DAILY_SPEND_CAP_USD:
        return BudgetCheckResult(
            status=BudgetStatus.DAILY_CAP_REACHED,
            can_proceed=False,
            message="Daily budget cap reached. Try again tomorrow.",
            daily_spend=daily_spend,
            daily_remaining=Decimal("0"),
            estimated_cost=estimated_cost,
        )

    # Check 2: Per-run cap
    if estimated_cost > APIFY_PER_REGENERATE_CAP_USD:
        return BudgetCheckResult(
            status=BudgetStatus.PER_RUN_CAP_EXCEEDED,
            can_proceed=False,
            message=f"Estimated cost ${estimated_cost} exceeds per-run cap ${APIFY_PER_REGENERATE_CAP_USD}.",
            daily_spend=daily_spend,
            daily_remaining=daily_remaining,
            estimated_cost=estimated_cost,
        )

    # Check 3: Total budget (if hard stop enabled)
    if APIFY_HARD_STOP_ON_EXHAUSTION:
        # We use APIFY_BUDGET_REMAINING_USD as a proxy for remaining budget
        # In production, this would be managed by the operator
        if estimated_cost > APIFY_BUDGET_REMAINING_USD:
            return BudgetCheckResult(
                status=BudgetStatus.TOTAL_BUDGET_EXHAUSTED,
                can_proceed=False,
                message="Total budget exhausted. Contact administrator.",
                daily_spend=daily_spend,
                daily_remaining=daily_remaining,
                estimated_cost=estimated_cost,
            )

    # All checks passed
    return BudgetCheckResult(
        status=BudgetStatus.OK,
        can_proceed=True,
        message="Budget check passed.",
        daily_spend=daily_spend,
        daily_remaining=daily_remaining,
        estimated_cost=estimated_cost,
    )


def get_actor_cap(actor_id: str) -> ActorCaps | None:
    """Get result caps for an actor."""
    return ACTOR_CAPS.get(actor_id)


def apply_caps_to_input(actor_id: str, input_data: dict) -> dict:
    """
    Apply result caps to actor input.

    Per PRD G.1: Caps are enforced at actor input level.

    Args:
        actor_id: The Apify actor ID
        input_data: The input dictionary to modify

    Returns:
        Input dictionary with caps applied
    """
    caps = get_actor_cap(actor_id)
    if caps:
        input_data = input_data.copy()
        input_data[caps.cap_field] = caps.our_limit
        logger.debug(
            "Applied cap to actor %s: %s=%d",
            actor_id,
            caps.cap_field,
            caps.our_limit,
        )
    else:
        logger.warning("No caps defined for actor %s", actor_id)

    return input_data


# =============================================================================
# EVIDENCE SUFFICIENCY GATES (Per PRD G.1.2)
# =============================================================================
# Phase 3: These gates are now set high to collect MORE evidence (not less).
# With BYOK, users pay for their own usage and want maximum quality.

# Minimum evidence items for synthesis - Phase 3: INCREASED to collect more
# Before we might early-exit at 8 items; now we want ~100 items
MIN_EVIDENCE_ITEMS = 100

# Minimum transcript coverage for quality - kept for quality assurance
MIN_TRANSCRIPT_COVERAGE = 0.30  # 30%


def should_continue_recipes(evidence_items: list) -> bool:
    """
    Check if more recipes should execute.

    Phase 3 Update: With BYOK, we ALWAYS want to continue and collect
    maximum evidence. Users pay for their own usage and want quality.

    The early-exit logic is effectively disabled by setting MIN_EVIDENCE_ITEMS
    very high, so all recipes in the execution plan will run.

    Args:
        evidence_items: List of evidence items collected so far

    Returns:
        True (always continue) - collect all evidence from all recipes
    """
    # Phase 3: Always continue to collect maximum evidence
    # Early-exit was a budget-saving measure; BYOK users want maximum quality
    item_count = len(evidence_items)

    # Only early-exit if we have a truly massive amount (defensive limit)
    if item_count >= MIN_EVIDENCE_ITEMS:
        transcript_count = sum(
            1 for e in evidence_items
            if getattr(e, "has_transcript", False)
        )
        coverage = transcript_count / item_count if item_count > 0 else 0

        if coverage >= MIN_TRANSCRIPT_COVERAGE:
            logger.info(
                "Evidence gates met: %d items, %.1f%% transcripts - early exit",
                item_count,
                coverage * 100,
            )
            return False

    return True
