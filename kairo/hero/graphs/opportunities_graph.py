"""
Opportunities Graph for F1 - Today Board Generation.

PR-8: Implements graph_hero_generate_opportunities per PRD-1 §5.1 and
docs/technical/05-llm-and-deepagents-conventions.md.

This module defines a small, focused graph that:
1. Synthesizes candidate opportunity ideas from context
2. Normalizes, scores, and prunes opportunities

Design constraints (per 05-llm-and-deepagents-conventions.md):
- NO ORM imports anywhere in this module
- NO DB reads/writes - graph deals only in DTOs
- ALL LLM calls go through kairo.hero.llm_client.LLMClient
- Returns list[OpportunityDraftDTO] only

Invariants the output must satisfy:
- Each opportunity has non-empty title and angle
- primary_channel is Channel.LINKEDIN or Channel.X
- score is in [0, 100]
- type is a valid OpportunityType
- 6-24 opportunities returned per run
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from kairo.core.enums import Channel, OpportunityType
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ExternalSignalBundleDTO,
    LearningSummaryDTO,
    OpportunityDraftDTO,
)
from kairo.hero.llm_client import (
    LLMCallError,
    LLMClient,
    StructuredOutputError,
    get_default_client,
    parse_structured_output,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("kairo.hero.graphs.opportunities")


# =============================================================================
# EXCEPTIONS
# =============================================================================


class GraphError(Exception):
    """
    Exception raised when a graph operation fails.

    Used by the engine to distinguish graph failures from other errors
    and trigger degraded mode behavior.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


# =============================================================================
# INTERNAL SCHEMAS FOR LLM OUTPUT
# =============================================================================


class RawOpportunityIdea(BaseModel):
    """
    Raw opportunity idea from LLM synthesis node.

    Internal schema - converted to OpportunityDraftDTO by the scoring node.
    """

    title: str = Field(min_length=5, max_length=200)
    angle: str = Field(min_length=10, max_length=500)
    type: str = Field(description="One of: trend, evergreen, competitive, campaign")
    primary_channel: str = Field(description="One of: linkedin, x")
    suggested_channels: list[str] = Field(default_factory=list)
    reasoning: str = Field(
        default="", description="Brief explanation of why this opportunity matters"
    )
    why_now: str = Field(
        default="", description="Timing justification per rubric §4.3"
    )
    source: str = Field(default="", description="Signal source if applicable")
    source_url: str | None = Field(default=None)
    persona_hint: str | None = Field(
        default=None, description="Target persona name if specific"
    )
    pillar_hint: str | None = Field(
        default=None, description="Content pillar name if specific"
    )


class SynthesisOutput(BaseModel):
    """Output from the opportunity synthesis LLM node."""

    opportunities: list[RawOpportunityIdea] = Field(
        min_length=6, max_length=24, description="List of opportunity ideas"
    )


class ScoredOpportunity(BaseModel):
    """Opportunity with normalized score from scoring node."""

    title: str
    angle: str
    type: str
    primary_channel: str
    suggested_channels: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    score_explanation: str = Field(default="")
    why_now: str = Field(default="")  # Timing justification per rubric §4.3
    source: str = Field(default="")
    source_url: str | None = Field(default=None)
    persona_hint: str | None = Field(default=None)
    pillar_hint: str | None = Field(default=None)
    raw_reasoning: str | None = Field(default=None)


class ScoringOutput(BaseModel):
    """Output from the scoring/normalization LLM node."""

    opportunities: list[ScoredOpportunity] = Field(min_length=6, max_length=24)


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

SYNTHESIS_SYSTEM_PROMPT = """You are a content strategist for {brand_name}.

Your role is to identify content opportunities - timely, relevant topics that the brand should create content about.

BRAND CONTEXT:
- Positioning: {positioning}
- Voice/Tone: {tone_tags}
- Content Pillars: {pillars}
- Target Personas: {personas}
- TABOOS (never suggest content about these): {taboos}

You must NEVER suggest opportunities that violate the brand's taboos or could be controversial.

Your output must be valid JSON matching the required schema."""

