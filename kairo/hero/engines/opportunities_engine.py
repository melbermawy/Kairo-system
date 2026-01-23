"""
Opportunities Engine.

PR-8: Opportunities Graph Wired via Opportunities Engine (F1).
PR-4: SourceActivation integration (fixture-only mode).
PR-4b: Strict PRD compliance - EvidenceBundle replaces external signals (no merge).

Manages opportunity lifecycle:
- Generation of Today board (via graph)
- Scoring / re-scoring (via learning engine inputs)
- Board-level state: pin, snooze, staleness
- DB writes for Opportunity rows

Per docs/technical/03-engines-overview.md §5 and PR-map-and-standards §PR-8.

Key responsibilities (per 05-llm-and-deepagents-conventions.md):
- Engine owns all DB writes
- Graph returns DTOs only; engine converts to ORM and persists
- Engine handles failure modes and returns degraded board on graph failure

PR-4/4b: SourceActivation replaces external signals:
- PRD §C.1: BrandBrainSnapshot -> SeedPack -> EvidenceBundle -> signals
- No merging with legacy signals - pure replacement per PRD intent
- evidence_ids required (>= 1) for READY opportunities
"""

import logging
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID, uuid4, uuid5

from django.db import transaction

from kairo.core.enums import Channel, CreatedVia, OpportunityType
from kairo.core.models import Brand, Opportunity
from kairo.hero.dto import (
    BrandSnapshotDTO,
    LearningSummaryDTO,
    OpportunityDTO,
    OpportunityDraftDTO,
    PersonaDTO,
    PillarDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
)
from kairo.hero.engines import learning_engine
from kairo.hero.graphs.opportunities_graph import GraphError, graph_hero_generate_opportunities
from kairo.hero.graphs.synthesis_pipeline import (
    run_synthesis_pipeline,
    PipelineTimings,
    MIN_READY_OPPS,
)
from kairo.hero.llm_client import get_client_for_user
from kairo.hero.observability_store import (
    classify_f1_run,
    log_classification,
    log_run_complete,
    log_run_fail,
    log_run_start,
)
# PR-4b: external_signals_service import kept for legacy but NOT used in new path
# Per PRD §B.0.3: "external_signals" as upstream concept is deprecated
# from kairo.hero.services import external_signals_service  # DEPRECATED - do not use in new path

logger = logging.getLogger("kairo.hero.engines.opportunities")

# Namespace UUID for deterministic opportunity ID generation
OPPORTUNITY_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

# Feature flag: Use new multi-stage synthesis pipeline instead of monolithic graph
# Set KAIRO_USE_SYNTHESIS_PIPELINE=true to enable (default: true for performance)
import os
USE_SYNTHESIS_PIPELINE = os.getenv("KAIRO_USE_SYNTHESIS_PIPELINE", "true").lower() in ("true", "1", "yes")


class GenerationResult(NamedTuple):
    """Result of opportunity generation."""

    board: TodayBoardDTO
    opportunities_created: int
    status: str  # "success", "partial", "degraded"
    notes: list[str]


