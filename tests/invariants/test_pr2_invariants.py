"""
PR-2 Invariant Tests.

Per opportunities_v1_prd.md Section C.4 + F.1 (PR-2 why_now + evidence_ids contract).

These tests verify:
1. why_now is REQUIRED for all opportunities in READY boards (>= 10 chars)
2. Drafts with missing/short why_now are NOT persisted
3. evidence_ids exists on every opportunity DTO (may be empty until PR-4/5)
4. PR-1b flow still works (no regression)
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from kairo.core.enums import Channel, OpportunityType, TodayBoardState
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import OpportunityDraftDTO, OpportunityDTO


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="PR2 Test Tenant",
        slug="pr2-test-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="PR2 Test Brand",
        positioning="Testing PR-2 why_now invariants",
    )


def _create_evidence_item(brand, suffix: str, with_transcript: bool = False):
    """Helper to create a NormalizedEvidenceItem with correct fields."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    return NormalizedEvidenceItem.objects.create(
        brand=brand,
        platform="instagram",
        content_type="post",
        external_id=f"pr2_ext_{suffix}",
        canonical_url=f"https://instagram.com/p/{suffix}",
        published_at="2024-01-01T00:00:00Z",
        author_ref=f"pr2_author_{suffix}",
        title=None,
        text_primary=f"Test content for {suffix} with enough text to be meaningful",
        text_secondary="Sample transcript text" if with_transcript else None,
        hashtags=["test", "pr2"],
        metrics_json={"likes": 100},
        media_json={},
        raw_refs=[],
        flags_json={"has_transcript": with_transcript},
    )


def _create_brandbrain_snapshot(brand):
    """Helper to create a BrandBrainSnapshot for testing."""
    from kairo.brandbrain.models import BrandBrainSnapshot
    return BrandBrainSnapshot.objects.create(
        brand=brand,
        snapshot_json={
            "positioning": "Test positioning",
            "tone_tags": ["professional"],
            "taboos": [],
            "persona_ids": [],
            "pillar_ids": [],
        },
        diff_from_previous_json={},
    )


# =============================================================================
# Test 1 - why_now Required for Persistence
# Per PRD Section C.4: why_now must be >= 10 chars
# =============================================================================


class TestWhyNowRequiredForPersistence:
    """Verify why_now validation during persistence."""

    def test_draft_with_valid_why_now_is_persisted(self, brand):
        """Draft with valid why_now (>= 10 chars) is persisted."""
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity with Valid Why Now",
            proposed_angle="A good angle for testing",
            why_now="This is a valid why_now with more than 10 characters explaining timing.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
        )

        # PR-4b: evidence_ids is now required for persistence
        evidence_ids = [uuid.uuid4(), uuid.uuid4()]
        opportunities = _persist_opportunities(brand, [draft], uuid.uuid4(), evidence_ids=evidence_ids)

        assert len(opportunities) == 1
        assert opportunities[0].metadata.get("why_now") == draft.why_now.strip()

    def test_draft_with_short_why_now_is_skipped(self, brand):
        """Draft with short why_now (< 10 chars) is NOT persisted."""
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity with Short Why Now",
            proposed_angle="A good angle for testing",
            why_now="Short",  # Only 5 chars - should be skipped
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
        )

        opportunities = _persist_opportunities(brand, [draft], uuid.uuid4())

        assert len(opportunities) == 0, "Draft with short why_now should not be persisted"

    def test_draft_with_empty_why_now_is_skipped(self, brand):
        """Draft with empty why_now is NOT persisted."""
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity with Empty Why Now",
            proposed_angle="A good angle for testing",
            why_now="",  # Empty - should be skipped
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
        )

        opportunities = _persist_opportunities(brand, [draft], uuid.uuid4())

        assert len(opportunities) == 0, "Draft with empty why_now should not be persisted"

    def test_draft_with_none_why_now_is_skipped(self, brand):
        """Draft with None why_now is NOT persisted."""
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity with None Why Now",
            proposed_angle="A good angle for testing",
            why_now=None,  # None - should be skipped
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
        )

        opportunities = _persist_opportunities(brand, [draft], uuid.uuid4())

        assert len(opportunities) == 0, "Draft with None why_now should not be persisted"

    def test_draft_with_whitespace_only_why_now_is_skipped(self, brand):
        """Draft with whitespace-only why_now is NOT persisted."""
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity with Whitespace Why Now",
            proposed_angle="A good angle for testing",
            why_now="          ",  # Only whitespace - should be skipped after strip
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
        )

        opportunities = _persist_opportunities(brand, [draft], uuid.uuid4())

        assert len(opportunities) == 0, "Draft with whitespace-only why_now should not be persisted"


