"""
PR-5 Invariant Tests.

Per opportunities_v1_prd.md Section I.5: Evidence Preview Read-Time Join.

Test Categories:
1. Single query for all evidence previews (no N+1)
2. Stable ordering (preview order matches evidence_ids order)
3. Correct truncation (text_snippet <= 200 chars)
4. Missing evidence ID raises invariant violation
5. Read-only (GET does not trigger SourceActivation)
6. OpportunityDTO includes evidence_preview field

CRITICAL: These tests enforce that:
- GET /today remains read-only
- Evidence previews are derived at read-time, not stored in Opportunity
- Missing evidence IDs are loud failures (no silent skipping)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from kairo.core.enums import Channel, OpportunityType, TodayBoardState
from kairo.core.models import Brand, Opportunity
from kairo.hero.models import (
    ActivationRun,
    EvidenceItem,
    OpportunitiesBoard,
    OpportunitiesJob,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="PR5 Test Tenant",
        slug="pr5-test-tenant",
    )


@pytest.fixture
def brand(tenant) -> Brand:
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="PR5 Test Brand",
        slug="pr5-test-brand",
        positioning="Test positioning for PR-5",
    )


@pytest.fixture
def job(brand: Brand) -> OpportunitiesJob:
    """Create a test job."""
    return OpportunitiesJob.objects.create(
        brand=brand,
        status="completed",
    )


@pytest.fixture
def activation_run(brand: Brand, job: OpportunitiesJob) -> ActivationRun:
    """Create a test activation run."""
    return ActivationRun.objects.create(
        brand_id=brand.id,
        job=job,
        snapshot_id=brand.id,  # Use brand_id as snapshot for simplicity
        seed_pack_json={"sources": []},
    )


def _create_evidence_items(
    brand: Brand,
    activation_run: ActivationRun,
    count: int = 3,
    text_length: int = 100,
) -> list[EvidenceItem]:
    """Create test evidence items."""
    now = datetime.now(timezone.utc)
    items = []
    for i in range(count):
        # Create text of specified length for truncation tests
        text_primary = f"Evidence item {i}: " + "x" * (text_length - len(f"Evidence item {i}: "))

        item = EvidenceItem.objects.create(
            id=uuid.uuid4(),
            activation_run=activation_run,
            brand_id=brand.id,
            platform="instagram" if i % 2 == 0 else "tiktok",
            actor_id="TEST_ACTOR",
            acquisition_stage=1,
            recipe_id="IG-1" if i % 2 == 0 else "TT-1",
            canonical_url=f"https://example.com/content/{i}",
            external_id=f"ext_{i}",
            author_ref=f"@author_{i}",
            title=f"Test Content {i}",
            text_primary=text_primary,
            text_secondary=f"Transcript {i}" if i % 2 == 0 else "",
            has_transcript=i % 2 == 0,
            view_count=10000 * (i + 1),
            like_count=1000 * (i + 1),
            published_at=now - timedelta(days=i),
            fetched_at=now,  # Required field
        )
        items.append(item)
    return items


def _create_opportunity_with_evidence(
    brand: Brand,
    evidence_ids: list[UUID],
    title: str = "Test Opportunity",
) -> Opportunity:
    """Create an opportunity with evidence_ids in metadata."""
    return Opportunity.objects.create(
        brand=brand,
        title=title,
        angle="Test angle for opportunity",
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=80.0,
        source="test",
        metadata={
            "why_now": "Market trends show high engagement with this topic area for testing.",
            "evidence_ids": [str(eid) for eid in evidence_ids],
        },
    )


def _create_board_with_opportunities(
    brand: Brand,
    opportunity_ids: list[UUID],
) -> OpportunitiesBoard:
    """Create an OpportunitiesBoard with opportunity IDs."""
    return OpportunitiesBoard.objects.create(
        brand=brand,
        state=TodayBoardState.READY,
        opportunity_ids=[str(oid) for oid in opportunity_ids],
    )


# =============================================================================
# Test 1 - Single Query for Evidence Previews (No N+1)
# =============================================================================


@pytest.mark.django_db
class TestSingleQueryForPreviews:
    """
    PR-5: Evidence previews must be fetched in a single batched query.

    Per PRD §I.5: "Single query per board to fetch all previews."
    No N+1 queries allowed regardless of number of opportunities or evidence items.
    """

    def test_single_query_for_multiple_opportunities(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Board with multiple opportunities uses single evidence query."""
        # Create evidence items
        evidence_items = _create_evidence_items(brand, activation_run, count=6)

        # Create multiple opportunities, each with different evidence
        opp1 = _create_opportunity_with_evidence(
            brand, [evidence_items[0].id, evidence_items[1].id], "Opportunity 1"
        )
        opp2 = _create_opportunity_with_evidence(
            brand, [evidence_items[2].id, evidence_items[3].id], "Opportunity 2"
        )
        opp3 = _create_opportunity_with_evidence(
            brand, [evidence_items[4].id, evidence_items[5].id], "Opportunity 3"
        )

        # Create board
        board = _create_board_with_opportunities(
            brand, [opp1.id, opp2.id, opp3.id]
        )

        # Count queries during to_dto()
        with CaptureQueriesContext(connection) as context:
            dto = board.to_dto()

        # Verify DTOs have previews
        assert len(dto.opportunities) == 3
        for opp_dto in dto.opportunities:
            assert len(opp_dto.evidence_preview) == 2

        # Count evidence-related queries
        # Should be: 1 for opportunities, 1 for evidence (not N+1)
        evidence_queries = [
            q for q in context.captured_queries
            if "hero_evidence_item" in q["sql"].lower()
        ]
        assert len(evidence_queries) == 1, (
            f"Expected single evidence query, got {len(evidence_queries)}. "
            "This indicates N+1 query bug."
        )

    def test_no_evidence_query_when_no_opportunities(
        self, brand: Brand
    ):
        """Board with no opportunities should not query evidence table."""
        board = _create_board_with_opportunities(brand, [])

        with CaptureQueriesContext(connection) as context:
            dto = board.to_dto()

        assert len(dto.opportunities) == 0

        evidence_queries = [
            q for q in context.captured_queries
            if "hero_evidence_item" in q["sql"].lower()
        ]
        assert len(evidence_queries) == 0