SYNTHESIS_USER_PROMPT = """Based on the following external signals and learning context, generate {target_count} content opportunities for {brand_name}.

EXTERNAL SIGNALS:
{external_signals_summary}

LEARNING CONTEXT (what has worked recently):
- Top performing channels: {top_channels}
- Recent engagement: {engagement_context}
{learning_notes}

REQUIREMENTS:
1. Each opportunity MUST have:
   - A clear, specific title (not generic)
   - An angle explaining the core thesis
   - A why_now field with timing justification:
     - For trend: reference the specific trend/news/event
     - For evergreen: explain enduring value or recurring customer need
     - For competitive: reference competitor move or category shift
     - For campaign: reference the campaign moment
   - A type: trend (timely), evergreen (always relevant), competitive (differentiation), or campaign (planned initiative)
   - A primary channel: linkedin or x (choose based on content type fit)

2. Mix of opportunity types:
   - At least 2 trend-based (responding to current signals)
   - At least 2 evergreen (pillar-aligned, always relevant)
   - At least 1 competitive (differentiation opportunity)

3. Distribute across channels appropriately

Return your response as JSON with an "opportunities" array."""

SCORING_SYSTEM_PROMPT = """You are evaluating content opportunities for {brand_name}.

Score each opportunity on a 0-100 scale based on:
- Relevance to brand positioning and pillars (0-30 points)
- Timeliness and urgency (0-25 points)
- Audience fit for target personas (0-25 points)
- Channel appropriateness (0-20 points)

BRAND TABOOS (score 0 if violated): {taboos}

Be strict but fair. Great opportunities score 80+. Good ones score 65-79. Marginal ones score 50-64.
Remove any that violate taboos by giving them score 0.

Your output must be valid JSON matching the required schema."""

SCORING_USER_PROMPT = """Score and normalize these content opportunities:

{opportunities_json}

For each opportunity:
1. Assign a score (0-100) based on the criteria
2. Add a brief score_explanation
3. Normalize channel names to lowercase: "linkedin" or "x"
4. Normalize type to lowercase: "trend", "evergreen", "competitive", or "campaign"

Return JSON with "opportunities" array containing all scored opportunities."""


# =============================================================================
# GRAPH NODE FUNCTIONS
# =============================================================================


def _build_external_signals_summary(signals: ExternalSignalBundleDTO) -> str:
    """Build a concise summary of external signals for the prompt."""
    lines = []

    if signals.trends:
        lines.append("TRENDS:")
        for t in signals.trends[:5]:  # Limit to top 5
            lines.append(f"  - {t.topic} (relevance: {t.relevance_score:.0f})")

    if signals.web_mentions:
        lines.append("WEB MENTIONS:")
        for w in signals.web_mentions[:3]:
            lines.append(f"  - {w.title} ({w.source})")

    if signals.competitor_posts:
        lines.append("COMPETITOR ACTIVITY:")
        for c in signals.competitor_posts[:3]:
            lines.append(f"  - {c.competitor_name} on {c.channel.value}: {c.post_snippet or 'N/A'}")

    if signals.social_moments:
        lines.append("SOCIAL MOMENTS:")
        for s in signals.social_moments[:3]:
            lines.append(f"  - {s.description}")

    if not lines:
        return "No external signals available. Focus on evergreen opportunities."

    return "\n".join(lines)


