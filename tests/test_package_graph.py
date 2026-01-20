"""
Package Graph unit tests for PR-9.

Tests verify:
- Graph returns valid ContentPackageDraftDTO
- Graph uses LLMClient only (no direct provider SDK calls)
- Graph handles LLM failures by raising PackageGraphError
- No ORM imports in the graph module
- Deterministic stub output in LLM_DISABLED mode
- Rubric validation per docs/technical/09-package-rubric.md

Per PR-map-and-standards §PR-9:
- All tests use fake LLM (no network calls)
- Invariants: thesis non-vacuous, channels valid, primary_channel in channels
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel, OpportunityType, CreatedVia
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ContentPackageDraftDTO,
    OpportunityDTO,
    PersonaDTO,
    PillarDTO,
)
from kairo.hero.graphs.package_graph import (
    PackageGraphError,
    PackageSynthesisOutput,
    RawPackageIdea,
    _compute_package_score,
    _convert_to_draft_dto,
    _validate_package,
    graph_hero_package_from_opportunity,
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
def sample_opportunity(sample_brand_id):
    """Sample OpportunityDTO for testing."""
    return OpportunityDTO(
        id=uuid4(),
        brand_id=sample_brand_id,
        title="AI Marketing Trends: What CMOs Need to Know",
        angle="Emerging AI tools are transforming how marketing teams work. Share insights on practical adoption.",
        # PR-2/4b: Required fields
        why_now="AI adoption is accelerating across marketing teams, making this a timely topic for thought leadership.",
        evidence_ids=[uuid4(), uuid4()],
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=85.0,
        score_explanation="High relevance and timeliness",
        source="linkedin_trending",
        suggested_channels=[Channel.LINKEDIN, Channel.X],
        is_pinned=False,
        is_snoozed=False,
        created_via=CreatedVia.AI_SUGGESTED,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def fake_package_output():
    """Fake LLM output for package synthesis."""
    return PackageSynthesisOutput(
        package=RawPackageIdea(
            title="AI Marketing Transformation Guide",
            thesis="Show how marketing teams can practically adopt AI tools to improve efficiency, using real examples and clear steps that build trust with our CMO audience.",
            summary="This package explores practical AI adoption for marketing teams. We'll cover tool selection, team onboarding, and measuring ROI with concrete examples from our experience.",
            primary_channel="linkedin",
            channels=["linkedin", "x"],
            cta="Book a demo to see our AI-powered marketing tools in action",
            pattern_hints=["thought_leadership", "how_to"],
            persona_hint="CMO",
            pillar_hint="Thought Leadership",
            notes_for_humans="Focus on practical, non-hype AI content",
            reasoning="Aligned with thought leadership pillar and CMO persona priorities",
        )
    )


def create_fake_llm_client(package_output):
    """Create a fake LLM client that returns deterministic output."""

    def fake_call(
        *,
        brand_id,
        flow,
        prompt,
        role="heavy",
        tools=None,
        system_prompt=None,
        max_output_tokens=None,
        run_id=None,
        trigger_source="api",
    ):
        output_json = package_output.model_dump_json()

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
    client.config = MagicMock()
    client.config.llm_disabled = False

    return client


# =============================================================================
# MODULE INTEGRITY TESTS
# =============================================================================


class TestModuleIntegrity:
    """Tests to verify graph module follows conventions."""

    def test_no_orm_imports_in_graph_module(self):
        """Graph module must not import ORM (django.db, models)."""
        from kairo.hero.graphs import package_graph
        import inspect

        source = inspect.getsource(package_graph)

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
        from kairo.hero.graphs import package_graph
        import inspect

        source = inspect.getsource(package_graph)

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


class TestGraphHeroPackageFromOpportunity:
    """Tests for the main graph entrypoint."""

    def test_returns_content_package_draft(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Graph returns a ContentPackageDraftDTO."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert isinstance(result, ContentPackageDraftDTO)

    def test_package_has_valid_title(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Package has non-empty title."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.title, "Title must be non-empty"
        assert len(result.title) >= 5, "Title must be at least 5 chars"

    def test_package_has_valid_thesis(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Package has non-empty, non-vacuous thesis."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.thesis, "Thesis must be non-empty"
        assert len(result.thesis) >= 20, "Thesis must be at least 20 chars"

    def test_package_has_valid_channels(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Package has valid primary_channel and channels list."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        valid_channels = {Channel.LINKEDIN, Channel.X, Channel.NEWSLETTER}
        assert result.primary_channel in valid_channels
        assert result.channels, "Channels list must not be empty"
        assert result.primary_channel in result.channels, "primary_channel must be in channels"

    def test_package_is_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Package passes rubric validation."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.is_valid is True, f"Expected valid but got: {result.rejection_reasons}"
        assert result.rejection_reasons == []

    def test_package_has_quality_band(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Package has quality band assigned."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.quality_band in ["invalid", "weak", "board_ready"]

    def test_package_has_score(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Package has score in [0, 15]."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.package_score is not None
        assert 0 <= result.package_score <= 15

    def test_llm_client_called_once(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Graph makes exactly 1 LLM call."""
        fake_client = create_fake_llm_client(fake_package_output)

        graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert fake_client.call.call_count == 1


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestGraphErrorHandling:
    """Tests for graph error handling."""

    def test_llm_call_error_raises_package_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """LLMCallError is wrapped in PackageGraphError."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = False
        fake_client.call.side_effect = LLMCallError("API timeout")

        with pytest.raises(PackageGraphError) as exc_info:
            graph_hero_package_from_opportunity(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                opportunity=sample_opportunity,
                llm_client=fake_client,
            )

        assert "LLM call failed" in str(exc_info.value)
        assert exc_info.value.original_error is not None

    def test_parsing_error_raises_package_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """Invalid JSON from LLM raises PackageGraphError."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = False
        fake_client.call.return_value = LLMResponse(
            raw_text="not valid json at all",
            model="test-model",
            usage_tokens_in=100,
            usage_tokens_out=50,
            latency_ms=50,
            role="heavy",
            status="success",
        )

        with pytest.raises(PackageGraphError) as exc_info:
            graph_hero_package_from_opportunity(
                run_id=sample_run_id,
                brand_snapshot=sample_brand_snapshot,
                opportunity=sample_opportunity,
                llm_client=fake_client,
            )

        assert "Output parsing failed" in str(exc_info.value)


