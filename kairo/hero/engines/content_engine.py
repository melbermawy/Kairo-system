"""
Content Engine.

PR-9: Package + Variants Graphs Wired via Content Engine (F2).

Owns ContentPackage and Variant lifecycles:
- Create packages from opportunities (via graph)
- Generate multi-channel variants (via graph)
- Handle workflow statuses (draft → in_review → scheduled → published)

Per docs/technical/03-engines-overview.md §7.

Key responsibilities (per 05-llm-and-deepagents-conventions.md):
- Engine owns all DB writes
- Graph returns DTOs only; engine converts to ORM and persists
- Engine handles failure modes and enforces rubric validation
- Idempotency: same brand+opportunity = same package (returns existing)
- No-regeneration: reject variant generation if variants already exist
"""

import logging
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID, uuid4

from django.db import transaction

from kairo.core.enums import Channel, CreatedVia, PackageStatus, VariantStatus
from kairo.core.models import Brand, ContentPackage, Opportunity, PatternTemplate, Variant
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ContentPackageDTO,
    ContentPackageDraftDTO,
    OpportunityDTO,
    PersonaDTO,
    PillarDTO,
    VariantDTO,
    VariantDraftDTO,
)
from kairo.hero.graphs.package_graph import (
    PackageGraphError,
    graph_hero_package_from_opportunity,
)
from kairo.hero.graphs.variants_graph import (
    VariantsGraphError,
    graph_hero_variants_from_package,
)
from kairo.hero.llm_client import get_default_client
from kairo.hero.observability_store import (
    classify_f2_run,
    log_classification,
    log_run_complete,
    log_run_fail,
    log_run_start,
)

logger = logging.getLogger("kairo.hero.engines.content")


# =============================================================================
# EXCEPTIONS
# =============================================================================


class PackageCreationError(Exception):
    """Raised when package creation fails."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class VariantGenerationError(Exception):
    """Raised when variant generation fails."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class VariantsAlreadyExistError(Exception):
    """Raised when attempting to regenerate variants (prohibited in PRD-1)."""

    pass


# =============================================================================
# RESULT TYPES
# =============================================================================


class PackageCreationResult(NamedTuple):
    """Result of package creation."""

    package: ContentPackage
    was_existing: bool  # True if returned existing package (idempotency)
    draft: ContentPackageDraftDTO | None  # The draft used (None if existing)


class VariantGenerationResult(NamedTuple):
    """Result of variant generation."""

    variants: list[Variant]
    valid_count: int
    invalid_count: int
    notes: list[str]


# =============================================================================
# MAIN ENTRYPOINTS
# =============================================================================