def _synthesize_opportunities(
    brand_snapshot: BrandSnapshotDTO,
    learning_summary: LearningSummaryDTO,
    external_signals: ExternalSignalBundleDTO,
    llm_client: LLMClient,
    run_id: UUID,
) -> list[RawOpportunityIdea]:
    """
    Node 1: Synthesize candidate opportunity ideas.

    Uses LLM to generate initial opportunity candidates based on
    brand context, learning summary, and external signals.
    """
    # Build prompt context
    pillars_str = ", ".join(p.name for p in brand_snapshot.pillars) or "None defined"
    personas_str = ", ".join(p.name for p in brand_snapshot.personas) or "None defined"
    taboos_str = ", ".join(brand_snapshot.taboos) or "None"
    tone_str = ", ".join(brand_snapshot.voice_tone_tags) or "professional"

    # Learning context
    top_channels = (
        ", ".join(c.value for c in learning_summary.top_performing_channels)
        or "linkedin, x (no preference data)"
    )
    engagement_context = (
        f"Score: {learning_summary.recent_engagement_score:.1f}/100"
        if learning_summary.recent_engagement_score
        else "No recent data"
    )
    learning_notes = "\n".join(f"- {n}" for n in learning_summary.notes) if learning_summary.notes else ""

    # External signals summary
    signals_summary = _build_external_signals_summary(external_signals)

    # Build prompts
    system_prompt = SYNTHESIS_SYSTEM_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
        positioning=brand_snapshot.positioning or "Not specified",
        tone_tags=tone_str,
        pillars=pillars_str,
        personas=personas_str,
        taboos=taboos_str,
    )

    user_prompt = SYNTHESIS_USER_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
        target_count=12,  # Request 12, may get 6-24
        external_signals_summary=signals_summary,
        top_channels=top_channels,
        engagement_context=engagement_context,
        learning_notes=learning_notes,
    )

    # Make LLM call
    response = llm_client.call(
        brand_id=brand_snapshot.brand_id,
        flow="F1_opportunities_synthesis",
        prompt=user_prompt,
        role="heavy",  # Use smart model for synthesis
        system_prompt=system_prompt,
        run_id=run_id,
        trigger_source="graph",
    )

    # Parse structured output
    try:
        result = parse_structured_output(response.raw_text, SynthesisOutput)
        return result.opportunities
    except StructuredOutputError as e:
        logger.warning(
            "Synthesis output parsing failed",
            extra={"run_id": str(run_id), "error": str(e)},
        )
        raise


def _score_and_normalize_opportunities(
    raw_opportunities: list[RawOpportunityIdea],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
) -> list[ScoredOpportunity]:
    """
    Node 2: Score and normalize opportunities.

    Uses LLM to assign scores and normalize the output format.
    """
    # Convert raw opportunities to JSON for the prompt
    opps_data = [opp.model_dump() for opp in raw_opportunities]
    import json

    opps_json = json.dumps(opps_data, indent=2)

    taboos_str = ", ".join(brand_snapshot.taboos) or "None"

    system_prompt = SCORING_SYSTEM_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
        taboos=taboos_str,
    )

    user_prompt = SCORING_USER_PROMPT.format(opportunities_json=opps_json)

    # Make LLM call - use fast model for scoring
    response = llm_client.call(
        brand_id=brand_snapshot.brand_id,
        flow="F1_opportunities_scoring",
        prompt=user_prompt,
        role="fast",
        system_prompt=system_prompt,
        run_id=run_id,
        trigger_source="graph",
    )

    # Parse structured output
    try:
        result = parse_structured_output(response.raw_text, ScoringOutput)
        return result.opportunities
    except StructuredOutputError as e:
        logger.warning(
            "Scoring output parsing failed",
            extra={"run_id": str(run_id), "error": str(e)},
        )
        raise