# =============================================================================
# LLM DISABLED MODE TESTS
# =============================================================================


class TestLLMDisabledMode:
    """Tests for LLM_DISABLED mode (stub output)."""

    def test_returns_stub_when_llm_disabled(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """Returns stub output when LLM is disabled."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert isinstance(result, ContentPackageDraftDTO)
        assert "[STUB]" in result.notes_for_humans

    def test_stub_is_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """Stub output is valid."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.is_valid is True
        assert result.quality_band == "board_ready"

    def test_stub_no_llm_calls(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """No LLM calls made when disabled."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        fake_client.call.assert_not_called()


# =============================================================================
# VALIDATION TESTS
# =============================================================================


class TestValidatePackage:
    """Tests for _validate_package helper."""

    def test_valid_package_passes(self, sample_brand_snapshot, sample_opportunity):
        """Valid package passes validation."""
        pkg = RawPackageIdea(
            title="AI Marketing Transformation Guide",
            thesis="Show how marketing teams can practically adopt AI tools to improve efficiency using real examples.",
            summary="This package explores practical AI adoption for marketing teams with concrete examples.",
            primary_channel="linkedin",
            channels=["linkedin", "x"],
            cta="Book a demo",
            reasoning="Good alignment",
        )

        is_valid, reasons = _validate_package(pkg, sample_opportunity, sample_brand_snapshot)

        assert is_valid is True
        assert reasons == []

    def test_vacuous_thesis_fails(self, sample_brand_snapshot, sample_opportunity):
        """Vacuous thesis fails validation per §5.1."""
        pkg = RawPackageIdea(
            title="AI Marketing Package",
            thesis="Write a post about AI marketing trends and things",
            summary="A package about AI marketing.",
            primary_channel="linkedin",
            channels=["linkedin"],
            reasoning="Generic thesis",
        )

        is_valid, reasons = _validate_package(pkg, sample_opportunity, sample_brand_snapshot)

        assert is_valid is False
        assert any("vacuous" in r.lower() for r in reasons)

    def test_short_thesis_rejected_by_pydantic(self, sample_brand_snapshot, sample_opportunity):
        """Short thesis is rejected by Pydantic schema validation.

        Note: Pydantic enforces min_length=20 for thesis field.
        This test verifies schema validation works.
        """
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            RawPackageIdea(
                title="AI Marketing Package",
                thesis="short",  # Too short - Pydantic rejects
                summary="A package about AI marketing that explains things.",
                primary_channel="linkedin",
                channels=["linkedin"],
                reasoning="Short thesis",
            )

        assert "thesis" in str(exc_info.value).lower()

    def test_invalid_primary_channel_fails(self, sample_brand_snapshot, sample_opportunity):
        """Invalid primary_channel fails validation per §5.2."""
        pkg = RawPackageIdea(
            title="AI Marketing Package",
            thesis="Show how marketing teams can adopt AI tools with practical examples and clear guidance.",
            summary="A package about AI marketing.",
            primary_channel="instagram",  # Invalid
            channels=["instagram"],
            reasoning="Invalid channel",
        )

        is_valid, reasons = _validate_package(pkg, sample_opportunity, sample_brand_snapshot)

        assert is_valid is False
        assert any("channel" in r.lower() for r in reasons)

    def test_primary_channel_not_in_channels_fails(self, sample_brand_snapshot, sample_opportunity):
        """primary_channel not in channels fails validation per §5.2."""
        pkg = RawPackageIdea(
            title="AI Marketing Package",
            thesis="Show how marketing teams can adopt AI tools with practical examples and clear guidance.",
            summary="A package about AI marketing.",
            primary_channel="linkedin",
            channels=["x"],  # primary not in channels
            reasoning="Mismatched channels",
        )

        is_valid, reasons = _validate_package(pkg, sample_opportunity, sample_brand_snapshot)

        assert is_valid is False
        assert any("channel" in r.lower() for r in reasons)

    def test_empty_channels_rejected_by_pydantic(self, sample_brand_snapshot, sample_opportunity):
        """Empty channels list is rejected by Pydantic schema validation.

        Note: Pydantic enforces min_length=1 for channels field.
        """
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            RawPackageIdea(
                title="AI Marketing Package",
                thesis="Show how marketing teams can adopt AI tools with practical examples and clear guidance.",
                summary="A package about AI marketing explained in detail.",
                primary_channel="linkedin",
                channels=[],  # Empty - Pydantic rejects
                reasoning="No channels",
            )

        assert "channels" in str(exc_info.value).lower()

    def test_taboo_violation_fails(self, sample_brand_snapshot, sample_opportunity):
        """Taboo violation fails validation per §5.5."""
        pkg = RawPackageIdea(
            title="Competitor Mentions in AI Marketing",
            thesis="Compare our AI tools with competitor mentions and show why we are better.",
            summary="A package comparing us to competitors.",
            primary_channel="linkedin",
            channels=["linkedin"],
            reasoning="Taboo violation",
        )

        is_valid, reasons = _validate_package(pkg, sample_opportunity, sample_brand_snapshot)

        assert is_valid is False
        assert any("taboo" in r.lower() for r in reasons)


# =============================================================================
# SCORING TESTS
# =============================================================================


class TestComputePackageScore:
    """Tests for _compute_package_score helper."""

    def test_score_in_valid_range(self, sample_opportunity):
        """Score is in [0, 15]."""
        pkg = RawPackageIdea(
            title="AI Marketing Guide",
            thesis="Show how marketing teams can adopt AI tools with practical examples and guidance.",
            summary="Exploring practical AI adoption.",
            primary_channel="linkedin",
            channels=["linkedin", "x"],
            cta="Book a demo to see our AI tools",
            persona_hint="CMO",
            pillar_hint="Thought Leadership",
            reasoning="Good alignment",
        )

        score, breakdown = _compute_package_score(pkg, sample_opportunity)

        assert 0 <= score <= 15
        assert "thesis" in breakdown
        assert "coherence" in breakdown
        assert "relevance" in breakdown
        assert "cta" in breakdown
        assert "brand_alignment" in breakdown

    def test_high_quality_package_high_score(self, sample_opportunity):
        """High quality package gets high score."""
        pkg = RawPackageIdea(
            title="AI Marketing Transformation: What CMOs Need to Know",
            thesis="Show how marketing teams can practically adopt AI tools to improve efficiency, using real examples from leading brands and clear step-by-step implementation guides.",
            summary="This comprehensive guide explores practical AI adoption for marketing teams, covering tool selection criteria, team onboarding best practices, and measuring ROI with concrete examples from our experience working with Fortune 500 marketing teams.",
            primary_channel="linkedin",
            channels=["linkedin", "x"],
            cta="Book a personalized demo to see our AI-powered marketing tools in action",
            persona_hint="CMO",
            pillar_hint="Thought Leadership",
            reasoning="Strong alignment with thought leadership pillar and CMO priorities",
        )

        score, breakdown = _compute_package_score(pkg, sample_opportunity)

        assert score >= 10  # High quality should get 10+

    def test_low_quality_package_lower_than_high_quality(self, sample_opportunity):
        """Low quality package gets lower score than high quality."""
        low_pkg = RawPackageIdea(
            title="AI stuff for marketing",
            thesis="Some generic content about things and marketing and AI stuff.",
            summary="Content about marketing and AI and other general topics.",
            primary_channel="linkedin",
            channels=["linkedin", "x", "newsletter"],  # Many channels
            cta="",  # No CTA
            reasoning="Low quality",
        )

        high_pkg = RawPackageIdea(
            title="AI Marketing Transformation: What CMOs Need to Know",
            thesis="Show how marketing teams can practically adopt AI tools to improve efficiency, using real examples from leading brands and clear step-by-step implementation guides.",
            summary="This comprehensive guide explores practical AI adoption for marketing teams, covering tool selection criteria, team onboarding best practices, and measuring ROI with concrete examples from our experience working with Fortune 500 marketing teams.",
            primary_channel="linkedin",
            channels=["linkedin", "x"],
            cta="Book a personalized demo to see our AI-powered marketing tools in action",
            persona_hint="CMO",
            pillar_hint="Thought Leadership",
            reasoning="Strong alignment",
        )

        low_score, _ = _compute_package_score(low_pkg, sample_opportunity)
        high_score, _ = _compute_package_score(high_pkg, sample_opportunity)

        assert low_score < high_score, "Low quality should score less than high quality"


# =============================================================================
# QUALITY BAND TESTS
# =============================================================================


class TestQualityBands:
    """Tests for quality band assignment."""

    def test_invalid_package_gets_invalid_band(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """Invalid package gets 'invalid' quality band."""
        # Create a fake output with vacuous thesis
        bad_output = PackageSynthesisOutput(
            package=RawPackageIdea(
                title="Generic Package",
                thesis="Write a post about something marketing related.",
                summary="Generic marketing content.",
                primary_channel="linkedin",
                channels=["linkedin"],
                reasoning="Generic",
            )
        )

        fake_client = create_fake_llm_client(bad_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        assert result.quality_band == "invalid"

    def test_board_ready_package_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
        fake_package_output,
    ):
        """Board-ready package is valid and has high score."""
        fake_client = create_fake_llm_client(fake_package_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=sample_opportunity,
            llm_client=fake_client,
        )

        if result.quality_band == "board_ready":
            assert result.is_valid is True
            assert result.package_score >= 8

    def test_package_rubric_produces_weak_band_for_mid_score(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_opportunity,
    ):
        """Package with mid-range score (valid but < 8) gets 'weak' quality band.

        Per 09-package-rubric.md:
        - Score in [0, 15] total (5 dimensions × 3 max each)
        - Quality bands: invalid (is_valid=False), weak (score < 8), board_ready (score >= 8)

        This test constructs output that:
        - Passes all hard validation rules (is_valid=True)
        - Has rubric scores that sum to a weak range (e.g., 4-7)

        Score breakdown targets:
        - thesis: <30 chars = 0, 30-50 = 1, 50-100 = 2, 100+ = 3
        - coherence: 0 channels = 0, 1 = 2, 2-3 = 3, 4+ = 1
        - relevance: keyword overlap with opportunity (title + angle)
        - cta: <5 chars = 0, 5-20 = 1, 20-50 = 2, 50+ = 3
        - brand_alignment: base 2, +0.5 each for persona/pillar hint
        """
        # Create an opportunity with limited keywords
        # Package thesis needs at least 1 keyword overlap to pass §5.6 validity check
        from datetime import datetime, timezone
        weak_opportunity = OpportunityDTO(
            id=uuid4(),
            brand_id=sample_brand_snapshot.brand_id,
            title="Content strategy basics",  # 'content' keyword will overlap
            angle="Learning fundamentals",  # 'learning' available
            # PR-2/4b: Required fields
            why_now="Content strategy is evolving with new trends in marketing automation.",
            evidence_ids=[uuid4()],
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=85.0,
            score_explanation="Test opportunity",
            source="test",
            suggested_channels=[Channel.LINKEDIN],
            is_pinned=False,
            is_snoozed=False,
            created_via=CreatedVia.AI_SUGGESTED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Target scores (looking at actual scoring logic):
        # - thesis: 30-50 chars = 1 (thesis length-based)
        # - coherence: 1 channel = 2
        # - relevance: 1 keyword overlap = 1 (need exactly 1 overlap)
        # - cta: 5-20 chars = 1
        # - brand_alignment: no hints = 2
        # Total: 1 + 2 + 1 + 1 + 2 = 7 (weak band, just under 8)
        #
        # To get relevance=1, we need exactly 1 keyword overlap between
        # (thesis + summary) and (opportunity.title + opportunity.angle)
        weak_output = PackageSynthesisOutput(
            package=RawPackageIdea(
                title="Simple Guide",
                # Thesis: exactly 30-50 chars = thesis score 1
                # Only 'content' overlaps with opportunity
                thesis="Learn about content in this guide.",  # 34 chars, 1 overlap
                # Summary adds no new overlapping keywords
                summary="A brief guide about writing things.",
                primary_channel="linkedin",
                channels=["linkedin"],  # Single channel = coherence 2
                cta="Click here",  # Short CTA ~10 chars = cta score 1
                # No persona_hint, no pillar_hint = brand_alignment 2
                reasoning="Minimal but valid package with low relevance",
            )
        )

        fake_client = create_fake_llm_client(weak_output)

        result = graph_hero_package_from_opportunity(
            run_id=sample_run_id,
            brand_snapshot=sample_brand_snapshot,
            opportunity=weak_opportunity,  # Use the weak opportunity
            llm_client=fake_client,
        )

        # Assert weak band criteria
        assert result.is_valid is True, f"Expected valid but got rejection: {result.rejection_reasons}"
        assert result.package_score is not None
        assert 0 < result.package_score < 8, f"Expected score in weak range (0-8), got {result.package_score}. Breakdown: {result.package_score_breakdown}"
        assert result.quality_band == "weak", f"Expected 'weak' band, got '{result.quality_band}'"
        assert "invalid" not in [r.lower() for r in result.rejection_reasons]


# =============================================================================
# CONVERSION TESTS
# =============================================================================


class TestConvertToDraftDto:
    """Tests for _convert_to_draft_dto helper."""

    def test_converts_all_fields(self, sample_brand_snapshot, sample_opportunity):
        """All fields are converted correctly."""
        pkg = RawPackageIdea(
            title="Test Package",
            thesis="A comprehensive test thesis about AI marketing with practical examples.",
            summary="Test summary for the package.",
            primary_channel="linkedin",
            channels=["linkedin", "x"],
            cta="Learn more",
            pattern_hints=["how_to"],
            persona_hint="CMO",
            pillar_hint="Thought Leadership",
            notes_for_humans="Test notes",
            reasoning="Test reasoning",
        )

        result = _convert_to_draft_dto(pkg, sample_opportunity, sample_brand_snapshot)

        assert result.title == "Test Package"
        assert "AI marketing" in result.thesis
        assert result.primary_channel == Channel.LINKEDIN
        assert Channel.LINKEDIN in result.channels
        assert Channel.X in result.channels
        assert result.cta == "Learn more"
        assert result.persona_hint == "CMO"
        assert result.pillar_hint == "Thought Leadership"

    def test_normalizes_channel_values(self, sample_brand_snapshot, sample_opportunity):
        """Channel strings are normalized to Channel enum."""
        pkg = RawPackageIdea(
            title="Test Package",
            thesis="A comprehensive test thesis about AI marketing with practical examples.",
            summary="Test summary that meets minimum length requirements for validation.",
            primary_channel="LINKEDIN",  # Uppercase
            channels=["LINKEDIN", "X"],
            reasoning="Test",
        )

        result = _convert_to_draft_dto(pkg, sample_opportunity, sample_brand_snapshot)

        assert result.primary_channel == Channel.LINKEDIN
        assert Channel.LINKEDIN in result.channels