def generate_today_board(
    brand_id: UUID,
    run_id: UUID | None = None,
    trigger_source: str = "api",
    mode: str = "fixture_only",
    evidence_bundle=None,  # PERF: Pre-fetched bundle to avoid duplicate SourceActivation
    user_id: UUID | None = None,  # Phase 2 BYOK
) -> TodayBoardDTO:
    """
    Generate the Today board for a brand.

    PR-8 implementation:
    1. Build BrandSnapshotDTO from Brand + Persona + ContentPillar
    2. Obtain LearningSummaryDTO via learning_engine
    3. Call graph_hero_generate_opportunities
    4. Persist Opportunity rows (replace previous run's opportunities)
    5. Return TodayBoardDTO computed from persisted data

    PR-4b: SourceActivation REPLACES external signals (per PRD §C.1):
    1. Derive SeedPack from brand (BrandBrainSnapshot)
    2. Execute SourceActivation (fixture-only mode) -> EvidenceBundle
    3. Convert EvidenceBundle to signals via convert_evidence_bundle_to_signals()
    4. Pass signals to graph (NO MERGE with legacy signals)
    5. Propagate evidence_ids to persisted opportunities (>= 1 for READY)

    Failure modes (per PRD):
    - Graph failure: Log failure, return degraded board with existing or empty opportunities
    - SourceActivation failure: Return degraded/insufficient_evidence board
    - Learning summary failure: Use default summary and continue

    CRITICAL (PR-1): This function runs LLM synthesis and MUST NOT be called
    from GET /today context. Use background jobs for generation.

    Phase 2 BYOK: If user_id is provided, uses user's API keys for external services.

    Args:
        brand_id: UUID of the brand
        run_id: Optional run ID for correlation (auto-generated if None)
        trigger_source: Trigger source for observability
        mode: SourceActivation mode ("fixture_only" or "live_cap_limited")
        user_id: Optional user UUID for BYOK token lookup

    Returns:
        TodayBoardDTO with opportunities

    Raises:
        Brand.DoesNotExist: If brand not found
        GuardrailViolationError: If called from GET /today context (PR-1 invariant)
    """
    # PR-1: Guard against calling from GET /today context
    # Per PRD Section G.2 INV-G1: GET /today/ never directly executes LLM synthesis
    from kairo.core.guardrails import assert_not_in_get_today, get_sourceactivation_mode
    assert_not_in_get_today()

    # Generate run_id if not provided
    if run_id is None:
        run_id = uuid4()

    logger.info(
        "Starting Today board generation",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_id),
            "trigger_source": trigger_source,
        },
    )

    # Log run start to observability sink
    log_run_start(
        run_id=run_id,
        brand_id=brand_id,
        flow="F1_today",
        trigger_source=trigger_source,
    )

    # Look up brand from DB to validate it exists
    brand = Brand.objects.get(id=brand_id)

    # Build brand snapshot from actual brand data
    snapshot = _build_brand_snapshot(brand)

    # Fetch learning summary (with fallback)
    learning_summary = _get_learning_summary_safe(brand_id, run_id)

    # PR-4b/PR-6: Execute SourceActivation - this REPLACES external signals (per PRD §C.1)
    # Sequence: BrandBrainSnapshot -> SeedPack -> EvidenceBundle -> signals
    # PR-6: Mode determines fixture_only vs live_cap_limited execution
    # PERF: Skip SourceActivation if evidence_bundle was pre-fetched by caller (e.g., from task)
    if evidence_bundle is None:
        evidence_bundle = _get_evidence_bundle_safe(brand_id, run_id, mode=mode)
    else:
        logger.info(
            "Using pre-fetched evidence_bundle (skipping duplicate SourceActivation)",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "items_count": len(evidence_bundle.items) if evidence_bundle.items else 0,
            },
        )
    selected_evidence_ids: list[UUID] = []

    # PR-4b: Signals come exclusively from EvidenceBundle (no merge with legacy)
    signals = _convert_evidence_to_signals(brand_id, run_id, evidence_bundle)

    if evidence_bundle and evidence_bundle.items:
        # Select evidence for opportunities
        from kairo.sourceactivation.adapters import select_evidence_for_opportunity
        selected_evidence_ids = select_evidence_for_opportunity(evidence_bundle, max_items=3)

        logger.info(
            "SourceActivation completed: %d items, %d selected for opportunities",
            len(evidence_bundle.items),
            len(selected_evidence_ids),
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "activation_run_id": str(evidence_bundle.activation_run_id) if evidence_bundle.activation_run_id else None,
            },
        )

    # Call synthesis to generate opportunities
    total_candidates: int | None = None
    degraded_reason: str | None = None
    pipeline_timings: PipelineTimings | None = None

    try:
        if USE_SYNTHESIS_PIPELINE and evidence_bundle and evidence_bundle.items:
            # NEW: Use multi-stage synthesis pipeline for better performance
            logger.info(
                "Using synthesis pipeline (USE_SYNTHESIS_PIPELINE=true)",
                extra={"run_id": str(run_id), "brand_id": str(brand_id)},
            )
            # Phase 2 BYOK: Get LLM client with user's API key if available
            llm_client = get_client_for_user(user_id)
            drafts, pipeline_timings = run_synthesis_pipeline(
                run_id=run_id,
                brand_snapshot=snapshot,
                evidence_items=evidence_bundle.items,
                llm_client=llm_client,
            )
        else:
            # LEGACY: Use monolithic graph (fallback or when no evidence)
            logger.info(
                "Using legacy graph (USE_SYNTHESIS_PIPELINE=false or no evidence)",
                extra={"run_id": str(run_id), "brand_id": str(brand_id)},
            )
            drafts = graph_hero_generate_opportunities(
                run_id=run_id,
                brand_snapshot=snapshot,
                learning_summary=learning_summary,
                external_signals=signals,  # PR-4b: Pure EvidenceBundle-derived signals
            )

        # Track total candidates from graph before any filtering
        total_candidates = len(drafts)

        # Per rubric §4.7: Filter out invalid opportunities before persisting
        valid_drafts, invalid_count = _filter_invalid_opportunities(drafts, run_id)

        # Per rubric §5.4: Filter near-duplicates
        deduped_drafts, dupe_count = _filter_redundant_opportunities(valid_drafts)

        # Persist valid, non-duplicate opportunities
        # PR-4: Pass evidence_ids for propagation
        opportunities = _persist_opportunities(
            brand=brand,
            drafts=deduped_drafts,
            run_id=run_id,
            evidence_ids=selected_evidence_ids,
        )

        # Determine status based on opportunity count and MIN_READY_OPPS threshold
        # CRITICAL: Partial success (1-2 opps) is still valid - better than nothing
        if len(opportunities) >= MIN_READY_OPPS:
            status = "success"
        elif len(opportunities) > 0:
            status = "partial"  # Less than minimum but still usable
        else:
            status = "empty"  # No opportunities at all

        notes = [f"Generated {len(opportunities)} opportunities (min_required={MIN_READY_OPPS})"]
        if status == "partial":
            notes.append(f"Partial result: {len(opportunities)} < {MIN_READY_OPPS} minimum")
        if pipeline_timings:
            notes.append(f"Pipeline: {pipeline_timings.total_ms}ms total")
            # Add expansion stats if available
            if pipeline_timings.expansion_attempts > 0:
                notes.append(
                    f"Expansions: {pipeline_timings.expansion_successes}/{pipeline_timings.expansion_attempts} "
                    f"(timeouts={pipeline_timings.expansion_timeouts}, failures={pipeline_timings.expansion_failures})"
                )
        if invalid_count > 0:
            notes.append(f"Filtered {invalid_count} invalid opportunities")
        if dupe_count > 0:
            notes.append(f"Filtered {dupe_count} near-duplicate opportunities")

        # Build metrics with optional pipeline timings
        metrics = {
            "opportunities_count": len(opportunities),
            "invalid_filtered": invalid_count,
            "duplicates_filtered": dupe_count,
            "total_candidates": total_candidates,
        }
        if pipeline_timings:
            metrics["pipeline_timings"] = pipeline_timings.to_dict()

        logger.info(
            "Today board generation complete",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "status": status,
                **metrics,
            },
        )

        # Log run completion to observability sink
        log_run_complete(
            run_id=run_id,
            brand_id=brand_id,
            flow="F1_today",
            status=status,
            metrics=metrics,
        )

        # Classify and log classification
        f1_health, f1_reason = classify_f1_run(
            opportunity_count=total_candidates,
            valid_opportunity_count=len(opportunities),
            taboo_violations=0,  # Taboo check happens at package level
            status="ok",
        )
        log_classification(
            run_id=run_id,
            brand_id=brand_id,
            f1_health=f1_health,
            f2_health=None,
            run_health=f1_health,
            reason=f1_reason,
        )

    except GraphError as e:
        logger.error(
            "Graph failed, returning degraded board",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "error": str(e),
            },
        )

        # Log run failure to observability sink
        log_run_fail(
            run_id=run_id,
            brand_id=brand_id,
            flow="F1_today",
            error=str(e),
            error_type="GraphError",
        )

        # Classify and log classification for failed run
        f1_health, f1_reason = classify_f1_run(
            opportunity_count=0,
            valid_opportunity_count=0,
            taboo_violations=0,
            status="fail",
        )
        log_classification(
            run_id=run_id,
            brand_id=brand_id,
            f1_health=f1_health,
            f2_health=None,
            run_health=f1_health,
            reason=f1_reason,
        )

        # Return degraded board with existing opportunities or stub
        opportunities = _get_degraded_opportunities(brand, run_id)
        status = "degraded"
        degraded_reason = "graph_error"
        notes = [
            f"Graph failed: {str(e)[:100]}",
            "Returning degraded board with fallback opportunities",
        ]

    # Build the final board DTO
    return _build_today_board_dto(
        brand=brand,
        snapshot=snapshot,
        opportunities=opportunities,
        status=status,
        notes=notes,
        total_candidates=total_candidates,
        degraded_reason=degraded_reason,
    )


