"""
Multi-Stage Synthesis Pipeline for F1 - Today Board Generation.

Performance PR: Replaces monolithic synthesis with kernel → expand → score pipeline.

Architecture (per ChatGPT guidance):
- Stage 1: Kernel Generation (parallel, gpt-5-nano) - fast atomic judgments
- Stage 2: Kernel Consolidation (gpt-5-nano) - dedupe + select top kernels
- Stage 3: Explanation Expansion (gpt-5) - rich prose per kernel
- Stage 4: Scoring + Validation (gpt-5-nano) - rubric scoring

CRITICAL DESIGN (opportunity-atomic, not board-atomic):
- Stage 3 expands kernels INDEPENDENTLY with hard timeouts
- Each expansion has MAX 20s timeout, 0 retries
- Pipeline commits partial success once MIN_READY_OPPS (3) succeed
- This prevents one slow/stuck LLM call from blocking entire generation

Target Properties:
- Total wall-clock time < 60-90s (vs current 20-30 minutes)
- No single LLM call blocks the entire pipeline
- Partial results are valid - 3+ opportunities = success
- Rich, paragraph-style explanations preserved

Design constraints (per 05-llm-and-deepagents-conventions.md):
- NO ORM imports anywhere in this module
- NO DB reads/writes - pipeline deals only in DTOs
- ALL LLM calls go through kairo.hero.llm_client.LLMClient
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from kairo.core.enums import Channel, OpportunityType
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ExternalSignalBundleDTO,
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
    from kairo.sourceactivation.types import EvidenceItemData

logger = logging.getLogger("kairo.hero.graphs.synthesis_pipeline")


# =============================================================================
# PIPELINE CONFIGURATION - Non-negotiable constraints
# =============================================================================

# Minimum opportunities required for READY state (partial success threshold)
MIN_READY_OPPS = 3

# Hard timeout per expansion call (seconds) - no retries, fail fast
EXPANSION_TIMEOUT_SECONDS = 20

# Maximum kernels to attempt expanding (even if more consolidated)
MAX_EXPANSION_ATTEMPTS = 8


# =============================================================================
# TIMING INSTRUMENTATION
# =============================================================================


@dataclass
class PipelineTimings:
    """Timing breakdown for each stage of the pipeline."""

    total_ms: int = 0
    kernel_generation_ms: int = 0
    kernel_consolidation_ms: int = 0
    explanation_expansion_ms: int = 0
    scoring_ms: int = 0

    # Detailed breakdown
    kernel_call_count: int = 0
    kernel_calls_parallel: int = 0
    expansion_call_count: int = 0

    # Partial success tracking (opportunity-atomic)
    expansion_attempts: int = 0
    expansion_successes: int = 0
    expansion_timeouts: int = 0
    expansion_failures: int = 0

    # Token estimates
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "total_ms": self.total_ms,
            "kernel_generation_ms": self.kernel_generation_ms,
            "kernel_consolidation_ms": self.kernel_consolidation_ms,
            "explanation_expansion_ms": self.explanation_expansion_ms,
            "scoring_ms": self.scoring_ms,
            "kernel_call_count": self.kernel_call_count,
            "kernel_calls_parallel": self.kernel_calls_parallel,
            "expansion_call_count": self.expansion_call_count,
            "expansion_attempts": self.expansion_attempts,
            "expansion_successes": self.expansion_successes,
            "expansion_timeouts": self.expansion_timeouts,
            "expansion_failures": self.expansion_failures,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }


# =============================================================================
# STAGE 1: KERNEL GENERATION SCHEMAS
# =============================================================================


class OpportunityKernel(BaseModel):
    """
    Atomic opportunity kernel - minimal structured output from Stage 1.

    No prose, no explanations, just the core idea.
    """
    core_idea: str = Field(min_length=10, max_length=300, description="The core content opportunity idea (max 300 chars)")
    type: str = Field(description="One of: trend, evergreen, competitive, campaign")
    primary_channel: str = Field(description="One of: linkedin, x, instagram, tiktok")
    timing_hook: str = Field(min_length=5, max_length=200, description="What just happened / why now (max 200 chars)")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence score")

    # Linkage to evidence (for later stages)
    evidence_indices: list[int] = Field(default_factory=list, description="Indices of evidence items used")


class KernelGenerationOutput(BaseModel):
    """Output from a single kernel generation call."""
    kernel: OpportunityKernel


class KernelConsolidationOutput(BaseModel):
    """Output from kernel consolidation stage."""
    kernels: list[OpportunityKernel] = Field(min_length=1, max_length=8)


# =============================================================================
# STAGE 3: EXPLANATION EXPANSION SCHEMAS
# =============================================================================


class ExpandedOpportunity(BaseModel):
    """
    Fully expanded opportunity with rich prose explanation.

    This is the output of Stage 3 - the expensive but valuable expansion.
    """
    title: str = Field(min_length=10, max_length=300)
    angle: str = Field(min_length=20, max_length=800, description="The core thesis/hook")
    why_now: str = Field(min_length=30, max_length=1500, description="Rich paragraph explanation of timing")
    type: str = Field(default="evergreen", description="One of: trend, evergreen, competitive, campaign")
    primary_channel: str = Field(default="linkedin", description="One of: linkedin, x, instagram, tiktok")
    suggested_channels: list[str] = Field(default_factory=lambda: ["linkedin", "x", "instagram", "tiktok"])
    persona_hint: str | None = None
    pillar_hint: str | None = None


class ExpansionOutput(BaseModel):
    """Output from a single expansion call."""
    opportunity: ExpandedOpportunity


# =============================================================================
# STAGE 4: SCORING SCHEMAS
# =============================================================================


class ScoringItem(BaseModel):
    """Scoring result for a single opportunity."""
    idx: int = Field(ge=0, description="Index into expanded opportunities")
    score: int = Field(ge=0, le=100)
    band: str = Field(description="invalid, weak, or strong")
    is_valid: bool = Field(default=True)
    rejection_reason: str | None = None


class ScoringOutput(BaseModel):
    """Output from scoring stage."""
    scores: list[ScoringItem]


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

# Stage 1: Kernel generation (one per evidence item or cluster)
KERNEL_SYSTEM_PROMPT = """You extract content IDEAS from trending evidence for a brand.
Brand: {brand_name}
Positioning: {positioning}
TABOOS (never suggest): {taboos}

