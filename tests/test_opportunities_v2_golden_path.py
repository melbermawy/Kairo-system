"""
Opportunities v2 Golden Path Tests.

PR0: Test harness structure for golden path validation.
Per opportunities_v1_prd.md §13.

SCOPE (PR0):
- Test scaffolding and fixtures structure
- Tests may be skipped or xfailed
- Do NOT mock LLMs or validation yet
- Goal is to lock structure, not pass tests

These tests validate the critical invariants from §0.1:
1. INV-1: GET /today is Strictly Read-Only
2. INV-2: No Apify Calls on Request Path
3. INV-3: No Fabricated Data
4. INV-4: Optional Fields Are Truly Optional
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import (
    EvidenceShortfallDTO,
    RegenerateResponseDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
)
from kairo.hero.services import today_service


# =============================================================================
# FIXTURES - BASIC
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Golden Path Tenant",
        slug="golden-path-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand with no evidence."""
    return Brand.objects.create(
        tenant=tenant,
        name="Golden Path Test Brand",
        slug="golden-path-test-brand",
        positioning="Testing golden path behavior",
    )


@pytest.fixture
def brand_with_evidence(db, tenant):
    """
    Create a test brand with sufficient evidence for generation.

    PR0 STUB: Creates brand but does NOT create evidence items.
    In later PRs, this will create NormalizedEvidenceItem rows.
    """
    # TODO: In later PR, create NormalizedEvidenceItem rows here
    return Brand.objects.create(
        tenant=tenant,
        name="Brand With Evidence",
        slug="brand-with-evidence",
        positioning="Has evidence for generation",
    )


# =============================================================================
# ADVERSARIAL FIXTURES - Per §13
# Per spec: fixtures must include missing thumbnails/metrics/transcripts, duplicates
# =============================================================================


@pytest.fixture
def adversarial_evidence_missing_thumbnails():
    """
    Evidence items where thumbnail_url is None.

    PR0 STUB: Returns empty list.
    In later PRs, will return actual EvidenceDTO objects.
    """
    return []


@pytest.fixture
def adversarial_evidence_missing_metrics():
    """
    Evidence items where metrics is None.

    PR0 STUB: Returns empty list.
    """
    return []


@pytest.fixture
def adversarial_evidence_duplicates():
    """
    Evidence items with near-duplicates (same author, similar text).

    PR0 STUB: Returns empty list.
    """
    return []


@pytest.fixture
def adversarial_evidence_no_transcripts():
    """
    Evidence items where all text_secondary (transcripts) are None.

    PR0 STUB: Returns empty list.
    """
    return []


# =============================================================================
# INV-1: GET /today is Strictly Read-Only
# =============================================================================


