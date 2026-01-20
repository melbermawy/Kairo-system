"""
Opportunities Engine integration tests for PR-8.

Tests verify:
- Engine calls graph and persists Opportunity rows
- Engine returns TodayBoardDTO matching persisted data
- Engine handles graph failures with degraded board
- Engine handles external signals failures gracefully
- All invariants from PRD are respected

Per PR-map-and-standards §PR-8:
- Patch graph to return known OpportunityDraft set
- Verify Opportunity rows exist after call
- Verify TodayBoardDTO matches persisted data
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel, OpportunityType
from kairo.core.models import Brand, ContentPillar, Opportunity, Persona, Tenant
from kairo.hero.dto import (
    OpportunityDraftDTO,
    TodayBoardDTO,
)
from kairo.hero.engines import opportunities_engine
from kairo.hero.graphs.opportunities_graph import GraphError


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="Integration Test Brand",
        slug="integration-test",
        positioning="A brand for integration testing",
        tone_tags=["professional", "technical"],
        taboos=["competitor mentions"],
    )


@pytest.fixture
def brand_with_personas_and_pillars(db, tenant):
    """Create a brand with personas and pillars for richer testing."""
    brand = Brand.objects.create(
        tenant=tenant,
        name="Full Context Brand",
        slug="full-context",
        positioning="Complete brand with all context",
        tone_tags=["insightful", "authoritative"],
        taboos=["controversial topics"],
    )

    # Create personas
    Persona.objects.create(
        brand=brand,
        name="Engineering Lead",
        role="Technical Decision Maker",
        summary="Senior engineer making architecture decisions",
    )
    Persona.objects.create(
        brand=brand,
        name="Product Manager",
        role="Product Owner",
        summary="PM balancing features and timelines",
    )

    # Create pillars
    ContentPillar.objects.create(
        brand=brand,
        name="Technical Deep Dives",
        description="In-depth technical content",
        priority_rank=1,
    )
    ContentPillar.objects.create(
        brand=brand,
        name="Industry Trends",
        description="Market and industry analysis",
        priority_rank=2,
    )

    return brand


@pytest.fixture
def sample_opportunity_drafts():
    """Sample OpportunityDraftDTO list for testing.

    PR-4c: Updated to include required why_now field.
    """
    return [
        OpportunityDraftDTO(
            proposed_title="AI Revolution in DevOps: A Deep Dive",
            proposed_angle="Exploring how AI is transforming CI/CD pipelines and deployment strategies.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=88.0,
            score_explanation="High relevance to technical audience",
            source="industry_report",
            why_now="Major AI announcements this week make this topic highly relevant and timely.",
        ),
        OpportunityDraftDTO(
            proposed_title="Weekly Engineering Insights",
            proposed_angle="Regular thought leadership showcasing technical expertise.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN],
            score=75.0,
            score_explanation="Consistent pillar coverage",
            why_now="Engineering teams actively seeking insights this quarter; high search volume.",
        ),
        OpportunityDraftDTO(
            proposed_title="Quick Tips: Kubernetes Best Practices",
            proposed_angle="Tactical thread format with actionable K8s advice.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.X,
            suggested_channels=[Channel.X],
            score=72.0,
            score_explanation="Good engagement format for X",
            why_now="K8s adoption trending up; practical tips format performing well on X.",
        ),
        OpportunityDraftDTO(
            proposed_title="Our Approach vs. Traditional Methods",
            proposed_angle="Clear differentiation showing our unique value proposition.",
            type=OpportunityType.COMPETITIVE,
            primary_channel=Channel.X,
            suggested_channels=[Channel.X, Channel.LINKEDIN],
            score=68.0,
            score_explanation="Competitive positioning",
            why_now="Competitor launched similar feature; opportunity to differentiate now.",
        ),
        OpportunityDraftDTO(
            proposed_title="Customer Success: Scaling to 10M Users",
            proposed_angle="Case study showcasing customer achievement.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN],
            score=70.0,
            score_explanation="Social proof content",
            why_now="Customer just hit milestone; fresh data for compelling case study content.",
        ),
        OpportunityDraftDTO(
            proposed_title="Industry Report Analysis",
            proposed_angle="Breaking down the latest market research with contrarian takes.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=80.0,
            score_explanation="Timely and relevant",
            why_now="Gartner released annual report yesterday; high visibility window this week.",
        ),
    ]


def _make_mock_evidence_bundle(brand_id):
    """Create a mock evidence bundle for integration tests."""
    from tests.fixtures.opportunity_factory import make_mock_evidence_bundle
    return make_mock_evidence_bundle(brand_id)


@pytest.fixture(autouse=True)
def mock_evidence_bundle():
    """
    Auto-mock _get_evidence_bundle_safe for all tests in this module.

    PR-4c: Since PR-4b requires a real OpportunitiesJob for evidence bundle,
    we mock the evidence bundle retrieval for tests that focus on other aspects.
    PR-6: Added mode parameter for live_cap_limited support.
    """
    def make_bundle(brand_id, run_id, mode="fixture_only"):
        return _make_mock_evidence_bundle(brand_id)

    with patch(
        "kairo.hero.engines.opportunities_engine._get_evidence_bundle_safe",
        side_effect=make_bundle,
    ):
        yield


# =============================================================================
# ENGINE + GRAPH INTEGRATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestEngineGraphIntegration:
    """Tests for engine + graph integration."""

    def test_engine_calls_graph_and_returns_board(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Engine calls graph and returns TodayBoardDTO."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert isinstance(result, TodayBoardDTO)
            assert result.brand_id == brand.id
            mock_graph.assert_called_once()

    def test_engine_persists_opportunity_rows(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Engine creates Opportunity rows in the database."""
        initial_count = Opportunity.objects.filter(brand=brand).count()

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            opportunities_engine.generate_today_board(brand.id)

            final_count = Opportunity.objects.filter(brand=brand).count()
            assert final_count >= initial_count + len(sample_opportunity_drafts)

    def test_engine_dto_matches_persisted_data(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """TodayBoardDTO opportunities match what was persisted."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Verify counts match
            assert len(result.opportunities) == len(sample_opportunity_drafts)

            # Verify titles match
            result_titles = {opp.title for opp in result.opportunities}
            draft_titles = {d.proposed_title for d in sample_opportunity_drafts}
            assert result_titles == draft_titles

    def test_engine_opportunities_sorted_by_score(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Returned opportunities are sorted by score descending."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            scores = [opp.score for opp in result.opportunities]
            assert scores == sorted(scores, reverse=True)

    def test_engine_persists_correct_fields(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Persisted Opportunity rows have correct field values."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            opportunities_engine.generate_today_board(brand.id)

            # Check one specific opportunity
            draft = sample_opportunity_drafts[0]
            opp = Opportunity.objects.filter(
                brand=brand,
                title=draft.proposed_title,
            ).first()

            assert opp is not None
            assert opp.angle == draft.proposed_angle
            assert opp.type == draft.type.value
            assert opp.primary_channel == draft.primary_channel.value
            assert opp.score == draft.score
            assert opp.score_explanation == draft.score_explanation

    def test_engine_idempotent_on_same_titles(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Same titles produce same opportunity IDs (idempotent)."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            # First call
            result1 = opportunities_engine.generate_today_board(brand.id)

            # Second call with same drafts
            result2 = opportunities_engine.generate_today_board(brand.id)

            # Should have same IDs
            ids1 = {opp.id for opp in result1.opportunities}
            ids2 = {opp.id for opp in result2.opportunities}
            assert ids1 == ids2

    def test_engine_metadata_has_success_status(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Successful generation has degraded=False in metadata."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.meta.degraded is False
            assert "Generated" in result.meta.notes[0]


# =============================================================================
# DEGRADED MODE TESTS
# =============================================================================


@pytest.mark.django_db
class TestDegradedMode:
    """Tests for degraded mode when graph fails."""

    def test_graph_error_returns_degraded_board(self, brand):
        """Graph failure returns degraded board, not exception."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("LLM timeout")

            result = opportunities_engine.generate_today_board(brand.id)

            # Should return a board, not raise
            assert isinstance(result, TodayBoardDTO)
            assert result.meta.degraded is True

    def test_degraded_board_has_opportunities(self, brand):
        """Degraded board still has opportunities (stubs or existing)."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Connection error")

            result = opportunities_engine.generate_today_board(brand.id)

            # Should have stub opportunities
            assert len(result.opportunities) >= 6

    def test_degraded_stub_opportunities_persisted_to_db(self, brand):
        """8c: Stub opportunities in degraded mode are persisted to DB."""
        # Clear any existing opportunities
        Opportunity.objects.filter(brand=brand).delete()

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Total failure")

            result = opportunities_engine.generate_today_board(brand.id)

            # Stubs should be in the result
            assert len(result.opportunities) >= 6
            assert result.meta.degraded is True

            # 8c KEY ASSERTION: Stubs must exist in DB
            db_opps = list(Opportunity.objects.filter(brand=brand))
            assert len(db_opps) >= 6, "Stub opportunities must be persisted to DB"

            # Verify we can look up each returned opp by ID
            for opp_dto in result.opportunities:
                db_opp = Opportunity.objects.filter(id=opp_dto.id).first()
                assert db_opp is not None, f"Opportunity {opp_dto.id} not found in DB"
                assert db_opp.title == opp_dto.title

    def test_degraded_stub_opportunities_have_stub_metadata(self, brand):
        """8c: Stub opportunities have metadata.stub=True for identification."""
        Opportunity.objects.filter(brand=brand).delete()

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Graph unavailable")

            result = opportunities_engine.generate_today_board(brand.id)

            # Check metadata on persisted stubs
            for opp_dto in result.opportunities:
                db_opp = Opportunity.objects.get(id=opp_dto.id)
                assert db_opp.metadata is not None
                assert db_opp.metadata.get("stub") is True, (
                    "Stub opportunities should have metadata.stub=True"
                )

    def test_degraded_stubs_can_be_used_by_content_engine(self, brand):
        """8c: F2 (content engine) can use degraded stub opportunities."""
        from kairo.hero.engines import content_engine

        Opportunity.objects.filter(brand=brand).delete()

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("LLM unavailable")

            result = opportunities_engine.generate_today_board(brand.id)

            # Get one of the stub opportunities
            stub_opp_id = result.opportunities[0].id

            # F2 should be able to look up this opportunity by ID
            # This is the key 8c test - previously this would raise DoesNotExist
            db_opp = Opportunity.objects.get(id=stub_opp_id)
            assert db_opp is not None
            assert db_opp.title == result.opportunities[0].title

            # Verify it can be passed to content_engine (just the lookup, not full generation)
            # The opportunity should exist and be usable
            assert db_opp.brand_id == brand.id
            assert db_opp.angle is not None
            assert db_opp.primary_channel in ["linkedin", "x"]

    def test_degraded_board_notes_explain_failure(self, brand):
        """Degraded board notes explain the failure."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Test failure message")

            result = opportunities_engine.generate_today_board(brand.id)

            # Notes should mention the failure
            notes_text = " ".join(result.meta.notes)
            assert "failed" in notes_text.lower() or "Graph" in notes_text

    def test_degraded_uses_existing_opportunities(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Degraded mode uses existing opportunities if available."""
        # First, create some opportunities via successful call
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts
            opportunities_engine.generate_today_board(brand.id)

        # Now simulate failure - should use existing
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("LLM unavailable")

            result = opportunities_engine.generate_today_board(brand.id)

            # Should have the previously created opportunities
            assert len(result.opportunities) >= len(sample_opportunity_drafts)

    def test_degraded_stubs_have_valid_structure(self, brand):
        """Stub opportunities in degraded mode have valid structure."""
        # Clear any existing opportunities
        Opportunity.objects.filter(brand=brand).delete()

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Total failure")

            result = opportunities_engine.generate_today_board(brand.id)

            for opp in result.opportunities:
                assert opp.title, "Stub must have title"
                assert opp.angle, "Stub must have angle"
                assert opp.primary_channel in {Channel.LINKEDIN, Channel.X}
                assert 0 <= opp.score <= 100

    def test_degraded_stubs_full_f2_package_creation(self, brand):
        """
        8c END-TO-END: Degraded F1 stubs can be used by F2 to create packages.

        This is the critical 8c test that proves:
        1. F1 degraded mode produces opportunities in DB
        2. F2 can successfully look them up by ID
        3. F2 can create packages from them (no DoesNotExist)

        Previously this would fail because stubs were in-memory only.
        """
        from kairo.hero.dto import ContentPackageDraftDTO
        from kairo.hero.engines import content_engine

        # Clear any existing opportunities
        Opportunity.objects.filter(brand=brand).delete()

        # Step 1: Run F1 in degraded mode (graph failure)
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("LLM unavailable for F1")

            f1_result = opportunities_engine.generate_today_board(brand.id)

            # Verify F1 returned degraded stubs
            assert f1_result.meta.degraded is True
            assert len(f1_result.opportunities) >= 6
            stub_opp = f1_result.opportunities[0]

        # Step 2: F2 creates package from the degraded stub opportunity
        # Mock the F2 graph to avoid LLM calls
        mock_package_draft = ContentPackageDraftDTO(
            title="Test Package from Stub Opportunity",
            thesis="Testing that degraded stubs can be used by F2 successfully.",
            summary="This package verifies the 8c fix for stub opportunity persistence.",
            primary_channel=Channel.LINKEDIN,
            channels=[Channel.LINKEDIN],
            is_valid=True,
            rejection_reasons=[],
            package_score=10.0,
            quality_band="board_ready",
        )
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=stub_opp.id,
            )

        # Step 3: Verify package was created successfully
        assert package is not None
        assert package.brand_id == brand.id
        assert package.origin_opportunity_id == stub_opp.id
        assert package.title is not None
        assert len(package.title) > 0

        # Package should be in DB
        from kairo.core.models import ContentPackage
        db_package = ContentPackage.objects.get(id=package.id)
        assert db_package.origin_opportunity_id == stub_opp.id

    def test_degraded_reason_code_is_populated(self, brand):
        """
        8c: Degraded board meta has non-empty reason code.
        """
        Opportunity.objects.filter(brand=brand).delete()

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Total graph failure")

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.meta.degraded is True
            assert result.meta.reason is not None
            assert len(result.meta.reason) > 0
            assert result.meta.reason == "graph_error"


# =============================================================================
# EXTERNAL DEPENDENCIES TESTS
# =============================================================================


@pytest.mark.django_db
class TestExternalDependencies:
    """Tests for handling external dependency failures."""

    def test_external_signals_failure_continues(
        self,
        brand,
        sample_opportunity_drafts,
        mock_evidence_bundle,  # Disable autouse for this specific test
    ):
        """SourceActivation evidence failure doesn't block generation (PR-4b).

        PR-4c: Updated from external_signals_service to _get_evidence_bundle_safe,
        since external signals are now sourced from EvidenceBundle.
        """
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph, patch(
            "kairo.hero.engines.opportunities_engine._get_evidence_bundle_safe"
        ) as mock_evidence:
            mock_evidence.return_value = None  # Simulate failure
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Should still return a board (degraded)
            assert isinstance(result, TodayBoardDTO)
            # Board may be degraded due to empty evidence_ids
            # But engine should NOT crash

    def test_learning_summary_failure_continues(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Learning summary failure doesn't block generation."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph, patch(
            "kairo.hero.engines.opportunities_engine.learning_engine.summarize_learning_for_brand"
        ) as mock_learning:
            mock_learning.side_effect = Exception("Learning engine error")
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Should still return a board
            assert isinstance(result, TodayBoardDTO)
            assert len(result.opportunities) == len(sample_opportunity_drafts)


# =============================================================================
# BRAND CONTEXT TESTS
# =============================================================================


@pytest.mark.django_db
class TestBrandContext:
    """Tests for brand context handling."""

    def test_brand_snapshot_includes_personas(
        self,
        brand_with_personas_and_pillars,
        sample_opportunity_drafts,
    ):
        """Brand snapshot passed to graph includes personas."""
        captured_snapshot = None

        def capture_args(run_id, brand_snapshot, learning_summary, external_signals, **kwargs):
            nonlocal captured_snapshot
            captured_snapshot = brand_snapshot
            return sample_opportunity_drafts

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities",
            side_effect=capture_args,
        ):
            opportunities_engine.generate_today_board(brand_with_personas_and_pillars.id)

            assert captured_snapshot is not None
            assert len(captured_snapshot.personas) == 2
            assert any(p.name == "Engineering Lead" for p in captured_snapshot.personas)

    def test_brand_snapshot_includes_pillars(
        self,
        brand_with_personas_and_pillars,
        sample_opportunity_drafts,
    ):
        """Brand snapshot passed to graph includes pillars."""
        captured_snapshot = None

        def capture_args(run_id, brand_snapshot, learning_summary, external_signals, **kwargs):
            nonlocal captured_snapshot
            captured_snapshot = brand_snapshot
            return sample_opportunity_drafts

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities",
            side_effect=capture_args,
        ):
            opportunities_engine.generate_today_board(brand_with_personas_and_pillars.id)

            assert captured_snapshot is not None
            assert len(captured_snapshot.pillars) == 2
            assert any(p.name == "Technical Deep Dives" for p in captured_snapshot.pillars)

    def test_brand_snapshot_includes_taboos(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Brand snapshot includes taboos list."""
        captured_snapshot = None

        def capture_args(run_id, brand_snapshot, learning_summary, external_signals, **kwargs):
            nonlocal captured_snapshot
            captured_snapshot = brand_snapshot
            return sample_opportunity_drafts

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities",
            side_effect=capture_args,
        ):
            opportunities_engine.generate_today_board(brand.id)

            assert captured_snapshot is not None
            assert "competitor mentions" in captured_snapshot.taboos