def create_package_from_opportunity(
    brand_id: UUID,
    opportunity_id: UUID,
    run_id: UUID | None = None,
) -> ContentPackage:
    """
    Create a content package from an opportunity.

    PR-9 implementation:
    1. Check for existing package (idempotency)
    2. Build BrandSnapshotDTO from Brand model
    3. Look up Opportunity and convert to DTO
    4. Call graph_hero_package_from_opportunity
    5. Validate package (reject invalid)
    6. Persist ContentPackage to DB

    Idempotency rule (per rubric §8.2):
    - If a package already exists for this brand+opportunity, return it unchanged
    - No duplicate packages for the same opportunity

    Args:
        brand_id: UUID of the brand
        opportunity_id: UUID of the source opportunity
        run_id: Optional run ID for correlation

    Returns:
        ContentPackage (either existing or newly created)

    Raises:
        Brand.DoesNotExist: If brand not found
        Opportunity.DoesNotExist: If opportunity not found
        PackageCreationError: If graph fails and no fallback possible
    """
    if run_id is None:
        run_id = uuid4()

    logger.info(
        "Starting package creation from opportunity",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_id),
            "opportunity_id": str(opportunity_id),
        },
    )

    # Log run start to observability sink
    log_run_start(
        run_id=run_id,
        brand_id=brand_id,
        flow="F2_package",
        trigger_source="api",
    )

    # Look up brand and opportunity
    brand = Brand.objects.get(id=brand_id)
    opportunity = Opportunity.objects.get(id=opportunity_id, brand_id=brand_id)

    # Idempotency check: return existing package if one exists
    existing_package = ContentPackage.objects.filter(
        brand_id=brand_id,
        origin_opportunity_id=opportunity_id,
    ).first()

    if existing_package:
        logger.info(
            "Returning existing package (idempotency)",
            extra={
                "run_id": str(run_id),
                "package_id": str(existing_package.id),
            },
        )
        return existing_package

    # Build brand snapshot for graph
    snapshot = _build_brand_snapshot(brand)

    # Convert opportunity to DTO
    opp_dto = _opportunity_to_dto(opportunity)

    # PR-2: Check for invalid opportunity (missing why_now)
    if opp_dto is None:
        raise ValueError(
            f"Opportunity {opportunity.id} has invalid or missing why_now - cannot create package"
        )

    # Get LLM client
    llm_client = get_default_client()

    # Call graph
    try:
        draft = graph_hero_package_from_opportunity(
            run_id=run_id,
            brand_snapshot=snapshot,
            opportunity=opp_dto,
            llm_client=llm_client,
        )
    except PackageGraphError as e:
        logger.error(
            "Package graph failed",
            extra={
                "run_id": str(run_id),
                "error": str(e),
            },
        )

        # Log run failure to observability sink
        log_run_fail(
            run_id=run_id,
            brand_id=brand_id,
            flow="F2_package",
            error=str(e),
            error_type="PackageGraphError",
        )

        raise PackageCreationError(f"Graph failed: {e}", original_error=e) from e

    # Validate: reject invalid packages per rubric §7
    if not draft.is_valid:
        logger.warning(
            "Package draft is invalid, rejecting",
            extra={
                "run_id": str(run_id),
                "rejection_reasons": draft.rejection_reasons,
            },
        )
        raise PackageCreationError(
            f"Package failed rubric validation: {', '.join(draft.rejection_reasons)}"
        )

    # Engine-level taboo enforcement per rubric §8.2
    # This is the last line of defense before persistence
    taboo_valid, taboo_reasons = _validate_package_taboos(draft, snapshot.taboos, run_id)
    if not taboo_valid:
        logger.warning(
            "Package draft violates taboos (engine check), rejecting",
            extra={
                "run_id": str(run_id),
                "taboo_violations": taboo_reasons,
            },
        )
        raise PackageCreationError(
            f"Package violates brand taboos: {', '.join(taboo_reasons)}"
        )

    # Persist to DB
    package = _persist_package(
        brand=brand,
        opportunity=opportunity,
        draft=draft,
        run_id=run_id,
    )

    logger.info(
        "Package created successfully",
        extra={
            "run_id": str(run_id),
            "package_id": str(package.id),
            "quality_band": draft.quality_band,
            "package_score": draft.package_score,
        },
    )

    # Log run completion to observability sink (partial F2: package only, no variants yet)
    log_run_complete(
        run_id=run_id,
        brand_id=brand_id,
        flow="F2_package",
        status="success",
        metrics={
            "package_id": str(package.id),
            "quality_band": draft.quality_band,
            "package_score": draft.package_score,
        },
    )

    return package