def _build_brand_snapshot(brand: Brand) -> BrandSnapshotDTO:
    """
    Build a BrandSnapshotDTO from a Brand model.

    Loads related personas and pillars from DB.
    Also extracts cta_policy and content_goal from BrandBrainSnapshot if available.
    """
    # Load personas
    personas = []
    for persona in brand.personas.all():
        personas.append(
            PersonaDTO(
                id=persona.id,
                name=persona.name,
                role=persona.role or None,
                summary=persona.summary,
                priorities=persona.priorities or [],
                pains=persona.pains or [],
                success_metrics=persona.success_metrics or [],
                channel_biases=persona.channel_biases or {},
            )
        )

    # Load pillars
    pillars = []
    for pillar in brand.pillars.filter(is_active=True):
        pillars.append(
            PillarDTO(
                id=pillar.id,
                name=pillar.name,
                category=pillar.category or None,
                description=pillar.description,
                priority_rank=pillar.priority_rank,
                is_active=pillar.is_active,
            )
        )

    # Extract cta_policy and content_goal from BrandBrainSnapshot
    # These fields are in snapshot_json.voice.cta_policy and snapshot_json.meta.content_goal
    cta_policy = "soft"  # default
    content_goal = None
    voice_tone_tags = brand.tone_tags or []
    taboos = brand.taboos or []

    try:
        # Import here to avoid circular dependency
        from kairo.brandbrain.models import BrandBrainSnapshot

        snapshot = BrandBrainSnapshot.objects.filter(brand=brand).order_by("-created_at").first()
        if snapshot and snapshot.snapshot_json:
            data = snapshot.snapshot_json

            # Extract cta_policy from voice section
            voice = data.get("voice", {})
            cta_policy_field = voice.get("cta_policy", {})
            if isinstance(cta_policy_field, dict):
                cta_policy = cta_policy_field.get("value", "soft")
            elif isinstance(cta_policy_field, str):
                cta_policy = cta_policy_field

            # Extract content_goal from meta section
            meta = data.get("meta", {})
            content_goal_field = meta.get("content_goal", {})
            if isinstance(content_goal_field, dict):
                content_goal = content_goal_field.get("value")
            elif isinstance(content_goal_field, str):
                content_goal = content_goal_field

            # Also get tone_tags and taboos from snapshot if richer than Brand model
            snapshot_tone_tags = voice.get("tone_tags", [])
            if snapshot_tone_tags and len(snapshot_tone_tags) > len(voice_tone_tags):
                voice_tone_tags = snapshot_tone_tags

            snapshot_taboos = voice.get("taboos", [])
            if snapshot_taboos and len(snapshot_taboos) > len(taboos):
                taboos = snapshot_taboos

            # Also extract pillars from snapshot if Brand model has none
            if not pillars:
                content_section = data.get("content", {})
                content_pillars = content_section.get("content_pillars", [])
                for i, p in enumerate(content_pillars):
                    pillars.append(
                        PillarDTO(
                            id=uuid4(),  # Generate synthetic ID
                            name=p.get("name", f"Pillar {i+1}"),
                            description=p.get("description", ""),
                        )
                    )
    except Exception as e:
        # Log but don't fail - we have defaults
        logger.warning(f"Failed to extract snapshot fields: {e}")

    return BrandSnapshotDTO(
        brand_id=brand.id,
        brand_name=brand.name,
        positioning=brand.positioning or None,
        pillars=pillars,
        personas=personas,
        voice_tone_tags=voice_tone_tags,
        taboos=taboos,
        cta_policy=cta_policy,
        content_goal=content_goal,
    )


