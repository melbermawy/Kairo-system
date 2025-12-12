"""
Variants Graph for F2 - Variant Generation.

PR-9: Implements graph_hero_variants_from_package per PRD-1 §5.3 and
docs/technical/10-variant-rubric.md.

This module defines a focused graph that:
1. Generates channel-specific variants for a content package
2. Validates each variant against channel constraints
3. Produces a list of VariantDraftDTOs

Design constraints (per 05-llm-and-deepagents-conventions.md):
- NO ORM imports anywhere in this module
- NO DB reads/writes - graph deals only in DTOs
- ALL LLM calls go through kairo.hero.llm_client.LLMClient
- Returns list[VariantDraftDTO] only

Invariants per 10-variant-rubric.md:
- Non-empty body for each variant
- Channel-appropriate length and structure
- No taboo violations
- No template/prompt artifacts in output
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from kairo.core.enums import Channel
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ContentPackageDraftDTO,
    VariantDraftDTO,
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

logger = logging.getLogger("kairo.hero.graphs.variants")


# =============================================================================
# EXCEPTIONS
# =============================================================================


class VariantsGraphError(Exception):
    """
    Exception raised when a variants graph operation fails.

    Used by the engine to distinguish graph failures from other errors.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


# =============================================================================
# INTERNAL SCHEMAS FOR LLM OUTPUT
# =============================================================================


class RawVariant(BaseModel):
    """
    Raw variant from LLM generation node.

    Internal schema - converted to VariantDraftDTO.
    """

    channel: str = Field(description="Channel: linkedin, x, or newsletter")
    title: str | None = Field(default=None, description="Optional title (for newsletter)")
    body: str = Field(min_length=10, description="Main content body")
    call_to_action: str | None = Field(default=None, description="CTA for this variant")
    pattern_hint: str | None = Field(default=None, description="Pattern used")
    reasoning: str = Field(default="", description="Why this approach was chosen")


class VariantsGenerationOutput(BaseModel):
    """Output from the variants generation LLM node."""

    variants: list[RawVariant] = Field(min_length=1, description="List of variants")


# =============================================================================
# CHANNEL CONSTRAINTS PER RUBRIC §5
# =============================================================================

# Per 10-variant-rubric.md §5
CHANNEL_CONSTRAINTS = {
    "linkedin": {
        "min_length": 25,  # Minimum ~25 words
        "max_length": 3000,  # ~800 words max
        "min_chars": 100,
        "max_chars": 6000,
    },
    "x": {
        "min_length": 20,  # Short but meaningful
        "max_length": 600,  # Hard limit for tweet-like content
        "min_chars": 20,
        "max_chars": 600,
    },
    "newsletter": {
        "min_length": 50,  # Minimum ~50 words
        "max_length": 5000,  # Longer form allowed
        "min_chars": 200,
        "max_chars": 10000,
    },
}

# Template artifact patterns per rubric §3.3
TEMPLATE_ARTIFACT_PATTERNS = [
    r"\[insert\s+\w+\s*here\]",
    r"\{brand\}",
    r"\{name\}",
    r"\{cta\}",
    r"as an ai",
    r"language model",
    r"i cannot",
    r"i'm unable",
    r"TODO:",
    r"placeholder",
    r"you should write",
]


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

VARIANTS_SYSTEM_PROMPT = """You are a content writer for {brand_name}.

Your task is to write channel-specific content variants for a content package.

BRAND CONTEXT:
- Positioning: {positioning}
- Voice/Tone: {tone_tags}
- TABOOS (never include these): {taboos}

CHANNEL GUIDELINES:
- LinkedIn: Professional tone, 2-8 paragraphs, hook in first line, clear structure
- X (Twitter): Concise, punchy, under 280 characters ideally, strong hook
- Newsletter: Email-style, narrative structure, longer form allowed

IMPORTANT:
- Write actual content, NOT instructions or placeholders
- Match the channel's native format and length
- Include clear CTAs that fit the channel
- Never include template artifacts like [insert X here] or {{brand}}

Your output must be valid JSON matching the required schema."""

