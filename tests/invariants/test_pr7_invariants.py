"""
PR-7 Invariant Tests: Hardening (UI reliability).

Per opportunities_v1_prd.md §D.4 - TodayBoard Caching:

1. Cache key format: "today_board:v2:{brand_id}"
2. Cache TTL: 6 hours (21600 seconds)
3. Cache invalidation on job completion and POST /regenerate
4. Cache hit prevents expensive evidence preview queries
5. GET generating is cheap (no evidence preview join)
6. Response shape stability across all states
7. Read-only invariants not regressed

These tests prove the caching and polling-storm defense mechanisms.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        id=uuid.uuid4(),
        name="Test Tenant PR7",
    )


@pytest.fixture
def brand(db, tenant) -> Brand:
    """Create a test brand."""
    return Brand.objects.create(
        id=uuid.uuid4(),
        tenant=tenant,
        name="Test Brand PR7",
        positioning="A test brand for PR-7 invariant testing",
    )


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test."""
    cache.clear()
    yield
    cache.clear()


# =============================================================================
# 1. Cache key format and TTL invariants
# =============================================================================


@pytest.mark.unit
class TestCacheKeyAndTTL:
    """
    Verify cache key format and TTL match PRD §D.4 exactly.

    Per PRD:
    - Cache key: "today_board:v2:{brand_id}"
    - TTL: 6 hours (21600 seconds)
    """

    def test_cache_key_format_matches_prd(self):
        """Cache key MUST be 'today_board:v2:{brand_id}'."""
        from kairo.hero.cache import CACHE_KEY_PREFIX, get_cache_key

        test_brand_id = uuid.uuid4()

        # Verify prefix
        assert CACHE_KEY_PREFIX == "today_board:v2", (
            f"Cache key prefix must be 'today_board:v2', got '{CACHE_KEY_PREFIX}'"
        )

        # Verify full key format
        cache_key = get_cache_key(test_brand_id)
        expected = f"today_board:v2:{test_brand_id}"
        assert cache_key == expected, (
            f"Cache key format mismatch: expected '{expected}', got '{cache_key}'"
        )

    def test_cache_ttl_is_6_hours(self):
        """Cache TTL MUST be 21600 seconds (6 hours) per PRD §D.4."""
        from kairo.hero.cache import DEFAULT_CACHE_TTL_SECONDS, get_cache_ttl

        # Default constant
        assert DEFAULT_CACHE_TTL_SECONDS == 21600, (
            f"Default TTL must be 21600 (6 hours), got {DEFAULT_CACHE_TTL_SECONDS}"
        )

        # Function returns correct value (may be overridden by env)
        ttl = get_cache_ttl()
        assert ttl > 0, "TTL must be positive"

    def test_settings_cache_ttl_constant(self):
        """Settings OPPORTUNITIES_CACHE_TTL_S must default to 21600."""
        from django.conf import settings

        ttl = getattr(settings, "OPPORTUNITIES_CACHE_TTL_S", None)
        assert ttl is not None, "Settings must define OPPORTUNITIES_CACHE_TTL_S"
        assert ttl == 21600, (
            f"OPPORTUNITIES_CACHE_TTL_S must be 21600, got {ttl}"
        )


# =============================================================================
# 2. Cache hit prevents repeated heavy work
# =============================================================================