# =============================================================================
# PERSONA/PILLAR RESOLUTION TESTS
# =============================================================================


@pytest.mark.django_db
class TestHintResolution:
    """Tests for persona/pillar hint resolution."""

    def test_persona_hint_resolved_to_id(
        self,
        brand_with_personas_and_pillars,
    ):
        """Persona hint in draft is resolved to actual persona ID."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Content for Engineering Leads",
                proposed_angle="Technical deep dive targeted at engineering decision makers.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=85.0,
                persona_hint="Engineering Lead",  # Should be resolved
                why_now="Engineering teams are actively evaluating tools this quarter.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(
                brand_with_personas_and_pillars.id
            )

            # Check the persisted opportunity has persona_id set
            opp = result.opportunities[0]
            assert opp.persona_id is not None

    def test_pillar_hint_resolved_to_id(
        self,
        brand_with_personas_and_pillars,
    ):
        """Pillar hint in draft is resolved to actual pillar ID."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Technical Deep Dive on Architecture",
                proposed_angle="Comprehensive analysis of system architecture patterns.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                pillar_hint="Technical Deep Dives",  # Should be resolved
                why_now="Architecture discussions trending in engineering communities this week.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(
                brand_with_personas_and_pillars.id
            )

            # Check the persisted opportunity has pillar_id set
            opp = result.opportunities[0]
            assert opp.pillar_id is not None


