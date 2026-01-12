"""
Opportunities Graph unit tests for PR-8.

Tests verify:
- Graph returns valid OpportunityDraftDTO list
- Graph uses LLMClient only (no direct provider SDK calls)
- Graph handles LLM failures by raising GraphError
- No ORM imports in the graph module
- Deterministic fake LLM produces expected outputs

Per PR-map-and-standards §PR-8:
- All tests use fake LLM (no network calls)
- Invariants: scores in [0,100], channels valid, titles non-empty
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel, OpportunityType
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ExternalSignalBundleDTO,
    LearningSummaryDTO,
    OpportunityDraftDTO,
    PersonaDTO,
    PillarDTO,
    TrendSignalDTO,
)
from kairo.hero.graphs.opportunities_graph import (
    GraphError,
    MinimalScoringItem,
    MinimalScoringOutput,
    RawOpportunityIdea,
    ScoredOpportunity,
    ScoringOutput,
    SynthesisOutput,
    _build_external_signals_summary,
    _convert_to_draft_dtos,
    graph_hero_generate_opportunities,
)
from kairo.hero.llm_client import LLMCallError, LLMConfig, LLMClient, LLMResponse


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_brand_id():
    """Sample brand UUID for testing."""
    return UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def sample_run_id():
    """Sample run UUID for testing."""
    return uuid4()


@pytest.fixture
def sample_brand_snapshot(sample_brand_id):
    """Sample BrandSnapshotDTO for testing."""
    return BrandSnapshotDTO(
        brand_id=sample_brand_id,
        brand_name="Test Brand",
        positioning="A test brand for unit testing",
        pillars=[
            PillarDTO(
                id=uuid4(),
                name="Thought Leadership",
                description="Industry insights",
                priority_rank=1,
            ),
            PillarDTO(
                id=uuid4(),
                name="Product Updates",
                description="New features",
                priority_rank=2,
            ),
        ],
        personas=[
            PersonaDTO(
                id=uuid4(),
                name="CMO",
                role="Marketing Executive",
                summary="Senior marketing leader",
            ),
        ],
        voice_tone_tags=["professional", "insightful"],
        taboos=["competitor mentions", "controversial politics"],
    )


@pytest.fixture
def sample_learning_summary(sample_brand_id):
    """Sample LearningSummaryDTO for testing."""
    return LearningSummaryDTO(
        brand_id=sample_brand_id,
        generated_at=datetime.now(timezone.utc),
        top_performing_patterns=[],
        top_performing_channels=[Channel.LINKEDIN],
        recent_engagement_score=75.0,
        pillar_performance={},
        persona_engagement={},
        notes=["Test learning data"],
    )


@pytest.fixture
def sample_external_signals(sample_brand_id):
    """Sample ExternalSignalBundleDTO for testing."""
    return ExternalSignalBundleDTO(
        brand_id=sample_brand_id,
        fetched_at=datetime.now(timezone.utc),
        trends=[
            TrendSignalDTO(
                id="trend-1",
                topic="AI in Marketing",
                source="linkedin_trending",
                relevance_score=85.0,
                recency_days=1,
            ),
        ],
        web_mentions=[],
        competitor_posts=[],
        social_moments=[],
    )


@pytest.fixture
def fake_synthesis_output():
    """Fake LLM output for synthesis node."""
    return SynthesisOutput(
        opportunities=[
            RawOpportunityIdea(
                title="AI Marketing Trends: What CMOs Need to Know",
                angle="Emerging AI tools are transforming how marketing teams work. Share insights on practical adoption.",
                type="trend",
                primary_channel="linkedin",
                suggested_channels=["linkedin", "x"],
                reasoning="Strong alignment with thought leadership pillar",
                source="linkedin_trending",
                why_now="Recent AI announcements from major tech companies make this timely.",
            ),
            RawOpportunityIdea(
                title="Weekly Leadership Insights",
                angle="Regular thought leadership content showcasing expertise.",
                type="evergreen",
                primary_channel="linkedin",
                suggested_channels=["linkedin"],
                reasoning="Consistent pillar coverage",
                why_now="Q4 planning season creates demand for leadership perspectives.",
            ),
            RawOpportunityIdea(
                title="Quick Tips for Marketing Efficiency",
                angle="Tactical advice thread format for engagement.",
                type="evergreen",
                primary_channel="x",
                suggested_channels=["x"],
                reasoning="Good for X engagement",
                why_now="Budget constraints in current market drive efficiency focus.",
            ),
            RawOpportunityIdea(
                title="Industry Report Deep Dive",
                angle="Analysis of recent industry report with contrarian take.",
                type="trend",
                primary_channel="linkedin",
                suggested_channels=["linkedin", "x"],
                reasoning="Timely content opportunity",
                why_now="New Forrester report released this week sparks discussion.",
            ),
            RawOpportunityIdea(
                title="Customer Success Spotlight",
                angle="Share customer achievement as case study.",
                type="evergreen",
                primary_channel="linkedin",
                suggested_channels=["linkedin"],
                reasoning="Social proof content",
                why_now="Customer just hit major milestone worth celebrating publicly.",
            ),
            RawOpportunityIdea(
                title="Differentiation Point: Our Unique Approach",
                angle="Contrast our approach with market standard.",
                type="competitive",
                primary_channel="x",
                suggested_channels=["x", "linkedin"],
                reasoning="Competitive positioning",
                why_now="Competitor announcement yesterday creates differentiation opportunity.",
            ),
        ]
    )


@pytest.fixture
def fake_scoring_output():
    """Fake LLM output for scoring node - uses new minimal schema."""
    return MinimalScoringOutput(
        scores=[
            MinimalScoringItem(idx=0, score=88, band="strong", reason="High relevance"),
            MinimalScoringItem(idx=1, score=75, band="strong", reason="Strong pillar alignment"),
            MinimalScoringItem(idx=2, score=72, band="strong", reason="Good engagement format"),
            MinimalScoringItem(idx=3, score=80, band="strong", reason="Timely and relevant"),
            MinimalScoringItem(idx=4, score=70, band="strong", reason="Solid social proof"),
            MinimalScoringItem(idx=5, score=68, band="strong", reason="Clear differentiation"),
        ]
    )


def create_fake_llm_client(synthesis_output, scoring_output):
    """Create a fake LLM client that returns deterministic outputs."""
    call_count = [0]  # Use list to allow mutation in closure

    def fake_call(
        *,
        brand_id,
        flow,
        prompt,
        role="fast",
        tools=None,
        system_prompt=None,
        max_output_tokens=None,
        temperature=None,  # New parameter
        run_id=None,
        trigger_source="api",
    ):
        call_count[0] += 1

        if "synthesis" in flow.lower():
            output_json = synthesis_output.model_dump_json()
        else:
            # Scoring now uses minimal schema
            output_json = scoring_output.model_dump_json()

        return LLMResponse(
            raw_text=output_json,
            model="test-model",
            usage_tokens_in=100,
            usage_tokens_out=200,
            latency_ms=50,
            role=role,
            status="success",
        )

    client = MagicMock(spec=LLMClient)
    client.call = MagicMock(side_effect=fake_call)
    client._call_count = call_count

    return client


# =============================================================================
# MODULE INTEGRITY TESTS
# =============================================================================


class TestModuleIntegrity:
    """Tests to verify graph module follows conventions."""

    def test_no_orm_imports_in_graph_module(self):
        """Graph module must not import ORM (django.db, models)."""
        import importlib
        import sys

        # Get the module
        from kairo.hero.graphs import opportunities_graph

        # Check module's source
        import inspect

        source = inspect.getsource(opportunities_graph)

        # These imports should NOT be present
        forbidden_patterns = [
            "from django.db",
            "from kairo.core.models",
            "import django.db",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in source, f"Found forbidden import: {pattern}"

    def test_no_requests_imports_in_graph_module(self):
        """Graph module must not make HTTP calls."""
        from kairo.hero.graphs import opportunities_graph
        import inspect

        source = inspect.getsource(opportunities_graph)

        forbidden_patterns = [
            "import requests",
            "import httpx",
            "import aiohttp",
            "from requests",
            "from httpx",
            "from aiohttp",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in source, f"Found forbidden import: {pattern}"


# =============================================================================
# GRAPH FUNCTION TESTS
# =============================================================================


class TestGraphHeroGenerateOpportunities:
    """Tests for the main graph entrypoint."""

    def test_returns_opportunity_draft_list(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Graph returns a list of OpportunityDraftDTO."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        assert isinstance(result, list)
        assert len(result) >= 6
        for draft in result:
            assert isinstance(draft, OpportunityDraftDTO)

    def test_opportunities_have_valid_titles(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Each opportunity has non-empty title."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        for draft in result:
            assert draft.proposed_title, "Title must be non-empty"
            assert len(draft.proposed_title) >= 5, "Title must be at least 5 chars"

    def test_opportunities_have_valid_angles(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Each opportunity has non-empty angle."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        for draft in result:
            assert draft.proposed_angle, "Angle must be non-empty"
            assert len(draft.proposed_angle) >= 10, "Angle must be at least 10 chars"

    def test_opportunities_have_valid_channels(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Each opportunity has valid primary_channel."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        valid_channels = {Channel.LINKEDIN, Channel.X}
        for draft in result:
            assert draft.primary_channel in valid_channels, (
                f"Invalid channel: {draft.primary_channel}"
            )

    def test_opportunities_have_valid_scores(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Each opportunity has score in [0, 100]."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        for draft in result:
            assert 0 <= draft.score <= 100, f"Score {draft.score} out of range"

    def test_opportunities_have_valid_types(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Each opportunity has valid OpportunityType."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        for draft in result:
            assert isinstance(draft.type, OpportunityType)

    def test_opportunities_sorted_by_score_descending(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Opportunities are sorted by score descending."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        scores = [d.score for d in result]
        assert scores == sorted(scores, reverse=True)

    def test_llm_client_called_twice(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Graph makes exactly 2 LLM calls (synthesis + scoring)."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        assert fake_client.call.call_count == 2


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestGraphErrorHandling:
    """Tests for graph error handling."""

    def test_llm_call_error_raises_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
    ):
        """LLMCallError is wrapped in GraphError."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.call.side_effect = LLMCallError("API timeout")

        with pytest.raises(GraphError) as exc_info:
            graph_hero_generate_opportunities(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                learning_summary=sample_learning_summary,
                external_signals=sample_external_signals,
                llm_client=fake_client,
            )

        assert "LLM call failed" in str(exc_info.value)
        assert exc_info.value.original_error is not None

    def test_parsing_error_raises_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
    ):
        """Invalid JSON from LLM raises GraphError."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.call.return_value = LLMResponse(
            raw_text="not valid json at all",
            model="test-model",
            usage_tokens_in=100,
            usage_tokens_out=50,
            latency_ms=50,
            role="heavy",
            status="success",
        )

        with pytest.raises(GraphError) as exc_info:
            graph_hero_generate_opportunities(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                learning_summary=sample_learning_summary,
                external_signals=sample_external_signals,
                llm_client=fake_client,
            )

        assert "Output parsing failed" in str(exc_info.value)

    def test_validation_error_raises_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
    ):
        """Invalid schema from LLM raises GraphError."""
        fake_client = MagicMock(spec=LLMClient)
        # Valid JSON but missing required fields
        fake_client.call.return_value = LLMResponse(
            raw_text='{"opportunities": []}',  # Empty list violates min_length
            model="test-model",
            usage_tokens_in=100,
            usage_tokens_out=50,
            latency_ms=50,
            role="heavy",
            status="success",
        )

        with pytest.raises(GraphError) as exc_info:
            graph_hero_generate_opportunities(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                learning_summary=sample_learning_summary,
                external_signals=sample_external_signals,
                llm_client=fake_client,
            )

        assert "Output parsing failed" in str(exc_info.value)


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestBuildExternalSignalsSummary:
    """Tests for _build_external_signals_summary helper."""

    def test_empty_signals_returns_fallback_message(self, sample_brand_id):
        """Empty signals bundle returns sensible fallback."""
        signals = ExternalSignalBundleDTO(
            brand_id=sample_brand_id,
            fetched_at=datetime.now(timezone.utc),
            trends=[],
            web_mentions=[],
            competitor_posts=[],
            social_moments=[],
        )

        result = _build_external_signals_summary(signals)

        assert "No external signals available" in result
        assert "evergreen" in result.lower()

    def test_trends_included_in_summary(self, sample_brand_id):
        """Trend signals are included in summary."""
        signals = ExternalSignalBundleDTO(
            brand_id=sample_brand_id,
            fetched_at=datetime.now(timezone.utc),
            trends=[
                TrendSignalDTO(
                    id="t1",
                    topic="AI Marketing",
                    source="linkedin",
                    relevance_score=90.0,
                ),
            ],
            web_mentions=[],
            competitor_posts=[],
            social_moments=[],
        )

        result = _build_external_signals_summary(signals)

        assert "AI Marketing" in result
        assert "TRENDS" in result


class TestConvertToDraftDtos:
    """Tests for _convert_to_draft_dtos helper."""

    def test_zero_score_marks_invalid_not_filtered(self):
        """Opportunities with score 0 are marked invalid but not filtered.

        Per rubric §4.7: Graph returns all opps; engine filters invalid ones.
        """
        scored = [
            ScoredOpportunity(
                title="Good Opportunity",
                angle="Valid angle for testing purposes.",
                type="trend",
                primary_channel="linkedin",
                score=75.0,
                score_explanation="Good",
                why_now="Trending topic this week due to recent announcements.",
            ),
            ScoredOpportunity(
                title="Bad Opportunity",
                angle="This violates taboos and should be filtered.",
                type="trend",
                primary_channel="linkedin",
                score=0.0,  # Taboo violation
                score_explanation="Violates taboo",
                why_now="Competitor announcement yesterday.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        # Both are returned, but bad one is marked invalid
        assert len(result) == 2
        good = next(r for r in result if r.proposed_title == "Good Opportunity")
        bad = next(r for r in result if r.proposed_title == "Bad Opportunity")

        assert good.is_valid is True
        assert good.score == 75.0

        assert bad.is_valid is False
        assert bad.score == 0.0
        assert any("taboo" in r.lower() for r in bad.rejection_reasons)

    def test_normalizes_channel_values(self):
        """Channel strings are normalized to Channel enum."""
        scored = [
            ScoredOpportunity(
                title="Test Opportunity Title",
                angle="Testing channel normalization behavior.",
                type="evergreen",
                primary_channel="LINKEDIN",  # Uppercase
                score=70.0,
                why_now="Evergreen topic with recurring customer value.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert result[0].primary_channel == Channel.LINKEDIN

    def test_normalizes_type_values(self):
        """Type strings are normalized to OpportunityType enum."""
        scored = [
            ScoredOpportunity(
                title="Test Opportunity Title",
                angle="Testing type normalization behavior.",
                type="TREND",  # Uppercase
                primary_channel="linkedin",
                score=70.0,
                why_now="This topic is trending this week due to news.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert result[0].type == OpportunityType.TREND

    def test_unknown_type_defaults_to_evergreen(self):
        """Unknown type defaults to EVERGREEN but marks invalid due to bad type."""
        scored = [
            ScoredOpportunity(
                title="Test Opportunity Title",
                angle="Testing unknown type fallback behavior.",
                type="unknown_type",
                primary_channel="linkedin",
                score=70.0,
                why_now="Evergreen content with recurring value.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert result[0].type == OpportunityType.EVERGREEN
        # Invalid type is a rejection reason
        assert result[0].is_valid is False

    def test_unknown_channel_defaults_to_linkedin(self):
        """Unknown channel defaults to LINKEDIN but marks invalid."""
        scored = [
            ScoredOpportunity(
                title="Test Opportunity Title",
                angle="Testing unknown channel fallback behavior.",
                type="trend",
                primary_channel="unknown_channel",
                score=70.0,
                why_now="This topic is trending due to recent news.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert result[0].primary_channel == Channel.LINKEDIN
        # Invalid channel is a rejection reason
        assert result[0].is_valid is False

    def test_score_within_valid_range(self):
        """Scores within range are preserved for valid opps."""
        scored = [
            ScoredOpportunity(
                title="Test Opportunity Title",
                angle="Testing score within valid range behavior.",
                type="trend",
                primary_channel="linkedin",
                score=95.0,  # Valid score
                why_now="Trending topic this week due to major announcements.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert result[0].is_valid is True
        assert result[0].score == 95.0

    def test_empty_suggested_channels_defaults(self):
        """Empty suggested_channels gets default values."""
        scored = [
            ScoredOpportunity(
                title="Test Opportunity Title",
                angle="Testing default suggested channels.",
                type="trend",
                primary_channel="linkedin",
                suggested_channels=[],
                score=70.0,
                why_now="This topic is timely due to recent events.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert Channel.LINKEDIN in result[0].suggested_channels
        assert Channel.X in result[0].suggested_channels


# =============================================================================
# LLM CLIENT ISOLATION TESTS
# =============================================================================


class TestLLMClientIsolation:
    """Tests verifying LLM client is properly isolated."""

    def test_graph_uses_provided_client(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """Graph uses the injected LLM client."""
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        # Verify our fake client was called
        assert fake_client.call.called

    def test_no_real_llm_calls_with_disabled(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
    ):
        """With LLM_DISABLED, real calls are not made and stub JSON is returned."""
        # Create a client with LLM_DISABLED
        config = LLMConfig(llm_disabled=True)
        client = LLMClient(config=config)

        # This would fail if it tried to make real calls (no API key)
        # But with disabled mode, it returns valid stub JSON that matches the schema
        # So the graph should complete successfully
        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=client,
        )

        # Verify stub opportunities were returned
        assert len(result) >= 6  # Min per schema
        assert all(isinstance(opp, OpportunityDraftDTO) for opp in result)
        # Verify all have valid fields
        for opp in result:
            assert opp.proposed_title
            assert opp.proposed_angle
            assert opp.score >= 0


# =============================================================================
# VALIDITY AND REJECTION TESTS (per rubric §4.7)
# =============================================================================


class TestOpportunityValidity:
    """Tests for opportunity validity per rubric §4.7."""

    def test_valid_opportunity_has_is_valid_true(self):
        """Valid opportunity with all required fields is marked valid."""
        scored = [
            ScoredOpportunity(
                title="AI Marketing Trends: What CMOs Need to Know",
                angle="Emerging AI tools are transforming how marketing teams work.",
                type="trend",
                primary_channel="linkedin",
                score=85.0,
                why_now="Recent AI announcements from major tech companies make this timely.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is True
        assert result[0].rejection_reasons == []
        assert result[0].score == 85.0

    def test_missing_why_now_marks_invalid(self):
        """Opportunity missing why_now is marked invalid per §4.3."""
        scored = [
            ScoredOpportunity(
                title="Some Generic Topic",
                angle="A generic angle that could apply to anything.",
                type="evergreen",
                primary_channel="linkedin",
                score=70.0,
                why_now="",  # Empty why_now
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is False
        assert any("why_now" in r.lower() for r in result[0].rejection_reasons)
        assert result[0].score == 0.0  # Per §7.3, invalid opps get score=0

    def test_vacuous_why_now_marks_invalid(self):
        """Opportunity with vacuous why_now is marked invalid per §4.3."""
        scored = [
            ScoredOpportunity(
                title="Some Topic That Is Always Relevant",
                angle="Content about a topic that marketers always care about.",
                type="evergreen",
                primary_channel="linkedin",
                score=72.0,
                why_now="This is always relevant to marketers.",  # Vacuous
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is False
        assert any("vacuous" in r.lower() for r in result[0].rejection_reasons)

    def test_zero_score_marks_invalid(self):
        """Opportunity with score=0 (taboo violation) is marked invalid per §4.6."""
        scored = [
            ScoredOpportunity(
                title="Competitor Bash Post",
                angle="Let's talk about why our competitors are terrible.",
                type="competitive",
                primary_channel="x",
                score=0.0,  # Taboo violation from LLM
                why_now="Competitor just released a bad product.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is False
        assert any("taboo" in r.lower() for r in result[0].rejection_reasons)

    def test_short_title_marks_invalid(self):
        """Opportunity with too-short title is marked invalid per §4.1."""
        scored = [
            ScoredOpportunity(
                title="AI",  # Too short
                angle="Emerging AI tools are transforming marketing.",
                type="trend",
                primary_channel="linkedin",
                score=75.0,
                why_now="AI is trending this week due to new releases.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is False
        assert any("title" in r.lower() for r in result[0].rejection_reasons)

    def test_invalid_channel_marks_invalid(self):
        """Opportunity with invalid channel is marked invalid per §4.2."""
        scored = [
            ScoredOpportunity(
                title="Great Content Opportunity",
                angle="This is a great opportunity for our brand.",
                type="trend",
                primary_channel="instagram",  # Invalid for PRD-1
                score=80.0,
                why_now="This is trending on social media right now.",
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is False
        assert any("channel" in r.lower() for r in result[0].rejection_reasons)

    def test_why_now_preserved_in_dto(self):
        """why_now field is preserved in the DTO."""
        why_now_text = "Recent AI announcements from OpenAI make this timely."
        scored = [
            ScoredOpportunity(
                title="AI Marketing Trends",
                angle="Exploring AI impact on marketing.",
                type="trend",
                primary_channel="linkedin",
                score=85.0,
                why_now=why_now_text,
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert result[0].why_now == why_now_text

    def test_multiple_rejection_reasons(self):
        """Opportunity with multiple issues has multiple rejection reasons."""
        scored = [
            ScoredOpportunity(
                title="AI",  # Too short
                angle="Short",  # Too short
                type="invalid_type",  # Invalid
                primary_channel="tiktok",  # Invalid
                score=0.0,  # Taboo
                why_now="",  # Empty
            ),
        ]

        result = _convert_to_draft_dtos(scored)

        assert len(result) == 1
        assert result[0].is_valid is False
        assert len(result[0].rejection_reasons) >= 4  # Multiple issues


class TestScoringOutputParsing:
    """Tests for scoring output parsing, including real LLM failure cases."""

    def test_broken_scoring_response_fails_to_parse(self):
        """
        Demonstrate that truncated LLM scoring output fails to parse.

        This test uses a real LLM response that was captured during eval.
        The response is truncated (JSON incomplete) which causes parse failure.
        """
        from kairo.hero.llm_client import parse_structured_output, StructuredOutputError
        import os

        # Load the broken response fixture
        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "fixtures/llm/scoring_broken_example.txt"
        )
        with open(fixture_path, "r") as f:
            broken_response = f.read()

        # This should fail with StructuredOutputError due to invalid/truncated JSON
        with pytest.raises(StructuredOutputError) as exc_info:
            parse_structured_output(broken_response, ScoringOutput)

        # Verify the error message indicates JSON parsing failure
        assert "Invalid JSON" in str(exc_info.value)


class TestNormalGraphRunValidity:
    """Tests ensuring normal graph runs produce valid opportunities."""

    def test_normal_run_all_opps_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """For typical inputs, all returned opps should be valid."""
        # why_now is now included in fake_synthesis_output fixture
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        # All should be valid
        for draft in result:
            assert draft.is_valid is True, f"Expected valid: {draft.proposed_title}"
            assert draft.rejection_reasons == []

    def test_normal_run_scores_in_expected_range(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """For typical inputs, scores should be in [60, 95] range."""
        # why_now is now included in fake_synthesis_output fixture
        fake_client = create_fake_llm_client(fake_synthesis_output, fake_scoring_output)

        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=fake_client,
        )

        for draft in result:
            if draft.is_valid:
                assert 60 <= draft.score <= 95, f"Score {draft.score} not in expected range"


# =============================================================================
# TOLERANT PARSING TESTS
# =============================================================================


class TestTolerantParsing:
    """Tests for per-item tolerant parsing in scoring step."""

    def test_partial_malformed_scores_still_succeeds(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
    ):
        """
        When exactly one scoring item is malformed but others are fine,
        F1 run stays ok and the malformed item becomes invalid with score=0.

        The opportunity at index 2 (Quick Tips for Marketing Efficiency) won't
        have a scoring entry because the item at array position 2 is malformed.
        """
        # Create scoring output with one malformed item at array position 2
        # This means opportunity at idx=2 won't have a valid score
        scoring_json = json.dumps({
            "scores": [
                {"idx": 0, "score": 88, "band": "strong", "reason": "Good"},
                {"idx": 1, "score": 75, "band": "strong", "reason": "OK"},
                {"idx": 2, "score": "invalid_score"},  # Malformed - will fail validation
                {"idx": 3, "score": 80, "band": "strong", "reason": "Timely"},
                {"idx": 4, "score": 70, "band": "strong", "reason": "Solid"},
                {"idx": 5, "score": 68, "band": "strong", "reason": "Clear"},
            ]
        })

        def fake_call(*, brand_id, flow, prompt, role="fast", tools=None,
                      system_prompt=None, max_output_tokens=None, temperature=None,
                      run_id=None, trigger_source="api"):
            if "synthesis" in flow.lower():
                return LLMResponse(
                    raw_text=fake_synthesis_output.model_dump_json(),
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )
            else:
                return LLMResponse(
                    raw_text=scoring_json,
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )

        client = MagicMock(spec=LLMClient)
        client.call = MagicMock(side_effect=fake_call)

        # Graph should succeed, not raise GraphError
        result = graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=client,
        )

        # Should have all 6 opportunities
        assert len(result) == 6

        # Find the invalid opportunity (should have score=0)
        invalid_opps = [r for r in result if r.score == 0.0]
        assert len(invalid_opps) == 1, f"Expected 1 invalid opp, got {len(invalid_opps)}"

        invalid_opp = invalid_opps[0]
        assert invalid_opp.is_valid is False
        # The score_explanation should contain schema mismatch info
        assert "scoring_schema_mismatch" in invalid_opp.score_explanation

        # Other items should have their scores
        valid_opps = [r for r in result if r.score > 0]
        assert len(valid_opps) == 5

    def test_all_malformed_scores_raises_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
    ):
        """
        When all scoring items are malformed, graph raises GraphError
        and f1_status becomes degraded.
        """
        # All items malformed - missing required fields
        scoring_json = json.dumps({
            "scores": [
                {"bad_field": "junk"},
                {"another_bad": 123},
                {"totally": "wrong"},
                {"not": "valid"},
                {"missing": "everything"},
                {"garbage": True},
            ]
        })

        def fake_call(*, brand_id, flow, prompt, role="fast", tools=None,
                      system_prompt=None, max_output_tokens=None, temperature=None,
                      run_id=None, trigger_source="api"):
            if "synthesis" in flow.lower():
                return LLMResponse(
                    raw_text=fake_synthesis_output.model_dump_json(),
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )
            else:
                return LLMResponse(
                    raw_text=scoring_json,
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )

        client = MagicMock(spec=LLMClient)
        client.call = MagicMock(side_effect=fake_call)

        # Should raise GraphError when all items fail
        with pytest.raises(GraphError) as exc_info:
            graph_hero_generate_opportunities(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                learning_summary=sample_learning_summary,
                external_signals=sample_external_signals,
                llm_client=client,
            )

        assert "All" in str(exc_info.value) and "failed validation" in str(exc_info.value)

    def test_truncated_json_raises_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
    ):
        """
        Truncated JSON (incomplete) raises GraphError with clear error.
        """
        # Truncated JSON - simulates LLM output cutoff
        truncated_json = '{"scores": [{"idx": 0, "score": 88, "band": "str'

        def fake_call(*, brand_id, flow, prompt, role="fast", tools=None,
                      system_prompt=None, max_output_tokens=None, temperature=None,
                      run_id=None, trigger_source="api"):
            if "synthesis" in flow.lower():
                return LLMResponse(
                    raw_text=fake_synthesis_output.model_dump_json(),
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )
            else:
                return LLMResponse(
                    raw_text=truncated_json,
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )

        client = MagicMock(spec=LLMClient)
        client.call = MagicMock(side_effect=fake_call)

        with pytest.raises(GraphError) as exc_info:
            graph_hero_generate_opportunities(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                learning_summary=sample_learning_summary,
                external_signals=sample_external_signals,
                llm_client=client,
            )

        assert "JSON decode failed" in str(exc_info.value)

    def test_scoring_call_uses_max_tokens_override(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_learning_summary,
        sample_external_signals,
        fake_synthesis_output,
        fake_scoring_output,
    ):
        """
        Scoring LLM call should use explicit max_tokens override (1024).
        """
        from kairo.hero.graphs.opportunities_graph import SCORING_MAX_TOKENS

        call_args = []

        def fake_call(*, brand_id, flow, prompt, role="fast", tools=None,
                      system_prompt=None, max_output_tokens=None, temperature=None,
                      run_id=None, trigger_source="api"):
            call_args.append({
                "flow": flow,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            })
            if "synthesis" in flow.lower():
                return LLMResponse(
                    raw_text=fake_synthesis_output.model_dump_json(),
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )
            else:
                return LLMResponse(
                    raw_text=fake_scoring_output.model_dump_json(),
                    model="test-model",
                    usage_tokens_in=100,
                    usage_tokens_out=200,
                    latency_ms=50,
                    role=role,
                    status="success",
                )

        client = MagicMock(spec=LLMClient)
        client.call = MagicMock(side_effect=fake_call)

        graph_hero_generate_opportunities(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            learning_summary=sample_learning_summary,
            external_signals=sample_external_signals,
            llm_client=client,
        )

        # Find the scoring call
        scoring_call = next(c for c in call_args if "scoring" in c["flow"].lower())

        # Verify explicit max_tokens and temperature overrides
        assert scoring_call["max_output_tokens"] == SCORING_MAX_TOKENS
        assert scoring_call["temperature"] == 0.0  # Deterministic
