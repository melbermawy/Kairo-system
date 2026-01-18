"""
Today Service.

PR0: Foundational scaffolding for opportunities v2.
PR1: Real job queue and persistence layer.
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

Per PR-map-and-standards §PR-3 4.2.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from django.core.cache import cache

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand
from kairo.hero.dto import (
    BrandSnapshotDTO,
    EvidenceShortfallDTO,
    RegenerateResponseDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
)

logger = logging.getLogger("kairo.hero.services.today")

# =============================================================================
# CACHE CONFIGURATION
# Per opportunities_v1_prd.md §7.3
# =============================================================================

CACHE_KEY_PREFIX = "today_board:v2"
CACHE_TTL_SECONDS = int(os.environ.get("OPPORTUNITIES_CACHE_TTL_S", "21600"))  # 6 hours

# Job tracking key prefix (for checking if generation is running)
JOB_KEY_PREFIX = "today_job:v2"
JOB_TTL_SECONDS = 600  # 10 minutes max for generation

# Minimum evidence items for first-run auto-enqueue
MIN_EVIDENCE_ITEMS = 8


def _get_cache_key(brand_id: UUID) -> str:
    """Generate cache key for a brand's today board."""
    return f"{CACHE_KEY_PREFIX}:{brand_id}"


def _get_job_key(brand_id: UUID) -> str:
    """Generate job tracking key for a brand's generation job."""
    return f"{JOB_KEY_PREFIX}:{brand_id}"


# =============================================================================
# READ-ONLY GET LOGIC
# Per opportunities_v1_prd.md §0.2
# =============================================================================


def get_today_board(brand_id: UUID) -> TodayBoardDTO:
    """
    GET /today/ implementation.

    CRITICAL: This function MUST NOT call LLMs or block on generation.

    Per opportunities_v1_prd.md §0.2:

    IF board exists in cache (Redis):
      - Return cached board with state: "ready"
      - Set meta.cache_hit = true

    ELSE IF board exists in DB:
      - Return persisted board with state: "ready"
      - Populate cache for next request

    ELSE IF generation job is running:
      - Return state: "generating"
      - Include job_id for polling
      - Return empty opportunities OR stale cached board (if exists)

    ELSE IF brand has valid evidence but no board:
      - FIRST TIME ONLY: Auto-enqueue generation job
      - Return state: "generating"
      - This is the ONLY case where GET has a side effect

    ELSE (no evidence, no board):
      - Return state: "not_generated_yet"
      - Include remediation: "Connect sources and run BrandBrain compile"

    Args:
        brand_id: UUID of the brand

    Returns:
        TodayBoardDTO with appropriate state

    Raises:
        Brand.DoesNotExist: If brand not found
    """
    # Validate brand exists
    brand = Brand.objects.get(id=brand_id)

    # Build minimal snapshot (needed for all responses)
    snapshot = _build_minimal_snapshot(brand)

    cache_key = _get_cache_key(brand_id)
    now = datetime.now(timezone.utc)

    # 1. Check cache first (fast path)
    cached = cache.get(cache_key)
    if cached:
        try:
            board = TodayBoardDTO.model_validate_json(cached)
            board.meta.cache_hit = True
            board.meta.cache_key = cache_key
            logger.debug(
                "Cache hit for today board",
                extra={"brand_id": str(brand_id), "cache_key": cache_key},
            )
            return board
        except Exception as e:
            # Cache corruption - log and continue to DB check
            logger.warning(
                "Cache validation failed, falling back to DB",
                extra={"brand_id": str(brand_id), "error": str(e)},
            )

    # 2. Check for persisted board (PR1: real OpportunitiesBoard)
    persisted_board = _get_persisted_board(brand_id, snapshot)
    if persisted_board:
        # Return board regardless of state (could be ready, insufficient_evidence, etc.)
        persisted_board.meta.cache_hit = False
        persisted_board.meta.cache_key = cache_key

        # Only cache if state is READY
        if persisted_board.meta.state == TodayBoardState.READY:
            _populate_cache(brand_id, persisted_board)

        return persisted_board

    # 3. Check if generation job is running
    running_job_id = _get_running_job_id(brand_id)
    if running_job_id:
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

    # 4. Check if evidence exists (for first-run auto-enqueue)
    evidence_count = _get_evidence_count(brand_id)
    if evidence_count >= MIN_EVIDENCE_ITEMS:
        # First-run: auto-enqueue generation (non-blocking, idempotent)
        job_id = _enqueue_generation_job(brand_id, first_run=True)
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
                notes=["First-run auto-enqueue triggered"],
            ),
        )

    # 5. No evidence, no board - return not_generated_yet
    return TodayBoardDTO(
        brand_id=brand_id,
        snapshot=snapshot,
        opportunities=[],
        meta=TodayBoardMetaDTO(
            generated_at=now,
            state=TodayBoardState.NOT_GENERATED_YET,
            cache_hit=False,
            cache_key=cache_key,
            remediation="Connect Instagram or TikTok sources in Settings, then run BrandBrain compile.",
            evidence_shortfall=EvidenceShortfallDTO(
                required_items=MIN_EVIDENCE_ITEMS,
                found_items=evidence_count,
                required_platforms=["instagram", "tiktok"],
                found_platforms=[],  # Would be populated by actual evidence check
                missing_platforms=["instagram", "tiktok"],
            ),
        ),
    )


# =============================================================================
# REGENERATE LOGIC (GENERATION TRIGGER)
# Per opportunities_v1_prd.md §0.2
# =============================================================================


def regenerate_today_board(brand_id: UUID) -> RegenerateResponseDTO:
    """
    POST /regenerate/ implementation.

    This is the ONLY endpoint that triggers generation.

    Per opportunities_v1_prd.md §0.2:
    - Invalidate cache
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

    cache_key = _get_cache_key(brand_id)

    # Invalidate cache
    cache.delete(cache_key)
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

        # Convert to DTO
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
    """
    # First check cache (fast path)
    job_key = _get_job_key(brand_id)
    cached_job_id = cache.get(job_key)
    if cached_job_id:
        return cached_job_id

    # Check database for running/pending jobs
    try:
        from kairo.hero.jobs.queue import get_running_job_for_brand

        job = get_running_job_for_brand(brand_id)
        if job:
            # Update cache with job ID
            cache.set(job_key, str(job.id), timeout=JOB_TTL_SECONDS)
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
    job_key = _get_job_key(brand_id)

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
        cache.set(job_key, job_id, timeout=JOB_TTL_SECONDS)

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


def _populate_cache(brand_id: UUID, board: TodayBoardDTO) -> None:
    """
    Populate cache with a today board.
    """
    cache_key = _get_cache_key(brand_id)
    try:
        cache.set(cache_key, board.model_dump_json(), timeout=CACHE_TTL_SECONDS)
        logger.debug(
            "Cache populated",
            extra={
                "brand_id": str(brand_id),
                "cache_key": cache_key,
                "ttl_seconds": CACHE_TTL_SECONDS,
            },
        )
    except Exception as e:
        logger.warning(
            "Failed to populate cache",
            extra={"brand_id": str(brand_id), "error": str(e)},
        )


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
    """
    import warnings
    warnings.warn(
        "regenerate_today_board_legacy is deprecated and will be removed. "
        "Use regenerate_today_board() for async generation.",
        DeprecationWarning,
        stacklevel=2,
    )

    from kairo.hero.engines import opportunities_engine
    return opportunities_engine.generate_today_board(brand_id)