def generate_variants_for_package(
    package_id: UUID,
    run_id: UUID | None = None,
) -> list[Variant]:
    """
    Generate content variants for a package across its target channels.

    PR-9 implementation:
    1. Look up package and verify no existing variants (no-regeneration rule)
    2. Build BrandSnapshotDTO from package's brand
    3. Build ContentPackageDraftDTO from persisted package
    4. Call graph_hero_variants_from_package
    5. Filter invalid variants per rubric
    6. Persist valid Variant rows to DB

    No-regeneration rule (per rubric §8.2):
    - If variants already exist for this package, raise error
    - PRD-1 does not support regeneration or A/B testing

    Args:
        package_id: UUID of the package
        run_id: Optional run ID for correlation

    Returns:
        List of Variant instances (persisted)

    Raises:
        ContentPackage.DoesNotExist: If package not found
        VariantsAlreadyExistError: If variants already exist
        VariantGenerationError: If graph fails
    """
    if run_id is None:
        run_id = uuid4()

    logger.info(
        "Starting variant generation for package",
        extra={
            "run_id": str(run_id),
            "package_id": str(package_id),
        },
    )

    # Look up package first to get brand_id for logging
    package = ContentPackage.objects.select_related("brand").get(id=package_id)

    # Log run start to observability sink
    log_run_start(
        run_id=run_id,
        brand_id=package.brand_id,
        flow="F2_variants",
        trigger_source="api",
    )

    # No-regeneration rule: check for existing variants
    existing_count = Variant.objects.filter(package_id=package_id).count()
    if existing_count > 0:
        logger.warning(
            "Variants already exist, rejecting regeneration",
            extra={
                "run_id": str(run_id),
                "package_id": str(package_id),
                "existing_count": existing_count,
            },
        )
        raise VariantsAlreadyExistError(
            f"Package {package_id} already has {existing_count} variants. "
            "Regeneration is not supported in PRD-1."
        )

    # Build brand snapshot
    snapshot = _build_brand_snapshot(package.brand)

    # Build package draft DTO from persisted package
    # Note: We reconstruct a draft for the graph since it expects draft format
    pkg_draft = _package_to_draft_dto(package)

    # Get LLM client
    llm_client = get_default_client()

    # Call graph
    try:
        drafts = graph_hero_variants_from_package(
            run_id=run_id,
            package=pkg_draft,
            brand_snapshot=snapshot,
            llm_client=llm_client,
        )
    except VariantsGraphError as e:
        logger.error(
            "Variants graph failed",
            extra={
                "run_id": str(run_id),
                "error": str(e),
            },
        )

        # Log run failure to observability sink
        log_run_fail(
            run_id=run_id,
            brand_id=package.brand_id,
            flow="F2_variants",
            error=str(e),
            error_type="VariantsGraphError",
        )

        # Classify and log classification for failed run
        f2_health, f2_reason = classify_f2_run(
            package_count=1,  # Package exists
            variant_count=0,
            taboo_violations=0,
            status="fail",
        )
        log_classification(
            run_id=run_id,
            brand_id=package.brand_id,
            f1_health="ok",  # Assume F1 was ok if we got to F2
            f2_health=f2_health,
            run_health=f2_health,
            reason=f2_reason,
        )

        raise VariantGenerationError(f"Graph failed: {e}", original_error=e) from e

    # Filter invalid variants per rubric (includes engine-level taboo check)
    valid_drafts, invalid_count = _filter_invalid_variants(drafts, snapshot.taboos, run_id)

    if not valid_drafts:
        logger.error(
            "All variants failed validation",
            extra={
                "run_id": str(run_id),
                "total_drafts": len(drafts),
            },
        )
        raise VariantGenerationError("All generated variants failed rubric validation")

    # Persist valid variants
    variants = _persist_variants(
        package=package,
        drafts=valid_drafts,
        run_id=run_id,
    )

    logger.info(
        "Variants generated successfully",
        extra={
            "run_id": str(run_id),
            "package_id": str(package_id),
            "valid_count": len(variants),
            "invalid_count": invalid_count,
        },
    )

    # Log run completion to observability sink
    log_run_complete(
        run_id=run_id,
        brand_id=package.brand_id,
        flow="F2_variants",
        status="success",
        metrics={
            "package_id": str(package_id),
            "valid_count": len(variants),
            "invalid_count": invalid_count,
        },
    )

    # Classify and log classification for successful run
    f2_health, f2_reason = classify_f2_run(
        package_count=1,
        variant_count=len(variants),
        expected_channels=len(package.channels or []) or 2,  # Default to 2 if not set
        taboo_violations=0,
        status="ok",
    )
    log_classification(
        run_id=run_id,
        brand_id=package.brand_id,
        f1_health="ok",  # Assume F1 was ok if we got to F2
        f2_health=f2_health,
        run_health=f2_health,
        reason=f2_reason,
    )

    return variants


# =============================================================================
# HELPER FUNCTIONS - BRAND SNAPSHOT
# =============================================================================


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