def _get_learning_summary_safe(brand_id: UUID, run_id: UUID) -> LearningSummaryDTO:
    """
    Get learning summary with fallback on error.

    Returns a default summary if learning_engine fails.
    """
    try:
        return learning_engine.summarize_learning_for_brand(brand_id)
    except Exception as e:
        logger.warning(
            "Learning summary fetch failed, using default",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "error": str(e),
            },
        )
        return LearningSummaryDTO(
            brand_id=brand_id,
            generated_at=datetime.now(timezone.utc),
            top_performing_patterns=[],
            top_performing_channels=[],
            recent_engagement_score=0.0,
            pillar_performance={},
            persona_engagement={},
            notes=["Learning summary unavailable - using defaults"],
        )


def _get_evidence_bundle_safe(brand_id: UUID, run_id: UUID, mode: str = "fixture_only"):
    """
    Get evidence bundle via SourceActivation with fallback on error.

    PR-4: Fixture-only mode - no Apify calls.
    PR-6: Live-cap-limited mode - Apify calls with budget controls.
    Returns None if SourceActivation fails.

    Args:
        brand_id: UUID of the brand
        run_id: UUID of the job (for ActivationRun FK)
        mode: "fixture_only" or "live_cap_limited"
    """
    try:
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        logger.info(
            "Starting SourceActivation",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "mode": mode,
            },
        )

        # Derive seed pack from brand
        seed_pack = derive_seed_pack(brand_id)

        # Get or create evidence bundle (PR-6: mode passed through)
        evidence_bundle = get_or_create_evidence_bundle(
            brand_id=brand_id,
            seed_pack=seed_pack,
            job_id=run_id,
            mode=mode,
        )

        return evidence_bundle

    except Exception as e:
        logger.warning(
            "SourceActivation failed, continuing without evidence",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "error": str(e),
            },
        )
        return None