@pytest.mark.django_db
class TestCacheHitPreventsHeavyWork:
    """
    Verify cache hit returns immediately without DB/evidence queries.

    On a cached ready response:
    - No OpportunitiesBoard query
    - No Opportunity query
    - No EvidenceItem query (evidence preview)
    """

    def test_cache_hit_skips_board_query(self, brand: Brand):
        """Cache hit MUST NOT query OpportunitiesBoard."""
        from kairo.hero.cache import get_cache_key, set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            OpportunityDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )
        from kairo.hero.services import today_service

        # Pre-populate cache with a ready board
        now = datetime.now(timezone.utc)
        cached_dto = TodayBoardDTO(
            brand_id=brand.id,
            snapshot=BrandSnapshotDTO(
                brand_id=brand.id,
                brand_name=brand.name,
            ),
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
                ready_reason="fresh_generation",
                opportunity_count=0,
            ),
        )
        set_cached_board(brand.id, cached_dto)

        # Track DB queries
        from django.db import connection, reset_queries
        from django.conf import settings

        # Enable query logging temporarily
        old_debug = settings.DEBUG
        settings.DEBUG = True
        reset_queries()

        try:
            # Call get_today_board
            result = today_service.get_today_board(brand.id)

            # Check queries executed
            queries = connection.queries.copy()

            # Should only have Brand query, no Board/Opportunity/EvidenceItem queries
            board_queries = [q for q in queries if "opportunities_board" in q.get("sql", "").lower()]
            opportunity_queries = [q for q in queries if "hero_opportunity" in q.get("sql", "").lower()]
            evidence_queries = [q for q in queries if "hero_evidenceitem" in q.get("sql", "").lower()]

            assert len(board_queries) == 0, (
                f"Cache hit should NOT query OpportunitiesBoard, found {len(board_queries)} queries"
            )
            assert len(opportunity_queries) == 0, (
                f"Cache hit should NOT query Opportunity, found {len(opportunity_queries)} queries"
            )
            assert len(evidence_queries) == 0, (
                f"Cache hit should NOT query EvidenceItem, found {len(evidence_queries)} queries"
            )

            # Verify result is from cache
            assert result.meta.cache_hit is True
            assert result.meta.ready_reason == "cache_hit"

        finally:
            settings.DEBUG = old_debug

    def test_cache_hit_returns_full_dto_with_evidence_preview(self, brand: Brand):
        """Cached board includes evidence_preview (no read-time join needed)."""
        from kairo.hero.cache import set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            EvidencePreviewDTO,
            OpportunityDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )
        from kairo.hero.services import today_service

        # Pre-populate cache with a board containing evidence_preview
        now = datetime.now(timezone.utc)
        evidence_preview = [
            EvidencePreviewDTO(
                id=uuid.uuid4(),
                platform="instagram",
                canonical_url="https://instagram.com/p/test",
                author_ref="@testuser",
                text_snippet="Test evidence snippet",
                has_transcript=True,
            )
        ]
        opportunity = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=brand.id,
            title="Test Opportunity",
            angle="Test angle",
            why_now="This is timely because of test reasons.",
            type="trend",
            primary_channel="instagram",
            score=85.0,
            evidence_ids=[evidence_preview[0].id],
            evidence_preview=evidence_preview,
            created_at=now,
            updated_at=now,
        )

        cached_dto = TodayBoardDTO(
            brand_id=brand.id,
            snapshot=BrandSnapshotDTO(
                brand_id=brand.id,
                brand_name=brand.name,
            ),
            opportunities=[opportunity],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
                ready_reason="fresh_generation",
                opportunity_count=1,
            ),
        )
        set_cached_board(brand.id, cached_dto)

        # Get from cache
        result = today_service.get_today_board(brand.id)

        # Verify evidence_preview is present from cache
        assert result.meta.cache_hit is True
        assert len(result.opportunities) == 1
        assert len(result.opportunities[0].evidence_preview) == 1
        assert result.opportunities[0].evidence_preview[0].platform == "instagram"


# =============================================================================
# 3. Cache invalidation
# =============================================================================


