"""
Opportunities Generation Task.

PR1: Evidence gates only, NO LLM synthesis.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

CRITICAL INVARIANTS (PR1):
1. NO LLM calls
2. NO prompt execution
3. NO synthesis
4. NO fake/stub opportunities

This task:
1. Fetches evidence from NormalizedEvidenceItem
2. Runs quality gates
3. Runs usability gates
4. Creates OpportunitiesBoard with terminal state
5. Marks job complete

If gates pass:
- State = READY (but with 0 opportunities in PR1)
- Later PRs will add synthesis

If gates fail:
- State = INSUFFICIENT_EVIDENCE
- No retry (evidence won't improve without user action)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger("kairo.hero.tasks.generate")


@dataclass
class JobResult:
    """Result of job execution."""
    success: bool = False
    insufficient_evidence: bool = False
    error: str | None = None
    board_id: UUID | None = None
    diagnostics: dict = field(default_factory=dict)


def execute_opportunities_job(
    job_id: UUID,
    brand_id: UUID,
) -> JobResult:
    """
    Execute an opportunities generation job.

    PR1: Evidence gates ONLY. No LLM synthesis.

    Pipeline:
    1. Fetch evidence from NormalizedEvidenceItem
    2. Run quality gates
    3. Run usability gates
    4. Create OpportunitiesBoard
    5. Mark job complete

    Args:
        job_id: UUID of the OpportunitiesJob
        brand_id: UUID of the brand

    Returns:
        JobResult with outcome details
    """
    from django.core.cache import cache

    from kairo.core.enums import TodayBoardState
    from kairo.hero.jobs.queue import (
        complete_job,
        fail_job,
        fail_job_insufficient_evidence,
    )
    from kairo.hero.models import OpportunitiesBoard
    from kairo.hero.services.evidence_quality import (
        MIN_EVIDENCE_ITEMS,
        MIN_TRANSCRIPT_COVERAGE,
        REQUIRED_PLATFORMS,
        validate_evidence_for_synthesis,
    )
    from kairo.hero.services.evidence_service import get_evidence_for_brand

    start_time = time.monotonic()
    diagnostics: dict = {
        "job_id": str(job_id),
        "brand_id": str(brand_id),
        "started_at": time.time(),
    }

    try:
        # Step 1: Fetch evidence
        logger.info(
            "Fetching evidence for brand %s (job=%s)",
            brand_id,
            job_id,
        )
        evidence_start = time.monotonic()
        evidence_result = get_evidence_for_brand(brand_id)
        evidence_time_ms = int((time.monotonic() - evidence_start) * 1000)

        diagnostics["evidence_fetch_ms"] = evidence_time_ms
        diagnostics["evidence_count"] = len(evidence_result.evidence)
        diagnostics["evidence_summary"] = {
            "total_items": evidence_result.summary.total_items,
            "platforms": evidence_result.summary.platforms,
            "items_with_text": evidence_result.summary.items_with_text,
            "items_with_transcript": evidence_result.summary.items_with_transcript,
            "transcript_coverage": evidence_result.summary.transcript_coverage,
        }

        logger.info(
            "Loaded %d evidence items for brand %s in %dms",
            len(evidence_result.evidence),
            brand_id,
            evidence_time_ms,
        )

        # Step 2: Run gates
        logger.info(
            "Running evidence gates for brand %s (job=%s)",
            brand_id,
            job_id,
        )
        gate_start = time.monotonic()
        validation_result = validate_evidence_for_synthesis(evidence_result.evidence)
        gate_time_ms = int((time.monotonic() - gate_start) * 1000)

        diagnostics["gate_time_ms"] = gate_time_ms
        diagnostics["gates_passed"] = validation_result.can_proceed
        diagnostics["gate_diagnostics"] = validation_result.diagnostics

        # Step 3: Handle gate failure
        if not validation_result.can_proceed:
            logger.info(
                "Evidence gates FAILED for brand %s (job=%s): %s",
                brand_id,
                job_id,
                validation_result.failure_reason,
            )

            # Build shortfall from diagnostics
            shortfall_data = validation_result.diagnostics.get("shortfall", {})
            evidence_shortfall = {
                "required_items": shortfall_data.get("required_items", MIN_EVIDENCE_ITEMS),
                "found_items": shortfall_data.get("found_items", 0),
                "required_platforms": shortfall_data.get("required_platforms", list(REQUIRED_PLATFORMS)),
                "found_platforms": shortfall_data.get("found_platforms", []),
                "missing_platforms": shortfall_data.get("missing_platforms", []),
                "transcript_coverage": shortfall_data.get("transcript_coverage", 0.0),
                "min_transcript_coverage": shortfall_data.get("min_transcript_coverage", MIN_TRANSCRIPT_COVERAGE),
                "failures": shortfall_data.get("failures", []) + validation_result.diagnostics.get("failures", []),
            }

            # Create board with insufficient_evidence state
            board = OpportunitiesBoard.objects.create(
                brand_id=brand_id,
                state=TodayBoardState.INSUFFICIENT_EVIDENCE,
                opportunity_ids=[],
                evidence_summary_json=diagnostics.get("evidence_summary", {}),
                evidence_shortfall_json=evidence_shortfall,
                remediation="Connect Instagram or TikTok sources in Settings, then run BrandBrain compile.",
                diagnostics_json=diagnostics,
            )

            diagnostics["board_id"] = str(board.id)
            diagnostics["terminal_state"] = TodayBoardState.INSUFFICIENT_EVIDENCE

            # Mark job as insufficient_evidence
            fail_job_insufficient_evidence(
                job_id,
                board_id=board.id,
                result_json=diagnostics,
            )

            # Invalidate cache to ensure next GET reads from DB
            _invalidate_cache(brand_id)

            total_time_ms = int((time.monotonic() - start_time) * 1000)
            diagnostics["total_time_ms"] = total_time_ms

            return JobResult(
                success=False,
                insufficient_evidence=True,
                board_id=board.id,
                diagnostics=diagnostics,
            )

        # Step 4: Gates passed - create READY board
        # PR1: No synthesis, so 0 opportunities
        # PR1.1: MUST set ready_reason when state=ready AND opportunities=[]
        logger.info(
            "Evidence gates PASSED for brand %s (job=%s) - PR1: no synthesis",
            brand_id,
            job_id,
        )

        from kairo.hero.dto import ReadyReason

        board = OpportunitiesBoard.objects.create(
            brand_id=brand_id,
            state=TodayBoardState.READY,
            ready_reason=ReadyReason.GATES_ONLY_NO_SYNTHESIS,  # PR1.1: explicit reason
            opportunity_ids=[],  # PR1: No opportunities yet
            evidence_summary_json=diagnostics.get("evidence_summary", {}),
            evidence_shortfall_json={},
            remediation=None,
            diagnostics_json=diagnostics,
        )

        diagnostics["board_id"] = str(board.id)
        diagnostics["terminal_state"] = TodayBoardState.READY
        diagnostics["notes"] = ["PR1: Evidence gates passed, synthesis not implemented"]

        # Mark job as succeeded
        complete_job(
            job_id,
            board_id=board.id,
            result_json=diagnostics,
        )

        # Populate cache with board
        _populate_cache(brand_id, board)

        total_time_ms = int((time.monotonic() - start_time) * 1000)
        diagnostics["total_time_ms"] = total_time_ms

        return JobResult(
            success=True,
            board_id=board.id,
            diagnostics=diagnostics,
        )

    except Exception as e:
        error_msg = str(e)
        logger.exception(
            "Job %s failed with exception: %s",
            job_id,
            error_msg,
        )

        diagnostics["error"] = error_msg
        diagnostics["total_time_ms"] = int((time.monotonic() - start_time) * 1000)

        # Mark job as failed (will retry if attempts < max)
        fail_job(job_id, error_msg)

        return JobResult(
            success=False,
            error=error_msg,
            diagnostics=diagnostics,
        )


def _invalidate_cache(brand_id: UUID) -> None:
    """Invalidate cache for a brand's today board."""
    from django.core.cache import cache

    cache_key = f"today_board:v2:{brand_id}"
    cache.delete(cache_key)
    logger.debug("Invalidated cache for brand %s", brand_id)


def _populate_cache(brand_id: UUID, board: "OpportunitiesBoard") -> None:
    """Populate cache with a board."""
    from django.core.cache import cache

    # Get cache TTL from environment or use default
    import os
    cache_ttl = int(os.environ.get("OPPORTUNITIES_CACHE_TTL_S", "21600"))  # 6 hours

    cache_key = f"today_board:v2:{brand_id}"
    try:
        dto = board.to_dto()
        dto.meta.cache_hit = False
        dto.meta.cache_key = cache_key
        cache.set(cache_key, dto.model_dump_json(), timeout=cache_ttl)
        logger.debug("Populated cache for brand %s", brand_id)
    except Exception as e:
        logger.warning(
            "Failed to populate cache for brand %s: %s",
            brand_id,
            str(e),
        )
