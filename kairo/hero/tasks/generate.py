"""
Opportunities Generation Task.

PR1b: Background job runs full synthesis pipeline.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

CRITICAL INVARIANTS:
1. GET /today NEVER calls this directly (guardrail enforced at engine level)
2. All synthesis happens in background jobs only
3. Engine handles LLM calls, this task orchestrates the job lifecycle

This task:
1. Runs SourceActivation (creates ActivationRun + EvidenceItem rows)
2. Runs quality gates against the EvidenceBundle
3. If gates pass: calls opportunities_engine for synthesis
4. Persists board (engine handles this)
5. Marks job complete

Per PRD contract (Patch B compliance):
- Evidence does NOT exist until SourceActivation creates it
- Gates run against EvidenceBundle from SourceActivation
- ActivationRun + EvidenceItem are persisted even if gates fail
- NormalizedEvidenceItem is NOT used (PRD §B.0.3 forbidden term)

If gates pass:
- Calls engine for full synthesis
- Engine persists opportunities and board
- State = READY with opportunities

If gates fail:
- State = INSUFFICIENT_EVIDENCE
- No retry (evidence won't improve without user action)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
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
    mode: str | None = None,
    user_id: UUID | None = None,
) -> JobResult:
    """
    Execute an opportunities generation job.

    PR1: Evidence gates + LLM synthesis.
    PR-6: Mode selection for fixture_only vs live_cap_limited.
    Patch B: SourceActivation runs FIRST, gates run against EvidenceBundle.
    Phase 2 BYOK: If user_id is provided, uses user's API keys for external services.

    Pipeline:
    1. Run SourceActivation → EvidenceBundle (creates ActivationRun + EvidenceItem rows)
    2. Run quality gates against EvidenceBundle
    3. Run usability gates against EvidenceBundle
    4. If gates pass: Run synthesis via engine (uses same evidence)
    5. Create OpportunitiesBoard
    6. Mark job complete

    Args:
        job_id: UUID of the OpportunitiesJob
        brand_id: UUID of the brand
        mode: SourceActivation mode (if None, reads from job.params_json)
        user_id: Optional user UUID for BYOK token lookup (if None, reads from job.params_json)

    Returns:
        JobResult with outcome details
    """
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
        get_actionable_remediation,
    )
    from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

    start_time = time.monotonic()

    # PR-6: Get mode from params or use default
    # Phase 2 BYOK: Also extract user_id from params
    if mode is None or user_id is None:
        from kairo.hero.models import OpportunitiesJob
        try:
            job = OpportunitiesJob.objects.get(id=job_id)
            job_params = job.params_json or {}
            if mode is None:
                mode = job_params.get("mode", "fixture_only")
            if user_id is None:
                user_id_str = job_params.get("user_id")
                if user_id_str:
                    user_id = UUID(user_id_str)
        except OpportunitiesJob.DoesNotExist:
            mode = mode or "fixture_only"

    diagnostics: dict = {
        "job_id": str(job_id),
        "brand_id": str(brand_id),
        "started_at": time.time(),
        "mode": mode,  # PR-6: Track mode in diagnostics
    }

    try:
        # Phase 3: Import progress tracking
        from kairo.hero.jobs.queue import update_job_progress
        from kairo.hero.models.opportunities_job import ProgressStage

        # Step 1: Run SourceActivation - creates ActivationRun + EvidenceItem rows
        # Per PRD: Evidence does NOT exist until SourceActivation creates it
        logger.info(
            "Running SourceActivation for brand %s (job=%s, mode=%s)",
            brand_id,
            job_id,
            mode,
        )

        # Phase 3: Update progress - fetching evidence
        update_job_progress(
            job_id,
            ProgressStage.FETCHING_EVIDENCE,
            "Collecting content from social platforms...",
        )

        activation_start = time.monotonic()

        seed_pack = derive_seed_pack(brand_id)
        evidence_bundle = get_or_create_evidence_bundle(
            brand_id=brand_id,
            seed_pack=seed_pack,
            job_id=job_id,
            mode=mode,
            user_id=user_id,  # Phase 2 BYOK
        )

        activation_time_ms = int((time.monotonic() - activation_start) * 1000)

        # Build evidence summary from bundle
        platforms_dict: dict[str, int] = {}
        items_with_text = 0
        items_with_transcript = 0
        for item in evidence_bundle.items:
            platforms_dict[item.platform] = platforms_dict.get(item.platform, 0) + 1
            if item.text_primary and item.text_primary.strip():
                items_with_text += 1
            if item.has_transcript or (item.text_secondary and item.text_secondary.strip()):
                items_with_transcript += 1

        transcript_coverage = items_with_transcript / len(evidence_bundle.items) if evidence_bundle.items else 0.0

        diagnostics["activation_time_ms"] = activation_time_ms
        diagnostics["activation_run_id"] = str(evidence_bundle.activation_run_id) if evidence_bundle.activation_run_id else None
        diagnostics["evidence_count"] = len(evidence_bundle.items)
        diagnostics["evidence_summary"] = {
            "total_items": len(evidence_bundle.items),
            "platforms": platforms_dict,
            "items_with_text": items_with_text,
            "items_with_transcript": items_with_transcript,
            "transcript_coverage": transcript_coverage,
        }

        logger.info(
            "SourceActivation completed: %d items, ActivationRun=%s in %dms",
            len(evidence_bundle.items),
            evidence_bundle.activation_run_id,
            activation_time_ms,
        )

        # Step 2: Run gates against EvidenceBundle
        # Convert EvidenceItemData to gate-compatible format
        logger.info(
            "Running evidence gates for brand %s (job=%s)",
            brand_id,
            job_id,
        )

        # Phase 3: Update progress - running quality gates
        update_job_progress(
            job_id,
            ProgressStage.RUNNING_QUALITY_GATES,
            f"Validating {len(evidence_bundle.items)} evidence items...",
        )

        gate_start = time.monotonic()

        gate_items = _convert_bundle_to_gate_items(evidence_bundle)
        validation_result = _validate_evidence_bundle(gate_items)

        gate_time_ms = int((time.monotonic() - gate_start) * 1000)

        diagnostics["gate_time_ms"] = gate_time_ms
        diagnostics["gates_passed"] = validation_result.can_proceed
        diagnostics["gate_diagnostics"] = validation_result.diagnostics

        # Log detailed gate boundary summary (for both fixture_only and live modes)
        _log_gate_boundary_summary(
            brand_id=brand_id,
            job_id=job_id,
            mode=mode,
            recipes_executed=evidence_bundle.recipes_executed,
            evidence_summary=diagnostics.get("evidence_summary", {}),
            validation_result=validation_result,
        )

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

            # Generate actionable remediation message based on specific failures
            failures = evidence_shortfall.get("failures", [])
            summary = diagnostics.get("evidence_summary", {})
            actionable_remediation = get_actionable_remediation(failures, summary)

            # Create board with insufficient_evidence state
            board = OpportunitiesBoard.objects.create(
                brand_id=brand_id,
                state=TodayBoardState.INSUFFICIENT_EVIDENCE,
                opportunity_ids=[],
                evidence_summary_json=diagnostics.get("evidence_summary", {}),
                evidence_shortfall_json=evidence_shortfall,
                remediation=actionable_remediation,
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

        # Step 4: Gates passed - run full synthesis via engine
        # PR1b: Background job calls engine for synthesis
        logger.info(
            "Evidence gates PASSED for brand %s (job=%s) - running synthesis",
            brand_id,
            job_id,
        )

        # Phase 3: Update progress - synthesizing opportunities
        update_job_progress(
            job_id,
            ProgressStage.SYNTHESIZING,
            "Generating opportunities with AI...",
        )

        # Call the opportunities engine to run full synthesis
        # Engine handles: snapshot building, graph call, opportunity persistence, board creation
        # PR-6: Pass mode for SourceActivation execution
        # PERF: Pass pre-fetched evidence_bundle to avoid duplicate SourceActivation call
        from kairo.hero.engines import opportunities_engine

        synthesis_start = time.monotonic()
        try:
            board_dto = opportunities_engine.generate_today_board(
                brand_id=brand_id,
                run_id=job_id,  # Use job_id as run_id for correlation
                trigger_source="background_job",
                mode=mode,  # PR-6: Pass mode to engine
                evidence_bundle=evidence_bundle,  # PERF: Reuse existing bundle
                user_id=user_id,  # Phase 2 BYOK
            )
            synthesis_time_ms = int((time.monotonic() - synthesis_start) * 1000)

            diagnostics["synthesis_time_ms"] = synthesis_time_ms
            diagnostics["opportunities_count"] = len(board_dto.opportunities)

            # Create OpportunitiesBoard from engine DTO result
            # Engine persists Opportunity rows, but board record is created here
            opportunity_ids = [opp.id for opp in board_dto.opportunities]

            # Determine state based on board DTO metadata
            # CRITICAL: Gates already passed at this point. If synthesis returns degraded,
            # it's due to LLM/infra failure, NOT evidence insufficiency.
            # - degraded=True after gate pass → ERROR (retry-oriented)
            # - degraded=False → READY
            # insufficient_evidence is ONLY set when gates fail (handled above in Step 3)
            if board_dto.meta.degraded:
                board_state = TodayBoardState.ERROR
                remediation = "Synthesis failed due to a temporary error. Try regenerating."
            else:
                board_state = TodayBoardState.READY
                remediation = None

            board = OpportunitiesBoard.objects.create(
                brand_id=brand_id,
                state=board_state,
                opportunity_ids=[str(oid) for oid in opportunity_ids],
                evidence_summary_json=diagnostics.get("evidence_summary", {}),
                # evidence_shortfall_json defaults to {} - DTO converts empty to None
                remediation=remediation,
                diagnostics_json=diagnostics,
            )

            diagnostics["board_id"] = str(board.id)
            diagnostics["terminal_state"] = str(board.state)

            # Phase 3: Update progress - complete
            update_job_progress(
                job_id,
                ProgressStage.COMPLETE,
                f"Generated {len(opportunity_ids)} opportunities!",
            )

            # Mark job as succeeded
            complete_job(
                job_id,
                board_id=board.id,
                result_json=diagnostics,
            )

            # PR-7: Invalidate caches (clears job tracking + old board cache)
            # then populate with new board
            _invalidate_cache(brand_id)
            _populate_cache(brand_id, board)

            total_time_ms = int((time.monotonic() - start_time) * 1000)
            diagnostics["total_time_ms"] = total_time_ms

            return JobResult(
                success=True,
                board_id=board.id if board else None,
                diagnostics=diagnostics,
            )

        except Exception as synthesis_error:
            # Synthesis failed AFTER gates passed - this is an ERROR state, NOT insufficient_evidence
            # Create an ERROR board so UI shows correct remediation (retry, not "connect more sources")
            synthesis_time_ms = int((time.monotonic() - synthesis_start) * 1000)
            diagnostics["synthesis_time_ms"] = synthesis_time_ms
            diagnostics["synthesis_error"] = str(synthesis_error)
            diagnostics["gates_passed"] = True  # Preserve fact that gates passed

            logger.exception(
                "Synthesis failed for brand %s (job=%s): %s",
                brand_id,
                job_id,
                str(synthesis_error),
            )

            # Generate specific error remediation based on the error type
            error_str = str(synthesis_error).lower()
            if "apify" in error_str and ("401" in error_str or "authentication" in error_str):
                error_remediation = "Apify authentication failed. Check your Apify token in Settings."
            elif "apify" in error_str and ("402" in error_str or "credit" in error_str or "payment" in error_str):
                error_remediation = "Apify credits exhausted. Add credits at apify.com and try again."
            elif "openai" in error_str or "rate limit" in error_str:
                error_remediation = "AI service rate limited. Wait a few minutes and try regenerating."
            elif "timeout" in error_str:
                error_remediation = "Request timed out. The service may be slow. Try regenerating."
            else:
                error_remediation = "Synthesis failed due to a temporary error. Try regenerating."

            # Create ERROR board (gates passed, synthesis failed)
            board = OpportunitiesBoard.objects.create(
                brand_id=brand_id,
                state=TodayBoardState.ERROR,
                opportunity_ids=[],
                evidence_summary_json=diagnostics.get("evidence_summary", {}),
                # evidence_shortfall_json defaults to {} - DTO converts empty to None
                remediation=error_remediation,
                diagnostics_json=diagnostics,
            )

            diagnostics["board_id"] = str(board.id)
            diagnostics["terminal_state"] = TodayBoardState.ERROR

            # Mark job as failed (will retry if attempts < max)
            fail_job(job_id, str(synthesis_error))

            # Invalidate cache
            _invalidate_cache(brand_id)

            total_time_ms = int((time.monotonic() - start_time) * 1000)
            diagnostics["total_time_ms"] = total_time_ms

            return JobResult(
                success=False,
                error=str(synthesis_error),
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

        # PR-7: Invalidate cache on failure
        # - For retries: job will re-enqueue and set new cache entry
        # - For permanent failure: prevents stale "generating" state
        _invalidate_cache(brand_id)

        return JobResult(
            success=False,
            error=error_msg,
            diagnostics=diagnostics,
        )


def _invalidate_cache(brand_id: UUID) -> None:
    """
    Invalidate cache for a brand's TodayBoard.

    PR-7: Uses centralized cache module from kairo.hero.cache.
    Also clears job tracking cache.
    """
    from kairo.hero.services.today_service import invalidate_today_board_cache
    invalidate_today_board_cache(brand_id)


def _populate_cache(brand_id: UUID, board: "OpportunitiesBoard") -> None:
    """
    Populate cache with a board.

    PR-7: Uses centralized cache module from kairo.hero.cache.
    Only caches state=READY boards.
    """
    from kairo.hero.services.today_service import populate_today_board_cache

    try:
        dto = board.to_dto()
        populate_today_board_cache(brand_id, dto)
        logger.debug("Populated cache for brand %s", brand_id)
    except Exception as e:
        logger.warning(
            "Failed to populate cache for brand %s: %s",
            brand_id,
            str(e),
        )


@dataclass
class GateEvidenceItem:
    """
    Gate-compatible evidence item.

    Adapter type that matches what evidence_quality gates expect.
    Created from EvidenceItemData via _convert_bundle_to_gate_items().
    """
    id: UUID  # Generated from bundle item position
    brand_id: UUID
    platform: str
    content_type: str
    external_id: str | None
    canonical_url: str
    published_at: datetime | None
    author_ref: str
    title: str | None
    text_primary: str
    text_secondary: str | None
    hashtags: list
    metrics: dict
    media: dict
    has_transcript: bool
    is_low_value: bool
    created_at: datetime | None


def _convert_bundle_to_gate_items(evidence_bundle) -> list:
    """
    Convert EvidenceBundle items to gate-compatible format.

    The evidence_quality module expects items with specific attributes.
    This adapter bridges EvidenceItemData to that format.
    """
    from datetime import datetime, timezone
    from uuid import uuid5, UUID

    # Namespace for generating IDs for gate items
    GATE_ITEM_NS = UUID("c3d4e5f6-a7b8-9012-cdef-345678901234")

    items = []
    now = datetime.now(timezone.utc)

    for idx, item in enumerate(evidence_bundle.items):
        # Generate a deterministic ID for gate purposes
        item_id = uuid5(GATE_ITEM_NS, f"{evidence_bundle.brand_id}:{item.canonical_url}")

        gate_item = GateEvidenceItem(
            id=item_id,
            brand_id=evidence_bundle.brand_id,
            platform=item.platform,
            content_type="post",  # Default, not critical for gates
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            published_at=item.published_at,
            author_ref=item.author_ref,
            title=item.title,
            text_primary=item.text_primary or "",
            text_secondary=item.text_secondary if item.text_secondary else None,
            hashtags=item.hashtags or [],
            metrics={
                "view_count": item.view_count,
                "like_count": item.like_count,
                "comment_count": item.comment_count,
                "share_count": item.share_count,
            },
            media={},
            has_transcript=item.has_transcript,
            is_low_value=False,
            created_at=now,
        )
        items.append(gate_item)

    return items


def _validate_evidence_bundle(gate_items: list):
    """
    Run evidence gates against converted bundle items.

    Wrapper around validate_evidence_for_synthesis that works with
    GateEvidenceItem objects converted from EvidenceBundle.
    """
    from kairo.hero.services.evidence_quality import validate_evidence_for_synthesis
    return validate_evidence_for_synthesis(gate_items)


def _log_gate_boundary_summary(
    brand_id: UUID,
    job_id: UUID,
    mode: str,
    recipes_executed: list[str],
    evidence_summary: dict,
    validation_result,
) -> None:
    """
    Log detailed gate boundary summary.

    Per TASK-2 requirement: includes mode, recipes_executed, item_count,
    items_with_transcript, platforms_covered, and why the run will end.

    Args:
        brand_id: UUID of the brand
        job_id: UUID of the job
        mode: SourceActivation mode (fixture_only or live_cap_limited)
        recipes_executed: List of recipe IDs that were executed
        evidence_summary: Dict with evidence metrics
        validation_result: Result from validate_evidence_for_synthesis
    """
    from kairo.hero.models import EvidenceItem, ActivationRun

    # Get evidence summary details
    item_count = evidence_summary.get("total_items", 0)
    items_with_transcript = evidence_summary.get("items_with_transcript", 0)
    platforms_covered = list(evidence_summary.get("platforms", {}).keys()) if isinstance(evidence_summary.get("platforms"), dict) else evidence_summary.get("platforms", [])

    # Determine terminal state based on gates
    if validation_result.can_proceed:
        terminal_state = "READY (synthesis will proceed)"
    else:
        terminal_state = "INSUFFICIENT_EVIDENCE (synthesis blocked)"

    # Log comprehensive gate boundary summary
    logger.info(
        "\n"
        "╔══════════════════════════════════════════════════════════════════════╗\n"
        "║                      GATE BOUNDARY SUMMARY                           ║\n"
        "╠══════════════════════════════════════════════════════════════════════╣\n"
        "║ brand_id: %s\n"
        "║ job_id: %s\n"
        "║ mode: %s\n"
        "║ recipes_executed: %s\n"
        "╠══════════════════════════════════════════════════════════════════════╣\n"
        "║ Evidence Metrics:\n"
        "║   - item_count: %d\n"
        "║   - items_with_transcript: %d\n"
        "║   - platforms_covered: %s\n"
        "╠══════════════════════════════════════════════════════════════════════╣\n"
        "║ Gate Result: %s\n"
        "║ Terminal State: %s\n"
        "╚══════════════════════════════════════════════════════════════════════╝",
        brand_id,
        job_id,
        mode,
        recipes_executed,
        item_count,
        items_with_transcript,
        platforms_covered,
        "PASSED" if validation_result.can_proceed else "FAILED",
        terminal_state,
    )

    # Log gate failures if any
    if not validation_result.can_proceed:
        failure_reason = validation_result.failure_reason
        diagnostics = validation_result.diagnostics

        # Extract specific failures
        if failure_reason == "quality_gate_failed":
            shortfall = diagnostics.get("shortfall", {})
            failures = shortfall.get("failures", [])
            logger.info("  Gate failures (quality_gate):")
            for failure in failures:
                logger.info("    - %s", failure)
        elif failure_reason == "usability_gate_failed":
            failures = diagnostics.get("failures", [])
            logger.info("  Gate failures (usability_gate):")
            for failure in failures:
                logger.info("    - %s", failure)
        else:
            logger.info("  Gate failures: %s", failure_reason)

    # Query EvidenceItem count from latest ActivationRun
    try:
        latest_run = (
            ActivationRun.objects
            .filter(brand_id=brand_id)
            .order_by("-started_at")
            .first()
        )
        if latest_run:
            evidence_count = EvidenceItem.objects.filter(
                activation_run_id=latest_run.id
            ).count()
            logger.info(
                "  ActivationRun %s: %d EvidenceItem rows persisted",
                latest_run.id,
                evidence_count,
            )
        else:
            logger.info("  No ActivationRun found for brand %s", brand_id)
    except Exception as e:
        logger.warning("  Failed to query ActivationRun: %s", str(e))
