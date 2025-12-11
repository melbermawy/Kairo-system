"""
Engine stub behavior tests for PR-3 (updated for PR-8).

Tests verify:
- Engines return deterministic stub data
- DTOs validate correctly
- Invariants hold (scores in [0,100], channels in expected set, etc.)

Note: PR-8 changed opportunities_engine to call a graph, so these tests
now patch the graph to return mock data consistent with the stub behavior.
"""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel, DecisionType, OpportunityType
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import (
    ContentPackageDTO,
    LearningSummaryDTO,
    OpportunityDraftDTO,
    TodayBoardDTO,
    VariantDTO,
)
from kairo.hero.engines import content_engine, learning_engine, opportunities_engine


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
        name="Test Brand",
        slug="test-brand",
        positioning="A test brand for unit tests",
        tone_tags=["professional", "friendly"],
        taboos=["competitor mentions"],
    )


@pytest.fixture
def mock_opportunity_drafts():
    """Mock opportunity drafts that simulate PR-3 stub behavior.

    Updated for PR-8: includes is_valid, rejection_reasons, why_now per rubric §4.7.
    """
    return [
        OpportunityDraftDTO(
            proposed_title="Industry trend: AI adoption in Test Brand's sector",
            proposed_angle="Rising discussion about AI tools - opportunity to share our perspective on practical implementation.",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=92.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="AI tools are trending this week due to major announcements.",
        ),
        OpportunityDraftDTO(
            proposed_title="Weekly thought leadership post",
            proposed_angle="Regular cadence content about our core expertise area.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=85.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Founders consistently ask about this topic; recurring value.",
        ),
        OpportunityDraftDTO(
            proposed_title="Competitor announcement response",
            proposed_angle="Competitor just announced a feature - opportunity to differentiate our approach.",
            type=OpportunityType.COMPETITIVE,
            primary_channel=Channel.X,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=78.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Competitor launched new feature yesterday; timely response opportunity.",
        ),
        OpportunityDraftDTO(
            proposed_title="Customer success story",
            proposed_angle="Recent customer achieved notable results - great case study material.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=88.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Customer just hit 10M milestone; fresh data for case study.",
        ),
        OpportunityDraftDTO(
            proposed_title="Industry report commentary",
            proposed_angle="New industry report released - can provide contrarian take aligned with our positioning.",
            type=OpportunityType.TREND,
            primary_channel=Channel.X,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=75.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Gartner released annual report this week; high visibility window.",
        ),
        OpportunityDraftDTO(
            proposed_title="Behind the scenes: Product development",
            proposed_angle="Authenticity content showing how we build - builds trust with audience.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=70.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Team shipped major feature; great behind-the-scenes material.",
        ),
        OpportunityDraftDTO(
            proposed_title="Quick tip thread",
            proposed_angle="Tactical advice thread format works well for engagement.",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.X,
            suggested_channels=[Channel.X],
            score=82.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Thread format is performing well on X this quarter; proven format.",
        ),
        OpportunityDraftDTO(
            proposed_title="Event follow-up content",
            proposed_angle="Upcoming industry event - opportunity to share insights and connect.",
            type=OpportunityType.CAMPAIGN,
            primary_channel=Channel.LINKEDIN,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            score=65.0,
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            is_valid=True,
            rejection_reasons=[],
            why_now="Industry conference next week; pre-event visibility opportunity.",
        ),
    ]


# =============================================================================
# OPPORTUNITIES ENGINE TESTS
# =============================================================================