VARIANTS_USER_PROMPT = """Write content variants for this package:

PACKAGE:
- Title: {pkg_title}
- Thesis: {pkg_thesis}
- Summary: {pkg_summary}
- CTA: {pkg_cta}
- Channels: {channels}

REQUIREMENTS:
1. Generate ONE variant for EACH channel listed above
2. Each variant must:
   - Implement the package thesis in a channel-native way
   - Be actual publishable content (not instructions)
   - Include an appropriate CTA
3. Channel-specific:
   - LinkedIn: 2-8 paragraphs, professional, hook line first
   - X: Under 280 chars ideally, punchy, no greetings
   - Newsletter: Email-style, can be longer, narrative structure

Return your response as JSON with a "variants" array."""


# =============================================================================
# VALIDATION LOGIC
# =============================================================================


def _validate_variant(
    variant: RawVariant,
    brand_snapshot: BrandSnapshotDTO,
) -> tuple[bool, list[str]]:
    """
    Validate a variant against rubric §3 hard requirements.

    Returns (is_valid, rejection_reasons).

    Per 10-variant-rubric.md §3:
    - §3.1: Non-empty, non-junk body
    - §3.2: No hallucinated brand
    - §3.3: No template artifacts
    - §3.4: Link to package thesis (checked at scoring level)
    - §3.5: No taboo violations
    """
    reasons = []
    channel = variant.channel.lower()
    body = variant.body.strip()

    # §3.1: Empty or junk body
    if len(body) < 10:
        reasons.append("body too short or empty (§3.1)")

    # Check channel-specific length constraints
    constraints = CHANNEL_CONSTRAINTS.get(channel, CHANNEL_CONSTRAINTS["linkedin"])
    if len(body) < constraints["min_chars"]:
        reasons.append(f"body too short for {channel}: {len(body)} chars (§3.1)")
    if len(body) > constraints["max_chars"]:
        reasons.append(f"body too long for {channel}: {len(body)} chars (§3.1)")

    # §3.3: Template artifacts
    body_lower = body.lower()
    for pattern in TEMPLATE_ARTIFACT_PATTERNS:
        if re.search(pattern, body_lower, re.IGNORECASE):
            reasons.append(f"contains template artifact: '{pattern}' (§3.3)")
            break

    # §3.5: Taboo violations
    for taboo in brand_snapshot.taboos:
        if taboo.lower() in body_lower:
            reasons.append(f"taboo violation: '{taboo}' (§3.5)")
            break

    # X-specific: length check
    if channel == "x" and len(body) > 600:
        reasons.append("X variant too long (>600 chars) (§5.2.2)")

    is_valid = len(reasons) == 0
    return is_valid, reasons


def _compute_variant_score(
    variant: RawVariant,
    pkg_thesis: str,
) -> tuple[float, dict[str, float]]:
    """
    Compute variant quality score per rubric §4.

    Returns (total_score, breakdown).

    Dimensions (each 0-3):
    - clarity: clarity & completeness
    - anchoring: connection to package thesis
    - channel_fit: channel form fit
    - cta: CTA alignment

    Total in [0, 12].
    """
    breakdown: dict[str, float] = {}
    body = variant.body.strip()
    channel = variant.channel.lower()

    # Clarity & completeness (0-3)
    word_count = len(body.split())
    if word_count < 10:
        breakdown["clarity"] = 0
    elif word_count < 30:
        breakdown["clarity"] = 1
    elif word_count < 100:
        breakdown["clarity"] = 2
    else:
        breakdown["clarity"] = 3

    # Anchoring to thesis (0-3)
    thesis_keywords = set(pkg_thesis.lower().split())
    body_words = set(body.lower().split())
    overlap = len(thesis_keywords & body_words)
    if overlap >= 4:
        breakdown["anchoring"] = 3
    elif overlap >= 2:
        breakdown["anchoring"] = 2
    elif overlap >= 1:
        breakdown["anchoring"] = 1
    else:
        breakdown["anchoring"] = 0

    # Channel form fit (0-3)
    constraints = CHANNEL_CONSTRAINTS.get(channel, CHANNEL_CONSTRAINTS["linkedin"])
    body_len = len(body)

    # Check if within ideal range
    min_ideal = constraints["min_chars"]
    max_ideal = constraints["max_chars"]

    if min_ideal <= body_len <= max_ideal:
        # Structure checks
        if channel == "linkedin":
            # Good linkedin: has line breaks, paragraphs
            if "\n" in body and len(body.split("\n")) >= 2:
                breakdown["channel_fit"] = 3
            else:
                breakdown["channel_fit"] = 2
        elif channel == "x":
            # Good X: concise, punchy
            if body_len <= 280:
                breakdown["channel_fit"] = 3
            else:
                breakdown["channel_fit"] = 2
        elif channel == "newsletter":
            # Good newsletter: has structure
            if len(body.split("\n")) >= 3:
                breakdown["channel_fit"] = 3
            else:
                breakdown["channel_fit"] = 2
        else:
            breakdown["channel_fit"] = 2
    else:
        breakdown["channel_fit"] = 1 if body_len > 0 else 0

    # CTA alignment (0-3)
    cta = variant.call_to_action
    if not cta or len(cta.strip()) < 3:
        breakdown["cta"] = 0
    elif len(cta.strip()) < 15:
        breakdown["cta"] = 1
    elif len(cta.strip()) < 40:
        breakdown["cta"] = 2
    else:
        breakdown["cta"] = 3

    total = sum(breakdown.values())
    return total, breakdown