@pytest.mark.django_db
class TestCacheInvalidation:
    """
    Verify cache is invalidated at correct times.

    Per PRD §D.4:
    - On job completion (successful board generation)
    - On POST /regenerate (immediately)
    """

    def test_post_regenerate_invalidates_cache_immediately(self, brand: Brand):
        """POST /regenerate MUST invalidate cache before enqueueing job."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.cache import get_cache_key, set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )
        from kairo.hero.services import today_service

        # Create snapshot (required for job enqueue)
        BrandBrainSnapshot.objects.create(
            brand=brand,
            snapshot_json={"positioning": "test"},
            diff_from_previous_json={},
        )

        # Pre-populate cache
        now = datetime.now(timezone.utc)
        cached_dto = TodayBoardDTO(
            brand_id=brand.id,
            snapshot=BrandSnapshotDTO(
                brand_id=brand.id,
                brand_name=brand.name,
            ),
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
                ready_reason="fresh_generation",
                opportunity_count=0,
            ),
        )
        set_cached_board(brand.id, cached_dto)

        # Verify cache is populated
        cache_key = get_cache_key(brand.id)
        assert cache.get(cache_key) is not None, "Cache should be populated"

        # Call POST /regenerate
        result = today_service.regenerate_today_board(brand.id)

        # Verify cache is invalidated
        assert cache.get(cache_key) is None, (
            "POST /regenerate MUST invalidate cache immediately"
        )

        # Verify job was enqueued
        assert result.status == "accepted"
        assert result.job_id is not None

    def test_job_completion_clears_job_cache(self, brand: Brand):
        """Job completion MUST clear job tracking cache."""
        from kairo.hero.cache import get_job_cache_key, set_cached_job_id
        from kairo.hero.services.today_service import invalidate_today_board_cache

        # Set job tracking cache
        job_id = str(uuid.uuid4())
        set_cached_job_id(brand.id, job_id)

        # Verify job cache is set
        job_key = get_job_cache_key(brand.id)
        assert cache.get(job_key) == job_id

        # Call invalidation (simulates job completion)
        invalidate_today_board_cache(brand.id)

        # Verify job cache is cleared
        assert cache.get(job_key) is None, (
            "Job completion MUST clear job tracking cache"
        )


# =============================================================================
# 4. GET generating is cheap
# =============================================================================


@pytest.mark.django_db
class TestGeneratingStateCheap:
    """
    Verify GET /today when generating is cheap (no heavy DB work).

    When a job is running:
    - No OpportunitiesBoard.to_dto() call (expensive evidence join)
    - No Opportunity query
    - No EvidenceItem query
    """

    def test_generating_state_skips_evidence_preview_join(self, brand: Brand):
        """GET /today in generating state MUST NOT do evidence preview join."""
        from kairo.hero.cache import set_cached_job_id
        from kairo.hero.services import today_service

        # Set job tracking cache to simulate running job
        job_id = str(uuid.uuid4())
        set_cached_job_id(brand.id, job_id)

        # Track queries
        from django.db import connection, reset_queries
        from django.conf import settings

        old_debug = settings.DEBUG
        settings.DEBUG = True
        reset_queries()

        try:
            result = today_service.get_today_board(brand.id)

            queries = connection.queries.copy()

            # Should have Brand query, maybe OpportunitiesJob query
            # Should NOT have EvidenceItem query
            evidence_queries = [q for q in queries if "hero_evidenceitem" in q.get("sql", "").lower()]

            assert len(evidence_queries) == 0, (
                f"Generating state should NOT query EvidenceItem, found {len(evidence_queries)} queries"
            )

            # Verify state
            assert result.meta.state == TodayBoardState.GENERATING
            assert result.meta.job_id == job_id

        finally:
            settings.DEBUG = old_debug

    def test_generating_state_returns_empty_opportunities(self, brand: Brand):
        """GET /today in generating state returns empty opportunities array."""
        from kairo.hero.cache import set_cached_job_id
        from kairo.hero.services import today_service

        # Set job tracking cache
        job_id = str(uuid.uuid4())
        set_cached_job_id(brand.id, job_id)

        result = today_service.get_today_board(brand.id)

        assert result.meta.state == TodayBoardState.GENERATING
        assert result.opportunities == []
        assert result.meta.job_id == job_id


# =============================================================================
# 5. Response shape stability
# =============================================================================


@pytest.mark.django_db
class TestResponseShapeStability:
    """
    Verify response shape matches PRD examples for all states.

    Per PRD §E.2:
    - generating: { brand_id, opportunities: [], meta: { state, job_id } }
    - ready: { brand_id, snapshot, opportunities, meta: { state, ready_reason, generated_at, opportunity_count } }
    - insufficient_evidence: { brand_id, meta: { state, remediation, evidence_shortfall } }
    - not_generated_yet: { brand_id, meta: { state, remediation } }
    """

    def test_generating_state_shape(self, brand: Brand):
        """Generating state has required fields per PRD."""
        from kairo.hero.cache import set_cached_job_id
        from kairo.hero.services import today_service

        job_id = str(uuid.uuid4())
        set_cached_job_id(brand.id, job_id)

        result = today_service.get_today_board(brand.id)

        # Required fields
        assert result.brand_id == brand.id
        assert result.opportunities == []
        assert result.meta.state == TodayBoardState.GENERATING
        assert result.meta.job_id == job_id

    def test_ready_state_shape(self, brand: Brand):
        """Ready state has required fields per PRD."""
        from kairo.hero.cache import set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )
        from kairo.hero.services import today_service

        now = datetime.now(timezone.utc)
        cached_dto = TodayBoardDTO(
            brand_id=brand.id,
            snapshot=BrandSnapshotDTO(
                brand_id=brand.id,
                brand_name=brand.name,
            ),
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
                ready_reason="fresh_generation",
                opportunity_count=0,
            ),
        )
        set_cached_board(brand.id, cached_dto)

        result = today_service.get_today_board(brand.id)

        # Required fields per PRD
        assert result.brand_id == brand.id
        assert result.snapshot is not None
        assert result.meta.state == TodayBoardState.READY
        assert result.meta.ready_reason in ("cache_hit", "fresh_generation", "stale_cache_with_refresh_available")
        assert result.meta.generated_at is not None
        assert result.meta.opportunity_count is not None

    def test_not_generated_yet_state_shape(self, brand: Brand):
        """Not generated yet state has required fields per PRD."""
        from kairo.hero.services import today_service

        # No snapshot, no board = not_generated_yet
        result = today_service.get_today_board(brand.id)

        assert result.brand_id == brand.id
        assert result.meta.state == TodayBoardState.NOT_GENERATED_YET
        assert result.meta.remediation is not None
        assert "BrandBrain" in result.meta.remediation

    def test_insufficient_evidence_state_shape(self, brand: Brand):
        """Insufficient evidence state has required fields per PRD."""
        from kairo.core.enums import TodayBoardState
        from kairo.hero.models import OpportunitiesBoard
        from kairo.hero.services import today_service

        # Create board with insufficient_evidence state
        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.INSUFFICIENT_EVIDENCE,
            opportunity_ids=[],
            evidence_shortfall_json={
                "required_items": 8,
                "found_items": 2,
                "required_platforms": ["instagram", "tiktok"],
                "found_platforms": ["instagram"],
                "missing_platforms": ["tiktok"],
            },
            remediation="Connect more sources and run BrandBrain compile.",
        )

        result = today_service.get_today_board(brand.id)

        # Required fields per PRD
        assert result.brand_id == brand.id
        assert result.meta.state == TodayBoardState.INSUFFICIENT_EVIDENCE
        assert result.meta.remediation is not None
        assert result.meta.evidence_shortfall is not None
        assert result.meta.evidence_shortfall.required_items == 8
        assert result.meta.evidence_shortfall.found_items == 2


# =============================================================================
# 6. Read-only invariants not regressed
# =============================================================================


@pytest.mark.django_db
class TestReadOnlyInvariantsNotRegressed:
    """
    Verify GET /today read-only invariants are preserved.

    CRITICAL: Even with caching, GET /today MUST NOT:
    - Call LLMs
    - Call Apify
    - Trigger synchronous generation
    """

    def test_cache_miss_does_not_call_engine(self, brand: Brand):
        """GET /today with cache miss MUST NOT call opportunities engine."""
        from kairo.hero.services import today_service

        with patch(
            "kairo.hero.engines.opportunities_engine.generate_today_board"
        ) as mock_engine:
            # No snapshot = not_generated_yet (no engine call)
            result = today_service.get_today_board(brand.id)

            mock_engine.assert_not_called()
            assert result.meta.state == TodayBoardState.NOT_GENERATED_YET

    def test_cache_miss_does_not_call_apify(self, brand: Brand):
        """GET /today with cache miss MUST NOT call Apify."""
        from kairo.hero.services import today_service

        with patch(
            "kairo.integrations.apify.client.ApifyClient"
        ) as mock_apify_class:
            mock_apify = MagicMock()
            mock_apify_class.return_value = mock_apify

            result = today_service.get_today_board(brand.id)

            # Apify client should not be instantiated or called
            mock_apify_class.assert_not_called()
            mock_apify.start_actor_run.assert_not_called()

    def test_first_run_auto_enqueue_uses_fixture_mode(self, brand: Brand):
        """First-run auto-enqueue MUST use fixture_only mode (no Apify spend)."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        # Create snapshot for first-run trigger
        BrandBrainSnapshot.objects.create(
            brand=brand,
            snapshot_json={"positioning": "test"},
            diff_from_previous_json={},
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result = today_service.get_today_board(brand.id)

            # Should be generating (first-run auto-enqueue)
            assert result.meta.state == TodayBoardState.GENERATING
            assert result.meta.job_id is not None

            # Job MUST use fixture_only mode
            job = OpportunitiesJob.objects.get(id=result.meta.job_id)
            assert job.params_json["mode"] == "fixture_only", (
                "First-run auto-enqueue MUST use fixture_only mode"
            )
            assert job.params_json["first_run"] is True


# =============================================================================
# 7. Cache policy: only cache READY boards
# =============================================================================


@pytest.mark.unit
class TestCachePolicy:
    """
    Verify cache policy: only cache state=READY boards.

    NEVER cache:
    - state=GENERATING (stale immediately)
    - state=NOT_GENERATED_YET (may need first-run auto-enqueue)
    - state=INSUFFICIENT_EVIDENCE (user may add evidence)
    - state=ERROR (may be resolved)
    """

    def test_only_ready_boards_are_cached(self):
        """set_cached_board returns False for non-READY states."""
        from kairo.hero.cache import set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )

        brand_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        for state in [
            TodayBoardState.GENERATING,
            TodayBoardState.NOT_GENERATED_YET,
            TodayBoardState.INSUFFICIENT_EVIDENCE,
            TodayBoardState.ERROR,
        ]:
            dto = TodayBoardDTO(
                brand_id=brand_id,
                snapshot=BrandSnapshotDTO(
                    brand_id=brand_id,
                    brand_name="Test",
                ),
                opportunities=[],
                meta=TodayBoardMetaDTO(
                    generated_at=now,
                    state=state,
                ),
            )

            result = set_cached_board(brand_id, dto)

            assert result is False, (
                f"set_cached_board should return False for state={state}"
            )

    def test_ready_boards_are_cached(self):
        """set_cached_board returns True for READY state."""
        from kairo.hero.cache import get_cache_key, set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )

        brand_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        dto = TodayBoardDTO(
            brand_id=brand_id,
            snapshot=BrandSnapshotDTO(
                brand_id=brand_id,
                brand_name="Test",
            ),
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
                ready_reason="fresh_generation",
            ),
        )

        result = set_cached_board(brand_id, dto)

        assert result is True, "set_cached_board should return True for READY state"

        # Verify actually cached
        cache_key = get_cache_key(brand_id)
        assert cache.get(cache_key) is not None


