"""
Live SourceActivation Execution.

PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section B.4.

This module provides:
- execute_recipe(): Execute a single recipe (2-stage or single-stage)
- execute_live_activation(): Execute full activation with budget controls

CRITICAL INVARIANTS (per PRD):
- SA-1: Instagram MUST use 2-stage acquisition
- SA-2: Stage 2 inputs MUST be derived from Stage 1 outputs
- SA-4: LLMs do NOT interpret evidence in SourceActivation
- INV-G5: Only POST /regenerate/ may trigger Apify spend
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from kairo.core.guardrails import (
    ApifyDisabledError,
    require_apify_enabled,
    require_live_apify_allowed,
)
from kairo.integrations.apify.client import ApifyClient, ApifyError
from kairo.sourceactivation.budget import (
    APIFY_PER_REGENERATE_CAP_USD,
    BudgetStatus,
    apply_caps_to_input,
    check_budget_for_run,
    estimate_recipe_cost,
    should_continue_recipes,
)
from kairo.sourceactivation.normalizers import normalize_actor_output
from kairo.sourceactivation.recipes import (
    DEFAULT_EXECUTION_PLAN,
    RecipeSpec,
    get_execution_plan,
    get_recipe,
)
from kairo.sourceactivation.types import EvidenceBundle, EvidenceItemData, SeedPack

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT TYPES
# =============================================================================

@dataclass
class RecipeResult:
    """Result of executing a single recipe."""
    recipe_id: str
    success: bool
    items: list[EvidenceItemData]
    stage1_items_count: int
    stage2_items_count: int
    estimated_cost: Decimal
    error: str | None = None


@dataclass
class LiveActivationResult:
    """Result of full live activation."""
    success: bool
    items: list[EvidenceItemData]
    recipes_executed: list[str]
    total_cost: Decimal
    early_exit_reason: str | None = None
    error: str | None = None


# =============================================================================
# APIFY CLIENT FACTORY
# =============================================================================

def get_apify_client() -> ApifyClient:
    """
    Create Apify client with configured credentials.

    Raises:
        ApifyDisabledError: If APIFY_ENABLED=false
        ValueError: If APIFY_TOKEN is not configured
    """
    require_apify_enabled()

    token = getattr(settings, "APIFY_TOKEN", None)
    if not token:
        raise ValueError("APIFY_TOKEN is not configured")

    base_url = getattr(settings, "APIFY_BASE_URL", "https://api.apify.com")

    return ApifyClient(token=token, base_url=base_url)


# =============================================================================
# RECIPE EXECUTION
# =============================================================================

def execute_recipe(
    recipe: RecipeSpec,
    seed_pack: SeedPack,
    run_id: UUID,
    client: ApifyClient | None = None,
) -> RecipeResult:
    """
    Execute a recipe and return normalized evidence.

    Per PRD B.4:
    - For 2-stage recipes (Instagram): Stage 1 → Filter → Stage 2 → Merge
    - For single-stage recipes: Stage 1 → Normalize

    INVARIANTS:
    - SA-1: Instagram recipes MUST have stage2_actor
    - SA-2: Stage 2 inputs derived from stage1_to_stage2_filter (no hardcoded URLs)

    Args:
        recipe: Recipe specification
        seed_pack: Seed pack for input building
        run_id: ActivationRun ID for correlation
        client: Optional Apify client (created if not provided)

    Returns:
        RecipeResult with items and metrics
    """
    # Validate Instagram 2-stage invariant (SA-1)
    if recipe.platform == "instagram" and not recipe.stage2_actor:
        raise ValueError(
            f"SA-1 violation: Instagram recipe {recipe.recipe_id} MUST have stage2_actor"
        )

    # Get client
    if client is None:
        client = get_apify_client()

    estimated_cost = estimate_recipe_cost(recipe.recipe_id)
    all_items: list[EvidenceItemData] = []
    stage1_count = 0
    stage2_count = 0

    try:
        # =====================================================================
        # Stage 1: Discovery
        # =====================================================================
        logger.info(
            "Executing recipe %s Stage 1: %s",
            recipe.recipe_id,
            recipe.stage1_actor,
        )

        # Build input with caps
        stage1_input = recipe.stage1_input_builder(seed_pack)
        stage1_input = apply_caps_to_input(recipe.stage1_actor, stage1_input)

        # Execute actor
        run_info = client.start_actor_run(recipe.stage1_actor, stage1_input)
        run_info = client.poll_run(run_info.run_id, timeout_s=180)

        if not run_info.is_success():
            return RecipeResult(
                recipe_id=recipe.recipe_id,
                success=False,
                items=[],
                stage1_items_count=0,
                stage2_items_count=0,
                estimated_cost=estimated_cost,
                error=f"Stage 1 failed: {run_info.status} - {run_info.error_message}",
            )

        # Fetch and normalize Stage 1 results
        stage1_raw_items = client.fetch_dataset_items(
            run_info.dataset_id,
            limit=recipe.stage1_result_limit,
        )

        stage1_items = normalize_actor_output(
            raw_items=stage1_raw_items,
            actor_id=recipe.stage1_actor,
            recipe_id=recipe.recipe_id,
            stage=1,
            run_id=run_id,
        )

        # NOTE: Relevancy filtering now done at scrape time via:
        # - TikTok: searchSorting="1" (Most liked) + oldestPostDateUnified (date filter)
        # This gives us viral content from the last N days without post-scrape filtering.

        stage1_count = len(stage1_items)
        all_items.extend(stage1_items)

        # TASK-2: Log freshness diagnostics for observability
        _log_freshness_diagnostics(recipe.recipe_id, stage1_items)

        logger.info(
            "Recipe %s Stage 1 complete: %d items",
            recipe.recipe_id,
            stage1_count,
        )

        # =====================================================================
        # Stage 2: Enrichment (Instagram 2-stage only)
        # =====================================================================
        if recipe.stage2_actor and recipe.stage1_to_stage2_filter:
            # INVARIANT SA-2: Derive Stage 2 inputs from Stage 1 outputs
            stage2_urls = recipe.stage1_to_stage2_filter(stage1_raw_items)

            if not stage2_urls:
                logger.info(
                    "Recipe %s: No winners from Stage 1 filter, skipping Stage 2",
                    recipe.recipe_id,
                )
            else:
                logger.info(
                    "Executing recipe %s Stage 2: %s with %d URLs",
                    recipe.recipe_id,
                    recipe.stage2_actor,
                    len(stage2_urls),
                )

                # Build Stage 2 input (SA-2: URLs from filter, NOT hardcoded)
                stage2_input = recipe.stage2_input_builder(stage2_urls)
                stage2_input = apply_caps_to_input(recipe.stage2_actor, stage2_input)

                # Execute Stage 2
                run_info = client.start_actor_run(recipe.stage2_actor, stage2_input)
                run_info = client.poll_run(run_info.run_id, timeout_s=180)

                if run_info.is_success():
                    stage2_raw_items = client.fetch_dataset_items(
                        run_info.dataset_id,
                        limit=recipe.stage2_result_limit or 5,
                    )

                    stage2_items = normalize_actor_output(
                        raw_items=stage2_raw_items,
                        actor_id=recipe.stage2_actor,
                        recipe_id=recipe.recipe_id,
                        stage=2,
                        run_id=run_id,
                    )

                    stage2_count = len(stage2_items)

                    # Merge: Stage 2 items replace Stage 1 items with same URL
                    all_items = _merge_stage_results(all_items, stage2_items)

                    logger.info(
                        "Recipe %s Stage 2 complete: %d items (merged total: %d)",
                        recipe.recipe_id,
                        stage2_count,
                        len(all_items),
                    )
                else:
                    logger.warning(
                        "Recipe %s Stage 2 failed: %s - %s",
                        recipe.recipe_id,
                        run_info.status,
                        run_info.error_message,
                    )

        return RecipeResult(
            recipe_id=recipe.recipe_id,
            success=True,
            items=all_items,
            stage1_items_count=stage1_count,
            stage2_items_count=stage2_count,
            estimated_cost=estimated_cost,
        )

    except ApifyError as e:
        logger.exception("Apify error in recipe %s: %s", recipe.recipe_id, str(e))
        return RecipeResult(
            recipe_id=recipe.recipe_id,
            success=False,
            items=[],
            stage1_items_count=0,
            stage2_items_count=0,
            estimated_cost=estimated_cost,
            error=str(e),
        )
    except Exception as e:
        logger.exception("Unexpected error in recipe %s: %s", recipe.recipe_id, str(e))
        return RecipeResult(
            recipe_id=recipe.recipe_id,
            success=False,
            items=[],
            stage1_items_count=0,
            stage2_items_count=0,
            estimated_cost=estimated_cost,
            error=str(e),
        )


def _merge_stage_results(
    stage1_items: list[EvidenceItemData],
    stage2_items: list[EvidenceItemData],
) -> list[EvidenceItemData]:
    """
    Merge Stage 2 results into Stage 1 results.

    Stage 2 items (enriched, with transcript) replace Stage 1 items
    with the same canonical_url.
    """
    # Build URL index of Stage 2 items
    stage2_by_url = {item.canonical_url: item for item in stage2_items}

    # Merge: keep Stage 1 items not replaced by Stage 2
    merged = []
    seen_urls = set()

    # First, add all Stage 2 items (they're the enriched versions)
    for item in stage2_items:
        merged.append(item)
        seen_urls.add(item.canonical_url)

    # Then add Stage 1 items not covered by Stage 2
    for item in stage1_items:
        if item.canonical_url not in seen_urls:
            merged.append(item)
            seen_urls.add(item.canonical_url)

    return merged


# =============================================================================
# FULL LIVE ACTIVATION
# =============================================================================

def execute_live_activation(
    brand_id: UUID,
    seed_pack: SeedPack,
    run_id: UUID,
) -> LiveActivationResult:
    """
    Execute full live activation with budget controls.

    Per PRD G.1.2:
    - Execute recipes in priority order: IG-1 → IG-3 → TT-1
    - Early-exit on evidence sufficiency (gates met)
    - Early-exit on per-run budget exhaustion

    Args:
        brand_id: Brand UUID
        seed_pack: Seed pack for input building
        run_id: ActivationRun ID for correlation

    Returns:
        LiveActivationResult with all collected evidence
    """
    # INVARIANT: Only POST /regenerate/ may call this (INV-G5)
    require_live_apify_allowed()

    # Get execution plan
    execution_plan = get_execution_plan(seed_pack)

    # Estimate total cost
    total_estimated_cost = sum(
        estimate_recipe_cost(rid) for rid in execution_plan
    )

    # Check budget before starting
    budget_check = check_budget_for_run(total_estimated_cost)
    if not budget_check.can_proceed:
        return LiveActivationResult(
            success=False,
            items=[],
            recipes_executed=[],
            total_cost=Decimal("0"),
            error=budget_check.message,
        )

    # Get client once for all recipes
    try:
        client = get_apify_client()
    except ApifyDisabledError as e:
        return LiveActivationResult(
            success=False,
            items=[],
            recipes_executed=[],
            total_cost=Decimal("0"),
            error=str(e),
        )
    except ValueError as e:
        return LiveActivationResult(
            success=False,
            items=[],
            recipes_executed=[],
            total_cost=Decimal("0"),
            error=str(e),
        )

    # Execute recipes
    all_items: list[EvidenceItemData] = []
    recipes_executed: list[str] = []
    total_cost = Decimal("0")
    early_exit_reason: str | None = None

    for recipe_id in execution_plan:
        recipe = get_recipe(recipe_id)
        if not recipe:
            logger.warning("Recipe %s not found, skipping", recipe_id)
            continue

        # Check per-run budget cap
        if total_cost >= APIFY_PER_REGENERATE_CAP_USD:
            early_exit_reason = "per_run_budget_exhausted"
            logger.info(
                "Per-run budget cap reached ($%.2f), stopping execution",
                float(total_cost),
            )
            break

        # Check evidence sufficiency (early-exit opportunity)
        if not should_continue_recipes(all_items):
            early_exit_reason = "evidence_gates_met"
            logger.info(
                "Evidence gates met with %d items, stopping execution",
                len(all_items),
            )
            break

        # Execute recipe
        logger.info(
            "Executing recipe %s (%s) for brand %s",
            recipe_id,
            recipe.description,
            brand_id,
        )

        result = execute_recipe(
            recipe=recipe,
            seed_pack=seed_pack,
            run_id=run_id,
            client=client,
        )

        recipes_executed.append(recipe_id)
        total_cost += result.estimated_cost

        if result.success:
            all_items.extend(result.items)
            logger.info(
                "Recipe %s complete: %d items (total: %d, cost: $%.2f)",
                recipe_id,
                len(result.items),
                len(all_items),
                float(total_cost),
            )
        else:
            logger.warning(
                "Recipe %s failed: %s (continuing with other recipes)",
                recipe_id,
                result.error,
            )

    return LiveActivationResult(
        success=len(all_items) > 0,
        items=all_items,
        recipes_executed=recipes_executed,
        total_cost=total_cost,
        early_exit_reason=early_exit_reason,
    )


# =============================================================================
# FRESHNESS DIAGNOSTICS
# =============================================================================

def _log_freshness_diagnostics(recipe_id: str, items: list[EvidenceItemData]) -> None:
    """
    Log freshness diagnostics for observability.

    TASK-2: Track item ages to diagnose staleness gate failures.
    """
    if not items:
        logger.info(
            "FRESHNESS_DIAGNOSTICS recipe=%s items=0",
            recipe_id,
        )
        return

    now = datetime.now(timezone.utc)
    ages_days = []

    for item in items:
        if item.published_at:
            age = (now - item.published_at).days
            ages_days.append(age)

    if not ages_days:
        logger.info(
            "FRESHNESS_DIAGNOSTICS recipe=%s items=%d ages=unknown (no published_at)",
            recipe_id,
            len(items),
        )
        return

    newest = min(ages_days)
    oldest = max(ages_days)
    median = sorted(ages_days)[len(ages_days) // 2]
    fresh_count = sum(1 for age in ages_days if age < 7)

    logger.info(
        "FRESHNESS_DIAGNOSTICS recipe=%s items=%d newest_age_days=%d oldest_age_days=%d median_age_days=%d fresh_under_7d=%d",
        recipe_id,
        len(items),
        newest,
        oldest,
        median,
        fresh_count,
    )


# NOTE: Relevancy filtering removed - now done at scrape time via Apify inputs:
# - TikTok: searchSorting="1" (Most liked) + oldestPostDateUnified (date filter)
# This ensures we only scrape viral content from the last N days.