def _convert_evidence_to_signals(brand_id: UUID, run_id: UUID, evidence_bundle):
    """
    Convert EvidenceBundle to signals for graph consumption.

    PR-4b: Per PRD §C.1, this is a REPLACEMENT, not merge.
    Signals come exclusively from SourceActivation's EvidenceBundle.

    If evidence_bundle is None or empty, returns empty signals bundle.
    This may result in a degraded board state.
    """
    from kairo.hero.dto import ExternalSignalBundleDTO

    now = datetime.now(timezone.utc)

    # No evidence bundle = empty signals (may trigger degraded state)
    if not evidence_bundle or not evidence_bundle.items:
        logger.info(
            "No evidence bundle available, using empty signals",
            extra={"run_id": str(run_id), "brand_id": str(brand_id)},
        )
        return ExternalSignalBundleDTO(
            brand_id=brand_id,
            fetched_at=now,
            trends=[],
            web_mentions=[],
            competitor_posts=[],
            social_moments=[],
        )

    # Convert evidence to signals (pure transformation, no merge)
    try:
        from kairo.sourceactivation.adapters import convert_evidence_bundle_to_signals
        signals = convert_evidence_bundle_to_signals(evidence_bundle)
        logger.debug(
            "Converted %d evidence items to signals (pure, no merge)",
            len(evidence_bundle.items),
            extra={"run_id": str(run_id), "brand_id": str(brand_id)},
        )
        return signals
    except Exception as e:
        logger.warning(
            "Evidence to signals conversion failed, using empty signals",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "error": str(e),
            },
        )
        return ExternalSignalBundleDTO(
            brand_id=brand_id,
            fetched_at=now,
            trends=[],
            web_mentions=[],
            competitor_posts=[],
            social_moments=[],
        )


def _filter_invalid_opportunities(
    drafts: list[OpportunityDraftDTO],
    run_id: UUID,
) -> tuple[list[OpportunityDraftDTO], int]:
    """
    Filter out invalid opportunities per rubric §4.7.

    Per rubric:
    - Engine must drop all is_valid=False opps
    - Log rejection reasons for observability

    Returns (valid_drafts, invalid_count).
    """
    valid = []
    invalid_count = 0

    for draft in drafts:
        if draft.is_valid:
            valid.append(draft)
        else:
            invalid_count += 1
            logger.info(
                "Filtering invalid opportunity",
                extra={
                    "run_id": str(run_id),
                    "title": draft.proposed_title[:50],
                    "rejection_reasons": draft.rejection_reasons,
                },
            )

    return valid, invalid_count