You are NOT writing marketing copy. You are identifying what content a real creator would make.
Think: "what would make someone stop scrolling?" not "what would a marketer pitch?"

Output ONLY a JSON object with a single "kernel" field. No prose. No explanations."""

KERNEL_USER_PROMPT = """From this evidence, propose ONE content idea kernel.

EVIDENCE:
Platform: {platform}
Author: {author}
Text: {text_snippet}

CRITICAL: Keep fields SHORT and NATIVE to the platform:
- core_idea: max 60 words. Write it like a creator would describe their video idea to a friend, NOT like a marketing brief.
  BAD: "Create a TikTok series showing how brands can optimize..."
  GOOD: "POV: you ask ChatGPT for product recs and it only mentions brands that did this one thing"
- timing_hook: max 30 words. Why would someone care RIGHT NOW?
- primary_channel: match the evidence platform if it's tiktok/instagram. Only use linkedin/x if the content is genuinely better suited there.

Output format:
{{"kernel":{{"core_idea":"creator-style idea description","type":"trend|evergreen|competitive|campaign","primary_channel":"linkedin|x|instagram|tiktok","timing_hook":"why now","confidence":0.0-1.0,"evidence_indices":[{evidence_idx}]}}}}"""

# Stage 2: Consolidation
CONSOLIDATION_SYSTEM_PROMPT = """You deduplicate and select the best content idea kernels.
Brand: {brand_name}
Keep 5-8 strongest, most diverse kernels. Merge near-duplicates.
Prefer ideas that feel native to their platform, not marketing campaigns dressed as content.
Output ONLY JSON with "kernels" array. No prose."""

CONSOLIDATION_USER_PROMPT = """Select the 5-8 best kernels from these candidates:

{kernels_json}

Rules:
- Merge semantically similar ideas (keep highest confidence)
- Ensure type diversity (at least 1 trend, 1 evergreen)
- Prefer ideas that sound like something a creator would actually post, not a brand campaign
- Reject ideas that sound like marketing playbooks

Output: {{"kernels":[...]}}"""

# Stage 3: Expansion (this is where rich prose lives)
EXPANSION_SYSTEM_PROMPT = """You help {brand_name} develop content ideas into full opportunities.

Brand context:
- Positioning: {positioning}
- Pillars: {pillars}
- Content goal: {content_goal}

VOICE/TONE: {tone_tags}

CTA POLICY: {cta_policy}
- "none": This brand NEVER sells in content. Pure value, entertainment, or community. No CTAs, no "link in bio", no "DM me".
- "soft": Value-first. Occasional soft mentions are OK but most content should stand alone without any ask.
- "direct": Clear CTAs are fine when relevant, but content should still be valuable without them.
- "aggressive": Every piece drives action. Fine to be sales-forward.

