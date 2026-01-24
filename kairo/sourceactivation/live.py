"""
Live SourceActivation Execution.

PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section B.4.

This module provides:
- execute_recipe(): Execute a single recipe (2-stage or single-stage)
- execute_live_activation(): Execute full activation with budget controls
- execute_live_activation_parallel(): Phase 3 parallel execution for speed

CRITICAL INVARIANTS (per PRD):
- SA-1: Instagram MUST use 2-stage acquisition
- SA-2: Stage 2 inputs MUST be derived from Stage 1 outputs
- SA-4: LLMs do NOT interpret evidence in SourceActivation
- INV-G5: Only POST /regenerate/ may trigger Apify spend

Phase 3 Enhancements:
- Parallel execution of independent recipes for 3x faster evidence collection
- All recipes run simultaneously instead of sequentially
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    extract_trending_hashtags,
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

def get_apify_client(user_id: UUID | None = None) -> ApifyClient:
    """
    Create Apify client with user's BYOK credentials.

    BYOK only - no system .env token fallback.
    User must configure their own Apify token in settings.

    Args:
        user_id: User UUID for BYOK lookup (required)

    Raises:
        ApifyDisabledError: If APIFY_ENABLED=false
        ValueError: If no user_id provided or user has no BYOK token configured
    """
    require_apify_enabled()

    if not user_id:
        raise ValueError("No user context - cannot retrieve BYOK Apify token")

    from kairo.users.encryption import get_user_apify_token
    token = get_user_apify_token(user_id)
    if not token:
        raise ValueError(f"User has no Apify token configured in settings (user_id={user_id})")

    # Log token metadata for debugging (NOT the actual token)
    token_last4 = token[-4:] if len(token) >= 4 else "***"
    token_len = len(token)
    logger.info(
        "Using user's BYOK Apify token: user_id=%s, token_len=%d, last4=%s",
        user_id, token_len, token_last4
    )
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

# Phase 3: Maximum parallel workers for recipe execution
# Each recipe may have multiple stages, but recipes are independent
MAX_PARALLEL_RECIPES = 5


def execute_live_activation(
    brand_id: UUID,
    seed_pack: SeedPack,
    run_id: UUID,
    user_id: UUID | None = None,
    parallel: bool = True,
) -> LiveActivationResult:
    """
    Execute full live activation with budget controls.

    Phase 3 Enhancement: Now uses parallel execution by default for 3x faster
    evidence collection. All recipes run simultaneously instead of sequentially.

    Per PRD G.1.2:
    - Execute recipes (now in parallel by default)
    - Early-exit on evidence sufficiency (gates met) - only applies to sequential
    - Early-exit on per-run budget exhaustion - only applies to sequential

    Phase 2 BYOK: If user_id is provided, uses user's Apify token.

    Args:
        brand_id: Brand UUID
        seed_pack: Seed pack for input building
        run_id: ActivationRun ID for correlation
        user_id: Optional user UUID for BYOK token lookup
        parallel: If True (default), run recipes in parallel for speed

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

    # Get client once for all recipes (BYOK: use user's token if available)
    try:
        client = get_apify_client(user_id=user_id)
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

    # Phase 3: Use parallel execution by default for speed
    if parallel:
        return _execute_recipes_parallel(
            brand_id=brand_id,
            seed_pack=seed_pack,
            run_id=run_id,
            execution_plan=execution_plan,
            client=client,
        )
    else:
        return _execute_recipes_sequential(
            brand_id=brand_id,
            seed_pack=seed_pack,
            run_id=run_id,
            execution_plan=execution_plan,
            client=client,
        )


