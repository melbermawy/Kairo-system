"""
Package Graph for F2 - Content Package Generation.

PR-9: Implements graph_hero_package_from_opportunity per PRD-1 §5.2 and
docs/technical/09-package-rubric.md.

This module defines a focused graph that:
1. Generates a content package thesis from an opportunity
2. Selects appropriate channels and patterns
3. Produces a ContentPackageDraftDTO

Design constraints (per 05-llm-and-deepagents-conventions.md):
- NO ORM imports anywhere in this module
- NO DB reads/writes - graph deals only in DTOs
- ALL LLM calls go through kairo.hero.llm_client.LLMClient
- Returns ContentPackageDraftDTO only

Invariants the output must satisfy per 09-package-rubric.md:
- Non-empty, non-vacuous title, thesis, summary
- primary_channel is valid and in channels list
- channels list is non-empty
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from kairo.core.enums import Channel
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ContentPackageDraftDTO,
    OpportunityDTO,
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

logger = logging.getLogger("kairo.hero.graphs.package")


# =============================================================================
# EXCEPTIONS
# =============================================================================


class PackageGraphError(Exception):
    """
    Exception raised when a package graph operation fails.

    Used by the engine to distinguish graph failures from other errors
    and trigger degraded mode behavior.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


# =============================================================================
# INTERNAL SCHEMAS FOR LLM OUTPUT
# =============================================================================


class RawPackageIdea(BaseModel):
    """
    Raw package idea from LLM synthesis node.

    Internal schema - converted to ContentPackageDraftDTO.
    """

    title: str = Field(min_length=5, max_length=200)
    thesis: str = Field(
        min_length=20, max_length=500,
        description="Core content thesis - must be specific and actionable"
    )
    summary: str = Field(
        min_length=20, max_length=1000,
        description="Brief explanation of the package content"
    )
    primary_channel: str = Field(description="Main channel: linkedin, x, or newsletter")
    channels: list[str] = Field(
        min_length=1,
        description="All channels for this package"
    )
    cta: str | None = Field(default=None, description="Call to action")
    pattern_hints: list[str] = Field(
        default_factory=list,
        description="Suggested content patterns"
    )
    persona_hint: str | None = Field(default=None, description="Target persona name")
    pillar_hint: str | None = Field(default=None, description="Content pillar name")
    notes_for_humans: str | None = Field(default=None)
    reasoning: str = Field(default="", description="Explanation of choices made")


class PackageSynthesisOutput(BaseModel):
    """Output from the package synthesis LLM node."""

    package: RawPackageIdea


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

PACKAGE_SYSTEM_PROMPT = """You are a content strategist for {brand_name}.

Your task is to create a content package based on a specific opportunity. A content package:
- Has a clear thesis (the core argument/message)
- Spans one or more channels (linkedin, x, newsletter)
- Has a clear call-to-action

BRAND CONTEXT:
- Positioning: {positioning}
- Voice/Tone: {tone_tags}
- Content Pillars: {pillars}
- Target Personas: {personas}
- TABOOS (never include these): {taboos}

IMPORTANT:
- The thesis must be specific and actionable, NOT generic like "write a post about this"
- Channel selection should match the content type (long-form for linkedin/newsletter, punchy for x)
- CTA should match the package intent

Your output must be valid JSON matching the required schema."""

PACKAGE_USER_PROMPT = """Create a content package for this opportunity:

OPPORTUNITY:
- Title: {opp_title}
- Angle: {opp_angle}
- Type: {opp_type}
- Primary Channel: {opp_channel}
- Why Now: {opp_why_now}

REQUIREMENTS:
1. Title: Clear, specific package title (not just the opportunity title)
2. Thesis: The core argument/message - must be specific and actionable
   - BAD: "write about pricing"
   - GOOD: "show how our pricing works in plain numbers to rebuild trust"
3. Summary: 2-3 sentences explaining the content approach
4. primary_channel: The main channel for this package (must be one of: linkedin, x, newsletter)
5. channels: Array of all channels for this package (include primary_channel plus any others)
6. CTA: Clear call-to-action aligned with the package intent
7. Pattern hints: Suggest content patterns if relevant

Return your response as JSON with a "package" object containing these fields:
- title (string)
- thesis (string, 20-500 chars)
- summary (string, 20-1000 chars)
- primary_channel (string: "linkedin", "x", or "newsletter")
- channels (array of strings)
- cta (string, optional)
- pattern_hints (array of strings, optional)"""