def _validate_opportunity(
    opp: ScoredOpportunity,
    type_map: dict,
    channel_map: dict,
) -> tuple[bool, list[str]]:
    """
    Validate an opportunity against rubric §4 hard requirements.

    Returns (is_valid, rejection_reasons).

    Per 08-opportunity-rubric.md §4:
    - §4.1: Single clear content thesis (title + angle non-empty, specific)
    - §4.2: Explicit who + where (channel must be valid)
    - §4.3: Clear why-now / hook (why_now must be non-empty, non-vacuous)
    - §4.5: Actionable as content
    - §4.6: Safety / taboos respected (score=0 means taboo violation)
    """
    reasons = []

    # §4.1: Single clear content thesis
    if not opp.title or len(opp.title.strip()) < 5:
        reasons.append("title too short or empty (§4.1)")
    if not opp.angle or len(opp.angle.strip()) < 10:
        reasons.append("angle too short or empty (§4.1)")

    # §4.2: Explicit who + where
    if opp.primary_channel.lower() not in channel_map:
        reasons.append(f"invalid channel '{opp.primary_channel}' (§4.2)")

    # §4.3: Clear why-now / hook
    why_now = opp.why_now.strip() if opp.why_now else ""
    # Check for vacuous why_now
    vacuous_phrases = ["always relevant", "always useful", "timeless"]
    if not why_now or len(why_now) < 10:
        reasons.append("why_now missing or too short (§4.3)")
    elif any(phrase in why_now.lower() for phrase in vacuous_phrases):
        reasons.append("why_now is vacuous (§4.3)")

    # §4.6: Safety / taboos (score=0 from LLM means taboo violation)
    if opp.score <= 0:
        reasons.append("score=0 indicates taboo violation (§4.6)")

    # §4.4: on-brand, on-pillar - can't fully validate without brand context,
    # but invalid type is a signal
    if opp.type.lower() not in type_map:
        reasons.append(f"invalid opportunity type '{opp.type}' (§4.4)")

    is_valid = len(reasons) == 0
    return is_valid, reasons


def _convert_to_draft_dtos(
    scored_opportunities: list[ScoredOpportunity],
) -> list[OpportunityDraftDTO]:
    """
    Transform node: Convert scored opportunities to final DTOs.

    Per rubric §4.7:
    - All opps are converted (even invalid ones)
    - Invalid opps get is_valid=False, rejection_reasons populated, score=0
    - Engine is responsible for filtering out invalid opps

    Handles enum conversion and validation.
    """
    drafts = []

    # Type mapping
    type_map = {
        "trend": OpportunityType.TREND,
        "evergreen": OpportunityType.EVERGREEN,
        "competitive": OpportunityType.COMPETITIVE,
        "campaign": OpportunityType.CAMPAIGN,
    }

    # Channel mapping
    channel_map = {
        "linkedin": Channel.LINKEDIN,
        "x": Channel.X,
    }

    for opp in scored_opportunities:
        # Validate against rubric §4 hard requirements
        is_valid, rejection_reasons = _validate_opportunity(opp, type_map, channel_map)

        # Parse type (default to evergreen if unknown)
        opp_type = type_map.get(opp.type.lower(), OpportunityType.EVERGREEN)
        if opp.type.lower() not in type_map:
            logger.warning(f"Unknown opportunity type: {opp.type}, defaulting to evergreen")

        # Parse primary channel (default to linkedin if unknown)
        primary_channel = channel_map.get(opp.primary_channel.lower(), Channel.LINKEDIN)
        if opp.primary_channel.lower() not in channel_map:
            logger.warning(f"Unknown channel: {opp.primary_channel}, defaulting to linkedin")

        # Parse suggested channels
        suggested = []
        for ch in opp.suggested_channels:
            mapped = channel_map.get(ch.lower())
            if mapped:
                suggested.append(mapped)
        if not suggested:
            suggested = [Channel.LINKEDIN, Channel.X]

        # Per rubric §7.3: invalid opps get score=0
        if is_valid:
            score = max(0.0, min(100.0, opp.score))
        else:
            score = 0.0
            logger.debug(
                f"Marking opportunity as invalid: {opp.title[:50]}",
                extra={"reasons": rejection_reasons},
            )

        draft = OpportunityDraftDTO(
            proposed_title=opp.title,
            proposed_angle=opp.angle,
            type=opp_type,
            primary_channel=primary_channel,
            suggested_channels=suggested,
            score=score,
            score_explanation=opp.score_explanation,
            source=opp.source,
            source_url=opp.source_url,
            persona_hint=opp.persona_hint,
            pillar_hint=opp.pillar_hint,
            raw_reasoning=opp.raw_reasoning,
            is_valid=is_valid,
            rejection_reasons=rejection_reasons,
            why_now=opp.why_now or None,
        )
        drafts.append(draft)

    return drafts