def _opportunity_to_dto(opportunity: Opportunity) -> OpportunityDTO | None:
    """Convert Opportunity model to OpportunityDTO.

    PR-2: Reads why_now and evidence_ids from metadata.
    Returns None if opportunity has invalid why_now.
    """
    # PR-2: Read why_now and evidence_ids from metadata
    metadata = opportunity.metadata or {}
    why_now = metadata.get("why_now", "")

    # PR-2: Skip opportunities with invalid why_now
    if not why_now or len(why_now.strip()) < 10:
        return None

    # PR-2: Parse evidence_ids (may be empty until PR-4/5)
    evidence_ids_raw = metadata.get("evidence_ids", [])
    from uuid import UUID
    evidence_ids = []
    for eid in evidence_ids_raw:
        try:
            evidence_ids.append(UUID(str(eid)))
        except (ValueError, TypeError):
            pass

    return OpportunityDTO(
        id=opportunity.id,
        brand_id=opportunity.brand_id,
        title=opportunity.title,
        angle=opportunity.angle,
        why_now=why_now.strip(),  # PR-2: Required field
        type=opportunity.type,
        primary_channel=opportunity.primary_channel,
        score=opportunity.score,
        score_explanation=opportunity.score_explanation or None,
        source=opportunity.source or "",
        source_url=opportunity.source_url or None,
        persona_id=opportunity.persona_id,
        pillar_id=opportunity.pillar_id,
        suggested_channels=opportunity.suggested_channels or [],
        evidence_ids=evidence_ids,  # PR-2: Forward-compat field
        is_pinned=opportunity.is_pinned,
        is_snoozed=opportunity.is_snoozed,
        snoozed_until=opportunity.snoozed_until,
        created_via=opportunity.created_via,
        created_at=opportunity.created_at,
        updated_at=opportunity.updated_at,
    )


def _package_to_draft_dto(package: ContentPackage) -> ContentPackageDraftDTO:
    """
    Convert a persisted ContentPackage to ContentPackageDraftDTO for graph input.

    Note: Some fields (thesis, summary) are stored in notes/metadata in PRD-1.
    For simplicity, we reconstruct a reasonable draft from the persisted data.
    """
    # Parse channels
    channels = [Channel(c) for c in (package.channels or [])]
    primary_channel = channels[0] if channels else Channel.LINKEDIN

    # Extract thesis/summary from notes if available, otherwise use title
    # In PRD-1, we store the package thesis in notes field
    notes = package.notes or ""
    thesis = notes if notes and len(notes) > 20 else f"Content for: {package.title}"
    summary = f"Package: {package.title}"

    return ContentPackageDraftDTO(
        title=package.title,
        thesis=thesis,
        summary=summary,
        primary_channel=primary_channel,
        channels=channels,
        cta=None,  # Not stored in DB in PRD-1
        pattern_hints=[],
        persona_hint=None,
        pillar_hint=None,
        notes_for_humans=notes if notes else None,
        raw_reasoning=None,
        is_valid=True,  # Assume valid since it's persisted
        rejection_reasons=[],
        package_score=None,
        package_score_breakdown=None,
        quality_band="board_ready",
    )


# =============================================================================
# HELPER FUNCTIONS - VALIDATION
# =============================================================================


def _check_taboo_violations(
    text: str,
    taboos: list[str],
) -> list[str]:
    """
    Check for taboo violations in text.

    Per rubric §5.5 (packages) and §3.5/§7 (variants):
    - Engine must apply hard checks on generated text for banned terms
    - Simple keyword/regex matching for PRD-1

    Args:
        text: The text to check
        taboos: List of taboo phrases/keywords

    Returns:
        List of violated taboos (empty if no violations)
    """
    if not text or not taboos:
        return []

    text_lower = text.lower()
    violations = []

    for taboo in taboos:
        taboo_lower = taboo.lower().strip()
        if taboo_lower and taboo_lower in text_lower:
            violations.append(taboo)

    return violations


def _validate_package_taboos(
    draft: ContentPackageDraftDTO,
    taboos: list[str],
    run_id: UUID,
) -> tuple[bool, list[str]]:
    """
    Validate package draft for taboo violations.

    Per 09-package-rubric.md §5.5 and §8.2:
    - Engine must enforce taboos before persistence
    - If taboo violation found → drop (PRD-1)

    Checks: thesis, summary, cta, notes_for_humans

    Returns:
        (is_valid, rejection_reasons)
    """
    all_violations = []

    # Check thesis
    violations = _check_taboo_violations(draft.thesis, taboos)
    if violations:
        all_violations.extend([f"taboo in thesis: {v}" for v in violations])

    # Check summary
    violations = _check_taboo_violations(draft.summary, taboos)
    if violations:
        all_violations.extend([f"taboo in summary: {v}" for v in violations])

    # Check CTA
    if draft.cta:
        violations = _check_taboo_violations(draft.cta, taboos)
        if violations:
            all_violations.extend([f"taboo in CTA: {v}" for v in violations])

    # Check notes
    if draft.notes_for_humans:
        violations = _check_taboo_violations(draft.notes_for_humans, taboos)
        if violations:
            all_violations.extend([f"taboo in notes: {v}" for v in violations])

    if all_violations:
        logger.warning(
            "Package taboo violations detected",
            extra={
                "run_id": str(run_id),
                "violations": all_violations,
            },
        )
        return False, all_violations

    return True, []