# =============================================================================
# ChatGPT Spot Checks - Explicit Invariants
# =============================================================================


@pytest.mark.django_db
class TestCacheContainsFullDTO:
    """
    ChatGPT Spot Check 1: Cache stores full TodayBoardDTO.

    On cache hit, the returned DTO must include:
    - opportunities[].evidence_preview (not empty if opportunities exist)
    - All meta fields (generated_at, opportunity_count, etc.)
    """

    def test_cached_dto_serializes_evidence_preview(self, brand: Brand):
        """Cached DTO must preserve evidence_preview after serialization."""
        from kairo.hero.cache import get_cache_key, get_cached_board, set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            EvidencePreviewDTO,
            OpportunityDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )

        now = datetime.now(timezone.utc)
        evidence_preview = EvidencePreviewDTO(
            id=uuid.uuid4(),
            platform="tiktok",
            canonical_url="https://tiktok.com/@test/video/123",
            author_ref="@testcreator",
            text_snippet="Test snippet from TikTok",
            has_transcript=True,
        )
        opportunity = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=brand.id,
            title="Cached Opportunity",
            angle="Test angle",
            why_now="This is relevant because of current trends.",
            type="trend",
            primary_channel="tiktok",
            score=90.0,
            evidence_ids=[evidence_preview.id],
            evidence_preview=[evidence_preview],
            created_at=now,
            updated_at=now,
        )

        original_dto = TodayBoardDTO(
            brand_id=brand.id,
            snapshot=BrandSnapshotDTO(
                brand_id=brand.id,
                brand_name=brand.name,
            ),
            opportunities=[opportunity],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
                ready_reason="fresh_generation",
                opportunity_count=1,
            ),
        )

        # Cache it
        set_cached_board(brand.id, original_dto)

        # Retrieve from cache
        cached_dto = get_cached_board(brand.id)

        # Verify evidence_preview survived serialization
        assert cached_dto is not None
        assert len(cached_dto.opportunities) == 1
        assert len(cached_dto.opportunities[0].evidence_preview) == 1
        assert cached_dto.opportunities[0].evidence_preview[0].platform == "tiktok"
        assert cached_dto.opportunities[0].evidence_preview[0].author_ref == "@testcreator"