def _compute_title_similarity(title1: str, title2: str) -> float:
    """
    Compute simple token-based similarity between two titles.

    Uses Jaccard similarity on lowercased word tokens.
    Returns value in [0, 1].
    """
    words1 = set(title1.lower().split())
    words2 = set(title2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def _filter_redundant_opportunities(
    drafts: list[OpportunityDraftDTO],
    similarity_threshold: float = 0.75,
) -> tuple[list[OpportunityDraftDTO], int]:
    """
    Filter near-duplicate opportunities per rubric §5.4.

    Uses simple title similarity. Keeps the higher-scored opp in each duplicate pair.

    Returns (deduped_drafts, duplicate_count).
    """
    # Sort by score descending so we keep the best one
    sorted_drafts = sorted(drafts, key=lambda d: d.score, reverse=True)

    kept = []
    duplicate_count = 0

    for draft in sorted_drafts:
        is_duplicate = False

        for existing in kept:
            sim = _compute_title_similarity(draft.proposed_title, existing.proposed_title)
            if sim >= similarity_threshold:
                is_duplicate = True
                duplicate_count += 1
                logger.debug(
                    "Filtering duplicate opportunity",
                    extra={
                        "title": draft.proposed_title[:50],
                        "similar_to": existing.proposed_title[:50],
                        "similarity": sim,
                    },
                )
                break

        if not is_duplicate:
            kept.append(draft)

    return kept, duplicate_count


def _persist_opportunities(
    brand: Brand,
    drafts: list[OpportunityDraftDTO],
    run_id: UUID,
    evidence_ids: list[UUID] | None = None,
) -> list[Opportunity]:
    """
    Persist OpportunityDraftDTOs as Opportunity rows.

    PR-2: why_now is REQUIRED for persistence.
    - Drafts with missing/invalid why_now are SKIPPED (not persisted)
    - why_now must be non-empty and >= 10 chars after stripping

    PR-4b: evidence_ids contract enforcement (per PRD §F.1).
    - For READY board, evidence_ids must be >= 1
    - All persisted opportunities receive the same selected evidence_ids
    - If evidence_ids is empty, NO drafts are persisted (board = insufficient_evidence)

    Idempotency rules:
    - Each run creates new opportunities
    - Opportunities get deterministic IDs based on brand + title hash
    - Previous opportunities for the brand are NOT deleted (they may be pinned)

    Returns list of created/updated Opportunity model instances.
    """
    now = datetime.now(timezone.utc)
    opportunities = []

    # PR-4b: Convert evidence_ids to strings for JSON storage
    evidence_ids_str = [str(eid) for eid in (evidence_ids or [])]

    # PR-4b: REQUIRED - evidence_ids must be non-empty for READY opportunities
    # Per PRD §F.1: evidence_ids min_length=1 for real opportunities
    if not evidence_ids_str:
        logger.warning(
            "No evidence_ids provided - cannot persist READY opportunities",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand.id),
                "draft_count": len(drafts),
                "reason": "PRD §F.1 requires evidence_ids >= 1 for READY opportunities",
            },
        )
        return []  # Return empty - triggers degraded/insufficient_evidence board

    with transaction.atomic():
        for draft in drafts:
            # PR-2: Validate why_now (REQUIRED, >= 10 chars)
            why_now = (draft.why_now or "").strip()
            if len(why_now) < 10:
                logger.warning(
                    "Skipping draft with invalid why_now",
                    extra={
                        "run_id": str(run_id),
                        "title": draft.proposed_title[:50],
                        "why_now_len": len(why_now),
                        "reason": "why_now must be >= 10 chars",
                    },
                )
                continue  # Skip this draft - do not persist

            # Generate deterministic ID based on brand_id + title
            # This ensures idempotency if the same opportunity is generated again
            opp_id = uuid5(
                OPPORTUNITY_NAMESPACE,
                f"{brand.id}:{draft.proposed_title}",
            )

            # Resolve persona hint to ID if possible
            persona_id = None
            if draft.persona_hint:
                persona = brand.personas.filter(name__iexact=draft.persona_hint).first()
                if persona:
                    persona_id = persona.id

            # Resolve pillar hint to ID if possible
            pillar_id = None
            if draft.pillar_hint:
                pillar = brand.pillars.filter(name__iexact=draft.pillar_hint).first()
                if pillar:
                    pillar_id = pillar.id

            # Create or update opportunity
            # PR-2: Store why_now and evidence_ids in metadata
            # PR-4: Populate evidence_ids from SourceActivation
            opp, created = Opportunity.objects.update_or_create(
                id=opp_id,
                defaults={
                    "brand": brand,
                    "title": draft.proposed_title,
                    "angle": draft.proposed_angle,
                    "type": draft.type.value,
                    "primary_channel": draft.primary_channel.value,
                    "score": draft.score,
                    "score_explanation": draft.score_explanation or "",
                    "source": draft.source,
                    "source_url": draft.source_url or "",
                    "persona": brand.personas.filter(id=persona_id).first() if persona_id else None,
                    "pillar": brand.pillars.filter(id=pillar_id).first() if pillar_id else None,
                    "suggested_channels": [c.value for c in draft.suggested_channels],
                    "created_via": CreatedVia.AI_SUGGESTED.value,
                    "metadata": {
                        "raw_reasoning": draft.raw_reasoning,
                        "run_id": str(run_id),
                        "generated_at": now.isoformat(),
                        # PR-2: Persist why_now (REQUIRED)
                        "why_now": why_now,
                        # PR-4: Populate evidence_ids from SourceActivation
                        "evidence_ids": evidence_ids_str,
                    },
                },
            )

            opportunities.append(opp)

            logger.debug(
                "Persisted opportunity",
                extra={
                    "run_id": str(run_id),
                    "opp_id": str(opp_id),
                    "title": draft.proposed_title[:50],
                    "created": created,
                    "why_now_len": len(why_now),
                    "evidence_ids_count": len(evidence_ids_str),
                },
            )

    return opportunities


