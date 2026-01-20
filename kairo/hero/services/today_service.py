"""
Today Service.

PR0: Foundational scaffolding for opportunities v2.
PR1: Real job queue and persistence layer.
PR7: Hardening (UI reliability) - Redis caching with proper invalidation.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

CRITICAL INVARIANTS:
1. GET /today/ is STRICTLY READ-ONLY
   - MUST NOT call LLMs
   - MUST NOT trigger synchronous generation
   - MUST NOT call Apify actors
   - ONLY EXCEPTION: first-run auto-enqueue (non-blocking, idempotent)

2. POST /regenerate/ is the ONLY generation trigger
   - Enqueues background job (does not block)
   - Returns immediately with job_id

3. CACHING (PR-7, per PRD §D.4):
   - Cache key: "today_board:v2:{brand_id}"
   - TTL: 6 hours (21600 seconds)
   - Only cache state=READY boards
   - Invalidation: On job completion or POST /regenerate

Per PR-map-and-standards §PR-3 4.2.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from django.core.cache import cache

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand
from kairo.hero.cache import (
    JOB_TTL_SECONDS,
    clear_cached_job_id,
    get_cache_key,
    get_cache_ttl,
    get_cached_board,
    get_cached_job_id,
    get_job_cache_key,
    invalidate_cache,
    set_cached_board,
    set_cached_job_id,
)
from kairo.hero.dto import (
    BrandSnapshotDTO,
    RegenerateResponseDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
)

logger = logging.getLogger("kairo.hero.services.today")


# =============================================================================
# READ-ONLY GET LOGIC
# Per opportunities_v1_prd.md §0.2, §D.4
# =============================================================================


def get_today_board(brand_id: UUID) -> TodayBoardDTO:
    """
    GET /today/ implementation.

    CRITICAL: This function MUST NOT call LLMs or block on generation.

    PR-7: Optimized path ordering for polling-storm defense:
    1. Cache hit → Return immediately (cheapest path)
    2. Generating state → Return minimal response (no evidence join)
    3. Persisted board → Return with evidence join, populate cache
    4. First-run auto-enqueue → Return generating state
    5. No snapshot → Return not_generated_yet

    Per opportunities_v1_prd.md §0.2, §D.4:
    - Cache key: "today_board:v2:{brand_id}"
    - TTL: 6 hours
    - Only cache state=READY boards
    - ready_reason indicates cache_hit vs fresh_generation

    Args:
        brand_id: UUID of the brand

    Returns:
        TodayBoardDTO with appropriate state

    Raises:
        Brand.DoesNotExist: If brand not found
    """
    # Validate brand exists (single lightweight query)
    brand = Brand.objects.get(id=brand_id)

    cache_key = get_cache_key(brand_id)
    cache_ttl = get_cache_ttl()
    now = datetime.now(timezone.utc)

    # ==========================================================================
    # PATH 1: Cache hit (cheapest - no DB queries for board/opportunities)
    # ==========================================================================
    cached_board = get_cached_board(brand_id)
    if cached_board:
        # PR-7: Set ready_reason to indicate cache hit
        cached_board.meta.ready_reason = "cache_hit"
        cached_board.meta.cache_ttl_seconds = cache_ttl
        logger.debug(
            "GET /today cache hit for brand %s",
            brand_id,
        )
        return cached_board

    # Build minimal snapshot (needed for non-cached responses)
    snapshot = _build_minimal_snapshot(brand)

    # ==========================================================================
    # PATH 2: Check if generation job is running (cheap - cache then single query)
    # PR-7: Check this BEFORE loading persisted board to avoid expensive
    # evidence preview join when polling during generation
    # ==========================================================================
    running_job_id = _get_running_job_id(brand_id)
    if running_job_id:
        logger.debug(
            "GET /today returning generating state for brand %s (job=%s)",
            brand_id,
            running_job_id,
        )
        return TodayBoardDTO(
            brand_id=brand_id,
            snapshot=snapshot,
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.GENERATING,
                job_id=running_job_id,
                cache_hit=False,
                cache_key=cache_key,
            ),
        )

    # ==========================================================================
    # PATH 3: Load persisted board from DB (includes evidence preview join)
    # ==========================================================================
    persisted_board = _get_persisted_board(brand_id, snapshot)
    if persisted_board:
        # Return board regardless of state (ready, insufficient_evidence, error)
        persisted_board.meta.cache_hit = False
        persisted_board.meta.cache_key = cache_key
        persisted_board.meta.cache_ttl_seconds = cache_ttl

        # PR-7: Set ready_reason for ready boards (fresh_generation since not cached)
        if persisted_board.meta.state == TodayBoardState.READY:
            persisted_board.meta.ready_reason = "fresh_generation"
            # Populate cache for next request
            set_cached_board(brand_id, persisted_board)

        return persisted_board

    # ==========================================================================
    # PATH 4: First-run auto-enqueue (snapshot exists but no board)
    # ==========================================================================
    if _has_brandbrain_snapshot(brand_id):
        # First-run: auto-enqueue generation (non-blocking, idempotent)
        job_id = _enqueue_generation_job(brand_id, first_run=True)
        logger.info(
            "First-run auto-enqueue triggered for brand %s (job=%s)",
            brand_id,
            job_id,
        )
        return TodayBoardDTO(
            brand_id=brand_id,
            snapshot=snapshot,
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.GENERATING,
                job_id=job_id,
                cache_hit=False,
                cache_key=cache_key,
                notes=["First-run auto-enqueue triggered (BrandBrainSnapshot exists)"],
            ),
        )

    # ==========================================================================
    # PATH 5: No snapshot, no board - return not_generated_yet
    # ==========================================================================
    return TodayBoardDTO(
        brand_id=brand_id,
        snapshot=snapshot,
        opportunities=[],
        meta=TodayBoardMetaDTO(
            generated_at=now,
            state=TodayBoardState.NOT_GENERATED_YET,
            cache_hit=False,
            cache_key=cache_key,
            remediation="Run BrandBrain compile to establish brand context.",
        ),
    )


# =============================================================================
# REGENERATE LOGIC (GENERATION TRIGGER)
# Per opportunities_v1_prd.md §0.2, §D.4
# =============================================================================


def regenerate_today_board(brand_id: UUID) -> RegenerateResponseDTO:
    """
    POST /regenerate/ implementation.

    This is the ONLY endpoint that triggers generation.

    PR-7 (per PRD §D.4):
    - Invalidate cache IMMEDIATELY
    - Enqueue background job (Celery/RQ)
    - Return 202 Accepted with job_id
    - Client polls GET /today/ for completion

    Args:
        brand_id: UUID of the brand

    Returns:
        RegenerateResponseDTO with job_id and poll_url

    Raises:
        Brand.DoesNotExist: If brand not found
    """
    # Validate brand exists
    Brand.objects.get(id=brand_id)

    cache_key = get_cache_key(brand_id)

    # PR-7: Invalidate cache IMMEDIATELY (per PRD §D.4)
    invalidate_cache(brand_id)
    logger.info(
        "Cache invalidated for regeneration",
        extra={"brand_id": str(brand_id), "cache_key": cache_key},
    )

    # Enqueue background job (force=True to override any existing job)
    job_id = _enqueue_generation_job(brand_id, force=True)

    return RegenerateResponseDTO(
        status="accepted",
        job_id=job_id,
        poll_url=f"/api/brands/{brand_id}/today/",
    )


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _build_minimal_snapshot(brand: Brand) -> BrandSnapshotDTO:
    """
    Build a minimal BrandSnapshotDTO for degraded/empty responses.

    PR0: Simplified version - full snapshot building is in opportunities_engine.
    """
    return BrandSnapshotDTO(
        brand_id=brand.id,
        brand_name=brand.name,
        positioning=brand.positioning or None,
        pillars=[],  # Not loaded for minimal snapshot
        personas=[],  # Not loaded for minimal snapshot
        voice_tone_tags=brand.tone_tags or [],
        taboos=brand.taboos or [],
    )


def _get_persisted_board(brand_id: UUID, snapshot: BrandSnapshotDTO) -> TodayBoardDTO | None:
    """
    Get persisted board from database.

    PR1: Reads from OpportunitiesBoard model.
    PR5: Includes read-time evidence preview join.
    PR7: Only called on cache miss.

    Returns the latest board for the brand.
    """
    try:
        from kairo.hero.models import OpportunitiesBoard

        board = (
            OpportunitiesBoard.objects
            .filter(brand_id=brand_id)
            .order_by("-created_at")
            .first()
        )

        if not board:
            return None

        # Convert to DTO (PR5: includes evidence preview join)
        dto = board.to_dto()
        # Override snapshot with fresh one (board may have stale snapshot)
        dto.snapshot = snapshot
        return dto

    except Exception as e:
        logger.warning(
            "Failed to get persisted board",
            extra={"brand_id": str(brand_id), "error": str(e)},
        )
        return None


def _get_running_job_id(brand_id: UUID) -> str | None:
    """
    Check if a generation job is currently running for this brand.

    PR1: Checks both cache and database for running jobs.
    PR7: Cache-first for polling-storm defense.

    DESIGN NOTE (PR-7 spot check 2):
    - Job tracking cache has short TTL (10 min) as a hint for polling optimization
    - Cache is invalidated on ALL job completion paths (success, failure, insufficient_evidence)
    - If cache says job running, we trust it (avoids DB query storm during polling)
    - If cache miss, we check DB and update cache
    - DB is source of truth; cache correctness depends on proper invalidation
    """
    # First check cache (fast path - no DB query)
    cached_job_id = get_cached_job_id(brand_id)
    if cached_job_id:
        return cached_job_id

    # Cache miss - check database for running/pending jobs
    try:
        from kairo.hero.jobs.queue import get_running_job_for_brand

        job = get_running_job_for_brand(brand_id)
        if job:
            # Update cache with job ID for subsequent polls
            set_cached_job_id(brand_id, str(job.id))
            return str(job.id)
    except Exception as e:
        logger.warning(
            "Failed to check running job",
            extra={"brand_id": str(brand_id), "error": str(e)},
        )

    return None


def _get_evidence_count(brand_id: UUID) -> int:
    """
    Get count of normalized evidence items for a brand.

    PR0: Reads from NormalizedEvidenceItem table.
    """
    try:
        from kairo.brandbrain.models import NormalizedEvidenceItem
        return NormalizedEvidenceItem.objects.filter(brand_id=brand_id).count()
    except Exception as e:
        logger.warning(
            "Failed to get evidence count",
            extra={"brand_id": str(brand_id), "error": str(e)},
        )
        return 0


def _has_brandbrain_snapshot(brand_id: UUID) -> bool:
    """
    Check if a BrandBrainSnapshot exists for this brand.

    Per PRD Section I.2: First-visit auto-enqueue should trigger when
    "no board exists AND a snapshot exists", NOT when evidence exists.

    BrandBrainSnapshot is the required precondition for Opportunities generation.
    """
    try:
        from kairo.brandbrain.models import BrandBrainSnapshot
        return BrandBrainSnapshot.objects.filter(brand_id=brand_id).exists()
    except Exception as e:
        logger.warning(
            "Failed to check for BrandBrainSnapshot",
            extra={"brand_id": str(brand_id), "error": str(e)},
        )
        return False


def _enqueue_generation_job(brand_id: UUID, force: bool = False, first_run: bool = False) -> str:
    """
    Enqueue a background generation job.

    PR1: Creates real OpportunitiesJob in database.

    Args:
        brand_id: Brand to generate for
        force: If True, override any existing job
        first_run: If True, this is a first-run auto-enqueue

    Returns:
        job_id for tracking
    """
    # Check if job already running (idempotency)
    if not force:
        existing_job_id = _get_running_job_id(brand_id)
        if existing_job_id:
            logger.info(
                "Generation job already running",
                extra={"brand_id": str(brand_id), "job_id": existing_job_id},
            )
            return existing_job_id

    # Create real job in database
    try:
        from kairo.hero.jobs.queue import enqueue_opportunities_job

        result = enqueue_opportunities_job(
            brand_id,
            force=force,
            first_run=first_run,
        )
        job_id = str(result.job_id)

        # Set tracking key in cache
        set_cached_job_id(brand_id, job_id)

        logger.info(
            "Generation job enqueued",
            extra={
                "brand_id": str(brand_id),
                "job_id": job_id,
                "force": force,
                "first_run": first_run,
            },
        )

        return job_id

    except Exception as e:
        logger.error(
            "Failed to enqueue generation job",
            extra={"brand_id": str(brand_id), "error": str(e)},
        )
        raise


# =============================================================================
# CACHE MANAGEMENT (exposed for job completion)
# =============================================================================


def invalidate_today_board_cache(brand_id: UUID) -> None:
    """
    Invalidate cache for a brand's TodayBoard.

    PR7: Called on job completion before/after board persistence.
    Also clears job tracking cache.
    """
    invalidate_cache(brand_id)
    clear_cached_job_id(brand_id)


def populate_today_board_cache(brand_id: UUID, board: TodayBoardDTO) -> None:
    """
    Populate cache with a TodayBoard.

    PR7: Called on job completion after board persistence.
    Only caches state=READY boards.
    """
    set_cached_board(brand_id, board)


# =============================================================================
# LEGACY COMPATIBILITY
# =============================================================================


def regenerate_today_board_legacy(brand_id: UUID) -> TodayBoardDTO:
    """
    DEPRECATED: Legacy synchronous regeneration.

    PR1: This function is MARKED FOR REMOVAL.
    It exists only for backwards compatibility with existing tests.

    CRITICAL: This function MUST NOT be called from production code paths.
    It violates the async-only generation requirement.

    New code should use regenerate_today_board() which enqueues a job.

    Raises:
        GuardrailViolationError: If called from GET /today context (PR-0 guardrail)
    """
    import warnings

    # PR-0 / PR-1: Guard against calling from GET /today context
    # This ensures LLM synthesis NEVER happens during a GET request
    from kairo.core.guardrails import assert_not_in_get_today
    assert_not_in_get_today()

    warnings.warn(
        "regenerate_today_board_legacy is deprecated and will be removed. "
        "Use regenerate_today_board() for async generation.",
        DeprecationWarning,
        stacklevel=2,
    )

    from kairo.hero.engines import opportunities_engine
    return opportunities_engine.generate_today_board(brand_id)