# =============================================================================
# VALIDATION LOGIC
# =============================================================================

# Vacuous thesis patterns per rubric §5.1
VACUOUS_THESIS_PATTERNS = [
    "write a post",
    "write about",
    "create content",
    "talk about",
    "general marketing",
    "make some",
    "post about",
]


def _validate_package(
    pkg: RawPackageIdea,
    opportunity: OpportunityDTO,
    brand_snapshot: BrandSnapshotDTO,
) -> tuple[bool, list[str]]:
    """
    Validate a package against rubric §5 hard requirements.

    Returns (is_valid, rejection_reasons).

    Per 09-package-rubric.md §5:
    - §5.1: Non-vacuous thesis
    - §5.2: Valid primary_channel in channels
    - §5.3: Non-empty channels list
    - §5.4: CTA present (or missing is acceptable in PRD-1)
    - §5.5: No taboo violations
    - §5.6: Clear opportunity linkage
    """
    reasons = []

    # §5.1: Missing or vacuous thesis
    if not pkg.thesis or len(pkg.thesis.strip()) < 20:
        reasons.append("thesis too short or empty (§5.1)")
    else:
        thesis_lower = pkg.thesis.lower()
        for pattern in VACUOUS_THESIS_PATTERNS:
            if pattern in thesis_lower:
                reasons.append(f"thesis is vacuous: contains '{pattern}' (§5.1)")
                break

    # §5.2: Valid primary_channel
    valid_channels = {"linkedin", "x", "newsletter"}
    if pkg.primary_channel.lower() not in valid_channels:
        reasons.append(f"invalid primary_channel '{pkg.primary_channel}' (§5.2)")

    # Check primary_channel is in channels
    if pkg.primary_channel.lower() not in [c.lower() for c in pkg.channels]:
        reasons.append("primary_channel not in channels list (§5.2)")

    # §5.3: Non-empty channels
    if not pkg.channels:
        reasons.append("channels list is empty (§5.3)")

    # §5.5: Taboo violations
    text_to_check = f"{pkg.title} {pkg.thesis} {pkg.summary}"
    for taboo in brand_snapshot.taboos:
        if taboo.lower() in text_to_check.lower():
            reasons.append(f"taboo violation: '{taboo}' (§5.5)")
            break

    # §5.6: Opportunity linkage - check thesis relates to opportunity
    # Simple check: at least some keyword overlap
    opp_keywords = set(opportunity.title.lower().split())
    thesis_words = set(pkg.thesis.lower().split())
    if not opp_keywords & thesis_words and len(opp_keywords) > 2:
        # Only flag if opportunity has meaningful keywords and no overlap
        reasons.append("thesis doesn't clearly link to opportunity (§5.6)")

    is_valid = len(reasons) == 0
    return is_valid, reasons


def _compute_package_score(
    pkg: RawPackageIdea,
    opportunity: OpportunityDTO,
) -> tuple[float, dict[str, float]]:
    """
    Compute package quality score per rubric §6-7.

    Returns (total_score, breakdown).

    Dimensions (each 0-3):
    - thesis: clarity and specificity
    - coherence: cross-channel coherence
    - relevance: relevance to opportunity
    - cta: CTA quality
    - brand_alignment: brand/pattern alignment

    Total in [0, 15].
    """
    breakdown: dict[str, float] = {}

    # Thesis clarity (0-3)
    thesis_len = len(pkg.thesis.strip())
    if thesis_len < 30:
        breakdown["thesis"] = 0
    elif thesis_len < 50:
        breakdown["thesis"] = 1
    elif thesis_len < 100:
        breakdown["thesis"] = 2
    else:
        breakdown["thesis"] = 3

    # Cross-channel coherence (0-3)
    num_channels = len(pkg.channels)
    if num_channels == 0:
        breakdown["coherence"] = 0
    elif num_channels == 1:
        breakdown["coherence"] = 2  # Single channel is coherent
    elif num_channels <= 3:
        breakdown["coherence"] = 3  # 2-3 channels is ideal
    else:
        breakdown["coherence"] = 1  # Too many channels

    # Relevance to opportunity (0-3)
    opp_keywords = set(opportunity.title.lower().split())
    opp_keywords.update(opportunity.angle.lower().split())
    thesis_words = set(pkg.thesis.lower().split())
    summary_words = set(pkg.summary.lower().split())
    combined_words = thesis_words | summary_words

    overlap = len(opp_keywords & combined_words)
    if overlap >= 3:
        breakdown["relevance"] = 3
    elif overlap >= 2:
        breakdown["relevance"] = 2
    elif overlap >= 1:
        breakdown["relevance"] = 1
    else:
        breakdown["relevance"] = 0

    # CTA quality (0-3)
    if not pkg.cta or len(pkg.cta.strip()) < 5:
        breakdown["cta"] = 0
    elif len(pkg.cta.strip()) < 20:
        breakdown["cta"] = 1
    elif len(pkg.cta.strip()) < 50:
        breakdown["cta"] = 2
    else:
        breakdown["cta"] = 3

    # Brand alignment (0-3) - simplified heuristic
    # Better score if persona/pillar hints are provided
    alignment_score = 2  # Base score
    if pkg.persona_hint:
        alignment_score += 0.5
    if pkg.pillar_hint:
        alignment_score += 0.5
    breakdown["brand_alignment"] = min(3, alignment_score)

    total = sum(breakdown.values())
    return total, breakdown