def _determine_variant_quality_band(
    is_valid: bool,
    score: float,
) -> Literal["invalid", "weak", "publish_ready"]:
    """
    Determine quality band per rubric §6.

    - invalid: fails hard rules
    - weak: valid but score in [1, 6]
    - publish_ready: valid and score >= 7
    """
    if not is_valid:
        return "invalid"
    if score < 7:
        return "weak"
    return "publish_ready"


# =============================================================================
# CONVERSION TO DRAFT DTO
# =============================================================================


def _convert_to_draft_dto(
    variant: RawVariant,
    pkg_thesis: str,
    brand_snapshot: BrandSnapshotDTO,
) -> VariantDraftDTO:
    """
    Convert raw variant to VariantDraftDTO with validation.

    Applies rubric validation and scoring.
    """
    # Validate
    is_valid, rejection_reasons = _validate_variant(variant, brand_snapshot)

    # Score
    if is_valid:
        score, breakdown = _compute_variant_score(variant, pkg_thesis)
    else:
        score = 0.0
        breakdown = {}

    # Determine quality band
    quality_band = _determine_variant_quality_band(is_valid, score)

    # Parse channel
    channel_map = {
        "linkedin": Channel.LINKEDIN,
        "x": Channel.X,
        "newsletter": Channel.NEWSLETTER,
    }
    channel = channel_map.get(variant.channel.lower(), Channel.LINKEDIN)

    return VariantDraftDTO(
        channel=channel,
        body=variant.body,
        title=variant.title,
        call_to_action=variant.call_to_action,
        pattern_hint=variant.pattern_hint,
        raw_reasoning=variant.reasoning,
        is_valid=is_valid,
        rejection_reasons=rejection_reasons,
        variant_score=score,
        variant_score_breakdown=breakdown if breakdown else None,
        quality_band=quality_band,
    )


# =============================================================================
# STUB OUTPUT FOR LLM_DISABLED MODE
# =============================================================================

STUB_LINKEDIN_BODY = """Here's what we've learned about this opportunity:

The key insight is that our audience cares deeply about value and transparency.

When we focus on clear communication:
1. Trust increases
2. Engagement improves
3. Conversion follows

What's your experience with this? Share in the comments."""

STUB_X_BODY = """Key insight: value and transparency drive trust.

When you focus on clear communication, everything else follows.

What's your take?"""

STUB_NEWSLETTER_BODY = """Hi there,

I wanted to share something we've been thinking about.

The core idea is simple: when we prioritize transparency and clear value communication, our audience responds positively.

Here's what we've learned:
- Trust builds over time through consistent messaging
- Clear value propositions outperform vague promises
- Engagement comes from genuine connection

We're excited to explore this more and would love your thoughts.

Best,
The Team"""


