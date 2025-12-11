"""
Kairo Hero Loop DTOs.

PR-2: DTOs + Validation Layer + API Contracts.

These Pydantic v2 BaseModels define the request/response shapes for the hero loop API.
They serve as contracts - once defined, fields cannot be renamed or removed without
explicit migration and UI coordination.

Per docs/technical/02-canonical-objects.md and docs/prd/kairo-v1-prd.md.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# =============================================================================
# ENUMS - Single Source of Truth: kairo/core/enums.py
# =============================================================================
# We import Django TextChoices enums directly from core/enums.py.
# Django TextChoices are compatible with Pydantic v2 because they inherit from
# both str and Enum. This ensures enum values never drift between DB and API.
#
# If Pydantic compatibility issues arise in the future, create thin wrappers here
# that explicitly map to core enum values rather than duplicating them.

from kairo.core.enums import (
    Channel,
    CreatedVia,
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    LearningSignalType,
    OpportunityType,
    PackageStatus,
    PatternCategory,
    PatternStatus,
    VariantStatus,
)


# =============================================================================
# SHARED VALUE TYPES
# =============================================================================


class PersonaDTO(BaseModel):
    """
    Target audience persona - nested in BrandSnapshot.

    Per 02-canonical-objects.md §5.
    """
    id: UUID
    name: str
    role: str | None = None
    summary: str = ""
    priorities: list[str] = Field(default_factory=list)
    pains: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    channel_biases: dict[str, str] = Field(default_factory=dict)


class PillarDTO(BaseModel):
    """
    Content pillar / theme - nested in BrandSnapshot.

    Per 02-canonical-objects.md §6.
    """
    id: UUID
    name: str
    category: str | None = None
    description: str = ""
    priority_rank: int | None = None
    is_active: bool = True


class PatternTemplateDTO(BaseModel):
    """
    Reusable content pattern template.

    Per 02-canonical-objects.md §7.
    """
    id: UUID
    name: str
    category: PatternCategory
    status: PatternStatus = PatternStatus.ACTIVE
    beats: list[str] = Field(default_factory=list)
    supported_channels: list[Channel] = Field(default_factory=list)
    example_snippet: str | None = None
    performance_hint: str | None = None
    usage_count: int = 0
    avg_engagement_score: float | None = None


# =============================================================================
# BRAND SNAPSHOT DTO
# =============================================================================


class BrandSnapshotDTO(BaseModel):
    """
    Point-in-time snapshot of brand context for LLM prompts.

    Per PRD-1 §3.1.1-3.1.2 and 02-canonical-objects.md §4-5.
    Used by engines to provide brand context without DB queries.
    """
    brand_id: UUID
    brand_name: str
    positioning: str | None = None
    pillars: list[PillarDTO] = Field(default_factory=list)
    personas: list[PersonaDTO] = Field(default_factory=list)
    voice_tone_tags: list[str] = Field(default_factory=list)
    taboos: list[str] = Field(default_factory=list)


# =============================================================================
# OPPORTUNITY DTOs
# =============================================================================


class OpportunityDTO(BaseModel):
    """
    Persisted opportunity as seen by UI.

    Per PRD-1 §3.1.5 and 02-canonical-objects.md §8.
    Represents an "atom" on the Today board.
    """
    id: UUID
    brand_id: UUID
    title: str
    angle: str
    type: OpportunityType
    primary_channel: Channel
    score: float = Field(ge=0, le=100)
    score_explanation: str | None = None
    source: str = ""
    source_url: str | None = None
    persona_id: UUID | None = None
    pillar_id: UUID | None = None
    suggested_channels: list[Channel] = Field(default_factory=list)
    is_pinned: bool = False
    is_snoozed: bool = False
    snoozed_until: datetime | None = None
    created_via: CreatedVia = CreatedVia.AI_SUGGESTED
    created_at: datetime
    updated_at: datetime


class OpportunityDraftDTO(BaseModel):
    """
    Graph/LLM side output for proposed opportunities.

    Internal use for graph → engine communication.
    No DB IDs, includes raw reasoning from LLM.

    Per 08-opportunity-rubric.md §4.7:
    - is_valid: bool - whether this opp passes hard requirements
    - rejection_reasons: list[str] - why it failed (empty if valid)

    Engine must filter out is_valid=False opps before returning the board.
    """
    proposed_title: str
    proposed_angle: str
    type: OpportunityType
    primary_channel: Channel
    suggested_channels: list[Channel] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    score_explanation: str | None = None
    source: str = ""
    source_url: str | None = None
    persona_hint: str | None = None  # Name/role hint, resolved to ID by engine
    pillar_hint: str | None = None   # Name hint, resolved to ID by engine
    raw_reasoning: str | None = None
    # Per rubric §4.7: validity tracking
    is_valid: bool = True  # False if fails hard requirements (§4.1-4.6)
    rejection_reasons: list[str] = Field(default_factory=list)  # Why it failed
    # Per rubric §3.3: thesis and why_now (angle serves as thesis for now)
    why_now: str | None = None  # Timing justification - expected for valid opps


# =============================================================================
# CONTENT PACKAGE DTOs
# =============================================================================


class ContentPackageDTO(BaseModel):
    """
    Persisted content package.

    Per PRD-1 §3.1.6 and 02-canonical-objects.md §9.
    A bundle of content work anchored on a single opportunity.
    """
    id: UUID
    brand_id: UUID
    title: str
    status: PackageStatus = PackageStatus.DRAFT
    origin_opportunity_id: UUID | None = None
    persona_id: UUID | None = None
    pillar_id: UUID | None = None
    channels: list[Channel] = Field(default_factory=list)
    planned_publish_start: datetime | None = None
    planned_publish_end: datetime | None = None
    owner_user_id: UUID | None = None
    notes: str | None = None
    created_via: CreatedVia = CreatedVia.MANUAL
    created_at: datetime
    updated_at: datetime


# =============================================================================
# VARIANT DTOs
# =============================================================================


class VariantDTO(BaseModel):
    """
    Persisted variant.

    Per PRD-1 §3.1.7 and 02-canonical-objects.md §10.
    Single-channel realization of a package.
    """
    id: UUID
    package_id: UUID
    brand_id: UUID
    channel: Channel
    status: VariantStatus = VariantStatus.DRAFT
    pattern_template_id: UUID | None = None
    body: str = ""  # Active text (draft_text, edited_text, or approved_text)
    call_to_action: str | None = None
    generated_by_model: str | None = None
    proposed_at: datetime | None = None
    scheduled_publish_at: datetime | None = None
    published_at: datetime | None = None
    eval_score: float | None = None
    eval_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class VariantDraftDTO(BaseModel):
    """
    Graph/LLM side output for proposed variants.

    Internal use for graph → engine communication.
    No DB IDs, includes raw reasoning from LLM.
    """
    channel: Channel
    body: str
    call_to_action: str | None = None
    pattern_hint: str | None = None  # Pattern name hint, resolved to ID by engine
    raw_reasoning: str | None = None


class VariantUpdateDTO(BaseModel):
    """
    Request body for PATCH /api/variants/{variant_id}.

    Allows partial updates to variant fields.
    """
    body: str | None = None
    call_to_action: str | None = None
    status: VariantStatus | None = None


class VariantListDTO(BaseModel):
    """Response wrapper for list of variants."""
    package_id: UUID
    variants: list[VariantDTO]
    count: int


# =============================================================================
# EXECUTION & LEARNING DTOs
# =============================================================================


class ExecutionEventDTO(BaseModel):
    """
    Execution/engagement event from platforms.

    Per PRD-1 §3.1.8 and 02-canonical-objects.md §11.
    Wire shape for API responses.
    """
    id: UUID
    brand_id: UUID
    variant_id: UUID
    channel: Channel
    event_type: ExecutionEventType
    decision_type: DecisionType | None = None
    event_value: float | None = None
    count: int = 1
    source: ExecutionSource
    occurred_at: datetime
    received_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LearningEventDTO(BaseModel):
    """
    Learning signal event for the feedback loop.

    Per PRD-1 §3.1.9 and 02-canonical-objects.md §12.
    Wire shape for API responses.
    """
    id: UUID
    brand_id: UUID
    signal_type: LearningSignalType
    pattern_id: UUID | None = None
    opportunity_id: UUID | None = None
    variant_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    derived_from: list[UUID] = Field(default_factory=list)
    effective_at: datetime
    created_at: datetime


class LearningSummaryDTO(BaseModel):
    """
    In-memory DTO for learning summary.

    Per PRD-1 §3.1.10 and 02-canonical-objects.md:
    "LearningSummary is an in-memory DTO, reconstructed on demand by the
    LearningEngine. Do not create a table for it."

    Used by opportunities engine for scoring context.
    """
    brand_id: UUID
    generated_at: datetime
    top_performing_patterns: list[UUID] = Field(default_factory=list)
    top_performing_channels: list[Channel] = Field(default_factory=list)
    recent_engagement_score: float | None = None
    pillar_performance: dict[str, float] = Field(default_factory=dict)
    persona_engagement: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


# =============================================================================
# EXTERNAL SIGNALS BUNDLE DTOs
# =============================================================================
# Per PRD-1 §6.2 - External signals for opportunity generation


class TrendSignalDTO(BaseModel):
    """A trending topic signal."""
    id: str
    topic: str
    source: str  # e.g. "linkedin_trending", "google_trends"
    relevance_score: float = Field(ge=0, le=100)
    recency_days: int = 0
    url: str | None = None
    snippet: str | None = None


class WebMentionSignalDTO(BaseModel):
    """A web mention signal (news, blogs, etc.)."""
    id: str
    title: str
    source: str
    url: str
    snippet: str | None = None
    published_at: datetime | None = None
    relevance_score: float = Field(ge=0, le=100)


class CompetitorPostSignalDTO(BaseModel):
    """A competitor post signal."""
    id: str
    competitor_name: str
    channel: Channel
    post_url: str | None = None
    post_snippet: str | None = None
    engagement_hint: str | None = None  # e.g. "high engagement"
    published_at: datetime | None = None


class SocialMomentSignalDTO(BaseModel):
    """A social moment signal (viral content, memes, etc.)."""
    id: str
    description: str
    channel: Channel
    relevance_hint: str | None = None
    recency_hours: int = 0
    url: str | None = None


class ExternalSignalBundleDTO(BaseModel):
    """
    Bundle of external signals for opportunity generation.

    Per PRD-1 §6.2. Passed to opportunities engine/graph.
    In PRD-1, this is populated from fixtures, not real HTTP calls.
    """
    brand_id: UUID
    fetched_at: datetime
    trends: list[TrendSignalDTO] = Field(default_factory=list)
    web_mentions: list[WebMentionSignalDTO] = Field(default_factory=list)
    competitor_posts: list[CompetitorPostSignalDTO] = Field(default_factory=list)
    social_moments: list[SocialMomentSignalDTO] = Field(default_factory=list)


# =============================================================================
# TODAY BOARD DTOs
# =============================================================================


class TodayBoardMetaDTO(BaseModel):
    """
    Metadata for Today board generation.

    Per PRD-1 §3.3.6 and hero-loop-eval.md.

    Fields:
    - degraded: True if board is fallback/incomplete (graph error, etc.)
    - total_candidates: Count of raw candidates from graph before filtering
    - reason: Short code/description if degraded (e.g. "graph_error")
    """
    generated_at: datetime
    source: str = "hero_f1"  # Flow identifier
    degraded: bool = False   # True if board is stale/incomplete
    total_candidates: int | None = None  # Raw count from graph before filtering
    reason: str | None = None  # Degraded reason code if applicable
    notes: list[str] = Field(default_factory=list)
    opportunity_count: int = 0
    dominant_pillar: str | None = None
    dominant_persona: str | None = None
    channel_mix: dict[str, int] = Field(default_factory=dict)


class TodayBoardDTO(BaseModel):
    """
    Complete Today board response.

    Per PRD-1 §3.3.6. The main response for GET /api/brands/{brand_id}/today.
    """
    brand_id: UUID
    snapshot: BrandSnapshotDTO
    opportunities: list[OpportunityDTO] = Field(default_factory=list)
    meta: TodayBoardMetaDTO


# =============================================================================
# DECISION DTOs
# =============================================================================


class DecisionRequestDTO(BaseModel):
    """
    Request body for decision endpoints.

    Used by:
    - POST /api/opportunities/{opportunity_id}/decision
    - POST /api/packages/{package_id}/decision
    - POST /api/variants/{variant_id}/decision
    """
    decision_type: DecisionType
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionResponseDTO(BaseModel):
    """
    Response for decision endpoints.
    """
    status: str = "accepted"
    decision_type: DecisionType
    object_type: Literal["opportunity", "package", "variant"]
    object_id: UUID
    recorded_at: datetime


# =============================================================================
# API RESPONSE WRAPPERS
# =============================================================================


class RegenerateResponseDTO(BaseModel):
    """
    Response for POST /api/brands/{brand_id}/today/regenerate.

    Returns the regenerated Today board.
    """
    status: str = "regenerated"
    today_board: TodayBoardDTO


class CreatePackageResponseDTO(BaseModel):
    """
    Response for POST /api/brands/{brand_id}/opportunities/{opp_id}/packages.
    """
    status: str = "created"
    package: ContentPackageDTO


class GenerateVariantsResponseDTO(BaseModel):
    """
    Response for POST /api/packages/{package_id}/variants/generate.
    """
    status: str = "generated"
    package_id: UUID
    variants: list[VariantDTO]
    count: int