PLATFORM-NATIVE VOICE ({primary_channel}):
- TikTok: casual, raw, trend-aware, slightly chaotic energy. "POV:", "wait for it", hooks that stop the scroll. No corporate polish.
- Instagram: aesthetic but authentic. Can be polished but should feel personal, not produced. Carousel = teaching moment, Reel = entertainment or hot take.
- LinkedIn: professional but not boring. Hot takes welcome but grounded. "I've been thinking about..." or "Unpopular opinion:" energy.
- X: punchy, provocative, thread-worthy. One strong take per post. Quote-tweet energy.

IMPORTANT: Write opportunities that a creator would actually want to make, not marketing campaigns.
The title should sound like something you'd see in your feed and stop to watch, not a pitch deck slide."""

EXPANSION_USER_PROMPT = """Expand this kernel into a full opportunity.

KERNEL:
{kernel_json}

SUPPORTING EVIDENCE:
{evidence_text}

Create a JSON object with these REQUIRED fields:
- title: How a creator would describe this video/post to a friend. NOT a marketing headline.
  BAD: "Leverage AI Search Trends to Optimize Brand Visibility"
  GOOD: "that satisfying moment when ChatGPT recommends YOUR product"
  GOOD: "POV: you're a brand that actually shows up in AI search"
  GOOD: "I tested what makes ChatGPT recommend products. here's what I found."
- angle: The hook/thesis in 2-3 sentences. What's the actual insight or entertainment value? (max 500 chars)
- why_now: Why would this resonate RIGHT NOW? Ground it in the evidence. (2-3 sentences)
- type: copy from kernel (trend/evergreen/competitive/campaign)
- primary_channel: MUST match the kernel's primary_channel
- suggested_channels: 2-3 channels, primary_channel first

REMEMBER THE CTA POLICY ({cta_policy}):
- If "none" or "soft": The opportunity should deliver value WITHOUT any sales angle. Don't frame it as "how to get customers to..."
- The angle should be interesting to the AUDIENCE, not just useful for the BRAND.

Output ONLY JSON:
{{"opportunity":{{"title":"...","angle":"...","why_now":"...","type":"...","primary_channel":"...","suggested_channels":["..."]}}}}"""

# Stage 4: Scoring
SCORING_SYSTEM_PROMPT = """Score opportunities for {brand_name}.
TABOOS: {taboos}
CTA POLICY: {cta_policy}

Rubric:
- Platform-native (0-25): Does this sound like real content for this platform, or marketing dressed up?
- Audience value (0-25): Would the target audience find this genuinely interesting/useful/entertaining?
- Timeliness (0-25): Is the timing hook compelling? Does the evidence support "why now"?
- Brand fit (0-25): Does it align with positioning and pillars without feeling like an ad?

CRITICAL: If CTA policy is "none" or "soft", penalize opportunities that feel sales-forward or have implicit CTAs.
Band: invalid=0 (taboo or wrong CTA tone), weak=1-64, strong=65-100."""

SCORING_USER_PROMPT = """Score these opportunities:

{opportunities_summary}

Output: {{"scores":[{{"idx":0,"score":75,"band":"strong","is_valid":true}},...]}}"""


# =============================================================================
# PIPELINE STAGES
# =============================================================================


