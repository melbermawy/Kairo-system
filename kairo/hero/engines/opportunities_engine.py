"""
Opportunities Engine.

PR-8: Opportunities Graph Wired via Opportunities Engine (F1).

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
from kairo.hero.services import external_signals_service

logger = logging.getLogger("kairo.hero.engines.opportunities")

# Namespace UUID for deterministic opportunity ID generation
OPPORTUNITY_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


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
) -> TodayBoardDTO:
    """
    Generate the Today board for a brand.

    PR-8 implementation:
    1. Build BrandSnapshotDTO from Brand + Persona + ContentPillar
    2. Obtain LearningSummaryDTO via learning_engine
    3. Fetch ExternalSignalBundleDTO via external_signals_service
    4. Call graph_hero_generate_opportunities
    5. Persist Opportunity rows (replace previous run's opportunities)
    6. Return TodayBoardDTO computed from persisted data

    Failure modes (per PRD):
    - Graph failure: Log failure, return degraded board with existing or empty opportunities
    - External signals failure: Use empty bundle and continue
    - Learning summary failure: Use default summary and continue

    Args:
        brand_id: UUID of the brand
        run_id: Optional run ID for correlation (auto-generated if None)
        trigger_source: Trigger source for observability

    Returns:
        TodayBoardDTO with opportunities

    Raises:
        Brand.DoesNotExist: If brand not found
    """
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

    # Look up brand from DB to validate it exists
    brand = Brand.objects.get(id=brand_id)

    # Build brand snapshot from actual brand data
    snapshot = _build_brand_snapshot(brand)

    # Fetch learning summary (with fallback)
    learning_summary = _get_learning_summary_safe(brand_id, run_id)

    # Fetch external signals (with fallback)
    external_signals = _get_external_signals_safe(brand_id, run_id)

    # Call graph to generate opportunities
    total_candidates: int | None = None
    degraded_reason: str | None = None

    try:
        drafts = graph_hero_generate_opportunities(
            run_id=run_id,
            brand_snapshot=snapshot,
            learning_summary=learning_summary,
            external_signals=external_signals,
        )

        # Track total candidates from graph before any filtering
        total_candidates = len(drafts)

        # Per rubric §4.7: Filter out invalid opportunities before persisting
        valid_drafts, invalid_count = _filter_invalid_opportunities(drafts, run_id)

        # Per rubric §5.4: Filter near-duplicates
        deduped_drafts, dupe_count = _filter_redundant_opportunities(valid_drafts)

        # Persist valid, non-duplicate opportunities
        opportunities = _persist_opportunities(
            brand=brand,
            drafts=deduped_drafts,
            run_id=run_id,
        )

        status = "success"
        notes = [f"Generated {len(opportunities)} opportunities via graph"]
        if invalid_count > 0:
            notes.append(f"Filtered {invalid_count} invalid opportunities")
        if dupe_count > 0:
            notes.append(f"Filtered {dupe_count} near-duplicate opportunities")

        logger.info(
            "Today board generation complete",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "status": status,
                "opportunities_count": len(opportunities),
                "invalid_filtered": invalid_count,
                "duplicates_filtered": dupe_count,
                "total_candidates": total_candidates,
            },
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

    return BrandSnapshotDTO(
        brand_id=brand.id,
        brand_name=brand.name,
        positioning=brand.positioning or None,
        pillars=pillars,
        personas=personas,
        voice_tone_tags=brand.tone_tags or [],
        taboos=brand.taboos or [],
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


def _get_external_signals_safe(brand_id: UUID, run_id: UUID):
    """
    Get external signals with fallback on error.

    Returns empty bundle if external_signals_service fails.
    """
    try:
        return external_signals_service.get_bundle_for_brand(brand_id)
    except Exception as e:
        logger.warning(
            "External signals fetch failed, using empty bundle",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "error": str(e),
            },
        )
        from kairo.hero.dto import ExternalSignalBundleDTO

        return ExternalSignalBundleDTO(
            brand_id=brand_id,
            fetched_at=datetime.now(timezone.utc),
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
) -> list[Opportunity]:
    """
    Persist OpportunityDraftDTOs as Opportunity rows.

    Idempotency rules:
    - Each run creates new opportunities
    - Opportunities get deterministic IDs based on brand + title hash
    - Previous opportunities for the brand are NOT deleted (they may be pinned)

    Returns list of created/updated Opportunity model instances.
    """
    now = datetime.now(timezone.utc)
    opportunities = []

    with transaction.atomic():
        for draft in drafts:
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
                        "why_now": template["why_now"],
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

        opp_dto = OpportunityDTO(
            id=opp.id,
            brand_id=opp.brand_id,
            title=opp.title,
            angle=opp.angle,
            type=OpportunityType(opp.type),
            primary_channel=Channel(opp.primary_channel),
            score=opp.score,
            score_explanation=opp.score_explanation,
            source=opp.source or "",
            source_url=opp.source_url or None,
            persona_id=persona_id,
            pillar_id=pillar_id,
            suggested_channels=[Channel(c) for c in (opp.suggested_channels or [])],
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