def _validate_variant_taboos(
    draft: VariantDraftDTO,
    taboos: list[str],
    run_id: UUID,
) -> tuple[bool, list[str]]:
    """
    Validate variant draft for taboo violations.

    Per 10-variant-rubric.md §3.5 and §7:
    - Engine must apply hard checks on generated text
    - Any taboo violation makes variant invalid

    Checks: body, call_to_action

    Returns:
        (is_valid, rejection_reasons)
    """
    all_violations = []

    # Check body
    violations = _check_taboo_violations(draft.body, taboos)
    if violations:
        all_violations.extend([f"taboo in body: {v}" for v in violations])

    # Check CTA
    if draft.call_to_action:
        violations = _check_taboo_violations(draft.call_to_action, taboos)
        if violations:
            all_violations.extend([f"taboo in CTA: {v}" for v in violations])

    if all_violations:
        logger.debug(
            "Variant taboo violations detected",
            extra={
                "run_id": str(run_id),
                "channel": draft.channel.value,
                "violations": all_violations,
            },
        )
        return False, all_violations

    return True, []


def _filter_invalid_variants(
    drafts: list[VariantDraftDTO],
    taboos: list[str],
    run_id: UUID,
) -> tuple[list[VariantDraftDTO], int]:
    """
    Filter out invalid variants per rubric §3.

    Also performs engine-level taboo checks per rubric §7.

    Returns (valid_drafts, invalid_count).
    """
    valid = []
    invalid_count = 0

    for draft in drafts:
        # First check: graph-level validity
        if not draft.is_valid:
            invalid_count += 1
            logger.debug(
                "Filtering invalid variant (graph validation)",
                extra={
                    "run_id": str(run_id),
                    "channel": draft.channel.value,
                    "reasons": draft.rejection_reasons,
                },
            )
            continue

        # Second check: engine-level taboo enforcement
        taboo_valid, taboo_reasons = _validate_variant_taboos(draft, taboos, run_id)
        if not taboo_valid:
            invalid_count += 1
            logger.debug(
                "Filtering invalid variant (engine taboo check)",
                extra={
                    "run_id": str(run_id),
                    "channel": draft.channel.value,
                    "reasons": taboo_reasons,
                },
            )
            continue

        valid.append(draft)

    return valid, invalid_count


# =============================================================================
# HELPER FUNCTIONS - PERSISTENCE
# =============================================================================


@transaction.atomic
def _persist_package(
    brand: Brand,
    opportunity: Opportunity,
    draft: ContentPackageDraftDTO,
    run_id: UUID,
) -> ContentPackage:
    """
    Persist a package draft to DB.

    Atomic transaction ensures consistency.
    """
    now = datetime.now(timezone.utc)

    # Resolve persona_hint to actual persona if provided
    persona_id = None
    if draft.persona_hint:
        persona = brand.personas.filter(name__iexact=draft.persona_hint).first()
        if persona:
            persona_id = persona.id

    # Resolve pillar_hint to actual pillar if provided
    pillar_id = None
    if draft.pillar_hint:
        pillar = brand.pillars.filter(name__iexact=draft.pillar_hint).first()
        if pillar:
            pillar_id = pillar.id

    # Build channels list as strings for JSONField
    channels = [c.value for c in draft.channels]

    # Store thesis in notes field (PRD-1 doesn't have dedicated thesis column)
    # Include quality metadata for observability
    notes_content = draft.thesis
    if draft.notes_for_humans:
        notes_content += f"\n\n{draft.notes_for_humans}"

    package = ContentPackage.objects.create(
        brand=brand,
        title=draft.title,
        status=PackageStatus.DRAFT,
        origin_opportunity=opportunity,
        persona_id=persona_id,
        pillar_id=pillar_id,
        channels=channels,
        planned_publish_start=None,
        planned_publish_end=None,
        owner_user_id=None,
        notes=notes_content,
        created_via=CreatedVia.AI_SUGGESTED,
        metrics_snapshot={
            "package_score": draft.package_score,
            "quality_band": draft.quality_band,
            "run_id": str(run_id),
        },
    )

    logger.debug(
        "Package persisted",
        extra={
            "run_id": str(run_id),
            "package_id": str(package.id),
        },
    )

    return package


