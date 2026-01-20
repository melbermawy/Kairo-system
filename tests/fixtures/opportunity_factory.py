"""
Canonical Test Factory for Opportunities.

PR-4c: Test fixture contract cleanup.

This module provides canonical factory functions for creating valid OpportunityDTO,
Opportunity model instances, and EvidenceItem rows for tests. These factories
ensure all required fields (why_now, evidence_ids) are populated per PR-4b contract.

USAGE:
    from tests.fixtures.opportunity_factory import (
        make_valid_opportunity_dto,
        make_valid_opportunity_model,
        make_valid_opportunity_draft_dto,
        make_valid_evidence_item,
    )

IMPORTANT:
- All factories populate required fields: why_now (>= 10 chars), evidence_ids (non-empty for READY)
- Do NOT weaken these requirements - they reflect PRD compliance
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from kairo.core.enums import Channel, CreatedVia, OpportunityType
from kairo.hero.dto import OpportunityDTO, OpportunityDraftDTO


# =============================================================================
# DEFAULT VALUES (Single Source of Truth)
# =============================================================================

DEFAULT_WHY_NOW = "Market trends show high engagement with this topic area, making it timely for our audience."
DEFAULT_TITLE = "Test Opportunity Title"
DEFAULT_ANGLE = "A compelling angle for this content opportunity that resonates with the target audience."
DEFAULT_SCORE = 80.0
DEFAULT_SCORE_EXPLANATION = "High relevance score based on trend analysis and audience alignment."


# =============================================================================
# DTO FACTORIES
# =============================================================================


def make_valid_opportunity_dto(
    *,
    id: UUID | None = None,
    brand_id: UUID | None = None,
    title: str = DEFAULT_TITLE,
    angle: str = DEFAULT_ANGLE,
    why_now: str = DEFAULT_WHY_NOW,
    type: OpportunityType = OpportunityType.TREND,
    primary_channel: Channel = Channel.LINKEDIN,
    score: float = DEFAULT_SCORE,
    score_explanation: str | None = DEFAULT_SCORE_EXPLANATION,
    source: str = "test",
    source_url: str | None = None,
    persona_id: UUID | None = None,
    pillar_id: UUID | None = None,
    suggested_channels: list[Channel] | None = None,
    evidence_ids: list[UUID] | None = None,
    is_pinned: bool = False,
    is_snoozed: bool = False,
    snoozed_until: datetime | None = None,
    created_via: CreatedVia = CreatedVia.AI_SUGGESTED,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> OpportunityDTO:
    """
    Create a valid OpportunityDTO with all required fields populated.

    PR-4b compliance:
    - why_now: >= 10 chars (default provided)
    - evidence_ids: non-empty list[UUID] (default: 2 random UUIDs)

    Args:
        All OpportunityDTO fields, with sensible defaults.

    Returns:
        Valid OpportunityDTO instance.
    """
    now = datetime.now(timezone.utc)

    return OpportunityDTO(
        id=id or uuid4(),
        brand_id=brand_id or uuid4(),
        title=title,
        angle=angle,
        why_now=why_now,
        type=type,
        primary_channel=primary_channel,
        score=score,
        score_explanation=score_explanation,
        source=source,
        source_url=source_url,
        persona_id=persona_id,
        pillar_id=pillar_id,
        suggested_channels=suggested_channels or [primary_channel],
        evidence_ids=evidence_ids if evidence_ids is not None else [uuid4(), uuid4()],
        is_pinned=is_pinned,
        is_snoozed=is_snoozed,
        snoozed_until=snoozed_until,
        created_via=created_via,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


def make_valid_opportunity_draft_dto(
    *,
    proposed_title: str = DEFAULT_TITLE,
    proposed_angle: str = DEFAULT_ANGLE,
    why_now: str = DEFAULT_WHY_NOW,
    type: OpportunityType = OpportunityType.TREND,
    primary_channel: Channel = Channel.LINKEDIN,
    suggested_channels: list[Channel] | None = None,
    score: float = DEFAULT_SCORE,
    score_explanation: str | None = DEFAULT_SCORE_EXPLANATION,
    source: str = "test",
    source_url: str | None = None,
    persona_hint: str | None = None,
    pillar_hint: str | None = None,
    raw_reasoning: str | None = None,
    is_valid: bool = True,
    rejection_reasons: list[str] | None = None,
) -> OpportunityDraftDTO:
    """
    Create a valid OpportunityDraftDTO with all required fields populated.

    PR-4b compliance:
    - why_now: >= 10 chars (default provided)

    Args:
        All OpportunityDraftDTO fields, with sensible defaults.

    Returns:
        Valid OpportunityDraftDTO instance.
    """
    return OpportunityDraftDTO(
        proposed_title=proposed_title,
        proposed_angle=proposed_angle,
        why_now=why_now,
        type=type,
        primary_channel=primary_channel,
        suggested_channels=suggested_channels or [primary_channel],
        score=score,
        score_explanation=score_explanation,
        source=source,
        source_url=source_url,
        persona_hint=persona_hint,
        pillar_hint=pillar_hint,
        raw_reasoning=raw_reasoning,
        is_valid=is_valid,
        rejection_reasons=rejection_reasons or [],
    )


# =============================================================================
# MODEL FACTORIES
# =============================================================================


def make_valid_opportunity_model(
    brand,
    *,
    title: str = DEFAULT_TITLE,
    angle: str = DEFAULT_ANGLE,
    why_now: str = DEFAULT_WHY_NOW,
    type: OpportunityType = OpportunityType.TREND,
    primary_channel: Channel = Channel.LINKEDIN,
    score: float = DEFAULT_SCORE,
    score_explanation: str | None = DEFAULT_SCORE_EXPLANATION,
    source: str = "test",
    source_url: str | None = None,
    persona_id: UUID | None = None,
    pillar_id: UUID | None = None,
    suggested_channels: list[Channel] | None = None,
    evidence_ids: list[UUID] | None = None,
    is_pinned: bool = False,
    is_snoozed: bool = False,
    snoozed_until: datetime | None = None,
    created_via: CreatedVia = CreatedVia.AI_SUGGESTED,
    metadata: dict | None = None,
):
    """
    Create and persist a valid Opportunity model instance.

    PR-4b compliance:
    - metadata.why_now: >= 10 chars (default provided)
    - metadata.evidence_ids: non-empty list[str] (default: 2 random UUIDs as strings)

    Args:
        brand: Brand model instance (required)
        All other Opportunity fields, with sensible defaults.

    Returns:
        Persisted Opportunity model instance.
    """
    from kairo.core.models import Opportunity

    # Build evidence_ids as strings for JSON storage
    evidence_ids_final = evidence_ids if evidence_ids is not None else [uuid4(), uuid4()]
    evidence_ids_str = [str(eid) for eid in evidence_ids_final]

    # Build metadata dict
    metadata_final = metadata or {}
    metadata_final.setdefault("why_now", why_now)
    metadata_final.setdefault("evidence_ids", evidence_ids_str)
    metadata_final.setdefault("score_explanation", score_explanation)

    return Opportunity.objects.create(
        brand=brand,
        title=title,
        angle=angle,
        type=type,
        primary_channel=primary_channel,
        score=score,
        source=source,
        source_url=source_url,
        persona_id=persona_id,
        pillar_id=pillar_id,
        suggested_channels=suggested_channels or [primary_channel.value],
        is_pinned=is_pinned,
        is_snoozed=is_snoozed,
        snoozed_until=snoozed_until,
        created_via=created_via,
        metadata=metadata_final,
    )


def make_valid_evidence_item(
    brand_id: UUID,
    *,
    job_id: UUID | None = None,
    platform: str = "instagram",
    canonical_url: str | None = None,
    external_id: str | None = None,
    author_ref: str = "@test_author",
    title: str | None = None,
    text_primary: str = "Test content for evidence item fixture.",
    text_secondary: str | None = None,
    has_transcript: bool = False,
    view_count: int | None = 1000,
    like_count: int | None = 100,
    comment_count: int | None = 10,
    share_count: int | None = 5,
    published_at: datetime | None = None,
):
    """
    Create and persist a valid EvidenceItem model instance.

    This creates a real DB row that can be linked via evidence_ids.

    Args:
        brand_id: UUID of the brand
        job_id: OpportunitiesJob ID (will create one if not provided)
        All other EvidenceItem fields, with sensible defaults.

    Returns:
        Persisted EvidenceItem model instance.
    """
    from kairo.hero.models import ActivationRun, EvidenceItem, OpportunitiesJob
    from kairo.sourceactivation.fixtures.loader import generate_evidence_id

    now = datetime.now(timezone.utc)

    # Create job if needed
    if job_id is None:
        job = OpportunitiesJob.objects.create(
            brand_id=brand_id,
            status="pending",
        )
        job_id = job.id

    # Generate deterministic ID
    final_url = canonical_url or f"https://{platform}.com/p/{uuid4().hex[:8]}"
    item_id = generate_evidence_id(
        brand_id=brand_id,
        platform=platform,
        canonical_url=final_url,
    )

    # Create ActivationRun
    activation_run = ActivationRun.objects.create(
        job_id=job_id,
        brand_id=brand_id,
        snapshot_id=brand_id,
        seed_pack_json={
            "brand_name": "Test Brand",
            "positioning": "Test positioning",
            "search_terms": [],
            "pillar_keywords": [],
        },
        mode="fixture_only",
        started_at=now,
    )

    # Create EvidenceItem
    return EvidenceItem.objects.create(
        id=item_id,
        activation_run=activation_run,
        brand_id=brand_id,
        platform=platform,
        actor_id="FIXTURE",
        acquisition_stage=1,
        recipe_id="FIXTURE",
        canonical_url=final_url,
        external_id=external_id or uuid4().hex[:8],
        author_ref=author_ref,
        title=title,
        text_primary=text_primary,
        text_secondary=text_secondary,
        hashtags=[],
        view_count=view_count,
        like_count=like_count,
        comment_count=comment_count,
        share_count=share_count,
        published_at=published_at or now,
        has_transcript=has_transcript,
    )


# =============================================================================
# EVIDENCE BUNDLE MOCK HELPER
# =============================================================================


def make_mock_evidence_bundle(
    brand_id: UUID,
    *,
    num_items: int = 7,
    activation_run_id: UUID | None = None,
    mode: str = "fixture_only",
):
    """
    Create a mock EvidenceBundle for tests that don't need DB persistence.

    This returns an EvidenceBundle dataclass (not ORM objects) suitable for
    mocking get_or_create_evidence_bundle returns.

    Args:
        brand_id: UUID of the brand
        num_items: Number of evidence items to include
        activation_run_id: Optional activation run ID
        mode: Execution mode

    Returns:
        EvidenceBundle with mock items.
    """
    from datetime import timedelta

    from kairo.sourceactivation.types import EvidenceBundle, EvidenceItemData

    now = datetime.now(timezone.utc)

    items = []
    platforms = ["instagram", "tiktok", "linkedin", "youtube"]
    for i in range(num_items):
        platform = platforms[i % len(platforms)]
        items.append(
            EvidenceItemData(
                platform=platform,
                actor_id="FIXTURE",
                acquisition_stage=1,
                recipe_id="FIXTURE",
                canonical_url=f"https://{platform}.com/p/fixture_{i:03d}",
                external_id=f"fixture_{i:03d}",
                author_ref=f"@author_{i}",
                title=f"Test Content {i}",
                text_primary=f"This is test content number {i} with substantial text for testing purposes.",
                text_secondary=f"Transcript for item {i}" if i % 3 == 0 else "",
                hashtags=["test", f"tag{i}"],
                view_count=10000 * (i + 1),
                like_count=1000 * (i + 1),
                comment_count=50 * (i + 1),
                share_count=20 * (i + 1),
                published_at=now - timedelta(days=i),
                has_transcript=i % 3 == 0,
            )
        )

    return EvidenceBundle(
        brand_id=brand_id,
        activation_run_id=activation_run_id or uuid4(),
        snapshot_id=brand_id,  # Use brand_id as snapshot_id for simplicity
        mode=mode,
        items=items,
        fetched_at=now,
    )