@pytest.mark.django_db
class TestOpportunitiesEngine:
    """Tests for opportunities_engine.generate_today_board.

    PR-8 update: These tests now patch the graph to return mock data,
    since the engine now calls the graph instead of generating stubs inline.
    """

    def test_returns_today_board_dto(self, brand, mock_opportunity_drafts):
        """Engine returns a valid TodayBoardDTO."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert isinstance(result, TodayBoardDTO)
            # Validate through model_validate (should not raise)
            TodayBoardDTO.model_validate(result.model_dump())

    def test_brand_id_matches(self, brand, mock_opportunity_drafts):
        """Returned board has correct brand_id."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.brand_id == brand.id

    def test_snapshot_has_brand_data(self, brand, mock_opportunity_drafts):
        """Snapshot contains actual brand data."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.snapshot.brand_id == brand.id
            assert result.snapshot.brand_name == brand.name
            assert result.snapshot.positioning == brand.positioning
            assert result.snapshot.voice_tone_tags == brand.tone_tags
            assert result.snapshot.taboos == brand.taboos

    def test_returns_6_to_10_opportunities(self, brand, mock_opportunity_drafts):
        """Board has 6-10 opportunities per PR-3 spec."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert 6 <= len(result.opportunities) <= 10

    def test_opportunity_scores_in_valid_range(self, brand, mock_opportunity_drafts):
        """All opportunity scores are in [0, 100]."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            for opp in result.opportunities:
                assert 0 <= opp.score <= 100, f"Score {opp.score} out of range"

    def test_opportunity_scores_in_stub_range(self, brand, mock_opportunity_drafts):
        """Stub scores are in [60, 95] range per spec."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            for opp in result.opportunities:
                assert 60 <= opp.score <= 95, f"Score {opp.score} not in stub range"

    def test_opportunity_channels_valid(self, brand, mock_opportunity_drafts):
        """All opportunities have valid primary channels."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            valid_channels = {Channel.LINKEDIN, Channel.X}
            for opp in result.opportunities:
                assert opp.primary_channel in valid_channels, (
                    f"Channel {opp.primary_channel} not in {valid_channels}"
                )

    def test_opportunities_sorted_by_score_descending(self, brand, mock_opportunity_drafts):
        """Opportunities are sorted by score descending."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            scores = [opp.score for opp in result.opportunities]
            assert scores == sorted(scores, reverse=True)

    def test_opportunity_types_valid(self, brand, mock_opportunity_drafts):
        """All opportunities have valid types."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            for opp in result.opportunities:
                assert isinstance(opp.type, OpportunityType)

    def test_meta_has_correct_opportunity_count(self, brand, mock_opportunity_drafts):
        """Meta opportunity_count matches actual count."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.meta.opportunity_count == len(result.opportunities)

    def test_meta_has_channel_mix(self, brand, mock_opportunity_drafts):
        """Meta has non-empty channel_mix."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert len(result.meta.channel_mix) > 0

    def test_meta_source_is_hero_f1(self, brand, mock_opportunity_drafts):
        """Meta source is 'hero_f1'."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

            assert result.meta.source == "hero_f1"

    def test_meta_degraded_is_false(self, brand, mock_opportunity_drafts):
        """Meta degraded is False for successful generation."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result = opportunities_engine.generate_today_board(brand.id)

        assert result.meta.degraded is False

    def test_raises_on_missing_brand(self, db):
        """Engine raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            opportunities_engine.generate_today_board(fake_id)

    def test_deterministic_output(self, brand, mock_opportunity_drafts):
        """Same brand ID produces consistent output structure (via idempotent IDs)."""
        with patch(
            "kairo.hero.engines.opportunities_engine.graph_hero_generate_opportunities"
        ) as mock_graph:
            mock_graph.return_value = mock_opportunity_drafts

            result1 = opportunities_engine.generate_today_board(brand.id)
            result2 = opportunities_engine.generate_today_board(brand.id)

            # Same number of opportunities
            assert len(result1.opportunities) == len(result2.opportunities)
            # Same opportunity IDs (deterministic based on brand+title)
            ids1 = {opp.id for opp in result1.opportunities}
            ids2 = {opp.id for opp in result2.opportunities}
            assert ids1 == ids2


# =============================================================================
# CONTENT ENGINE TESTS (PR-9 UPDATE)
# =============================================================================
# PR-9 changed content_engine to call graphs, so these tests now:
# 1. Create real DB records (opportunity/package)
# 2. Mock the graph to return deterministic output
# 3. Persist packages/variants to DB


@pytest.fixture
def opportunity(brand):
    """Create a test opportunity for package tests."""
    from kairo.core.models import Opportunity
    from kairo.core.enums import OpportunityType, CreatedVia

    return Opportunity.objects.create(
        brand=brand,
        title="Test Opportunity for Package",
        angle="Testing content package creation",
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=80.0,
        created_via=CreatedVia.AI_SUGGESTED,
    )