@pytest.mark.django_db
class TestDBIsSourceOfTruth:
    """
    ChatGPT Spot Check 2: DB is source of truth for job state.

    Cache is a hint for polling optimization. If a stale job_id exists
    in cache but no running job exists in DB, subsequent behavior must
    be correct (not stuck in GENERATING forever).
    """

    def test_stale_job_cache_cleared_when_db_has_ready_board(self, brand: Brand):
        """
        After job completes, stale job cache should be cleared.

        Sequence:
        1. Job starts → job cache set
        2. Job completes → job cache cleared (via invalidation)
        3. GET /today → should NOT return GENERATING
        """
        from kairo.hero.cache import get_cached_job_id, set_cached_job_id
        from kairo.hero.models import OpportunitiesBoard
        from kairo.hero.services import today_service

        # Simulate: job was running (cache set)
        job_id = str(uuid.uuid4())
        set_cached_job_id(brand.id, job_id)

        # Simulate: job completed and created board (invalidation happened)
        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.READY,
            opportunity_ids=[],
            evidence_summary_json={},
            diagnostics_json={},
        )

        # Clear job cache (simulates what invalidate_today_board_cache does)
        from kairo.hero.services.today_service import invalidate_today_board_cache
        invalidate_today_board_cache(brand.id)

        # GET /today should return READY, not GENERATING
        result = today_service.get_today_board(brand.id)

        assert result.meta.state == TodayBoardState.READY, (
            "After job completion, GET should return READY, not GENERATING. "
            "Job cache invalidation must clear stale job_id."
        )