def _execute_recipes_parallel(
    brand_id: UUID,
    seed_pack: SeedPack,
    run_id: UUID,
    execution_plan: list[str],
    client: ApifyClient,
) -> LiveActivationResult:
    """
    Execute recipes in parallel with TikTok chaining for maximum quality and speed.

    Phase 3 Enhancement: Intelligent parallel execution with TikTok chaining.

    Execution Strategy:
    1. Run ALL non-TT-1 recipes in parallel (including TT-TRENDS recipes)
    2. Wait for TT-TRENDS recipes to complete and extract trending hashtags
    3. Run TT-1 with discovered trending hashtags for transcript-rich content

    This approach:
    - Maximizes parallelism (all non-TT-1 recipes run simultaneously)
    - Enables TT-TRENDS → TT-1 chaining for better quality
    - Only adds latency for TT-1 (must wait for TT-TRENDS)
    - Other platforms (IG, YT, LI) are unaffected by the wait
    """
    logger.info(
        "PARALLEL_EXECUTION brand=%s recipes=%s",
        brand_id,
        execution_plan,
    )

    all_items: list[EvidenceItemData] = []
    recipes_executed: list[str] = []
    total_cost = Decimal("0")
    errors: list[str] = []

    # Separate recipes into groups:
    # - TT-TRENDS recipes: run in parallel, extract hashtags when done
    # - TT-1: runs AFTER TT-TRENDS with discovered hashtags
    # - Other recipes: run in parallel immediately
    tt_trends_recipes = []
    tt_content_recipe = None
    other_recipes = []

    for recipe_id in execution_plan:
        recipe = get_recipe(recipe_id)
        if not recipe:
            logger.warning("Recipe %s not found, skipping", recipe_id)
            continue

        if recipe_id.startswith("TT-TRENDS"):
            tt_trends_recipes.append((recipe_id, recipe))
        elif recipe_id == "TT-1":
            tt_content_recipe = (recipe_id, recipe)
        else:
            other_recipes.append((recipe_id, recipe))

    if not other_recipes and not tt_trends_recipes and not tt_content_recipe:
        return LiveActivationResult(
            success=False,
            items=[],
            recipes_executed=[],
            total_cost=Decimal("0"),
            error="No valid recipes in execution plan",
        )

    # PHASE 1: Run TT-TRENDS + other recipes in parallel
    # TT-TRENDS discovers what's trending while other platforms collect evidence
    phase1_recipes = other_recipes + tt_trends_recipes
    tt_trends_raw_items: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_RECIPES) as executor:
        # Submit all Phase 1 recipes
        future_to_recipe = {
            executor.submit(
                execute_recipe,
                recipe=recipe,
                seed_pack=seed_pack,
                run_id=run_id,
                client=client,
            ): recipe_id
            for recipe_id, recipe in phase1_recipes
        }

        # Collect results as they complete
        for future in as_completed(future_to_recipe):
            recipe_id = future_to_recipe[future]
            try:
                result = future.result()
                recipes_executed.append(recipe_id)
                total_cost += result.estimated_cost

                if result.success:
                    all_items.extend(result.items)
                    logger.info(
                        "PARALLEL recipe %s complete: %d items (cost: $%.2f)",
                        recipe_id,
                        len(result.items),
                        float(result.estimated_cost),
                    )

                    # Collect raw items from TT-TRENDS for hashtag extraction
                    if recipe_id.startswith("TT-TRENDS"):
                        # Extract raw items from evidence items
                        for item in result.items:
                            if item.raw_json:
                                tt_trends_raw_items.append(item.raw_json)
                else:
                    errors.append(f"{recipe_id}: {result.error}")
                    logger.warning(
                        "PARALLEL recipe %s failed: %s",
                        recipe_id,
                        result.error,
                    )
            except Exception as e:
                errors.append(f"{recipe_id}: {str(e)}")
                logger.exception("PARALLEL recipe %s exception: %s", recipe_id, str(e))

    # PHASE 2: Execute TT-1 with discovered trending hashtags
    if tt_content_recipe:
        recipe_id, recipe = tt_content_recipe

        # Extract trending hashtags from TT-TRENDS results
        if tt_trends_raw_items:
            trending_hashtags = extract_trending_hashtags(tt_trends_raw_items)
            if trending_hashtags:
                # Create a modified seed_pack with trending hashtags
                seed_pack_with_trends = SeedPack(
                    brand_id=seed_pack.brand_id,
                    brand_name=seed_pack.brand_name,
                    positioning=seed_pack.positioning,
                    search_terms=seed_pack.search_terms,
                    pillar_keywords=seed_pack.pillar_keywords,
                    persona_contexts=seed_pack.persona_contexts,
                    snapshot_id=seed_pack.snapshot_id,
                    tiktok_queries=seed_pack.tiktok_queries,
                    tiktok_hashtags=seed_pack.tiktok_hashtags,
                    instagram_queries=seed_pack.instagram_queries,
                    instagram_hashtags=seed_pack.instagram_hashtags,
                    query_plan_error=seed_pack.query_plan_error,
                    inferred_industry=seed_pack.inferred_industry,
                    trending_hashtags=trending_hashtags,  # NEW: discovered trends
                )
                logger.info(
                    "TIKTOK_CHAIN TT-TRENDS → TT-1 with %d trending hashtags: %s",
                    len(trending_hashtags),
                    trending_hashtags,
                )
            else:
                seed_pack_with_trends = seed_pack
                logger.warning(
                    "TIKTOK_CHAIN no trending hashtags extracted from TT-TRENDS, "
                    "TT-1 will use Query Planner fallback"
                )
        else:
            seed_pack_with_trends = seed_pack
            logger.warning(
                "TIKTOK_CHAIN TT-TRENDS produced no raw items, "
                "TT-1 will use Query Planner fallback"
            )

        # Execute TT-1 with the (possibly enriched) seed pack
        logger.info(
            "PHASE2_EXECUTION: Running TT-1 with trending hashtags"
        )

        try:
            result = execute_recipe(
                recipe=recipe,
                seed_pack=seed_pack_with_trends,
                run_id=run_id,
                client=client,
            )
            recipes_executed.append(recipe_id)
            total_cost += result.estimated_cost

            if result.success:
                all_items.extend(result.items)
                logger.info(
                    "TIKTOK_CHAIN TT-1 complete: %d items with transcripts (cost: $%.2f)",
                    len(result.items),
                    float(result.estimated_cost),
                )
            else:
                errors.append(f"{recipe_id}: {result.error}")
                logger.warning(
                    "TIKTOK_CHAIN TT-1 failed: %s",
                    result.error,
                )
        except Exception as e:
            errors.append(f"{recipe_id}: {str(e)}")
            logger.exception("TIKTOK_CHAIN TT-1 exception: %s", str(e))

    logger.info(
        "PARALLEL_EXECUTION complete: %d items from %d recipes (cost: $%.2f)",
        len(all_items),
        len(recipes_executed),
        float(total_cost),
    )

    return LiveActivationResult(
        success=len(all_items) > 0,
        items=all_items,
        recipes_executed=recipes_executed,
        total_cost=total_cost,
        early_exit_reason=None,
        error="; ".join(errors) if errors and not all_items else None,
    )


def _execute_recipes_sequential(
    brand_id: UUID,
    seed_pack: SeedPack,
    run_id: UUID,
    execution_plan: list[str],
    client: ApifyClient,
) -> LiveActivationResult:
    """
    Execute recipes sequentially (legacy behavior).

    Kept for backwards compatibility and cases where sequential
    execution is preferred (e.g., debugging).
    """
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