# =============================================================================
# Test 2 - why_now Present in DTO
# Per PRD Section C.4: Every opportunity in READY board must have why_now
# =============================================================================


@pytest.mark.django_db
class TestWhyNowPresentInDTO:
    """Verify why_now is present in OpportunityDTO."""

    def test_opportunity_dto_requires_why_now(self):
        """OpportunityDTO requires why_now field."""
        from datetime import datetime, timezone
        from pydantic import ValidationError

        # Should raise ValidationError without why_now
        with pytest.raises(ValidationError) as exc_info:
            OpportunityDTO(
                id=uuid.uuid4(),
                brand_id=uuid.uuid4(),
                title="Test",
                angle="Test angle",
                # why_now is missing
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        # Error should mention why_now
        assert "why_now" in str(exc_info.value).lower()

    def test_opportunity_dto_rejects_short_why_now(self):
        """OpportunityDTO rejects why_now < 10 chars."""
        from datetime import datetime, timezone
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            OpportunityDTO(
                id=uuid.uuid4(),
                brand_id=uuid.uuid4(),
                title="Test",
                angle="Test angle",
                why_now="Short",  # Only 5 chars
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        # Error should be about string length
        error_str = str(exc_info.value).lower()
        assert "why_now" in error_str or "min_length" in error_str

    def test_opportunity_dto_accepts_valid_why_now(self):
        """OpportunityDTO accepts valid why_now >= 10 chars."""
        from datetime import datetime, timezone

        dto = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            title="Test",
            angle="Test angle",
            why_now="This is a valid why_now with sufficient length.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert dto.why_now == "This is a valid why_now with sufficient length."


# =============================================================================
# Test 3 - evidence_ids Forward Compatibility
# Per PRD: evidence_ids exists but may be empty until PR-4/5
# =============================================================================


@pytest.mark.django_db
class TestEvidenceIdsForwardCompat:
    """Verify evidence_ids field exists and allows empty list."""

    def test_opportunity_dto_has_evidence_ids_field(self):
        """OpportunityDTO has evidence_ids field."""
        from datetime import datetime, timezone

        dto = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            title="Test",
            angle="Test angle",
            why_now="Valid why_now with timing justification.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # evidence_ids should exist and be a list
        assert hasattr(dto, "evidence_ids")
        assert isinstance(dto.evidence_ids, list)

    def test_opportunity_dto_evidence_ids_defaults_to_empty(self):
        """evidence_ids defaults to empty list."""
        from datetime import datetime, timezone

        dto = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            title="Test",
            angle="Test angle",
            why_now="Valid why_now with timing justification.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert dto.evidence_ids == []

    def test_opportunity_dto_evidence_ids_accepts_uuids(self):
        """evidence_ids accepts list of UUIDs."""
        from datetime import datetime, timezone

        eid1 = uuid.uuid4()
        eid2 = uuid.uuid4()

        dto = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            title="Test",
            angle="Test angle",
            why_now="Valid why_now with timing justification.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            evidence_ids=[eid1, eid2],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert len(dto.evidence_ids) == 2
        assert eid1 in dto.evidence_ids
        assert eid2 in dto.evidence_ids

    def test_persisted_opportunity_has_evidence_ids_in_metadata(self, brand):
        """Persisted opportunity has evidence_ids in metadata."""
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity with Evidence IDs",
            proposed_angle="A good angle for testing",
            why_now="Valid why_now explaining the timing rationale.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
        )

        # PR-4b: evidence_ids is now required for persistence (min_length=1)
        evidence_ids = [uuid.uuid4(), uuid.uuid4()]
        opportunities = _persist_opportunities(brand, [draft], uuid.uuid4(), evidence_ids=evidence_ids)

        assert len(opportunities) == 1
        metadata = opportunities[0].metadata
        assert "evidence_ids" in metadata
        assert isinstance(metadata["evidence_ids"], list)
        # PR-4b: evidence_ids is now non-empty (required per PRD §F.1)
        assert len(metadata["evidence_ids"]) == 2


# =============================================================================
# Test 4 - Full Flow Integration (No Regression from PR-1b)
# =============================================================================


@pytest.mark.django_db
class TestFullFlowWithWhyNow:
    """Verify full flow still works with why_now requirements."""

    def test_ready_board_opportunities_have_valid_why_now(self, brand):
        """READY board opportunities have valid why_now."""
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.tasks.generate import execute_opportunities_job
        from kairo.hero.services import today_service
        from kairo.hero.jobs.queue import enqueue_opportunities_job

        # Setup: Create BrandBrainSnapshot and evidence
        _create_brandbrain_snapshot(brand)
        for i in range(10):
            _create_evidence_item(brand, f"fullflow_pr2_{i}", with_transcript=(i < 5))

        # Clean slate
        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # Enqueue and execute job
        result = enqueue_opportunities_job(brand.id)
        execute_opportunities_job(result.job_id, brand.id)

        # Get board
        board_dto = today_service.get_today_board(brand.id)

        # If READY, all opportunities must have valid why_now
        if board_dto.meta.state == TodayBoardState.READY:
            assert len(board_dto.opportunities) > 0, "READY board should have opportunities"

            for opp in board_dto.opportunities:
                # PR-2: Every opportunity must have valid why_now
                assert hasattr(opp, "why_now"), "Opportunity missing why_now field"
                assert opp.why_now is not None, "Opportunity why_now is None"
                assert len(opp.why_now.strip()) >= 10, (
                    f"Opportunity why_now too short: '{opp.why_now}' ({len(opp.why_now.strip())} chars)"
                )

                # PR-2: Every opportunity must have evidence_ids field
                assert hasattr(opp, "evidence_ids"), "Opportunity missing evidence_ids field"
                assert isinstance(opp.evidence_ids, list), "evidence_ids must be a list"

    def test_stub_opportunities_have_valid_why_now(self, brand):
        """Stub (degraded mode) opportunities have valid why_now."""
        from kairo.hero.engines.opportunities_engine import _generate_stub_opportunities

        stubs = _generate_stub_opportunities(brand, uuid.uuid4())

        assert len(stubs) > 0, "Should generate stub opportunities"

        for stub in stubs:
            metadata = stub.metadata or {}
            why_now = metadata.get("why_now", "")

            assert why_now, f"Stub '{stub.title}' missing why_now"
            assert len(why_now.strip()) >= 10, (
                f"Stub '{stub.title}' has short why_now: '{why_now}'"
            )

            # Forward-compat check
            assert "evidence_ids" in metadata, f"Stub '{stub.title}' missing evidence_ids"


# =============================================================================
# Test 5 - API Contract Verification
# =============================================================================


@pytest.mark.django_db
class TestAPIContractWhyNow:
    """Verify API contract includes why_now and evidence_ids."""

    def test_get_today_response_includes_why_now(self, client, brand):
        """GET /today response includes why_now for each opportunity."""
        from kairo.hero.models import OpportunitiesBoard, OpportunitiesJob
        from kairo.hero.tasks.generate import execute_opportunities_job
        from kairo.hero.jobs.queue import enqueue_opportunities_job

        # Setup
        _create_brandbrain_snapshot(brand)
        for i in range(10):
            _create_evidence_item(brand, f"api_pr2_{i}", with_transcript=(i < 5))

        OpportunitiesBoard.objects.filter(brand_id=brand.id).delete()
        OpportunitiesJob.objects.filter(brand_id=brand.id).delete()

        # Enqueue and execute
        result = enqueue_opportunities_job(brand.id)
        execute_opportunities_job(result.job_id, brand.id)

        # Make GET request
        response = client.get(f"/api/brands/{brand.id}/today/")
        assert response.status_code == 200

        data = response.json()

        # If state is READY, check opportunities
        if data["meta"]["state"] == "ready":
            assert len(data["opportunities"]) > 0

            for opp in data["opportunities"]:
                # PR-2: why_now must be present
                assert "why_now" in opp, f"Opportunity missing why_now: {opp.get('title')}"
                assert len(opp["why_now"]) >= 10, f"Opportunity why_now too short"

                # PR-2: evidence_ids must be present (may be empty)
                assert "evidence_ids" in opp, f"Opportunity missing evidence_ids"
                assert isinstance(opp["evidence_ids"], list)