@pytest.mark.django_db
class TestAllCompletionPathsInvalidate:
    """
    ChatGPT Spot Check 3: All job completion paths invalidate cache.

    Every path that transitions job to terminal state must call invalidation:
    - Success (READY board)
    - Insufficient evidence
    - Failure (permanent or retry)
    """

    def test_invalidation_function_clears_both_caches(self, brand: Brand):
        """invalidate_today_board_cache clears both board and job caches."""
        from kairo.hero.cache import (
            get_cache_key,
            get_job_cache_key,
            set_cached_board,
            set_cached_job_id,
        )
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )
        from kairo.hero.services.today_service import invalidate_today_board_cache

        # Set up both caches
        now = datetime.now(timezone.utc)
        board_dto = TodayBoardDTO(
            brand_id=brand.id,
            snapshot=BrandSnapshotDTO(brand_id=brand.id, brand_name="Test"),
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
            ),
        )
        set_cached_board(brand.id, board_dto)
        set_cached_job_id(brand.id, str(uuid.uuid4()))

        # Verify both set
        board_key = get_cache_key(brand.id)
        job_key = get_job_cache_key(brand.id)
        assert cache.get(board_key) is not None
        assert cache.get(job_key) is not None

        # Call invalidation
        invalidate_today_board_cache(brand.id)

        # Both must be cleared
        assert cache.get(board_key) is None, "Board cache not cleared"
        assert cache.get(job_key) is None, "Job cache not cleared"