def _determine_quality_band(
    is_valid: bool,
    score: float,
) -> Literal["invalid", "weak", "board_ready"]:
    """
    Determine quality band per rubric §7.

    - invalid: fails hard rules
    - weak: valid but score in [1, 7]
    - board_ready: valid and score >= 8
    """
    if not is_valid:
        return "invalid"
    if score < 8:
        return "weak"
    return "board_ready"


# =============================================================================
# CONVERSION TO DRAFT DTO
# =============================================================================


def _convert_to_draft_dto(
    pkg: RawPackageIdea,
    opportunity: OpportunityDTO,
    brand_snapshot: BrandSnapshotDTO,
) -> ContentPackageDraftDTO:
    """
    Convert raw package idea to ContentPackageDraftDTO with validation.

    Applies rubric validation and scoring.
    """
    # Validate
    is_valid, rejection_reasons = _validate_package(pkg, opportunity, brand_snapshot)

    # Score
    if is_valid:
        score, breakdown = _compute_package_score(pkg, opportunity)
    else:
        score = 0.0
        breakdown = {}

    # Determine quality band
    quality_band = _determine_quality_band(is_valid, score)

    # Parse channels
    channel_map = {
        "linkedin": Channel.LINKEDIN,
        "x": Channel.X,
        "newsletter": Channel.NEWSLETTER,
    }

    primary_channel = channel_map.get(
        pkg.primary_channel.lower(),
        Channel.LINKEDIN
    )

    channels = []
    for ch in pkg.channels:
        mapped = channel_map.get(ch.lower())
        if mapped:
            channels.append(mapped)

    # Ensure primary_channel is in channels
    if primary_channel not in channels:
        channels.insert(0, primary_channel)

    return ContentPackageDraftDTO(
        title=pkg.title,
        thesis=pkg.thesis,
        summary=pkg.summary,
        primary_channel=primary_channel,
        channels=channels,
        cta=pkg.cta,
        pattern_hints=pkg.pattern_hints,
        persona_hint=pkg.persona_hint,
        pillar_hint=pkg.pillar_hint,
        notes_for_humans=pkg.notes_for_humans,
        raw_reasoning=pkg.reasoning,
        is_valid=is_valid,
        rejection_reasons=rejection_reasons,
        package_score=score,
        package_score_breakdown=breakdown if breakdown else None,
        quality_band=quality_band,
    )


# =============================================================================
# STUB OUTPUT FOR LLM_DISABLED MODE
# =============================================================================