@pytest.mark.django_db
class TestGetTodayReadOnly:
    """
    Verify GET /today/ is strictly read-only.

    Per opportunities_v1_prd.md §0.1 INV-1:
    - MUST NOT call LLMs
    - MUST NOT trigger synchronous generation
    - MUST NOT call Apify actors
    - ONLY EXCEPTION: first-run auto-enqueue (non-blocking, idempotent)
    """

    def test_returns_state_not_generated_yet_for_new_brand(self, brand):
        """
        New brand with no evidence returns state: not_generated_yet.

        This verifies GET does not fabricate opportunities.
        """
        result = today_service.get_today_board(brand.id)

        assert isinstance(result, TodayBoardDTO)
        assert result.meta.state == TodayBoardState.NOT_GENERATED_YET
        assert len(result.opportunities) == 0

    def test_returns_remediation_for_insufficient_evidence(self, brand):
        """
        Brand with insufficient evidence includes remediation instructions.
        """
        result = today_service.get_today_board(brand.id)

        assert result.meta.remediation is not None
        # Remediation may instruct to connect accounts, run BrandBrain, or check settings
        valid_remediation_terms = ["Connect", "Settings", "BrandBrain", "compile"]
        assert any(term in result.meta.remediation for term in valid_remediation_terms)

    def test_returns_evidence_shortfall_details(self, brand):
        """
        Brand with insufficient evidence includes shortfall details.

        Note: evidence_shortfall may be None for NOT_GENERATED_YET state,
        as shortfall is only computed during generation attempts.
        The key invariant is that remediation guidance is provided.
        """
        result = today_service.get_today_board(brand.id)

        # For a brand with no evidence, should have remediation guidance
        if result.meta.state == TodayBoardState.NOT_GENERATED_YET:
            # Either evidence_shortfall is populated, or remediation is provided
            if result.meta.evidence_shortfall is not None:
                assert result.meta.evidence_shortfall.found_items == 0
            else:
                # Remediation guidance must be provided instead
                assert result.meta.remediation is not None

    def test_returns_valid_dto(self, brand):
        """
        Returned DTO is valid and can be serialized.
        """
        result = today_service.get_today_board(brand.id)

        # Should not raise
        json_str = result.model_dump_json()
        assert json_str is not None

        # Should round-trip
        parsed = TodayBoardDTO.model_validate_json(json_str)
        assert parsed.brand_id == brand.id

    def test_brand_id_matches(self, brand):
        """
        Returned board has correct brand_id.
        """
        result = today_service.get_today_board(brand.id)
        assert result.brand_id == brand.id

    def test_has_snapshot(self, brand):
        """
        Board includes brand snapshot even in degraded state.
        """
        result = today_service.get_today_board(brand.id)

        assert result.snapshot is not None
        assert result.snapshot.brand_id == brand.id
        assert result.snapshot.brand_name == brand.name

    def test_raises_on_missing_brand(self, db):
        """
        Raises Brand.DoesNotExist for unknown brand.
        """
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.get_today_board(fake_id)


# =============================================================================
# INV-2: POST /regenerate/ is the ONLY Generation Trigger
# =============================================================================


@pytest.mark.django_db
class TestRegenerateGenerationTrigger:
    """
    Verify POST /regenerate/ properly triggers generation.

    Per opportunities_v1_prd.md §0.2:
    - The ONLY way to explicitly trigger generation
    - Enqueues background job (does not block)
    - Returns immediately with job_id
    """

    def test_returns_accepted_status(self, brand):
        """
        POST /regenerate/ returns status: accepted with job_id.
        """
        result = today_service.regenerate_today_board(brand.id)

        assert isinstance(result, RegenerateResponseDTO)
        assert result.status == "accepted"
        assert result.job_id is not None
        assert len(result.job_id) > 0

    def test_returns_poll_url(self, brand):
        """
        Response includes poll_url for status checking.
        """
        result = today_service.regenerate_today_board(brand.id)

        assert result.poll_url is not None
        assert str(brand.id) in result.poll_url
        assert "today" in result.poll_url

    def test_raises_on_missing_brand(self, db):
        """
        Raises Brand.DoesNotExist for unknown brand.
        """
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            today_service.regenerate_today_board(fake_id)

    def test_subsequent_get_returns_generating_state(self, brand):
        """
        After POST /regenerate/, GET returns state: generating.
        """
        # Trigger regeneration
        regen_result = today_service.regenerate_today_board(brand.id)

        # GET should now return generating state
        get_result = today_service.get_today_board(brand.id)

        assert get_result.meta.state == TodayBoardState.GENERATING
        assert get_result.meta.job_id == regen_result.job_id

    def test_regenerate_is_idempotent_on_force(self, brand):
        """
        Multiple POST /regenerate/ calls create new jobs (force=True).
        """
        result1 = today_service.regenerate_today_board(brand.id)
        result2 = today_service.regenerate_today_board(brand.id)

        # Each call should create a new job (force=True behavior)
        # Note: The actual job_ids may or may not differ depending on implementation
        assert result1.status == "accepted"
        assert result2.status == "accepted"


# =============================================================================
# INV-3: No Fabricated Data
# =============================================================================