@pytest.fixture
def mock_package_draft():
    """Mock package draft for deterministic testing."""
    from kairo.hero.dto import ContentPackageDraftDTO

    return ContentPackageDraftDTO(
        title="Test Package from Graph",
        thesis="A comprehensive test thesis about marketing strategies and best practices.",
        summary="This package covers various marketing topics with practical examples.",
        primary_channel=Channel.LINKEDIN,
        channels=[Channel.LINKEDIN, Channel.X],
        cta="Learn more",
        is_valid=True,
        rejection_reasons=[],
        package_score=12.0,
        quality_band="board_ready",
    )


@pytest.fixture
def mock_variant_drafts():
    """Mock variant drafts for deterministic testing."""
    from kairo.hero.dto import VariantDraftDTO

    return [
        VariantDraftDTO(
            channel=Channel.LINKEDIN,
            body="This is test content for LinkedIn with multiple paragraphs and insights.",
            call_to_action="Share your thoughts",
            is_valid=True,
            rejection_reasons=[],
            variant_score=10.0,
            quality_band="publish_ready",
        ),
        VariantDraftDTO(
            channel=Channel.X,
            body="Concise X post about marketing strategies. Thread below.",
            call_to_action="Follow for more",
            is_valid=True,
            rejection_reasons=[],
            variant_score=9.0,
            quality_band="publish_ready",
        ),
    ]