def _generate_single_kernel(
    evidence_idx: int,
    evidence_item: "EvidenceItemData",
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
) -> OpportunityKernel | None:
    """
    Generate a single opportunity kernel from one evidence item.

    This is called in parallel for all evidence items.
    Returns None on failure (tolerant - doesn't crash pipeline).
    """
    try:
        # Truncate text to cap prompt size
        text_snippet = (evidence_item.text_primary or "")[:500]
        if evidence_item.text_secondary:
            text_snippet += f"\n[Transcript]: {evidence_item.text_secondary[:300]}"

        system_prompt = KERNEL_SYSTEM_PROMPT.format(
            brand_name=brand_snapshot.brand_name,
            positioning=(brand_snapshot.positioning or "Not specified")[:200],
            taboos=", ".join(brand_snapshot.taboos[:5]) or "None",
        )

        user_prompt = KERNEL_USER_PROMPT.format(
            platform=evidence_item.platform,
            author=evidence_item.author_ref or "Unknown",
            text_snippet=text_snippet,
            evidence_idx=evidence_idx,
        )

        response = llm_client.call(
            brand_id=brand_snapshot.brand_id,
            flow="F1_kernel_generation",
            prompt=user_prompt,
            role="fast",  # gpt-5-nano - fast and cheap
            system_prompt=system_prompt,
            run_id=run_id,
            trigger_source="pipeline",
            max_output_tokens=256,  # Very small output
        )

        result = parse_structured_output(response.raw_text, KernelGenerationOutput)
        kernel = result.kernel

        # Post-process: If evidence is from TikTok/Instagram with high engagement,
        # prefer that platform for trend-driven content
        evidence_platform = evidence_item.platform.lower()
        if evidence_platform in ("tiktok", "instagram"):
            # Check if this looks like trend content (type=trend or high view count)
            is_trendy = kernel.type == "trend" or (evidence_item.view_count and evidence_item.view_count > 10000)
            if is_trendy and kernel.primary_channel in ("linkedin", "x"):
                # Override to match evidence platform for trend content
                kernel.primary_channel = evidence_platform
                logger.debug(
                    "Overrode channel to %s for trendy evidence from %s",
                    evidence_platform,
                    evidence_platform,
                )

        return kernel

    except (LLMCallError, StructuredOutputError) as e:
        logger.warning(
            f"Kernel generation failed for evidence {evidence_idx}: {e}",
            extra={"run_id": str(run_id), "evidence_idx": evidence_idx},
        )
        return None


def stage1_generate_kernels(
    evidence_items: list["EvidenceItemData"],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
    timings: PipelineTimings,
    max_parallel: int = 8,
) -> list[OpportunityKernel]:
    """
    Stage 1: Generate opportunity kernels in parallel.

    Runs up to max_parallel LLM calls concurrently.
    Tolerant - individual failures don't crash the stage.
    """
    start_time = time.perf_counter()
    kernels: list[OpportunityKernel] = []

    # Cap evidence items to avoid too many calls
    items_to_process = evidence_items[:12]
    timings.kernel_calls_parallel = min(len(items_to_process), max_parallel)

    logger.info(
        f"Stage 1: Generating kernels for {len(items_to_process)} evidence items (parallel={max_parallel})",
        extra={"run_id": str(run_id)},
    )

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(
                _generate_single_kernel,
                idx,
                item,
                brand_snapshot,
                llm_client,
                run_id,
            ): idx
            for idx, item in enumerate(items_to_process)
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                kernel = future.result()
                if kernel:
                    kernels.append(kernel)
                    timings.kernel_call_count += 1
            except Exception as e:
                logger.warning(f"Kernel future failed: {e}", extra={"run_id": str(run_id)})

    timings.kernel_generation_ms = int((time.perf_counter() - start_time) * 1000)

    logger.info(
        f"Stage 1 complete: {len(kernels)} kernels in {timings.kernel_generation_ms}ms",
        extra={"run_id": str(run_id)},
    )

    return kernels


def stage2_consolidate_kernels(
    kernels: list[OpportunityKernel],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
    timings: PipelineTimings,
) -> list[OpportunityKernel]:
    """
    Stage 2: Consolidate and deduplicate kernels.

    Uses fast model to select 5-8 best kernels.
    """
    start_time = time.perf_counter()

    if len(kernels) <= 5:
        # No consolidation needed
        timings.kernel_consolidation_ms = int((time.perf_counter() - start_time) * 1000)
        return kernels

    logger.info(
        f"Stage 2: Consolidating {len(kernels)} kernels",
        extra={"run_id": str(run_id)},
    )

    # Build kernels JSON
    kernels_json = [
        {
            "idx": i,
            "core_idea": k.core_idea,
            "type": k.type,
            "timing_hook": k.timing_hook,
            "confidence": k.confidence,
        }
        for i, k in enumerate(kernels)
    ]

    system_prompt = CONSOLIDATION_SYSTEM_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
    )

    user_prompt = CONSOLIDATION_USER_PROMPT.format(
        kernels_json=str(kernels_json),
    )

    try:
        response = llm_client.call(
            brand_id=brand_snapshot.brand_id,
            flow="F1_kernel_consolidation",
            prompt=user_prompt,
            role="fast",
            system_prompt=system_prompt,
            run_id=run_id,
            trigger_source="pipeline",
            max_output_tokens=512,
        )

        result = parse_structured_output(response.raw_text, KernelConsolidationOutput)
        consolidated = result.kernels

    except (LLMCallError, StructuredOutputError) as e:
        logger.warning(
            f"Consolidation failed, using top kernels by confidence: {e}",
            extra={"run_id": str(run_id)},
        )
        # Fallback: just take top 6 by confidence
        consolidated = sorted(kernels, key=lambda k: k.confidence, reverse=True)[:6]

    timings.kernel_consolidation_ms = int((time.perf_counter() - start_time) * 1000)

    logger.info(
        f"Stage 2 complete: {len(consolidated)} kernels in {timings.kernel_consolidation_ms}ms",
        extra={"run_id": str(run_id)},
    )

    return consolidated