def _get_degraded_opportunities(brand: Brand, run_id: UUID) -> list[Opportunity]:
    """
    Get fallback opportunities for degraded mode.

    Strategy:
    1. Try to return existing opportunities for the brand (may have been pinned)
    2. If none exist, return stub opportunities

    This ensures the UI always has something to show.
    """
    # Try to get existing opportunities from DB
    existing = list(
        Opportunity.objects.filter(brand=brand)
        .order_by("-score", "-created_at")[:12]
    )

    if existing:
        logger.info(
            "Using existing opportunities for degraded board",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand.id),
                "count": len(existing),
            },
        )
        return existing

    # Generate stub opportunities as last resort
    logger.info(
        "No existing opportunities, generating stubs for degraded board",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand.id),
        },
    )

    return _generate_stub_opportunities(brand, run_id)


def _generate_stub_opportunities(brand: Brand, run_id: UUID) -> list[Opportunity]:
    """
    Generate deterministic stub opportunities as fallback.

    Used when graph fails and no existing opportunities are available.

    8c fix: Stubs are now PERSISTED to DB so that F2 (content engine) can
    look them up by ID. This ensures degraded mode is structurally valid
    end-to-end.

    The stubs have:
    - Deterministic IDs based on brand + index
    - metadata.stub = True to identify them as fallback content
    - metadata.degraded_run_id = run_id for tracking
    """
    now = datetime.now(timezone.utc)

    # Deterministic opportunity templates
    templates = [
        {
            "title": f"Industry trend: AI adoption in {brand.name}'s sector",
            "angle": "Rising discussion about AI tools - opportunity to share our perspective on practical implementation.",
            "why_now": "AI adoption is accelerating across industries, making this a timely topic for thought leadership.",
            "type": OpportunityType.TREND,
            "channel": Channel.LINKEDIN,
            "score": 75.0,
        },
        {
            "title": "Weekly thought leadership post",
            "angle": "Regular cadence content about our core expertise area.",
            "why_now": "Consistent content builds audience trust and maintains visibility.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.LINKEDIN,
            "score": 72.0,
        },
        {
            "title": "Competitor announcement response",
            "angle": "Competitor just announced a feature - opportunity to differentiate our approach.",
            "why_now": "Competitor activity creates a natural hook for differentiation content.",
            "type": OpportunityType.COMPETITIVE,
            "channel": Channel.X,
            "score": 68.0,
        },
        {
            "title": "Customer success story",
            "angle": "Recent customer achieved notable results - great case study material.",
            "why_now": "Fresh success stories resonate more and demonstrate current value.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.LINKEDIN,
            "score": 70.0,
        },
        {
            "title": "Industry report commentary",
            "angle": "New industry report released - can provide contrarian take aligned with our positioning.",
            "why_now": "Industry reports generate discussion windows for expert commentary.",
            "type": OpportunityType.TREND,
            "channel": Channel.X,
            "score": 65.0,
        },
        {
            "title": "Behind the scenes: Product development",
            "angle": "Authenticity content showing how we build - builds trust with audience.",
            "why_now": "Transparency content consistently performs well for building brand trust.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.LINKEDIN,
            "score": 60.0,
        },
    ]

    opportunities = []

    with transaction.atomic():
        for i, template in enumerate(templates):
            # Generate deterministic ID for stub
            opp_id = uuid5(OPPORTUNITY_NAMESPACE, f"stub:{brand.id}:{i}")

            # Use update_or_create to persist (idempotent)
            opp, created = Opportunity.objects.update_or_create(
                id=opp_id,
                defaults={
                    "brand": brand,
                    "title": template["title"],
                    "angle": template["angle"],
                    "type": template["type"].value,
                    "primary_channel": template["channel"].value,
                    "score": template["score"],
                    "score_explanation": "Fallback stub - graph was unavailable",
                    "source": "stub_engine",
                    "suggested_channels": [Channel.LINKEDIN.value, Channel.X.value],
                    "created_via": CreatedVia.AI_SUGGESTED.value,
                    "is_pinned": (i == 0),
                    "metadata": {
                        "stub": True,
                        "degraded_run_id": str(run_id),
                        # PR-2: Required fields
                        "why_now": template["why_now"],
                        "evidence_ids": [],  # Forward-compat (stubs have no evidence)
                        "generated_at": now.isoformat(),
                    },
                },
            )

            opportunities.append(opp)

            logger.debug(
                "Persisted stub opportunity",
                extra={
                    "run_id": str(run_id),
                    "opp_id": str(opp_id),
                    "title": template["title"][:50],
                    "created": created,
                },
            )

    logger.info(
        "Persisted stub opportunities for degraded board",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand.id),
            "count": len(opportunities),
        },
    )

    return opportunities


