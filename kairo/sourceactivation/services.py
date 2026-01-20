"""
SourceActivation Services.

PR-4: Fixture-only SourceActivation end-to-end.
PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section B.0.4.

Main entry point for evidence acquisition:
- get_or_create_evidence_bundle(): Main API for obtaining evidence
- derive_seed_pack(): Create SeedPack from BrandBrainSnapshot

CRITICAL INVARIANTS:
1. fixture_only: NO Apify calls (loads from fixtures)
2. live_cap_limited: Apify calls with budget guards (PR-6)
3. SourceActivation makes ZERO LLM calls
4. All calls happen in background jobs only (never GET /today)
5. Deterministic: Same fixtures + same seed_pack = same EvidenceItems
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from django.db import transaction

from kairo.sourceactivation.fixtures.loader import generate_evidence_id, load_fixtures_for_brand
from kairo.sourceactivation.types import EvidenceBundle, EvidenceItemData, SeedPack

logger = logging.getLogger(__name__)


def derive_seed_pack(
    brand_id: UUID,
    snapshot_id: UUID | None = None,
    *,
    use_query_planner: bool = True,
) -> SeedPack:
    """
    Derive SeedPack from brand data (BrandBrainSnapshot).

    Per PRD Section A:
    - Deterministic derivation from snapshot
    - Contains search terms, pillar keywords, persona contexts

    QUERY PLANNER INTEGRATION:
    - When use_query_planner=True, calls LLM to generate semantic search probes
    - Probes are stored in tiktok_queries, instagram_queries, etc.
    - Recipes use these instead of naive brand-name searches

    Args:
        brand_id: UUID of the brand
        snapshot_id: Optional snapshot ID (uses latest if None)
        use_query_planner: Whether to use LLM query planning (default True)

    Returns:
        SeedPack instance with query plan populated
    """
    from kairo.core.models import Brand
    from kairo.brandbrain.models import BrandBrainSnapshot

    # Load brand
    brand = Brand.objects.get(id=brand_id)

    # Extract search terms from brand context
    search_terms = []
    pillar_keywords = []
    persona_contexts = []

    # Add brand name as primary search term
    search_terms.append(brand.name)

    # Add pillar names as keywords
    for pillar in brand.pillars.filter(is_active=True):
        pillar_keywords.append(pillar.name)
        if pillar.description:
            # Extract first sentence as context
            search_terms.append(pillar.description.split(".")[0])

    # Add persona contexts
    for persona in brand.personas.all():
        persona_contexts.append(f"{persona.name}: {persona.summary[:100] if persona.summary else ''}")

    # Get latest snapshot
    latest_snapshot = None
    if snapshot_id is None:
        latest_snapshot = (
            BrandBrainSnapshot.objects.filter(brand_id=brand_id)
            .order_by("-created_at")
            .first()
        )
        if latest_snapshot:
            snapshot_id = latest_snapshot.id
    else:
        latest_snapshot = BrandBrainSnapshot.objects.filter(id=snapshot_id).first()

    # Initialize Query Planner outputs
    tiktok_queries = []
    tiktok_hashtags = []
    instagram_queries = []
    instagram_hashtags = []
    query_plan_error = None

    # Call Query Planner if enabled and snapshot exists
    if use_query_planner and latest_snapshot:
        try:
            from kairo.sourceactivation.query_planner import generate_query_plan

            logger.info(
                "DERIVE_SEED_PACK calling Query Planner for brand_id=%s",
                brand_id,
            )

            query_plan = generate_query_plan(
                brand_id=str(brand_id),
                snapshot_json=latest_snapshot.snapshot_json,
                model="fast",  # Use fast model for query planning
            )

            if query_plan.error:
                logger.warning(
                    "Query Planner failed for brand_id=%s: %s",
                    brand_id,
                    query_plan.error,
                )
                query_plan_error = query_plan.error
            else:
                tiktok_queries = query_plan.get_tiktok_queries()
                tiktok_hashtags = query_plan.get_tiktok_hashtags()
                instagram_queries = query_plan.get_instagram_queries()
                instagram_hashtags = query_plan.get_instagram_hashtags()

                logger.info(
                    "Query Planner succeeded: tiktok_queries=%s instagram_queries=%s",
                    tiktok_queries,
                    instagram_queries,
                )

        except Exception as e:
            logger.exception(
                "Query Planner exception for brand_id=%s: %s",
                brand_id,
                str(e),
            )
            query_plan_error = str(e)

    return SeedPack(
        brand_id=brand_id,
        brand_name=brand.name,
        positioning=brand.positioning,
        search_terms=search_terms[:10],  # Limit to top 10
        pillar_keywords=pillar_keywords,
        persona_contexts=persona_contexts,
        snapshot_id=snapshot_id,
        # Query Planner outputs
        tiktok_queries=tiktok_queries,
        tiktok_hashtags=tiktok_hashtags,
        instagram_queries=instagram_queries,
        instagram_hashtags=instagram_hashtags,
        query_plan_error=query_plan_error,
    )


def get_or_create_evidence_bundle(
    brand_id: UUID,
    seed_pack: SeedPack,
    job_id: UUID,
    mode: Literal["fixture_only", "live_cap_limited"] = "fixture_only",
) -> EvidenceBundle:
    """
    Get or create evidence bundle for a brand.

    PR-4: "fixture_only" mode - loads from fixtures, no Apify calls.
    PR-6: "live_cap_limited" mode - executes Apify actors with budget controls.

    CRITICAL INVARIANT (TASK-2):
    When mode=live_cap_limited, fixtures are NEVER loaded as fallback.
    If Apify returns 0 items, we return empty bundle → insufficient_evidence.
    This ensures we get real feedback about evidence quality, not demo data.

    This function:
    1. Loads fixture data (fixture_only) or executes Apify actors (live_cap_limited)
    2. Creates ActivationRun record
    3. Persists EvidenceItem rows with deterministic IDs
    4. Returns EvidenceBundle with items

    Args:
        brand_id: UUID of the brand
        seed_pack: SeedPack derived from snapshot
        job_id: OpportunitiesJob ID for linking
        mode: "fixture_only" or "live_cap_limited"

    Returns:
        EvidenceBundle with evidence items

    Raises:
        ValueError: If mode is not supported
        GuardrailViolationError: If called from GET /today context
        ApifyDisabledError: If live mode and APIFY_ENABLED=false
    """
    # Guard against calling from GET /today
    from kairo.core.guardrails import assert_not_in_get_today, is_fixture_fallback_allowed

    assert_not_in_get_today()

    # TASK-2: Log whether fixture fallback is allowed (explicit visibility)
    fallback_allowed = is_fixture_fallback_allowed()
    logger.info(
        "Creating evidence bundle for brand %s (job=%s, mode=%s, FIXTURE_FALLBACK_ALLOWED=%s)",
        brand_id,
        job_id,
        mode,
        fallback_allowed,
    )

    now = datetime.now(timezone.utc)

    if mode == "fixture_only":
        # TASK-2: Explicit logging that fixtures are being used
        logger.info("FIXTURE_FALLBACK_USED=true (mode=fixture_only)")
        return _create_fixture_bundle(brand_id, seed_pack, job_id, now)
    elif mode == "live_cap_limited":
        # TASK-2: In live mode, fixtures are NEVER used as fallback
        # If Apify returns empty, we return empty bundle → gates fail → insufficient_evidence
        logger.info("FIXTURE_FALLBACK_USED=false (mode=live_cap_limited, fixtures disabled)")
        return _create_live_bundle(brand_id, seed_pack, job_id, now)
    else:
        raise ValueError(f"Unknown mode: {mode}. Must be 'fixture_only' or 'live_cap_limited'.")


def _create_fixture_bundle(
    brand_id: UUID,
    seed_pack: SeedPack,
    job_id: UUID,
    now: datetime,
) -> EvidenceBundle:
    """Create evidence bundle from fixtures (PR-4 mode)."""
    # Load fixtures
    fixture_items = load_fixtures_for_brand(brand_id, seed_pack)

    if not fixture_items:
        logger.warning(
            "No fixture items found for brand %s",
            brand_id,
        )
        # Return empty bundle
        return EvidenceBundle(
            brand_id=brand_id,
            activation_run_id=None,
            snapshot_id=seed_pack.snapshot_id,
            items=[],
            mode="fixture_only",
            recipes_executed=["FIXTURE"],
            fetched_at=now,
        )

    # Persist to database
    activation_run_id, persisted_items = _persist_evidence(
        brand_id=brand_id,
        job_id=job_id,
        seed_pack=seed_pack,
        items=fixture_items,
        recipes_selected=["FIXTURE"],
        recipes_executed=["FIXTURE"],
        estimated_cost=0,
    )

    logger.info(
        "Created ActivationRun %s with %d EvidenceItems for brand %s (fixture_only)",
        activation_run_id,
        len(persisted_items),
        brand_id,
    )

    return EvidenceBundle(
        brand_id=brand_id,
        activation_run_id=activation_run_id,
        snapshot_id=seed_pack.snapshot_id,
        items=persisted_items,
        mode="fixture_only",
        recipes_executed=["FIXTURE"],
        fetched_at=now,
    )


def _create_live_bundle(
    brand_id: UUID,
    seed_pack: SeedPack,
    job_id: UUID,
    now: datetime,
) -> EvidenceBundle:
    """
    Create evidence bundle via live Apify execution (PR-6 mode).

    Per PRD G.1/G.2:
    - Requires APIFY_ENABLED=true
    - Budget checks before execution
    - Result caps enforced at actor input level
    - Early-exit on evidence sufficiency or budget exhaustion

    TASK-2: FAIL-FAST SEMANTICS
    - If APIFY_ENABLED=false → raise immediately (no hanging)
    - If APIFY_TOKEN missing → raise immediately
    - Log APIFY_PRECONDITION_CHECK for visibility
    """
    from django.conf import settings as django_settings
    from kairo.core.guardrails import (
        ApifyDisabledError,
        is_apify_enabled,
        require_live_apify_allowed,
    )
    from kairo.sourceactivation.budget import (
        BudgetStatus,
        check_budget_for_run,
        estimate_execution_plan_cost,
    )
    from kairo.sourceactivation.live import execute_live_activation
    from kairo.sourceactivation.recipes import get_execution_plan

    # TASK-2: Fail-fast precondition checks with explicit logging
    apify_enabled = is_apify_enabled()
    apify_token = getattr(django_settings, "APIFY_TOKEN", None)

    logger.info(
        "APIFY_PRECONDITION_CHECK brand_id=%s job_id=%s apify_enabled=%s token_present=%s",
        brand_id,
        job_id,
        apify_enabled,
        bool(apify_token),
    )

    if not apify_enabled:
        logger.error(
            "APIFY_PRECONDITION_FAILED brand_id=%s reason=APIFY_ENABLED_FALSE",
            brand_id,
        )
        raise ApifyDisabledError(
            "Live mode requested but APIFY_ENABLED=false. "
            "Set APIFY_ENABLED=true to use live_cap_limited mode."
        )

    if not apify_token:
        logger.error(
            "APIFY_PRECONDITION_FAILED brand_id=%s reason=APIFY_TOKEN_MISSING",
            brand_id,
        )
        raise ValueError(
            "Live mode requested but APIFY_TOKEN is not configured. "
            "Set APIFY_TOKEN environment variable."
        )

    # INVARIANT: Live mode requires Apify enabled and not in GET context
    require_live_apify_allowed()

    # Get execution plan and estimate cost
    execution_plan = get_execution_plan(seed_pack)

    # TASK-2: Hard invariant - recipes must be selected for live mode
    # If no recipes are selected, Apify will never be called → silent failure
    # Note: execution_plan is a list of recipe_id strings (e.g., ["IG-1", "TT-1"])
    logger.info(
        "RECIPE_SELECTION brand_id=%s recipes_count=%d recipes=%s",
        brand_id,
        len(execution_plan),
        execution_plan,  # Already a list of strings
    )

    if not execution_plan:
        logger.error(
            "RECIPE_SELECTION_FAILED brand_id=%s reason=NO_RECIPES_SELECTED seed_pack_platforms=%s",
            brand_id,
            seed_pack.search_terms,  # Log what seed pack contains for debugging
        )
        raise ValueError(
            "Live mode requested but no recipes were selected. "
            "Check seed_pack configuration and recipe selection logic."
        )

    estimated_cost = estimate_execution_plan_cost(execution_plan)

    # Check budget before starting
    budget_check = check_budget_for_run(estimated_cost)
    if not budget_check.can_proceed:
        logger.warning(
            "Budget check failed for brand %s: %s (status=%s)",
            brand_id,
            budget_check.message,
            budget_check.status.value,
        )
        # Return empty bundle with budget failure reason
        return EvidenceBundle(
            brand_id=brand_id,
            activation_run_id=None,
            snapshot_id=seed_pack.snapshot_id,
            items=[],
            mode="live_cap_limited",
            recipes_executed=[],
            fetched_at=now,
        )

    # Execute live activation
    result = execute_live_activation(
        brand_id=brand_id,
        seed_pack=seed_pack,
        run_id=job_id,  # Use job_id as run_id for correlation
    )

    if not result.success and not result.items:
        logger.warning(
            "Live activation failed for brand %s: %s",
            brand_id,
            result.error,
        )
        # Return empty bundle
        return EvidenceBundle(
            brand_id=brand_id,
            activation_run_id=None,
            snapshot_id=seed_pack.snapshot_id,
            items=[],
            mode="live_cap_limited",
            recipes_executed=result.recipes_executed,
            fetched_at=now,
        )

    # Persist to database
    activation_run_id, persisted_items = _persist_evidence(
        brand_id=brand_id,
        job_id=job_id,
        seed_pack=seed_pack,
        items=result.items,
        recipes_selected=execution_plan,
        recipes_executed=result.recipes_executed,
        estimated_cost=float(result.total_cost),
    )

    logger.info(
        "Created ActivationRun %s with %d EvidenceItems for brand %s (live_cap_limited, cost=$%.2f)",
        activation_run_id,
        len(persisted_items),
        brand_id,
        float(result.total_cost),
    )

    return EvidenceBundle(
        brand_id=brand_id,
        activation_run_id=activation_run_id,
        snapshot_id=seed_pack.snapshot_id,
        items=persisted_items,
        mode="live_cap_limited",
        recipes_executed=result.recipes_executed,
        fetched_at=now,
    )


def _persist_evidence(
    brand_id: UUID,
    job_id: UUID,
    seed_pack: SeedPack,
    items: list[EvidenceItemData],
    *,
    recipes_selected: list[str] | None = None,
    recipes_executed: list[str] | None = None,
    estimated_cost: float = 0,
) -> tuple[UUID, list[EvidenceItemData]]:
    """
    Persist evidence items to database.

    Creates:
    - ActivationRun record
    - EvidenceItem records (with deterministic IDs)

    PR-4 requirement: Idempotent - repeated runs don't duplicate items.
    Uses update_or_create with deterministic IDs.

    PR-4b requirement: job_id must be a real OpportunitiesJob.
    Per PRD §D.3.2: ActivationRun.job is required for ledger traceability.

    PR-6: Added recipes_selected, recipes_executed, estimated_cost params.

    Args:
        brand_id: UUID of the brand
        job_id: OpportunitiesJob ID (REQUIRED - must be a real job)
        seed_pack: SeedPack used
        items: List of EvidenceItemData to persist
        recipes_selected: List of recipe IDs that were selected for execution
        recipes_executed: List of recipe IDs that were actually executed
        estimated_cost: Estimated Apify cost for this run (USD)

    Returns:
        Tuple of (activation_run_id, persisted_items)

    Raises:
        ValueError: If job_id does not reference a real OpportunitiesJob
    """
    from kairo.hero.models import ActivationRun, EvidenceItem, OpportunitiesJob

    now = datetime.now(timezone.utc)

    # Default recipes
    if recipes_selected is None:
        recipes_selected = ["FIXTURE"]
    if recipes_executed is None:
        recipes_executed = ["FIXTURE"]

    # PR-4b: Validate job_id is a real OpportunitiesJob (required per PRD §D.3.2)
    if not job_id:
        raise ValueError(
            "job_id is required for SourceActivation. "
            "Per PRD §D.3.2: ActivationRun must link to OpportunitiesJob for ledger traceability."
        )

    if not OpportunitiesJob.objects.filter(id=job_id).exists():
        raise ValueError(
            f"job_id {job_id} does not reference a real OpportunitiesJob. "
            "SourceActivation must only be invoked from job execution context."
        )

    with transaction.atomic():
        # Create ActivationRun
        activation_run = ActivationRun.objects.create(
            job_id=job_id,  # PR-4b: Required FK
            brand_id=brand_id,
            snapshot_id=seed_pack.snapshot_id or brand_id,  # Fallback to brand_id if no snapshot
            seed_pack_json={
                "brand_name": seed_pack.brand_name,
                "positioning": seed_pack.positioning,
                "search_terms": seed_pack.search_terms,
                "pillar_keywords": seed_pack.pillar_keywords,
            },
            recipes_selected=recipes_selected,
            recipes_executed=recipes_executed,
            item_count=len(items),
            items_with_transcript=sum(1 for i in items if i.has_transcript),
            estimated_cost_usd=estimated_cost,
        )

        persisted_items = []
        for item in items:
            # Generate deterministic ID
            evidence_id = generate_evidence_id(
                brand_id=brand_id,
                platform=item.platform,
                canonical_url=item.canonical_url,
            )

            # Use update_or_create for idempotency
            evidence_item, created = EvidenceItem.objects.update_or_create(
                id=evidence_id,
                defaults={
                    "activation_run": activation_run,
                    "brand_id": brand_id,
                    "platform": item.platform,
                    "actor_id": item.actor_id,
                    "acquisition_stage": item.acquisition_stage,
                    "recipe_id": item.recipe_id,
                    "canonical_url": item.canonical_url,
                    "external_id": item.external_id,
                    "author_ref": item.author_ref,
                    "title": item.title,
                    "text_primary": item.text_primary,
                    "text_secondary": item.text_secondary,
                    "hashtags": item.hashtags,
                    "view_count": item.view_count,
                    "like_count": item.like_count,
                    "comment_count": item.comment_count,
                    "share_count": item.share_count,
                    "published_at": item.published_at,
                    "fetched_at": item.fetched_at or now,
                    "has_transcript": item.has_transcript,
                    "raw_json": item.raw_json,
                },
            )

            persisted_items.append(item)

            logger.debug(
                "Persisted EvidenceItem %s (created=%s) for brand %s",
                evidence_id,
                created,
                brand_id,
            )

        # Update activation_run with end time
        activation_run.ended_at = datetime.now(timezone.utc)
        activation_run.save(update_fields=["ended_at"])

    return activation_run.id, persisted_items


def get_evidence_item_ids_for_bundle(
    brand_id: UUID,
    activation_run_id: UUID,
) -> list[UUID]:
    """
    Get persisted EvidenceItem IDs for an activation run.

    Args:
        brand_id: UUID of the brand
        activation_run_id: UUID of the ActivationRun

    Returns:
        List of EvidenceItem UUIDs
    """
    from kairo.hero.models import EvidenceItem

    return list(
        EvidenceItem.objects.filter(
            brand_id=brand_id,
            activation_run_id=activation_run_id,
        ).values_list("id", flat=True)
    )