@pytest.mark.unit
class TestCacheStoresSerializedDTO:
    """
    Verify cache stores serialized JSON, not ORM objects.

    This prevents serialization bugs and ensures cache is backend-agnostic.
    """

    def test_cache_stores_json_string(self):
        """Cache value must be a JSON string, not a Python object."""
        from kairo.hero.cache import get_cache_key, set_cached_board
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )

        brand_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        dto = TodayBoardDTO(
            brand_id=brand_id,
            snapshot=BrandSnapshotDTO(brand_id=brand_id, brand_name="Test"),
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=now,
                state=TodayBoardState.READY,
            ),
        )

        set_cached_board(brand_id, dto)

        # Get raw cache value
        cache_key = get_cache_key(brand_id)
        raw_value = cache.get(cache_key)

        # Must be a string (JSON), not a dict or object
        assert isinstance(raw_value, str), (
            f"Cache must store JSON string, got {type(raw_value)}"
        )

        # Must be valid JSON
        import json
        parsed = json.loads(raw_value)
        assert isinstance(parsed, dict)
        assert str(parsed["brand_id"]) == str(brand_id)


# =============================================================================
# 8. POST /regenerate contract preserved
# =============================================================================


@pytest.mark.django_db
class TestRegenerateContractPreserved:
    """
    Verify POST /regenerate returns correct response shape.

    Per PRD §E.3:
    {
      "status": "accepted",
      "job_id": "abc-123-def",
      "poll_url": "/api/brands/{brand_id}/today/"
    }
    """

    def test_regenerate_response_shape(self, brand: Brand):
        """POST /regenerate returns correct response shape."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.services import today_service

        # Create snapshot (required)
        BrandBrainSnapshot.objects.create(
            brand=brand,
            snapshot_json={"positioning": "test"},
            diff_from_previous_json={},
        )

        result = today_service.regenerate_today_board(brand.id)

        assert result.status == "accepted"
        assert result.job_id is not None
        assert result.poll_url == f"/api/brands/{brand.id}/today/"

    def test_regenerate_enqueues_live_mode_when_apify_enabled(self, brand: Brand):
        """POST /regenerate with APIFY_ENABLED=True uses live_cap_limited mode."""
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        BrandBrainSnapshot.objects.create(
            brand=brand,
            snapshot_json={"positioning": "test"},
            diff_from_previous_json={},
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result = today_service.regenerate_today_board(brand.id)

            job = OpportunitiesJob.objects.get(id=result.job_id)
            assert job.params_json["mode"] == "live_cap_limited"
            assert job.params_json["force"] is True