def _generate_stub_variants(
    package: ContentPackageDraftDTO,
    brand_snapshot: BrandSnapshotDTO,
) -> list[VariantDraftDTO]:
    """
    Generate deterministic stub variants for LLM_DISABLED mode.

    Used for testing and eval runs without real LLM calls.
    """
    variants = []

    stub_content = {
        Channel.LINKEDIN: (STUB_LINKEDIN_BODY, "Share your thoughts in the comments"),
        Channel.X: (STUB_X_BODY, "Let me know"),
        Channel.NEWSLETTER: (STUB_NEWSLETTER_BODY, "Reply to this email"),
    }

    for channel in package.channels:
        body, cta = stub_content.get(channel, (STUB_LINKEDIN_BODY, "Learn more"))

        variants.append(VariantDraftDTO(
            channel=channel,
            body=body,
            title=f"[STUB] {package.title}" if channel == Channel.NEWSLETTER else None,
            call_to_action=cta,
            pattern_hint="thought_leadership",
            raw_reasoning="Stub output - deterministic for testing",
            is_valid=True,
            rejection_reasons=[],
            variant_score=9.0,
            variant_score_breakdown={
                "clarity": 2,
                "anchoring": 2,
                "channel_fit": 3,
                "cta": 2,
            },
            quality_band="publish_ready",
        ))

    return variants


# =============================================================================
# MAIN GRAPH ENTRYPOINT
# =============================================================================


def graph_hero_variants_from_package(
    run_id: UUID,
    package: ContentPackageDraftDTO,
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient | None = None,
) -> list[VariantDraftDTO]:
    """
    Generate content variants for a package.

    This is the main entrypoint for the variants graph.

    Args:
        run_id: UUID for tracing/logging
        package: The content package to generate variants for
        brand_snapshot: Brand context (taboos, voice, etc.)
        llm_client: Optional LLM client (uses default if None)

    Returns:
        List of VariantDraftDTOs with validation and scoring applied

    Raises:
        VariantsGraphError: If graph operation fails
    """
    client = llm_client or get_default_client()

    logger.info(
        "Starting variants graph",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "package_title": package.title[:50],
            "channels": [c.value for c in package.channels],
        },
    )

    # Check if LLM is disabled - return stubs
    if client.config.llm_disabled:
        logger.info(
            "LLM disabled, returning stub variants",
            extra={"run_id": str(run_id)},
        )
        return _generate_stub_variants(package, brand_snapshot)

    # Build prompts
    taboos_str = ", ".join(brand_snapshot.taboos) or "none"
    tone_str = ", ".join(brand_snapshot.voice_tone_tags) or "professional"
    channels_str = ", ".join(c.value for c in package.channels)

    system_prompt = VARIANTS_SYSTEM_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
        positioning=brand_snapshot.positioning or "not specified",
        tone_tags=tone_str,
        taboos=taboos_str,
    )

    user_prompt = VARIANTS_USER_PROMPT.format(
        pkg_title=package.title,
        pkg_thesis=package.thesis,
        pkg_summary=package.summary,
        pkg_cta=package.cta or "not specified",
        channels=channels_str,
    )

    # Call LLM
    try:
        response = client.call(
            brand_id=brand_snapshot.brand_id,
            flow="F2_variants",
            prompt=user_prompt,
            system_prompt=system_prompt,
            role="heavy",
            run_id=run_id,
        )

        logger.info(
            "Variants LLM call completed",
            extra={
                "run_id": str(run_id),
                "tokens_in": response.usage_tokens_in,
                "tokens_out": response.usage_tokens_out,
            },
        )

    except LLMCallError as e:
        logger.error(
            "Variants graph LLM call failed",
            extra={
                "run_id": str(run_id),
                "error": str(e),
            },
        )
        raise VariantsGraphError(f"LLM call failed: {e}", original_error=e) from e

    # Parse response
    try:
        output = parse_structured_output(response.raw_text, VariantsGenerationOutput)
    except StructuredOutputError as e:
        logger.warning(
            "Variants output parsing failed",
            extra={"run_id": str(run_id), "error": str(e)},
        )
        raise VariantsGraphError(f"Output parsing failed: {e}", original_error=e) from e

    # Convert to draft DTOs with validation
    drafts = []
    for raw_variant in output.variants:
        draft = _convert_to_draft_dto(
            raw_variant,
            package.thesis,
            brand_snapshot,
        )
        drafts.append(draft)

    # Log summary
    valid_count = sum(1 for d in drafts if d.is_valid)
    logger.info(
        "Variants graph completed",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "total_variants": len(drafts),
            "valid_variants": valid_count,
        },
    )

    return drafts