def _expand_single_kernel(
    kernel: OpportunityKernel,
    evidence_items: list["EvidenceItemData"],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
) -> ExpandedOpportunity | None:
    """
    Expand a single kernel into a full opportunity with rich prose.

    This is the expensive stage - uses heavier model.
    """
    import json
    import re

    try:
        # Build evidence context from linked items
        evidence_text = ""
        for idx in kernel.evidence_indices[:3]:  # Max 3 evidence items
            if 0 <= idx < len(evidence_items):
                item = evidence_items[idx]
                evidence_text += f"- [{item.platform}] {(item.text_primary or '')[:400]}\n"

        if not evidence_text:
            evidence_text = "No specific evidence linked."

        # Compact snapshot info
        pillars = ", ".join(p.name for p in brand_snapshot.pillars[:3]) or "None"
        tone = ", ".join(brand_snapshot.voice_tone_tags[:4]) or "professional"
        cta_policy = brand_snapshot.cta_policy or "soft"
        content_goal = brand_snapshot.content_goal or "Build brand awareness and engagement"
        primary_channel = kernel.primary_channel.lower() if kernel.primary_channel else "tiktok"

        system_prompt = EXPANSION_SYSTEM_PROMPT.format(
            brand_name=brand_snapshot.brand_name,
            positioning=(brand_snapshot.positioning or "Not specified")[:300],
            tone_tags=tone,
            pillars=pillars,
            content_goal=content_goal,
            cta_policy=cta_policy,
            primary_channel=primary_channel,
        )

        kernel_json = {
            "core_idea": kernel.core_idea,
            "type": kernel.type,
            "primary_channel": kernel.primary_channel,
            "timing_hook": kernel.timing_hook,
        }

        user_prompt = EXPANSION_USER_PROMPT.format(
            kernel_json=str(kernel_json),
            evidence_text=evidence_text,
            cta_policy=cta_policy,
        )

        response = llm_client.call(
            brand_id=brand_snapshot.brand_id,
            flow="F1_explanation_expansion",
            prompt=user_prompt,
            role="heavy",  # Use heavier model for quality prose
            system_prompt=system_prompt,
            run_id=run_id,
            trigger_source="pipeline",
            max_output_tokens=1024,  # Enough for rich explanation
        )

        # Try to parse, with fallback to fill in missing fields from kernel
        raw_text = response.raw_text.strip()

        # Handle markdown code fences
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        match = re.search(fence_pattern, raw_text)
        if match:
            raw_text = match.group(1).strip()

        try:
            parsed = json.loads(raw_text)
            opp_data = parsed.get("opportunity", parsed)

            # Fill in missing fields from kernel
            if "type" not in opp_data or not opp_data["type"]:
                opp_data["type"] = kernel.type
            if "primary_channel" not in opp_data or not opp_data["primary_channel"]:
                opp_data["primary_channel"] = kernel.primary_channel
            if "suggested_channels" not in opp_data or not opp_data["suggested_channels"]:
                # Default to kernel's primary_channel + complementary channels
                primary = kernel.primary_channel.lower() if kernel.primary_channel else "linkedin"
                if primary in ("tiktok", "instagram"):
                    opp_data["suggested_channels"] = [primary, "instagram" if primary == "tiktok" else "tiktok", "x"]
                else:
                    opp_data["suggested_channels"] = [primary, "x", "linkedin"]

            # Validate with filled data
            return ExpandedOpportunity.model_validate(opp_data)

        except (json.JSONDecodeError, Exception) as parse_err:
            logger.warning(
                f"Expansion parse failed, trying direct: {parse_err}",
                extra={"run_id": str(run_id)},
            )
            # Fall through to original parse attempt
            result = parse_structured_output(response.raw_text, ExpansionOutput)
            return result.opportunity

    except (LLMCallError, StructuredOutputError) as e:
        logger.warning(
            f"Expansion failed for kernel: {e}",
            extra={"run_id": str(run_id), "core_idea": kernel.core_idea[:50]},
        )
        return None