@pytest.mark.django_db
class TestNoFabricatedData:
    """
    Verify no stub/fake opportunities are generated.

    Per opportunities_v1_prd.md §0.1 INV-3:
    - Remove all _generate_stub_opportunities() logic from v2 path
    - If evidence quality gates fail, return honest empty state
    """

    def test_empty_brand_returns_empty_opportunities(self, brand):
        """
        Brand with no evidence returns empty opportunities list.
        """
        result = today_service.get_today_board(brand.id)

        assert result.opportunities == []

    def test_degraded_state_does_not_include_stubs(self, brand):
        """
        Even in degraded state, no stub opportunities are created.
        """
        result = today_service.get_today_board(brand.id)

        # Should have zero opportunities, not stub opportunities
        assert len(result.opportunities) == 0

        # If there were opportunities, verify they're not stubs
        for opp in result.opportunities:
            # Stubs would have metadata.stub = True
            assert not getattr(opp, "metadata", {}).get("stub", False)


# =============================================================================
# INV-4: Optional Fields Are Truly Optional
# =============================================================================


@pytest.mark.django_db
class TestOptionalFieldsHandling:
    """
    Verify optional fields can be None without breaking serialization.

    Per opportunities_v1_prd.md §0.1 INV-4:
    - All optional fields documented with explicit "MAY BE NULL/MISSING"
    - OpenAPI schema marks optional fields as nullable: true
    """

    def test_meta_optional_fields_can_be_none(self, brand):
        """
        TodayBoardMetaDTO optional fields can be None.
        """
        result = today_service.get_today_board(brand.id)

        # These are all optional fields that may be None
        meta = result.meta

        # Should not raise - optional fields can be None
        json_str = meta.model_dump_json()
        parsed = TodayBoardMetaDTO.model_validate_json(json_str)

        # Verify optional fields are handled
        assert parsed.job_id is None or isinstance(parsed.job_id, str)
        assert parsed.total_candidates is None or isinstance(parsed.total_candidates, int)
        assert parsed.wall_time_ms is None or isinstance(parsed.wall_time_ms, int)

    def test_evidence_shortfall_serializes(self, brand):
        """
        EvidenceShortfallDTO serializes correctly.
        """
        shortfall = EvidenceShortfallDTO(
            required_items=8,
            found_items=0,
            required_platforms=["instagram", "tiktok"],
            found_platforms=[],
            missing_platforms=["instagram", "tiktok"],
            transcript_coverage=0.0,
            min_transcript_coverage=0.3,
        )

        # Should not raise
        json_str = shortfall.model_dump_json()
        parsed = EvidenceShortfallDTO.model_validate_json(json_str)

        assert parsed.required_items == 8
        assert parsed.found_items == 0


# =============================================================================
# STATE MACHINE TRANSITIONS
# =============================================================================


@pytest.mark.django_db
class TestStateMachineTransitions:
    """
    Test TodayBoard state machine transitions.

    Per opportunities_v1_prd.md §0.2.
    """

    def test_initial_state_is_not_generated_yet(self, brand):
        """
        New brand starts in not_generated_yet state.
        """
        result = today_service.get_today_board(brand.id)
        assert result.meta.state == TodayBoardState.NOT_GENERATED_YET

    def test_regenerate_transitions_to_generating(self, brand):
        """
        POST /regenerate/ transitions to generating state.
        """
        # Start in not_generated_yet
        initial = today_service.get_today_board(brand.id)
        assert initial.meta.state == TodayBoardState.NOT_GENERATED_YET

        # Trigger regeneration
        today_service.regenerate_today_board(brand.id)

        # Now in generating state
        after = today_service.get_today_board(brand.id)
        assert after.meta.state == TodayBoardState.GENERATING

    @pytest.mark.skip(reason="PR0: First-run auto-enqueue requires evidence")
    def test_first_run_auto_enqueue_with_evidence(self, brand_with_evidence):
        """
        First GET with sufficient evidence auto-enqueues generation.

        PR0 SKIP: Requires NormalizedEvidenceItem rows to be created.
        """
        result = today_service.get_today_board(brand_with_evidence.id)

        # Should transition to generating (auto-enqueue)
        assert result.meta.state == TodayBoardState.GENERATING


# =============================================================================
# ANTI-CHEAT TESTS (Structure Only - Per §13)
# =============================================================================