# =============================================================================
# MAIN GRAPH ENTRYPOINT
# =============================================================================


def graph_hero_generate_opportunities(
    run_id: UUID,
    brand_snapshot: BrandSnapshotDTO,
    learning_summary: LearningSummaryDTO,
    external_signals: ExternalSignalBundleDTO,
    llm_client: LLMClient | None = None,
) -> list[OpportunityDraftDTO]:
    """
    Generate content opportunities for the Today board (F1 flow).

    Implements PRD-1 §5.1 hero opportunities graph.

    This graph:
    1. Synthesizes candidate opportunity ideas using LLM (heavy model)
    2. Scores and normalizes opportunities using LLM (fast model)
    3. Converts to final OpportunityDraftDTO format

    Args:
        run_id: UUID for run correlation and observability
        brand_snapshot: Brand context (positioning, pillars, personas, taboos)
        learning_summary: Recent learning data (top patterns, channels)
        external_signals: External signals bundle (trends, mentions, etc.)
        llm_client: Optional LLM client (uses default if not provided)

    Returns:
        List of 6-24 OpportunityDraftDTO instances, sorted by score descending

    Raises:
        GraphError: If the graph fails (LLM errors, parsing failures, etc.)
            The engine should catch this and return a degraded board.

    Invariants:
        - Each opportunity has non-empty title (5+ chars) and angle (10+ chars)
        - primary_channel is Channel.LINKEDIN or Channel.X
        - score is in [0, 100]
        - type is a valid OpportunityType
        - Returns 6-24 opportunities (may be fewer if many taboo violations)
    """
    client = llm_client or get_default_client()

    logger.info(
        "Starting opportunities graph",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "brand_name": brand_snapshot.brand_name,
        },
    )

    try:
        # Node 1: Synthesize opportunities
        raw_opportunities = _synthesize_opportunities(
            brand_snapshot=brand_snapshot,
            learning_summary=learning_summary,
            external_signals=external_signals,
            llm_client=client,
            run_id=run_id,
        )

        logger.debug(
            "Synthesis complete",
            extra={
                "run_id": str(run_id),
                "raw_count": len(raw_opportunities),
            },
        )

        # Node 2: Score and normalize
        scored_opportunities = _score_and_normalize_opportunities(
            raw_opportunities=raw_opportunities,
            brand_snapshot=brand_snapshot,
            llm_client=client,
            run_id=run_id,
        )

        logger.debug(
            "Scoring complete",
            extra={
                "run_id": str(run_id),
                "scored_count": len(scored_opportunities),
            },
        )

        # Transform: Convert to draft DTOs
        drafts = _convert_to_draft_dtos(scored_opportunities)

        # Sort by score descending
        drafts.sort(key=lambda d: d.score, reverse=True)

        logger.info(
            "Opportunities graph complete",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_snapshot.brand_id),
                "final_count": len(drafts),
            },
        )

        return drafts

    except LLMCallError as e:
        logger.error(
            "LLM call failed in opportunities graph",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_snapshot.brand_id),
                "error": str(e),
            },
        )
        raise GraphError(f"LLM call failed: {e}", original_error=e) from e

    except StructuredOutputError as e:
        logger.error(
            "Structured output parsing failed in opportunities graph",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_snapshot.brand_id),
                "error": str(e),
            },
        )
        raise GraphError(f"Output parsing failed: {e}", original_error=e) from e

    except Exception as e:
        logger.error(
            "Unexpected error in opportunities graph",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_snapshot.brand_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise GraphError(f"Graph failed: {e}", original_error=e) from e