def _expand_with_timeout(
    kernel: OpportunityKernel,
    evidence_items: list["EvidenceItemData"],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
    timeout_seconds: float,
) -> tuple[ExpandedOpportunity | None, str]:
    """
    Expand a single kernel with a hard timeout.

    Returns (opportunity, status) where status is one of:
    - "success": expansion succeeded
    - "timeout": expansion exceeded timeout
    - "failure": expansion failed (LLM error, parse error, etc.)
    """
    import signal
    import threading

    result: list[ExpandedOpportunity | None] = [None]
    error: list[str] = [""]

    def expand_task():
        try:
            result[0] = _expand_single_kernel(
                kernel=kernel,
                evidence_items=evidence_items,
                brand_snapshot=brand_snapshot,
                llm_client=llm_client,
                run_id=run_id,
            )
            if result[0]:
                error[0] = "success"
            else:
                error[0] = "failure"
        except Exception as e:
            error[0] = f"failure: {e}"
            result[0] = None

    # Run expansion in a thread with timeout
    thread = threading.Thread(target=expand_task)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # Thread is still running - timeout exceeded
        # We can't kill the thread, but we move on
        logger.warning(
            f"Expansion timeout ({timeout_seconds}s) for kernel, moving on",
            extra={"run_id": str(run_id), "core_idea": kernel.core_idea[:50]},
        )
        return None, "timeout"

    return result[0], error[0] if error[0] else "failure"


def stage3_expand_kernels(
    kernels: list[OpportunityKernel],
    evidence_items: list["EvidenceItemData"],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
    timings: PipelineTimings,
) -> list[ExpandedOpportunity]:
    """
    Stage 3: Expand kernels into full opportunities with rich prose.

    OPPORTUNITY-ATOMIC DESIGN:
    - Each expansion is independent with a hard timeout (EXPANSION_TIMEOUT_SECONDS)
    - No retries - if one fails, move to the next
    - Stop early once we have enough (MIN_READY_OPPS)
    - This prevents one slow LLM call from blocking the entire pipeline

    Returns partial results - even 3 successful expansions is a valid outcome.
    """
    start_time = time.perf_counter()
    expanded: list[ExpandedOpportunity] = []

    # Cap kernels to expand
    kernels_to_expand = kernels[:MAX_EXPANSION_ATTEMPTS]
    timings.expansion_attempts = len(kernels_to_expand)

    logger.info(
        f"Stage 3: Expanding {len(kernels_to_expand)} kernels (min_required={MIN_READY_OPPS}, timeout={EXPANSION_TIMEOUT_SECONDS}s each)",
        extra={"run_id": str(run_id)},
    )

    for i, kernel in enumerate(kernels_to_expand):
        expansion_start = time.perf_counter()

        opp, status = _expand_with_timeout(
            kernel=kernel,
            evidence_items=evidence_items,
            brand_snapshot=brand_snapshot,
            llm_client=llm_client,
            run_id=run_id,
            timeout_seconds=EXPANSION_TIMEOUT_SECONDS,
        )

        expansion_ms = int((time.perf_counter() - expansion_start) * 1000)

        if status == "success" and opp:
            expanded.append(opp)
            timings.expansion_successes += 1
            timings.expansion_call_count += 1
            logger.info(
                f"Stage 3: Expansion {i+1}/{len(kernels_to_expand)} succeeded ({expansion_ms}ms) - total: {len(expanded)}",
                extra={"run_id": str(run_id)},
            )
        elif status == "timeout":
            timings.expansion_timeouts += 1
            logger.warning(
                f"Stage 3: Expansion {i+1}/{len(kernels_to_expand)} timed out ({expansion_ms}ms)",
                extra={"run_id": str(run_id)},
            )
        else:
            timings.expansion_failures += 1
            logger.warning(
                f"Stage 3: Expansion {i+1}/{len(kernels_to_expand)} failed ({expansion_ms}ms): {status}",
                extra={"run_id": str(run_id)},
            )

        # Check if we have enough - can exit early!
        # But keep going a bit more if we have time to get better diversity
        remaining = len(kernels_to_expand) - (i + 1)
        if len(expanded) >= MIN_READY_OPPS and remaining <= 2:
            logger.info(
                f"Stage 3: Early exit - have {len(expanded)} opportunities (min={MIN_READY_OPPS}), only {remaining} remaining",
                extra={"run_id": str(run_id)},
            )
            break

    timings.explanation_expansion_ms = int((time.perf_counter() - start_time) * 1000)

    logger.info(
        f"Stage 3 complete: {len(expanded)}/{timings.expansion_attempts} succeeded "
        f"(timeouts={timings.expansion_timeouts}, failures={timings.expansion_failures}) "
        f"in {timings.explanation_expansion_ms}ms",
        extra={"run_id": str(run_id)},
    )

    return expanded