@transaction.atomic
def _persist_variants(
    package: ContentPackage,
    drafts: list[VariantDraftDTO],
    run_id: UUID,
) -> list[Variant]:
    """
    Persist variant drafts to DB.

    Atomic transaction ensures consistency.
    """
    now = datetime.now(timezone.utc)
    variants = []

    for draft in drafts:
        # Resolve pattern_hint to actual pattern if provided
        pattern_template_id = None
        if draft.pattern_hint:
            pattern = PatternTemplate.objects.filter(
                brand=package.brand,
                name__iexact=draft.pattern_hint,
            ).first()
            if pattern:
                pattern_template_id = pattern.id

        variant = Variant.objects.create(
            brand=package.brand,
            package=package,
            channel=draft.channel.value,
            status=VariantStatus.DRAFT,
            pattern_template_id=pattern_template_id,
            raw_prompt_context={
                "run_id": str(run_id),
                "variant_score": draft.variant_score,
                "quality_band": draft.quality_band,
            },
            draft_text=draft.body,
            edited_text="",
            approved_text="",
            generated_by_model="kairo-hero-f2",
            proposed_at=now,
            scheduled_publish_at=None,
            published_at=None,
            last_evaluated_at=None,
            eval_score=draft.variant_score,
            eval_notes=f"quality_band={draft.quality_band}",
            metadata={
                "title": draft.title,
                "call_to_action": draft.call_to_action,
                "score_breakdown": draft.variant_score_breakdown,
            },
        )
        variants.append(variant)

        logger.debug(
            "Variant persisted",
            extra={
                "run_id": str(run_id),
                "variant_id": str(variant.id),
                "channel": draft.channel.value,
            },
        )

    return variants


# =============================================================================
# DTO CONVERSION HELPERS
# =============================================================================


def package_to_dto(package: ContentPackage) -> ContentPackageDTO:
    """
    Convert a ContentPackage model to ContentPackageDTO.

    Helper for service layer.
    """
    return ContentPackageDTO(
        id=package.id,
        brand_id=package.brand_id,
        title=package.title,
        status=PackageStatus(package.status),
        origin_opportunity_id=package.origin_opportunity_id,
        persona_id=package.persona_id,
        pillar_id=package.pillar_id,
        channels=[Channel(c) for c in (package.channels or [])],
        planned_publish_start=package.planned_publish_start,
        planned_publish_end=package.planned_publish_end,
        owner_user_id=package.owner_user_id,
        notes=package.notes or None,
        created_via=CreatedVia(package.created_via),
        created_at=package.created_at,
        updated_at=package.updated_at,
    )


def variant_to_dto(variant: Variant) -> VariantDTO:
    """
    Convert a Variant model to VariantDTO.

    Helper for service layer.
    """
    # Determine active body based on status
    body = variant.draft_text
    if variant.edited_text:
        body = variant.edited_text
    if variant.approved_text:
        body = variant.approved_text

    # Extract call_to_action from metadata
    call_to_action = None
    if variant.metadata and isinstance(variant.metadata, dict):
        call_to_action = variant.metadata.get("call_to_action")

    return VariantDTO(
        id=variant.id,
        package_id=variant.package_id,
        brand_id=variant.brand_id,
        channel=Channel(variant.channel),
        status=VariantStatus(variant.status),
        pattern_template_id=variant.pattern_template_id,
        body=body,
        call_to_action=call_to_action,
        generated_by_model=variant.generated_by_model or None,
        proposed_at=variant.proposed_at,
        scheduled_publish_at=variant.scheduled_publish_at,
        published_at=variant.published_at,
        eval_score=variant.eval_score,
        eval_notes=variant.eval_notes or None,
        created_at=variant.created_at,
        updated_at=variant.updated_at,
    )
