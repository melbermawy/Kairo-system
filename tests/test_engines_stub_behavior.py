"""
Engine stub behavior tests for PR-3.

Tests verify:
- Engines return deterministic stub data
- DTOs validate correctly
- Invariants hold (scores in [0,100], channels in expected set, etc.)
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel, DecisionType, OpportunityType
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import (
    ContentPackageDTO,
    LearningSummaryDTO,
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
        positioning="A test brand for unit tests",
        tone_tags=["professional", "friendly"],
        taboos=["competitor mentions"],
    )


# =============================================================================
# OPPORTUNITIES ENGINE TESTS
# =============================================================================


@pytest.mark.django_db
class TestOpportunitiesEngine:
    """Tests for opportunities_engine.generate_today_board."""

    def test_returns_today_board_dto(self, brand):
        """Engine returns a valid TodayBoardDTO."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert isinstance(result, TodayBoardDTO)
        # Validate through model_validate (should not raise)
        TodayBoardDTO.model_validate(result.model_dump())

    def test_brand_id_matches(self, brand):
        """Returned board has correct brand_id."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert result.brand_id == brand.id

    def test_snapshot_has_brand_data(self, brand):
        """Snapshot contains actual brand data."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert result.snapshot.brand_id == brand.id
        assert result.snapshot.brand_name == brand.name
        assert result.snapshot.positioning == brand.positioning
        assert result.snapshot.voice_tone_tags == brand.tone_tags
        assert result.snapshot.taboos == brand.taboos

    def test_returns_6_to_10_opportunities(self, brand):
        """Board has 6-10 opportunities per PR-3 spec."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert 6 <= len(result.opportunities) <= 10

    def test_opportunity_scores_in_valid_range(self, brand):
        """All opportunity scores are in [0, 100]."""
        result = opportunities_engine.generate_today_board(brand.id)

        for opp in result.opportunities:
            assert 0 <= opp.score <= 100, f"Score {opp.score} out of range"

    def test_opportunity_scores_in_stub_range(self, brand):
        """Stub scores are in [60, 95] range per spec."""
        result = opportunities_engine.generate_today_board(brand.id)

        for opp in result.opportunities:
            assert 60 <= opp.score <= 95, f"Score {opp.score} not in stub range"

    def test_opportunity_channels_valid(self, brand):
        """All opportunities have valid primary channels."""
        result = opportunities_engine.generate_today_board(brand.id)

        valid_channels = {Channel.LINKEDIN, Channel.X}
        for opp in result.opportunities:
            assert opp.primary_channel in valid_channels, (
                f"Channel {opp.primary_channel} not in {valid_channels}"
            )

    def test_opportunities_sorted_by_score_descending(self, brand):
        """Opportunities are sorted by score descending."""
        result = opportunities_engine.generate_today_board(brand.id)

        scores = [opp.score for opp in result.opportunities]
        assert scores == sorted(scores, reverse=True)

    def test_opportunity_types_valid(self, brand):
        """All opportunities have valid types."""
        result = opportunities_engine.generate_today_board(brand.id)

        for opp in result.opportunities:
            assert isinstance(opp.type, OpportunityType)

    def test_meta_has_correct_opportunity_count(self, brand):
        """Meta opportunity_count matches actual count."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert result.meta.opportunity_count == len(result.opportunities)

    def test_meta_has_channel_mix(self, brand):
        """Meta has non-empty channel_mix."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert len(result.meta.channel_mix) > 0

    def test_meta_source_is_hero_f1(self, brand):
        """Meta source is 'hero_f1'."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert result.meta.source == "hero_f1"

    def test_meta_degraded_is_false(self, brand):
        """Meta degraded is False for stub data."""
        result = opportunities_engine.generate_today_board(brand.id)

        assert result.meta.degraded is False

    def test_raises_on_missing_brand(self, db):
        """Engine raises Brand.DoesNotExist for unknown brand."""
        fake_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            opportunities_engine.generate_today_board(fake_id)

    def test_at_least_one_pinned_opportunity(self, brand):
        """At least one opportunity is pinned (stub behavior)."""
        result = opportunities_engine.generate_today_board(brand.id)

        pinned_count = sum(1 for opp in result.opportunities if opp.is_pinned)
        assert pinned_count >= 1

    def test_deterministic_output(self, brand):
        """Same brand ID produces consistent output structure."""
        result1 = opportunities_engine.generate_today_board(brand.id)
        result2 = opportunities_engine.generate_today_board(brand.id)

        # Same number of opportunities
        assert len(result1.opportunities) == len(result2.opportunities)
        # Same opportunity IDs
        ids1 = {opp.id for opp in result1.opportunities}
        ids2 = {opp.id for opp in result2.opportunities}
        assert ids1 == ids2


# =============================================================================
# CONTENT ENGINE TESTS
# =============================================================================