def _build_today_board_dto(
    brand: Brand,
    snapshot: BrandSnapshotDTO,
    opportunities: list[Opportunity],
    status: str,
    notes: list[str],
    total_candidates: int | None = None,
    degraded_reason: str | None = None,
) -> TodayBoardDTO:
    """
    Build TodayBoardDTO from brand, snapshot, and opportunities.

    Converts Opportunity models to OpportunityDTOs and computes metadata.

    Args:
        total_candidates: Raw count from graph before filtering (None if degraded)
        degraded_reason: Short code if degraded (e.g. "graph_error")
    """
    now = datetime.now(timezone.utc)

    # Convert opportunities to DTOs
    opp_dtos = []
    for opp in opportunities:
        # Handle both persisted objects (with FK) and in-memory stubs
        try:
            persona_id = opp.persona.id if opp.persona else None
        except Exception:
            persona_id = None
        try:
            pillar_id = opp.pillar.id if opp.pillar else None
        except Exception:
            pillar_id = None

        # PR-2: Read why_now and evidence_ids from metadata
        metadata = opp.metadata or {}
        why_now = metadata.get("why_now", "")

        # PR-2: Invalid why_now is an INVARIANT VIOLATION
        # This function is called after _persist_opportunities which filters invalid drafts.
        # If we get here with invalid why_now, something is broken.
        if not why_now or len(why_now.strip()) < 10:
            raise ValueError(
                f"PR-2 invariant violation: Opportunity {opp.id} has invalid why_now "
                f"(length={len(why_now.strip()) if why_now else 0}). "
                "This should have been filtered at persist-time."
            )

        # PR-2: Parse evidence_ids (may be empty until PR-4/5)
        evidence_ids_raw = metadata.get("evidence_ids", [])
        evidence_ids = []
        for eid in evidence_ids_raw:
            try:
                evidence_ids.append(UUID(str(eid)))
            except (ValueError, TypeError):
                pass

        opp_dto = OpportunityDTO(
            id=opp.id,
            brand_id=opp.brand_id,
            title=opp.title,
            angle=opp.angle,
            why_now=why_now.strip(),  # PR-2: Required field
            type=OpportunityType(opp.type),
            primary_channel=Channel(opp.primary_channel),
            score=opp.score,
            score_explanation=opp.score_explanation,
            source=opp.source or "",
            source_url=opp.source_url or None,
            persona_id=persona_id,
            pillar_id=pillar_id,
            suggested_channels=[Channel(c) for c in (opp.suggested_channels or [])],
            evidence_ids=evidence_ids,  # PR-2: Forward-compat field
            is_pinned=opp.is_pinned,
            is_snoozed=opp.is_snoozed,
            snoozed_until=opp.snoozed_until,
            created_via=CreatedVia(opp.created_via),
            created_at=opp.created_at or now,
            updated_at=opp.updated_at or now,
        )
        opp_dtos.append(opp_dto)

    # Sort by score descending
    opp_dtos.sort(key=lambda x: x.score, reverse=True)

    # Compute channel mix
    channel_mix = _compute_channel_mix(opp_dtos)

    # Build metadata
    meta = TodayBoardMetaDTO(
        generated_at=now,
        source="hero_f1",
        degraded=(status == "degraded"),
        total_candidates=total_candidates,
        reason=degraded_reason,
        notes=notes,
        opportunity_count=len(opp_dtos),
        dominant_pillar=snapshot.pillars[0].name if snapshot.pillars else None,
        dominant_persona=snapshot.personas[0].name if snapshot.personas else None,
        channel_mix=channel_mix,
    )

    return TodayBoardDTO(
        brand_id=brand.id,
        snapshot=snapshot,
        opportunities=opp_dtos,
        meta=meta,
    )


def _compute_channel_mix(opportunities: list[OpportunityDTO]) -> dict[str, int]:
    """Compute channel distribution from opportunities."""
    mix: dict[str, int] = {}
    for opp in opportunities:
        channel_value = opp.primary_channel.value
        mix[channel_value] = mix.get(channel_value, 0) + 1
    return mix
