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
            ),
            RawOpportunityIdea(
                title="Weekly Leadership Insights",
                angle="Regular thought leadership content showcasing expertise.",
                type="evergreen",
                primary_channel="linkedin",
                suggested_channels=["linkedin"],
                reasoning="Consistent pillar coverage",
            ),
            RawOpportunityIdea(
                title="Quick Tips for Marketing Efficiency",
                angle="Tactical advice thread format for engagement.",
                type="evergreen",
                primary_channel="x",
                suggested_channels=["x"],
                reasoning="Good for X engagement",
            ),
            RawOpportunityIdea(
                title="Industry Report Deep Dive",
                angle="Analysis of recent industry report with contrarian take.",
                type="trend",
                primary_channel="linkedin",
                suggested_channels=["linkedin", "x"],
                reasoning="Timely content opportunity",
            ),
            RawOpportunityIdea(
                title="Customer Success Spotlight",
                angle="Share customer achievement as case study.",
                type="evergreen",
                primary_channel="linkedin",
                suggested_channels=["linkedin"],
                reasoning="Social proof content",
            ),
            RawOpportunityIdea(
                title="Differentiation Point: Our Unique Approach",
                angle="Contrast our approach with market standard.",
                type="competitive",
                primary_channel="x",
                suggested_channels=["x", "linkedin"],
                reasoning="Competitive positioning",
            ),
        ]
    )


@pytest.fixture
def fake_scoring_output():
    """Fake LLM output for scoring node."""
    return ScoringOutput(
        opportunities=[
            ScoredOpportunity(
                title="AI Marketing Trends: What CMOs Need to Know",
                angle="Emerging AI tools are transforming how marketing teams work. Share insights on practical adoption.",
                type="trend",
                primary_channel="linkedin",
                suggested_channels=["linkedin", "x"],
                score=88.0,
                score_explanation="High relevance and timeliness",
            ),
            ScoredOpportunity(
                title="Weekly Leadership Insights",
                angle="Regular thought leadership content showcasing expertise.",
                type="evergreen",
                primary_channel="linkedin",
                suggested_channels=["linkedin"],
                score=75.0,
                score_explanation="Strong pillar alignment",
            ),
            ScoredOpportunity(
                title="Quick Tips for Marketing Efficiency",
                angle="Tactical advice thread format for engagement.",
                type="evergreen",
                primary_channel="x",
                suggested_channels=["x"],
                score=72.0,
                score_explanation="Good engagement format",
            ),
            ScoredOpportunity(
                title="Industry Report Deep Dive",
                angle="Analysis of recent industry report with contrarian take.",
                type="trend",
                primary_channel="linkedin",
                suggested_channels=["linkedin", "x"],
                score=80.0,
                score_explanation="Timely and relevant",
            ),
            ScoredOpportunity(
                title="Customer Success Spotlight",
                angle="Share customer achievement as case study.",
                type="evergreen",
                primary_channel="linkedin",
                suggested_channels=["linkedin"],
                score=70.0,
                score_explanation="Solid social proof",
            ),
            ScoredOpportunity(
                title="Differentiation Point: Our Unique Approach",
                angle="Contrast our approach with market standard.",
                type="competitive",
                primary_channel="x",
                suggested_channels=["x", "linkedin"],
                score=68.0,
                score_explanation="Clear differentiation",
            ),
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
        run_id=None,
        trigger_source="api",
    ):
        call_count[0] += 1

        if "synthesis" in flow.lower():
            output_json = synthesis_output.model_dump_json()
        else:
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
        """With LLM_DISABLED, real calls are not made."""
        # Create a client with LLM_DISABLED
        config = LLMConfig(llm_disabled=True)
        client = LLMClient(config=config)

        # This would fail if it tried to make real calls (no API key)
        # But with disabled mode, it returns stub responses
        # However, the stub response won't have valid JSON for our schema
        # So we expect a GraphError
        with pytest.raises(GraphError):
            graph_hero_generate_opportunities(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                learning_summary=sample_learning_summary,
                external_signals=sample_external_signals,
                llm_client=client,
            )


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
        # Update fake scoring output to include why_now
        for opp in fake_scoring_output.opportunities:
            opp.why_now = "This is timely due to recent market trends and customer needs."

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
        # Update fake scoring output to include why_now
        for opp in fake_scoring_output.opportunities:
            opp.why_now = "This is timely due to recent market trends."

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