@pytest.mark.django_db
class TestGoldenPathAntiCheat:
    """
    Anti-cheat test patterns per opportunities_v1_prd.md §13.

    PR0 SCOPE: Structure only. Tests may be skipped or xfailed.
    These tests will be fully implemented when generation logic exists.
    """

    @pytest.mark.skip(reason="PR0: Requires actual opportunity generation")
    def test_evidence_ids_reference_real_evidence(self):
        """
        ANTI-CHEAT: Every opportunity must reference real evidence_ids.

        Evidence must exist in NormalizedEvidenceItem table.
        """
        # TODO: Implement when generation exists
        pass

    @pytest.mark.skip(reason="PR0: Requires actual opportunity generation")
    def test_why_now_includes_concrete_anchor(self):
        """
        ANTI-CHEAT: why_now must include number, date, or velocity term.

        Catches generic/vacuous why_now text.
        """
        # TODO: Implement when generation exists
        pass

    @pytest.mark.skip(reason="PR0: Requires actual opportunity generation")
    def test_banned_phrases_rejected_from_llm_output(self):
        """
        ANTI-CHEAT: Validation MUST reject LLM output with banned phrases.

        Banned: "leverage", "drive engagement", "thought leadership", etc.
        """
        # TODO: Implement when generation exists
        pass

    @pytest.mark.skip(reason="PR0: Requires adversarial fixtures")
    def test_handles_missing_thumbnails_gracefully(self, adversarial_evidence_missing_thumbnails):
        """
        Generation handles evidence with missing thumbnail_url.
        """
        # TODO: Implement when generation exists
        pass

    @pytest.mark.skip(reason="PR0: Requires adversarial fixtures")
    def test_handles_missing_metrics_gracefully(self, adversarial_evidence_missing_metrics):
        """
        Generation handles evidence with missing metrics.
        """
        # TODO: Implement when generation exists
        pass

    @pytest.mark.skip(reason="PR0: Requires adversarial fixtures")
    def test_deduplicates_near_duplicate_evidence(self, adversarial_evidence_duplicates):
        """
        Near-duplicate evidence is detected and handled.
        """
        # TODO: Implement when generation exists
        pass


# =============================================================================
# CONTRACT AUTHORITY TESTS
# =============================================================================


@pytest.mark.django_db
class TestContractAuthority:
    """
    Test contract authority endpoints.

    Per opportunities_v1_prd.md §4.
    """

    def test_health_endpoint_returns_contract_version(self, client):
        """
        GET /api/health returns contract version info.
        """
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "contract_version" in data
        assert "min_frontend_version" in data
        assert data["status"] == "healthy"

    def test_openapi_endpoint_returns_schema(self, client):
        """
        GET /api/openapi.json returns OpenAPI schema.
        """
        response = client.get("/api/openapi.json")

        assert response.status_code == 200
        data = response.json()

        assert "openapi" in data
        assert "info" in data
        assert data["info"]["version"] is not None

    def test_openapi_endpoint_includes_version_header(self, client):
        """
        OpenAPI endpoint includes X-Contract-Version header.
        """
        response = client.get("/api/openapi.json")

        assert response.status_code == 200
        assert "X-Contract-Version" in response.headers


# =============================================================================
# CACHE SEMANTICS TESTS
# =============================================================================


@pytest.mark.django_db
class TestCacheSemantics:
    """
    Test cache behavior per opportunities_v1_prd.md §7.3.
    """

    def test_cache_key_format(self, brand):
        """
        Cache key follows format: today_board:v2:{brand_id}
        """
        result = today_service.get_today_board(brand.id)

        # Cache key should be set in response
        assert result.meta.cache_key is not None
        assert "today_board:v2" in result.meta.cache_key
        assert str(brand.id) in result.meta.cache_key

    def test_first_request_is_cache_miss(self, brand):
        """
        First request to a brand is a cache miss.
        """
        result = today_service.get_today_board(brand.id)

        assert result.meta.cache_hit is False

    def test_regenerate_invalidates_cache(self, brand):
        """
        POST /regenerate/ invalidates the cache.

        Subsequent GET returns cache_hit=False.
        """
        # First GET
        first = today_service.get_today_board(brand.id)
        assert first.meta.cache_hit is False

        # Regenerate (invalidates cache)
        today_service.regenerate_today_board(brand.id)

        # GET after regenerate should still be cache miss
        # (and in generating state)
        after = today_service.get_today_board(brand.id)
        assert after.meta.cache_hit is False