def stage4_score_opportunities(
    opportunities: list[ExpandedOpportunity],
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient,
    run_id: UUID,
    timings: PipelineTimings,
) -> list[tuple[ExpandedOpportunity, int, bool, str | None]]:
    """
    Stage 4: Score and validate opportunities.

    Returns list of (opportunity, score, is_valid, rejection_reason).
    """
    start_time = time.perf_counter()

    logger.info(
        f"Stage 4: Scoring {len(opportunities)} opportunities",
        extra={"run_id": str(run_id)},
    )

    # Build compact summary for scoring
    opps_summary = "\n".join(
        f"{i}. [{o.type}] {o.title} ({o.primary_channel})"
        for i, o in enumerate(opportunities)
    )

    system_prompt = SCORING_SYSTEM_PROMPT.format(
        brand_name=brand_snapshot.brand_name,
        taboos=", ".join(brand_snapshot.taboos[:5]) or "None",
        cta_policy=brand_snapshot.cta_policy or "soft",
    )

    user_prompt = SCORING_USER_PROMPT.format(
        opportunities_summary=opps_summary,
    )

    try:
        response = llm_client.call(
            brand_id=brand_snapshot.brand_id,
            flow="F1_scoring",
            prompt=user_prompt,
            role="fast",
            system_prompt=system_prompt,
            run_id=run_id,
            trigger_source="pipeline",
            max_output_tokens=512,
        )

        result = parse_structured_output(response.raw_text, ScoringOutput)

        # Build lookup
        scores_by_idx = {s.idx: s for s in result.scores}

        scored = []
        for i, opp in enumerate(opportunities):
            scoring = scores_by_idx.get(i)
            if scoring:
                scored.append((opp, scoring.score, scoring.is_valid, scoring.rejection_reason))
            else:
                # Default to weak if not scored
                scored.append((opp, 50, True, None))

    except (LLMCallError, StructuredOutputError) as e:
        logger.warning(
            f"Scoring failed, using default scores: {e}",
            extra={"run_id": str(run_id)},
        )
        # Fallback: all get default score
        scored = [(opp, 70, True, None) for opp in opportunities]

    timings.scoring_ms = int((time.perf_counter() - start_time) * 1000)

    logger.info(
        f"Stage 4 complete: {len(scored)} scored in {timings.scoring_ms}ms",
        extra={"run_id": str(run_id)},
    )

    return scored


# =============================================================================
# MAIN PIPELINE ENTRYPOINT
# =============================================================================