def _generate_stub_package(
    opportunity: OpportunityDTO,
    brand_snapshot: BrandSnapshotDTO,
) -> ContentPackageDraftDTO:
    """
    Generate deterministic stub package for LLM_DISABLED mode.

    Used for testing and eval runs without real LLM calls.
    """
    return ContentPackageDraftDTO(
        title=f"Package: {opportunity.title[:50]}",
        thesis=f"Explore how {brand_snapshot.brand_name} can leverage this opportunity to engage {opportunity.angle[:100]}",
        summary=f"This package addresses the opportunity '{opportunity.title}' by creating content that resonates with our target audience across multiple channels.",
        primary_channel=opportunity.primary_channel,
        channels=[opportunity.primary_channel, Channel.X] if opportunity.primary_channel != Channel.X else [Channel.X, Channel.LINKEDIN],
        cta="Learn more about our approach",
        pattern_hints=["thought_leadership", "how_to"],
        persona_hint=brand_snapshot.personas[0].name if brand_snapshot.personas else None,
        pillar_hint=brand_snapshot.pillars[0].name if brand_snapshot.pillars else None,
        notes_for_humans="[STUB] Generated in LLM_DISABLED mode",
        raw_reasoning="Stub output - deterministic for testing",
        is_valid=True,
        rejection_reasons=[],
        package_score=10.0,
        package_score_breakdown={
            "thesis": 2,
            "coherence": 3,
            "relevance": 2,
            "cta": 1,
            "brand_alignment": 2,
        },
        quality_band="board_ready",
    )


# =============================================================================
# MAIN GRAPH ENTRYPOINT
# =============================================================================


def graph_hero_package_from_opportunity(
    run_id: UUID,
    brand_snapshot: BrandSnapshotDTO,
    opportunity: OpportunityDTO,
    llm_client: LLMClient | None = None,
) -> ContentPackageDraftDTO:
    """
    Generate a content package from an opportunity.

    This is the main entrypoint for the package graph.

    Args:
        run_id: UUID for tracing/logging
        brand_snapshot: Brand context (pillars, personas, taboos, etc.)
        opportunity: The opportunity to create a package for
        llm_client: Optional LLM client (uses default if None)

    Returns:
        ContentPackageDraftDTO with validation and scoring applied

    Raises:
        PackageGraphError: If graph operation fails
    """
    client = llm_client or get_default_client()

    logger.info(
        "Starting package graph",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "opportunity_id": str(opportunity.id),
        },
    )

    # Check if LLM is disabled - return stub
    if client.config.llm_disabled:
        logger.info(
            "LLM disabled, returning stub package",
            extra={"run_id": str(run_id)},
        )
        return _generate_stub_package(opportunity, brand_snapshot)

    # Build prompts
    pillars_str = ", ".join(p.name for p in brand_snapshot.pillars) or "none"
    personas_str = ", ".join(p.name for p in brand_snapshot.personas) or "none"
    taboos_str = ", ".join(brand_snapshot.taboos) or "none"
    tone_str = ", ".join(brand_snapshot.voice_tone_tags) or "professional"

    system_prompt = PACKAGE_SYSTEM_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
        positioning=brand_snapshot.positioning or "not specified",
        tone_tags=tone_str,
        pillars=pillars_str,
        personas=personas_str,
        taboos=taboos_str,
    )

    user_prompt = PACKAGE_USER_PROMPT.format(
        opp_title=opportunity.title,
        opp_angle=opportunity.angle,
        opp_type=opportunity.type.value,
        opp_channel=opportunity.primary_channel.value,
        opp_why_now=opportunity.score_explanation or "timely opportunity",
    )

    # Call LLM
    try:
        response = client.call(
            brand_id=brand_snapshot.brand_id,
            flow="F2_package",
            prompt=user_prompt,
            system_prompt=system_prompt,
            role="heavy",
            run_id=run_id,
        )

        logger.info(
            "Package LLM call completed",
            extra={
                "run_id": str(run_id),
                "tokens_in": response.usage_tokens_in,
                "tokens_out": response.usage_tokens_out,
            },
        )

    except LLMCallError as e:
        logger.error(
            "Package graph LLM call failed",
            extra={
                "run_id": str(run_id),
                "error": str(e),
            },
        )
        raise PackageGraphError(f"LLM call failed: {e}", original_error=e) from e

    # Parse response
    try:
        output = parse_structured_output(response.raw_text, PackageSynthesisOutput)
    except StructuredOutputError as e:
        logger.warning(
            "Package output parsing failed",
            extra={"run_id": str(run_id), "error": str(e)},
        )
        raise PackageGraphError(f"Output parsing failed: {e}", original_error=e) from e

    # Convert to draft DTO with validation
    draft = _convert_to_draft_dto(
        output.package,
        opportunity,
        brand_snapshot,
    )

    logger.info(
        "Package graph completed",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "is_valid": draft.is_valid,
            "quality_band": draft.quality_band,
            "package_score": draft.package_score,
        },
    )

    return draft