@pytest.mark.django_db
class TestContentEngine:
    """Tests for content_engine functions (PR-9 updated with graph mocking)."""

    def test_create_package_returns_content_package(self, brand, opportunity, mock_package_draft):
        """create_package_from_opportunity returns ContentPackage."""
        from kairo.core.models import ContentPackage

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert isinstance(result, ContentPackage)

    def test_create_package_has_correct_brand_id(self, brand, opportunity, mock_package_draft):
        """Created package has correct brand_id."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert result.brand_id == brand.id

    def test_create_package_has_origin_opportunity_id(self, brand, opportunity, mock_package_draft):
        """Created package references source opportunity."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert result.origin_opportunity_id == opportunity.id

    def test_create_package_has_draft_status(self, brand, opportunity, mock_package_draft):
        """Created package starts in draft status."""
        from kairo.core.enums import PackageStatus

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert result.status == PackageStatus.DRAFT.value

    def test_create_package_has_channels(self, brand, opportunity, mock_package_draft):
        """Created package has target channels."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert len(result.channels) >= 1

    def test_create_package_idempotent(self, brand, opportunity, mock_package_draft):
        """Same inputs produce same package (idempotency)."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            result1 = content_engine.create_package_from_opportunity(brand.id, opportunity.id)
            result2 = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert result1.id == result2.id

    def test_create_package_persisted(self, db, brand, opportunity, mock_package_draft):
        """Package IS saved to database (PR-9 change)."""
        from kairo.core.models import ContentPackage

        initial_count = ContentPackage.objects.count()

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            assert ContentPackage.objects.count() == initial_count + 1

    def test_generate_variants_returns_list(self, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """generate_variants_for_package returns list of Variants."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts

            result = content_engine.generate_variants_for_package(package.id)

            assert isinstance(result, list)
            assert len(result) >= 1

    def test_generate_variants_returns_two_channels(self, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """Generates variants for LinkedIn and X."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts

            result = content_engine.generate_variants_for_package(package.id)

            assert len(result) == 2
            channels = {v.channel for v in result}
            assert Channel.LINKEDIN.value in channels
            assert Channel.X.value in channels

    def test_generate_variants_have_body(self, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """All variants have non-empty draft_text."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts

            result = content_engine.generate_variants_for_package(package.id)

            for variant in result:
                assert variant.draft_text, "Variant should have draft_text"

    def test_generate_variants_have_draft_status(self, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """All variants start in draft status."""
        from kairo.core.enums import VariantStatus

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts

            result = content_engine.generate_variants_for_package(package.id)

            for variant in result:
                assert variant.status == VariantStatus.DRAFT.value

    def test_generate_variants_persisted(self, db, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """Variants ARE saved to database (PR-9 change)."""
        from kairo.core.models import Variant

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        initial_count = Variant.objects.count()

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts

            content_engine.generate_variants_for_package(package.id)

            assert Variant.objects.count() == initial_count + 2

    def test_generate_variants_no_regeneration(self, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """Second variant generation raises error (no-regeneration rule)."""
        from kairo.hero.engines.content_engine import VariantsAlreadyExistError

        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts
            content_engine.generate_variants_for_package(package.id)

            # Second call should fail
            with pytest.raises(VariantsAlreadyExistError):
                content_engine.generate_variants_for_package(package.id)

    def test_package_to_dto_converts_correctly(self, brand, opportunity, mock_package_draft):
        """package_to_dto converts model to DTO."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

            dto = content_engine.package_to_dto(package)

            assert isinstance(dto, ContentPackageDTO)
            assert dto.id == package.id
            assert dto.brand_id == package.brand_id
            assert dto.title == package.title

    def test_variant_to_dto_converts_correctly(self, brand, opportunity, mock_package_draft, mock_variant_drafts):
        """variant_to_dto converts model to DTO."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_pkg_graph:
            mock_pkg_graph.return_value = mock_package_draft
            package = content_engine.create_package_from_opportunity(brand.id, opportunity.id)

        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_var_graph:
            mock_var_graph.return_value = mock_variant_drafts
            variants = content_engine.generate_variants_for_package(package.id)

            dto = content_engine.variant_to_dto(variants[0])

            assert isinstance(dto, VariantDTO)
            assert dto.id == variants[0].id
            assert dto.package_id == variants[0].package_id


# =============================================================================
# LEARNING ENGINE TESTS
# =============================================================================


@pytest.mark.django_db
class TestLearningEngine:
    """Tests for learning_engine functions."""

    def test_summarize_learning_returns_dto(self, brand):
        """summarize_learning_for_brand returns LearningSummaryDTO."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result, LearningSummaryDTO)
        # Validate through model_validate
        LearningSummaryDTO.model_validate(result.model_dump())

    def test_summarize_learning_has_brand_id(self, brand):
        """Summary has correct brand_id."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert result.brand_id == brand.id

    def test_summarize_learning_has_generated_at(self, brand):
        """Summary has generated_at timestamp."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert result.generated_at is not None
        assert isinstance(result.generated_at, datetime)

    def test_summarize_learning_has_top_patterns(self, brand):
        """Summary has top_performing_patterns list."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.top_performing_patterns, list)
        # PR-4: List may be empty if no learning events exist

    def test_summarize_learning_has_top_channels(self, brand):
        """Summary has top_performing_channels list."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.top_performing_channels, list)
        # PR-4: List may be empty if no learning events exist
        for channel in result.top_performing_channels:
            assert isinstance(channel, Channel)

    def test_summarize_learning_has_engagement_score(self, brand):
        """Summary has recent_engagement_score."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert result.recent_engagement_score is not None
        assert 0 <= result.recent_engagement_score <= 100

    def test_summarize_learning_has_pillar_performance(self, brand):
        """Summary has pillar_performance dict."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.pillar_performance, dict)
        # PR-4: Dict may be empty if no pillar data exists
        for name, score in result.pillar_performance.items():
            assert isinstance(name, str)
            assert 0 <= score <= 100

    def test_summarize_learning_has_persona_engagement(self, brand):
        """Summary has persona_engagement dict."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.persona_engagement, dict)
        # PR-4: Dict may be empty if no persona data exists
        for name, score in result.persona_engagement.items():
            assert isinstance(name, str)
            assert 0 <= score <= 100

    def test_summarize_learning_has_notes(self, brand):
        """Summary has notes list."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.notes, list)
        assert len(result.notes) > 0

    def test_process_execution_events_returns_processing_result(self, brand):
        """process_execution_events returns ProcessingResult for PR-4."""
        result = learning_engine.process_execution_events(brand.id)

        # PR-4: Returns a ProcessingResult named tuple
        assert hasattr(result, "events_processed")
        assert hasattr(result, "learning_events_created")
        assert hasattr(result, "learning_events")

    def test_process_execution_events_with_window_hours(self, brand):
        """process_execution_events accepts window_hours param."""
        result = learning_engine.process_execution_events(brand.id, window_hours=7)

        # PR-4: Returns ProcessingResult even when no events
        assert result.events_processed == 0
        assert result.learning_events_created == 0