# =============================================================================
# Test 2 - Stable Ordering
# =============================================================================


@pytest.mark.django_db
class TestStableOrdering:
    """
    PR-5: evidence_preview order must match evidence_ids order.

    Per PRD §I.5: "Ordering is stable. evidence_preview must be in the
    same order as evidence_ids (per opportunity)."
    """

    def test_preview_order_matches_evidence_ids_order(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Previews are returned in same order as evidence_ids."""
        evidence_items = _create_evidence_items(brand, activation_run, count=4)

        # Deliberately order IDs in non-alphabetical, non-creation order
        ordered_ids = [
            evidence_items[2].id,
            evidence_items[0].id,
            evidence_items[3].id,
            evidence_items[1].id,
        ]

        opp = _create_opportunity_with_evidence(brand, ordered_ids)
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()

        assert len(dto.opportunities) == 1
        opp_dto = dto.opportunities[0]

        # Verify order matches
        assert len(opp_dto.evidence_preview) == 4
        for i, (expected_id, preview) in enumerate(zip(ordered_ids, opp_dto.evidence_preview)):
            assert preview.id == expected_id, (
                f"Position {i}: expected {expected_id}, got {preview.id}. "
                "Preview order must match evidence_ids order."
            )

    def test_multiple_opportunities_have_independent_ordering(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Each opportunity has its own evidence order preserved."""
        evidence_items = _create_evidence_items(brand, activation_run, count=4)

        # Two opportunities with different orderings
        opp1_ids = [evidence_items[0].id, evidence_items[1].id]
        opp2_ids = [evidence_items[1].id, evidence_items[0].id]  # Reversed

        opp1 = _create_opportunity_with_evidence(brand, opp1_ids, "Opp 1")
        opp2 = _create_opportunity_with_evidence(brand, opp2_ids, "Opp 2")

        board = _create_board_with_opportunities(brand, [opp1.id, opp2.id])
        dto = board.to_dto()

        # Find opportunities by title
        opp1_dto = next(o for o in dto.opportunities if o.title == "Opp 1")
        opp2_dto = next(o for o in dto.opportunities if o.title == "Opp 2")

        # Verify opp1 order
        assert [p.id for p in opp1_dto.evidence_preview] == opp1_ids

        # Verify opp2 order (reversed)
        assert [p.id for p in opp2_dto.evidence_preview] == opp2_ids


# =============================================================================
# Test 3 - Correct Truncation
# =============================================================================


@pytest.mark.django_db
class TestTextSnippetTruncation:
    """
    PR-5: text_snippet must be first 200 chars of text_primary.

    Per PRD §I.5: "text_snippet = first 200 chars of text_primary (strip whitespace)"
    """

    def test_short_text_not_truncated(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Text shorter than 200 chars is not truncated."""
        items = _create_evidence_items(brand, activation_run, count=1, text_length=50)

        opp = _create_opportunity_with_evidence(brand, [items[0].id])
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()

        preview = dto.opportunities[0].evidence_preview[0]
        assert len(preview.text_snippet) == 50
        assert "..." not in preview.text_snippet

    def test_long_text_truncated_to_200_chars_plus_ellipsis(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Text longer than 200 chars is truncated with ellipsis."""
        items = _create_evidence_items(brand, activation_run, count=1, text_length=300)

        opp = _create_opportunity_with_evidence(brand, [items[0].id])
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()

        preview = dto.opportunities[0].evidence_preview[0]
        # Should be 200 chars + "..." = max 203
        assert len(preview.text_snippet) <= 203
        assert preview.text_snippet.endswith("...")

    def test_exactly_200_chars_not_truncated(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Text exactly 200 chars is not truncated."""
        items = _create_evidence_items(brand, activation_run, count=1, text_length=200)

        opp = _create_opportunity_with_evidence(brand, [items[0].id])
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()

        preview = dto.opportunities[0].evidence_preview[0]
        assert len(preview.text_snippet) == 200
        assert "..." not in preview.text_snippet


# =============================================================================
# Test 4 - Missing Evidence ID Raises Invariant Violation
# =============================================================================


@pytest.mark.django_db
class TestMissingEvidenceIdViolation:
    """
    PR-5: Missing evidence_id must raise ValueError, not silently skip.

    Per PRD §I.5: "If an evidence_id is missing in DB, do not silently drop it.
    Option A (preferred): raise ValueError invariant violation."
    """

    def test_missing_evidence_id_raises_value_error(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Missing evidence_id in opportunity raises ValueError."""
        real_items = _create_evidence_items(brand, activation_run, count=1)

        # Include a fake ID that doesn't exist
        fake_id = uuid.uuid4()
        opp = _create_opportunity_with_evidence(
            brand, [real_items[0].id, fake_id]
        )
        board = _create_board_with_opportunities(brand, [opp.id])

        with pytest.raises(ValueError) as exc_info:
            board.to_dto()

        assert "PR-5 invariant violation" in str(exc_info.value)
        assert str(fake_id) in str(exc_info.value)

    def test_all_evidence_ids_missing_raises_value_error(
        self, brand: Brand
    ):
        """All evidence_ids missing raises ValueError."""
        fake_ids = [uuid.uuid4(), uuid.uuid4()]
        opp = _create_opportunity_with_evidence(brand, fake_ids)
        board = _create_board_with_opportunities(brand, [opp.id])

        with pytest.raises(ValueError) as exc_info:
            board.to_dto()

        assert "PR-5 invariant violation" in str(exc_info.value)


# =============================================================================
# Test 5 - Read-Only (GET Does Not Trigger SourceActivation)
# =============================================================================


@pytest.mark.django_db
class TestReadOnlyInvariant:
    """
    PR-5: GET /today must remain read-only.

    Per PRD §I.5: "GET /today remains read-only. No LLM calls, no SourceActivation,
    no Apify, no job creation beyond the already-allowed 'first visit enqueue'."
    """

    def test_to_dto_does_not_call_sourceactivation(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """to_dto() does not trigger SourceActivation."""
        evidence_items = _create_evidence_items(brand, activation_run, count=2)
        opp = _create_opportunity_with_evidence(brand, [e.id for e in evidence_items])
        board = _create_board_with_opportunities(brand, [opp.id])

        with patch(
            "kairo.sourceactivation.services.get_or_create_evidence_bundle"
        ) as mock_sa:
            dto = board.to_dto()

        mock_sa.assert_not_called()

    def test_to_dto_does_not_call_engine(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """to_dto() does not trigger opportunities engine."""
        evidence_items = _create_evidence_items(brand, activation_run, count=2)
        opp = _create_opportunity_with_evidence(brand, [e.id for e in evidence_items])
        board = _create_board_with_opportunities(brand, [opp.id])

        with patch(
            "kairo.hero.engines.opportunities_engine.generate_today_board"
        ) as mock_engine:
            dto = board.to_dto()

        mock_engine.assert_not_called()

    def test_to_dto_does_not_call_llm(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """to_dto() does not make LLM calls."""
        evidence_items = _create_evidence_items(brand, activation_run, count=2)
        opp = _create_opportunity_with_evidence(brand, [e.id for e in evidence_items])
        board = _create_board_with_opportunities(brand, [opp.id])

        # Patch the LLMClient class to ensure no instances are created
        with patch("kairo.hero.llm_client.LLMClient") as mock_llm_cls:
            dto = board.to_dto()

        mock_llm_cls.assert_not_called()


# =============================================================================
# Test 6 - EvidencePreviewDTO Structure
# =============================================================================


@pytest.mark.django_db
class TestEvidencePreviewDTOStructure:
    """
    PR-5: EvidencePreviewDTO must have correct fields.

    Per PRD §F.1: id, platform, canonical_url, author_ref, text_snippet, has_transcript
    """

    def test_preview_has_all_required_fields(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Preview contains all required fields from PRD."""
        items = _create_evidence_items(brand, activation_run, count=1)
        opp = _create_opportunity_with_evidence(brand, [items[0].id])
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()
        preview = dto.opportunities[0].evidence_preview[0]

        # Check all PRD-required fields exist and have correct types
        assert isinstance(preview.id, UUID)
        assert isinstance(preview.platform, str)
        assert isinstance(preview.canonical_url, str)
        assert isinstance(preview.author_ref, str)
        assert isinstance(preview.text_snippet, str)
        assert isinstance(preview.has_transcript, bool)

    def test_preview_values_match_evidence_item(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """Preview values match the source EvidenceItem."""
        items = _create_evidence_items(brand, activation_run, count=1)
        item = items[0]

        opp = _create_opportunity_with_evidence(brand, [item.id])
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()
        preview = dto.opportunities[0].evidence_preview[0]

        assert preview.id == item.id
        assert preview.platform == item.platform
        assert preview.canonical_url == item.canonical_url
        assert preview.author_ref == item.author_ref
        assert preview.has_transcript == item.has_transcript


# =============================================================================
# Test 7 - OpportunityDTO Has evidence_preview Field
# =============================================================================


@pytest.mark.django_db
class TestOpportunityDTOEvidencePreviewField:
    """
    PR-5: OpportunityDTO must include evidence_preview field.
    """

    def test_opportunity_dto_has_evidence_preview_field(self):
        """OpportunityDTO class has evidence_preview field."""
        from kairo.hero.dto import OpportunityDTO

        assert hasattr(OpportunityDTO.model_fields, "evidence_preview") or "evidence_preview" in OpportunityDTO.model_fields

    def test_evidence_preview_defaults_to_empty_list(self):
        """evidence_preview defaults to empty list if not provided."""
        from datetime import datetime, timezone
        from kairo.hero.dto import OpportunityDTO

        opp = OpportunityDTO(
            id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            title="Test",
            angle="Test angle",
            why_now="Valid why now for testing the evidence preview field.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert opp.evidence_preview == []

    def test_evidence_preview_serializes_correctly(
        self, brand: Brand, job: OpportunitiesJob, activation_run: ActivationRun
    ):
        """evidence_preview serializes and deserializes correctly."""
        from kairo.hero.dto import TodayBoardDTO

        items = _create_evidence_items(brand, activation_run, count=2)
        opp = _create_opportunity_with_evidence(brand, [e.id for e in items])
        board = _create_board_with_opportunities(brand, [opp.id])

        dto = board.to_dto()

        # Serialize and deserialize
        serialized = dto.model_dump(mode="json")
        deserialized = TodayBoardDTO.model_validate(serialized)

        # Verify previews survived round-trip
        assert len(deserialized.opportunities) == 1
        assert len(deserialized.opportunities[0].evidence_preview) == 2