@pytest.mark.django_db
class TestContentEngine:
    """Tests for content_engine functions."""

    def test_create_package_returns_content_package(self, brand):
        """create_package_from_opportunity returns ContentPackage."""
        opportunity_id = uuid4()

        result = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        # It's a model instance (not saved to DB)
        from kairo.core.models import ContentPackage

        assert isinstance(result, ContentPackage)

    def test_create_package_has_correct_brand_id(self, brand):
        """Created package has correct brand_id."""
        opportunity_id = uuid4()

        result = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        assert result.brand_id == brand.id

    def test_create_package_has_origin_opportunity_id(self, brand):
        """Created package references source opportunity."""
        opportunity_id = uuid4()

        result = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        assert result.origin_opportunity_id == opportunity_id

    def test_create_package_has_draft_status(self, brand):
        """Created package starts in draft status."""
        from kairo.core.enums import PackageStatus

        opportunity_id = uuid4()

        result = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        assert result.status == PackageStatus.DRAFT.value

    def test_create_package_has_channels(self, brand):
        """Created package has target channels."""
        opportunity_id = uuid4()

        result = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        assert len(result.channels) >= 1

    def test_create_package_deterministic(self, brand):
        """Same inputs produce same package ID."""
        opportunity_id = uuid4()

        result1 = content_engine.create_package_from_opportunity(brand.id, opportunity_id)
        result2 = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        assert result1.id == result2.id

    def test_create_package_not_persisted(self, db, brand):
        """Package is not saved to database."""
        from kairo.core.models import ContentPackage

        initial_count = ContentPackage.objects.count()
        opportunity_id = uuid4()

        content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        assert ContentPackage.objects.count() == initial_count

    def test_generate_variants_returns_list(self, brand):
        """generate_variants_for_package returns list of Variants."""
        package_id = uuid4()

        result = content_engine.generate_variants_for_package(package_id)

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_generate_variants_returns_two_channels(self, brand):
        """Generates variants for LinkedIn and X."""
        package_id = uuid4()

        result = content_engine.generate_variants_for_package(package_id)

        assert len(result) == 2
        channels = {v.channel for v in result}
        assert Channel.LINKEDIN.value in channels
        assert Channel.X.value in channels

    def test_generate_variants_have_body(self, brand):
        """All variants have non-empty draft_text."""
        package_id = uuid4()

        result = content_engine.generate_variants_for_package(package_id)

        for variant in result:
            assert variant.draft_text, "Variant should have draft_text"

    def test_generate_variants_have_draft_status(self, brand):
        """All variants start in draft status."""
        from kairo.core.enums import VariantStatus

        package_id = uuid4()

        result = content_engine.generate_variants_for_package(package_id)

        for variant in result:
            assert variant.status == VariantStatus.DRAFT.value

    def test_generate_variants_not_persisted(self, db, brand):
        """Variants are not saved to database."""
        from kairo.core.models import Variant

        initial_count = Variant.objects.count()
        package_id = uuid4()

        content_engine.generate_variants_for_package(package_id)

        assert Variant.objects.count() == initial_count

    def test_generate_variants_deterministic(self, brand):
        """Same package_id produces same variant IDs."""
        package_id = uuid4()

        result1 = content_engine.generate_variants_for_package(package_id)
        result2 = content_engine.generate_variants_for_package(package_id)

        ids1 = {v.id for v in result1}
        ids2 = {v.id for v in result2}
        assert ids1 == ids2

    def test_package_to_dto_converts_correctly(self, brand):
        """package_to_dto converts model to DTO."""
        opportunity_id = uuid4()
        package = content_engine.create_package_from_opportunity(brand.id, opportunity_id)

        dto = content_engine.package_to_dto(package)

        assert isinstance(dto, ContentPackageDTO)
        assert dto.id == package.id
        assert dto.brand_id == package.brand_id
        assert dto.title == package.title

    def test_variant_to_dto_converts_correctly(self, brand):
        """variant_to_dto converts model to DTO."""
        package_id = uuid4()
        variants = content_engine.generate_variants_for_package(package_id)

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
        # Stub has at least 2 patterns
        assert len(result.top_performing_patterns) >= 2

    def test_summarize_learning_has_top_channels(self, brand):
        """Summary has top_performing_channels list."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.top_performing_channels, list)
        assert len(result.top_performing_channels) >= 1
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
        assert len(result.pillar_performance) > 0
        for name, score in result.pillar_performance.items():
            assert isinstance(name, str)
            assert 0 <= score <= 100

    def test_summarize_learning_has_persona_engagement(self, brand):
        """Summary has persona_engagement dict."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.persona_engagement, dict)
        assert len(result.persona_engagement) > 0
        for name, score in result.persona_engagement.items():
            assert isinstance(name, str)
            assert 0 <= score <= 100

    def test_summarize_learning_has_notes(self, brand):
        """Summary has notes list."""
        result = learning_engine.summarize_learning_for_brand(brand.id)

        assert isinstance(result.notes, list)
        assert len(result.notes) > 0

    def test_process_execution_events_returns_empty_list(self, brand):
        """process_execution_events returns empty list for PR-3."""
        result = learning_engine.process_execution_events(brand.id)

        assert result == []

    def test_process_execution_events_with_window_size(self, brand):
        """process_execution_events accepts window_size param."""
        result = learning_engine.process_execution_events(brand.id, window_size=7)

        assert result == []