# =============================================================================
# INVARIANTS TESTS
# =============================================================================


@pytest.mark.django_db
class TestInvariants:
    """Tests for PR-8 invariants."""

    def test_opportunities_have_valid_scores(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """All returned opportunities have scores in [0, 100]."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            for opp in result.opportunities:
                assert 0 <= opp.score <= 100, f"Score {opp.score} out of range"

    def test_opportunities_have_valid_channels(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """All returned opportunities have valid channels."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            valid_channels = {Channel.LINKEDIN, Channel.X}
            for opp in result.opportunities:
                assert opp.primary_channel in valid_channels

    def test_opportunities_have_valid_types(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """All returned opportunities have valid OpportunityType."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            for opp in result.opportunities:
                assert isinstance(opp.type, OpportunityType)

    def test_brand_not_found_raises(self, db):
        """Missing brand raises Brand.DoesNotExist."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            opportunities_engine.generate_today_board(fake_id)


# =============================================================================
# INVALID OPPORTUNITY FILTERING TESTS (per rubric §4.7)
# =============================================================================


@pytest.mark.django_db
class TestInvalidOpportunityFiltering:
    """Tests for engine filtering of invalid opportunities per rubric §4.7."""

    def test_invalid_opps_not_persisted(self, brand):
        """Invalid opportunities (is_valid=False) are not persisted."""
        drafts_with_invalid = [
            OpportunityDraftDTO(
                proposed_title="Valid Opportunity: AI Trends",
                proposed_angle="Exploring AI impact on marketing.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=85.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="AI is trending due to recent announcements.",
            ),
            OpportunityDraftDTO(
                proposed_title="Invalid: Missing Why Now",
                proposed_angle="Some generic content opportunity.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=0.0,  # Invalid opps get score=0 from graph
                is_valid=False,
                rejection_reasons=["why_now missing or too short (§4.3)"],
                why_now=None,
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts_with_invalid

            result = opportunities_engine.generate_today_board(brand.id)

            # Only valid opp should be in result
            assert len(result.opportunities) == 1
            assert result.opportunities[0].title == "Valid Opportunity: AI Trends"

    def test_no_invalid_opps_on_board(self, brand, sample_opportunity_drafts):
        """Final board should never contain is_valid=False opportunities."""
        # Mark all as valid with why_now
        for draft in sample_opportunity_drafts:
            draft.is_valid = True
            draft.rejection_reasons = []
            draft.why_now = "Timely due to recent market trends."

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # All should be valid (no is_valid check on DTO but score > 0)
            for opp in result.opportunities:
                assert opp.score > 0, "Invalid opp leaked to board"

    def test_invalid_filtering_logged_in_notes(self, brand):
        """When invalid opps are filtered, notes reflect the count."""
        drafts_with_invalids = [
            OpportunityDraftDTO(
                proposed_title="Valid Opportunity One",
                proposed_angle="Good content opportunity for the brand.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Trending topic this week.",
            ),
            OpportunityDraftDTO(
                proposed_title="Invalid One",
                proposed_angle="Generic content.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=0.0,
                is_valid=False,
                rejection_reasons=["why_now missing"],
            ),
            OpportunityDraftDTO(
                proposed_title="Invalid Two",
                proposed_angle="Another generic one.",
                type=OpportunityType.TREND,
                primary_channel=Channel.X,
                score=0.0,
                is_valid=False,
                rejection_reasons=["taboo violation"],
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts_with_invalids

            result = opportunities_engine.generate_today_board(brand.id)

            # Notes should mention filtered invalids
            notes_text = " ".join(result.meta.notes)
            assert "2" in notes_text and "invalid" in notes_text.lower()


# =============================================================================
# REDUNDANCY FILTERING TESTS (per rubric §5.4)
# =============================================================================


@pytest.mark.django_db
class TestRedundancyFiltering:
    """Tests for engine filtering of near-duplicate opportunities per rubric §5.4."""

    def test_near_duplicates_filtered(self, brand):
        """Near-duplicate titles are filtered out."""
        drafts_with_dupes = [
            OpportunityDraftDTO(
                proposed_title="AI Marketing Trends for CMOs",
                proposed_angle="Exploring AI impact on marketing.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=85.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="AI is trending due to recent announcements.",
            ),
            OpportunityDraftDTO(
                proposed_title="AI Marketing Trends for CMOs Today",  # Near duplicate
                proposed_angle="Similar angle about AI in marketing.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="AI continues to trend this week.",
            ),
            OpportunityDraftDTO(
                proposed_title="Completely Different Topic",
                proposed_angle="Something entirely different.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.X,
                score=75.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Evergreen topic with enduring value.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts_with_dupes

            result = opportunities_engine.generate_today_board(brand.id)

            # Should have 2 opps (one dupe removed)
            assert len(result.opportunities) == 2
            # Higher-scored one should be kept
            titles = {opp.title for opp in result.opportunities}
            assert "AI Marketing Trends for CMOs" in titles
            assert "Completely Different Topic" in titles

    def test_keeps_higher_scored_when_duplicate(self, brand):
        """When duplicates found, keeps the higher-scored one."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Weekly Thought Leadership Post",
                proposed_angle="Regular thought leadership content.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=70.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Evergreen with recurring value.",
            ),
            OpportunityDraftDTO(
                proposed_title="Weekly Thought Leadership Post Update",  # Duplicate
                proposed_angle="Updated thought leadership.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=90.0,  # Higher score
                is_valid=True,
                rejection_reasons=[],
                why_now="Updated with new insights.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Should keep the higher-scored one
            assert len(result.opportunities) == 1
            assert result.opportunities[0].score == 90.0


# =============================================================================
# EVAL HARNESS READINESS TESTS
# =============================================================================


@pytest.mark.django_db
class TestEvalHarnessReadiness:
    """Tests ensuring F1 output is compatible with eval harness metrics."""

    def test_board_has_required_fields_for_coverage_metric(
        self,
        brand_with_personas_and_pillars,
        sample_opportunity_drafts,
    ):
        """Board opportunities have fields needed for coverage metrics."""
        # Add validity fields
        for draft in sample_opportunity_drafts:
            draft.is_valid = True
            draft.rejection_reasons = []
            draft.why_now = "Timely content opportunity."

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(
                brand_with_personas_and_pillars.id
            )

            # Per hero-loop-eval.md §3.1 - need title for similarity
            for opp in result.opportunities:
                assert opp.title is not None
                assert len(opp.title) >= 5

    def test_board_has_pillar_persona_for_diversity_metrics(
        self,
        brand_with_personas_and_pillars,
    ):
        """Board has pillar/persona IDs needed for diversity metrics."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Technical Deep Dive Content",
                proposed_angle="In-depth technical analysis.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Technical topics have recurring value.",
                pillar_hint="Technical Deep Dives",
                persona_hint="Engineering Lead",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(
                brand_with_personas_and_pillars.id
            )

            # Per hero-loop-eval.md §3.2 - need pillar_id and persona_id
            opp = result.opportunities[0]
            assert opp.pillar_id is not None
            assert opp.persona_id is not None

    def test_board_can_compute_redundancy_rate(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Board data allows redundancy rate computation."""
        # Add validity fields
        for draft in sample_opportunity_drafts:
            draft.is_valid = True
            draft.rejection_reasons = []
            draft.why_now = "Timely content opportunity."

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Per hero-loop-eval.md §3.3 - can compute similarity between titles
            titles = [opp.title for opp in result.opportunities]
            assert len(titles) >= 2  # Need pairs for redundancy

            # Simple check that we can compute Jaccard similarity
            from kairo.hero.engines.opportunities_engine import _compute_title_similarity

            sim = _compute_title_similarity(titles[0], titles[1])
            assert 0.0 <= sim <= 1.0

    def test_board_meta_has_degraded_flag(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Board meta has degraded flag for eval classification."""
        # Add validity fields
        for draft in sample_opportunity_drafts:
            draft.is_valid = True
            draft.rejection_reasons = []
            draft.why_now = "Timely content opportunity."

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Per hero-loop-eval.md - need degraded flag
            assert hasattr(result.meta, "degraded")
            assert result.meta.degraded is False  # Normal run

    def test_board_score_distribution_checkable(
        self,
        brand,
        sample_opportunity_drafts,
    ):
        """Board scores allow distribution checks per hero-loop-eval.md §3.4."""
        # Add validity fields
        for draft in sample_opportunity_drafts:
            draft.is_valid = True
            draft.rejection_reasons = []
            draft.why_now = "Timely content opportunity."

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            scores = [opp.score for opp in result.opportunities]

            # Per hero-loop-eval.md §3.4 - can check score distribution
            assert len(scores) >= 6  # Board size
            assert all(0 <= s <= 100 for s in scores)

            # Can compute metrics like "at least 2 opps with score >= 80"
            high_score_count = sum(1 for s in scores if s >= 80)
            assert high_score_count >= 0  # Just checking we can compute it


# =============================================================================
# SCORE BAND TESTS (PR-8b per rubric §7)
# =============================================================================


@pytest.mark.django_db
class TestScoreBands:
    """Tests for score band behavior per rubric §7.

    Per 08-opportunity-rubric.md:
    - Strong: score >= 80
    - Valid-but-weak: ~40-65
    - Invalid: score = 0 (fails hard requirements)
    """

    def test_board_prioritizes_strong_scores(self, brand):
        """Board should be sorted so strong scores (>=80) come first."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Weak Opportunity About Marketing",
                proposed_angle="Generic marketing opportunity content.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=55.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Evergreen topic with recurring value.",
            ),
            OpportunityDraftDTO(
                proposed_title="Strong Opportunity: AI Trends",
                proposed_angle="Timely AI trends impacting our industry.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=88.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Major AI announcement this week.",
            ),
            OpportunityDraftDTO(
                proposed_title="Medium Opportunity Content",
                proposed_angle="Decent content opportunity for engagement.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.X,
                score=70.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Consistent customer interest.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Board should be sorted by score descending
            scores = [opp.score for opp in result.opportunities]
            assert scores == sorted(scores, reverse=True), (
                "Board should be sorted by score descending"
            )
            # First opp should be the strong one
            assert result.opportunities[0].score == 88.0

    def test_strong_opps_at_top_of_mixed_board(self, brand):
        """In a mixed board, strong opps (>=80) should appear before weak ones."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title=f"Opportunity {i}",
                proposed_angle="Content opportunity for testing.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=score,
                is_valid=True,
                rejection_reasons=[],
                why_now="Timely content opportunity.",
            )
            for i, score in enumerate([60, 85, 45, 90, 72, 82])
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(brand.id)

            scores = [opp.score for opp in result.opportunities]
            # Strong scores (>=80) should be first
            strong_scores = [s for s in scores if s >= 80]
            weak_scores = [s for s in scores if s < 80]
            # All strong scores should come before all weak scores
            assert all(
                scores.index(s) < scores.index(w)
                for s in strong_scores
                for w in weak_scores
            ), "Strong scores should appear before weak scores"


# =============================================================================
# REDUNDANCY THRESHOLD TESTS (PR-8b per rubric §5.4)
# =============================================================================


@pytest.mark.django_db
class TestRedundancyThreshold:
    """Tests for redundancy filtering threshold behavior.

    Per 08-opportunity-rubric.md §5.4 and hero-loop-eval.md §3.3:
    - Near-duplicates (Jaccard >= 0.75) should be filtered
    - Distinct ideas (Jaccard < 0.75) should NOT be filtered
    """

    def test_similar_titles_below_threshold_not_filtered(self, brand):
        """Titles with Jaccard similarity < 0.75 should NOT be filtered."""
        # These are similar but different enough (Jaccard ~0.5)
        drafts = [
            OpportunityDraftDTO(
                proposed_title="AI Marketing Trends for CMOs",
                proposed_angle="AI impact on marketing leadership.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=85.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="AI is trending due to recent announcements.",
            ),
            OpportunityDraftDTO(
                proposed_title="DevOps Best Practices for Engineers",
                proposed_angle="DevOps practices for engineering teams.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Evergreen topic with recurring demand.",
            ),
            OpportunityDraftDTO(
                proposed_title="B2B Sales Automation Insights",
                proposed_angle="Automation trends in B2B sales.",
                type=OpportunityType.TREND,
                primary_channel=Channel.X,
                score=75.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="New automation tools released this month.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # All should be kept - they're distinct
            assert len(result.opportunities) == 3

    def test_multiple_near_duplicates_reduced(self, brand):
        """Multiple near-duplicates should be reduced to just one.

        Jaccard >= 0.75 threshold means at least 3/4 of words must overlap.
        Title 1: "AI Marketing Trends" (3 words)
        Title 2: "AI Marketing Trends Update" (4 words, intersection=3, union=4, J=0.75)
        """
        # These are actual near-duplicates (Jaccard >= 0.75)
        drafts = [
            OpportunityDraftDTO(
                proposed_title="AI Marketing Trends",
                proposed_angle="AI impact on marketing.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=90.0,  # Highest - should be kept
                is_valid=True,
                rejection_reasons=[],
                why_now="AI announcement this week.",
            ),
            OpportunityDraftDTO(
                proposed_title="AI Marketing Trends Update",  # J=3/4=0.75
                proposed_angle="AI impact on marketing teams.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=85.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="AI news this week.",
            ),
            OpportunityDraftDTO(
                proposed_title="Marketing Trends AI",  # J=3/3=1.0 (same words)
                proposed_angle="AI trends for marketing.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=80.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="AI trending now.",
            ),
            OpportunityDraftDTO(
                proposed_title="Completely Different Topic Here",
                proposed_angle="Something totally unrelated.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.X,
                score=70.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Evergreen topic value.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # Only 2 should remain: highest-scored AI one + the different one
            assert len(result.opportunities) == 2
            titles = {opp.title for opp in result.opportunities}
            assert "AI Marketing Trends" in titles
            assert "Completely Different Topic Here" in titles


# =============================================================================
# DEGRADED MODE META FIELD TESTS (PR-8b)
# =============================================================================


@pytest.mark.django_db
class TestDegradedModeMetaFields:
    """Tests for TodayBoardMetaDTO degraded mode fields.

    Per PR-8b and hero-loop-eval.md:
    - meta.degraded: True when graph fails
    - meta.reason: Short code describing why (e.g. "graph_error")
    - meta.total_candidates: Raw count before filtering (None if degraded)
    """

    def test_normal_run_meta_fields(self, brand, sample_opportunity_drafts):
        """Normal run has degraded=False and total_candidates set."""
        # Add validity fields
        for draft in sample_opportunity_drafts:
            draft.is_valid = True
            draft.rejection_reasons = []
            draft.why_now = "Timely content opportunity."

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = sample_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.meta.degraded is False
            assert result.meta.reason is None
            assert result.meta.total_candidates == len(sample_opportunity_drafts)

    def test_graph_error_sets_degraded_true(self, brand):
        """Graph error sets meta.degraded=True and meta.reason."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("LLM call failed")

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.meta.degraded is True
            assert result.meta.reason == "graph_error"
            assert result.meta.total_candidates is None  # No candidates from graph

    def test_degraded_board_still_returns_opportunities(self, brand):
        """Degraded board returns stub/fallback opportunities."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.side_effect = GraphError("Network error")

            result = opportunities_engine.generate_today_board(brand.id)

            # Should return fallback opportunities (stubs)
            assert result.meta.degraded is True
            assert len(result.opportunities) > 0  # Not empty
            assert "Graph failed" in " ".join(result.meta.notes)

    def test_total_candidates_reflects_pre_filter_count(self, brand):
        """total_candidates is raw count before invalid/redundancy filtering."""
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Valid Opportunity One",
                proposed_angle="Good content opportunity.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=85.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Trending topic this week.",
            ),
            OpportunityDraftDTO(
                proposed_title="Invalid Opportunity",
                proposed_angle="Missing why now.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.LINKEDIN,
                score=0.0,
                is_valid=False,
                rejection_reasons=["why_now missing"],
            ),
            OpportunityDraftDTO(
                proposed_title="Valid Opportunity Two",
                proposed_angle="Another good opportunity.",
                type=OpportunityType.EVERGREEN,
                primary_channel=Channel.X,
                score=75.0,
                is_valid=True,
                rejection_reasons=[],
                why_now="Evergreen value.",
            ),
        ]

        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = drafts

            result = opportunities_engine.generate_today_board(brand.id)

            # total_candidates is raw count (3), not filtered count (2)
            assert result.meta.total_candidates == 3
            assert len(result.opportunities) == 2  # Invalid one filtered