def run_synthesis_pipeline(
    run_id: UUID,
    brand_snapshot: BrandSnapshotDTO,
    evidence_items: list["EvidenceItemData"],
    llm_client: LLMClient | None = None,
) -> tuple[list[OpportunityDraftDTO], PipelineTimings]:
    """
    Run the multi-stage synthesis pipeline.

    Replaces graph_hero_generate_opportunities with a faster, more observable pipeline.

    CRITICAL: OPPORTUNITY-ATOMIC DESIGN
    - Stage 3 (expansion) runs each opportunity independently
    - Hard timeout per expansion (20s), no retries
    - Pipeline succeeds if MIN_READY_OPPS (3) opportunities are created
    - Partial results are valid - prevents total failure from one slow call

    Stages:
    1. Kernel Generation (parallel, fast) - ~5-10s for 8 items
    2. Kernel Consolidation (fast) - ~1-2s
    3. Explanation Expansion (heavy, opportunity-atomic) - bounded by timeout
    4. Scoring (fast) - ~2-3s

    Total target: < 60s typical, bounded worst-case

    Args:
        run_id: UUID for correlation
        brand_snapshot: Brand context
        evidence_items: Evidence from SourceActivation
        llm_client: Optional LLM client

    Returns:
        Tuple of (list[OpportunityDraftDTO], PipelineTimings)
        - If len(drafts) >= MIN_READY_OPPS, this is a success
        - If 0 < len(drafts) < MIN_READY_OPPS, this is partial failure
        - If len(drafts) == 0, this is total failure
    """
    pipeline_start = time.perf_counter()
    timings = PipelineTimings()
    client = llm_client or get_default_client()

    logger.info(
        "=== STARTING SYNTHESIS PIPELINE ===",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "evidence_count": len(evidence_items),
        },
    )

    # Stage 1: Generate kernels in parallel
    kernels = stage1_generate_kernels(
        evidence_items=evidence_items,
        brand_snapshot=brand_snapshot,
        llm_client=client,
        run_id=run_id,
        timings=timings,
    )

    if not kernels:
        logger.warning("No kernels generated, returning empty", extra={"run_id": str(run_id)})
        timings.total_ms = int((time.perf_counter() - pipeline_start) * 1000)
        return [], timings

    # Stage 2: Consolidate kernels
    consolidated_kernels = stage2_consolidate_kernels(
        kernels=kernels,
        brand_snapshot=brand_snapshot,
        llm_client=client,
        run_id=run_id,
        timings=timings,
    )

    # Stage 3: Expand into full opportunities
    expanded = stage3_expand_kernels(
        kernels=consolidated_kernels,
        evidence_items=evidence_items,
        brand_snapshot=brand_snapshot,
        llm_client=client,
        run_id=run_id,
        timings=timings,
    )

    if not expanded:
        logger.warning("No expansions succeeded, returning empty", extra={"run_id": str(run_id)})
        timings.total_ms = int((time.perf_counter() - pipeline_start) * 1000)
        return [], timings

    # Stage 4: Score
    scored = stage4_score_opportunities(
        opportunities=expanded,
        brand_snapshot=brand_snapshot,
        llm_client=client,
        run_id=run_id,
        timings=timings,
    )

    # Convert to OpportunityDraftDTO
    drafts = _convert_to_drafts(scored)

    # Sort by score descending
    drafts.sort(key=lambda d: d.score, reverse=True)

    timings.total_ms = int((time.perf_counter() - pipeline_start) * 1000)

    # Determine success status
    if len(drafts) >= MIN_READY_OPPS:
        status = "success"
    elif len(drafts) > 0:
        status = "partial"
    else:
        status = "failure"

    logger.info(
        f"=== SYNTHESIS PIPELINE COMPLETE ({status}) ===",
        extra={
            "run_id": str(run_id),
            "brand_id": str(brand_snapshot.brand_id),
            "final_count": len(drafts),
            "min_required": MIN_READY_OPPS,
            "status": status,
            "timings": timings.to_dict(),
        },
    )

    return drafts, timings


def _convert_to_drafts(
    scored: list[tuple[ExpandedOpportunity, int, bool, str | None]],
) -> list[OpportunityDraftDTO]:
    """Convert scored opportunities to OpportunityDraftDTO."""

    type_map = {
        "trend": OpportunityType.TREND,
        "evergreen": OpportunityType.EVERGREEN,
        "competitive": OpportunityType.COMPETITIVE,
        "campaign": OpportunityType.CAMPAIGN,
    }

    channel_map = {
        "linkedin": Channel.LINKEDIN,
        "x": Channel.X,
        "instagram": Channel.INSTAGRAM,
        "tiktok": Channel.TIKTOK,
    }

    drafts = []
    for opp, score, is_valid, rejection_reason in scored:
        opp_type = type_map.get(opp.type.lower(), OpportunityType.EVERGREEN)
        # Map channel - default to LinkedIn only if truly unknown
        primary_channel = channel_map.get(opp.primary_channel.lower(), Channel.LINKEDIN)

        suggested_channels = []
        for ch in opp.suggested_channels:
            mapped = channel_map.get(ch.lower())
            if mapped:
                suggested_channels.append(mapped)
        if not suggested_channels:
            # Include all platforms in suggested channels
            suggested_channels = [Channel.LINKEDIN, Channel.X, Channel.INSTAGRAM, Channel.TIKTOK]

        rejection_reasons = [rejection_reason] if rejection_reason else []

        draft = OpportunityDraftDTO(
            proposed_title=opp.title,
            proposed_angle=opp.angle,
            type=opp_type,
            primary_channel=primary_channel,
            suggested_channels=suggested_channels,
            score=float(score) if is_valid else 0.0,
            score_explanation="",
            source="synthesis_pipeline",
            source_url=None,
            persona_hint=opp.persona_hint,
            pillar_hint=opp.pillar_hint,
            raw_reasoning=None,
            is_valid=is_valid,
            rejection_reasons=rejection_reasons,
            why_now=opp.why_now,
        )
        drafts.append(draft)

    return drafts
