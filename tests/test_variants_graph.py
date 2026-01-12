"""
Variants Graph unit tests for PR-9.

Tests verify:
- Graph returns list of valid VariantDraftDTOs
- Graph uses LLMClient only (no direct provider SDK calls)
- Graph handles LLM failures by raising VariantsGraphError
- No ORM imports in the graph module
- Deterministic stub output in LLM_DISABLED mode
- Rubric validation per docs/technical/10-variant-rubric.md

Per PR-map-and-standards §PR-9:
- All tests use fake LLM (no network calls)
- Invariants: body non-empty, channel valid, appropriate length per channel
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel
from kairo.hero.dto import (
    BrandSnapshotDTO,
    ContentPackageDraftDTO,
    PersonaDTO,
    PillarDTO,
    VariantDraftDTO,
)
from kairo.hero.graphs.variants_graph import (
    CHANNEL_CONSTRAINTS,
    RawVariant,
    VariantsGenerationOutput,
    VariantsGraphError,
    _compute_variant_score,
    _convert_to_draft_dto,
    _validate_variant,
    graph_hero_variants_from_package,
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
def sample_package():
    """Sample ContentPackageDraftDTO for testing."""
    return ContentPackageDraftDTO(
        title="AI Marketing Transformation Guide",
        thesis="Show how marketing teams can practically adopt AI tools to improve efficiency, using real examples and clear steps.",
        summary="This package explores practical AI adoption for marketing teams with concrete examples.",
        primary_channel=Channel.LINKEDIN,
        channels=[Channel.LINKEDIN, Channel.X],
        cta="Book a demo to see our AI tools in action",
        pattern_hints=["thought_leadership", "how_to"],
        persona_hint="CMO",
        pillar_hint="Thought Leadership",
        is_valid=True,
        quality_band="board_ready",
    )


@pytest.fixture
def fake_variants_output():
    """Fake LLM output for variants generation."""
    return VariantsGenerationOutput(
        variants=[
            RawVariant(
                channel="linkedin",
                body="""Here's what we've learned about AI adoption in marketing teams:

The reality is that most marketing teams struggle with AI adoption - not because the tools are bad, but because implementation is hard.

After working with dozens of CMOs, we've identified three key success factors:

1. Start with one use case, not ten
2. Measure time saved, not just accuracy
3. Train the team before launching

The teams that succeed treat AI as a tool, not a replacement.

What's been your experience with AI adoption? I'd love to hear what's worked for you.""",
                call_to_action="Share your thoughts in the comments",
                pattern_hint="thought_leadership",
                reasoning="LinkedIn format with strong hook and clear takeaways",
            ),
            RawVariant(
                channel="x",
                body="""AI adoption in marketing: the hard truth.

Most teams fail not because of bad tools, but bad implementation.

3 things that actually work:
1. One use case at a time
2. Measure time saved
3. Train first, launch second

Thread below on what we've learned.""",
                call_to_action="Follow for more",
                pattern_hint="thread_starter",
                reasoning="X format with concise hook and thread teaser",
            ),
        ]
    )


def create_fake_llm_client(variants_output):
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
        output_json = variants_output.model_dump_json()

        return LLMResponse(
            raw_text=output_json,
            model="test-model",
            usage_tokens_in=100,
            usage_tokens_out=400,
            latency_ms=75,
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
        from kairo.hero.graphs import variants_graph
        import inspect

        source = inspect.getsource(variants_graph)

        forbidden_patterns = [
            "from django.db",
            "from kairo.core.models",
            "import django.db",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in source, f"Found forbidden import: {pattern}"

    def test_no_requests_imports_in_graph_module(self):
        """Graph module must not make HTTP calls."""
        from kairo.hero.graphs import variants_graph
        import inspect

        source = inspect.getsource(variants_graph)

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


class TestGraphHeroVariantsFromPackage:
    """Tests for the main graph entrypoint."""

    def test_returns_variant_draft_list(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Graph returns a list of VariantDraftDTO."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        assert isinstance(result, list)
        assert len(result) == 2
        for variant in result:
            assert isinstance(variant, VariantDraftDTO)

    def test_variants_have_valid_channels(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Each variant has valid channel."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        valid_channels = {Channel.LINKEDIN, Channel.X, Channel.NEWSLETTER}
        for variant in result:
            assert variant.channel in valid_channels

    def test_variants_have_non_empty_body(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Each variant has non-empty body."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        for variant in result:
            assert variant.body, "Body must be non-empty"
            assert len(variant.body) >= 20, "Body must be at least 20 chars"

    def test_variants_are_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Each variant passes validation."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        for variant in result:
            assert variant.is_valid is True, f"Expected valid but got: {variant.rejection_reasons}"
            assert variant.rejection_reasons == []

    def test_variants_have_quality_band(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Each variant has quality band assigned."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        for variant in result:
            assert variant.quality_band in ["invalid", "weak", "publish_ready"]

    def test_variants_have_score(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Each variant has score in [0, 12]."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        for variant in result:
            assert variant.variant_score is not None
            assert 0 <= variant.variant_score <= 12

    def test_llm_client_called_once(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Graph makes exactly 1 LLM call."""
        fake_client = create_fake_llm_client(fake_variants_output)

        graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        assert fake_client.call.call_count == 1


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestGraphErrorHandling:
    """Tests for graph error handling."""

    def test_llm_call_error_raises_variants_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
    ):
        """LLMCallError is wrapped in VariantsGraphError."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = False
        fake_client.call.side_effect = LLMCallError("API timeout")

        with pytest.raises(VariantsGraphError) as exc_info:
            graph_hero_variants_from_package(
                run_id=sample_run_id,
                package=sample_package,
                brand_snapshot=sample_brand_snapshot,
                llm_client=fake_client,
            )

        assert "LLM call failed" in str(exc_info.value)
        assert exc_info.value.original_error is not None

    def test_parsing_error_raises_variants_graph_error(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
    ):
        """Invalid JSON from LLM raises VariantsGraphError."""
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

        with pytest.raises(VariantsGraphError) as exc_info:
            graph_hero_variants_from_package(
                run_id=sample_run_id,
                package=sample_package,
                brand_snapshot=sample_brand_snapshot,
                llm_client=fake_client,
            )

        assert "Output parsing failed" in str(exc_info.value)


# =============================================================================
# LLM DISABLED MODE TESTS
# =============================================================================


class TestLLMDisabledMode:
    """Tests for LLM_DISABLED mode (stub output)."""

    def test_returns_stubs_when_llm_disabled(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
    ):
        """Returns stub output when LLM is disabled."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        assert isinstance(result, list)
        assert len(result) == len(sample_package.channels)

    def test_stubs_are_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
    ):
        """Stub outputs are valid."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        for variant in result:
            assert variant.is_valid is True
            assert variant.quality_band == "publish_ready"

    def test_stubs_no_llm_calls(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
    ):
        """No LLM calls made when disabled."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        fake_client.call.assert_not_called()

    def test_stubs_cover_all_channels(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
    ):
        """Stub generates one variant per channel."""
        fake_client = MagicMock(spec=LLMClient)
        fake_client.config = MagicMock()
        fake_client.config.llm_disabled = True

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        result_channels = {v.channel for v in result}
        expected_channels = set(sample_package.channels)
        assert result_channels == expected_channels


# =============================================================================
# VALIDATION TESTS
# =============================================================================


class TestValidateVariant:
    """Tests for _validate_variant helper."""

    def test_valid_linkedin_variant_passes(self, sample_brand_snapshot):
        """Valid LinkedIn variant passes validation."""
        variant = RawVariant(
            channel="linkedin",
            body="""Here's what we've learned about AI adoption in marketing teams:

The reality is that most marketing teams struggle with AI adoption.

After working with dozens of CMOs, we've identified three key success factors:
1. Start small
2. Measure results
3. Train the team

What's your experience?""",
            call_to_action="Share in comments",
            reasoning="Good format",
        )

        is_valid, reasons = _validate_variant(variant, sample_brand_snapshot)

        assert is_valid is True
        assert reasons == []

    def test_valid_x_variant_passes(self, sample_brand_snapshot):
        """Valid X variant passes validation."""
        variant = RawVariant(
            channel="x",
            body="AI adoption truth: most teams fail on implementation, not tools. Three keys: start small, measure time saved, train first. More below.",
            call_to_action="Follow for more",
            reasoning="Concise X format",
        )

        is_valid, reasons = _validate_variant(variant, sample_brand_snapshot)

        assert is_valid is True
        assert reasons == []

    def test_too_short_body_rejected_by_pydantic(self, sample_brand_snapshot):
        """Too short body is rejected by Pydantic schema validation.

        Note: Pydantic enforces min_length=10 for body field.
        """
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            RawVariant(
                channel="linkedin",
                body="Short.",  # Too short - Pydantic rejects (min_length=10)
                reasoning="Short",
            )

        assert "body" in str(exc_info.value).lower()

    def test_too_long_x_variant_fails(self, sample_brand_snapshot):
        """Too long X variant fails validation per §5.2.2."""
        variant = RawVariant(
            channel="x",
            body="A" * 700,  # Way too long for X
            reasoning="Too long",
        )

        is_valid, reasons = _validate_variant(variant, sample_brand_snapshot)

        assert is_valid is False
        assert any("long" in r.lower() for r in reasons)

    def test_template_artifact_fails(self, sample_brand_snapshot):
        """Template artifact fails validation per §3.3."""
        variant = RawVariant(
            channel="linkedin",
            body="""Here's our marketing guide:

[Insert your company name here] is leading the way in AI marketing.

Please customize the following: {brand} will help you succeed.""",
            reasoning="Has artifacts",
        )

        is_valid, reasons = _validate_variant(variant, sample_brand_snapshot)

        assert is_valid is False
        assert any("artifact" in r.lower() for r in reasons)

    def test_taboo_violation_fails(self, sample_brand_snapshot):
        """Taboo violation fails validation per §3.5."""
        variant = RawVariant(
            channel="linkedin",
            body="""Why competitor mentions are bad:

Our analysis shows that competitor mentions in content reduce engagement.
Here's why you should avoid competitor mentions...""",
            reasoning="Taboo",
        )

        is_valid, reasons = _validate_variant(variant, sample_brand_snapshot)

        assert is_valid is False
        assert any("taboo" in r.lower() for r in reasons)


# =============================================================================
# SCORING TESTS
# =============================================================================


class TestComputeVariantScore:
    """Tests for _compute_variant_score helper."""

    def test_score_in_valid_range(self):
        """Score is in [0, 12]."""
        variant = RawVariant(
            channel="linkedin",
            body="""Here's what we've learned about AI tools:

The key insight is that AI adoption requires careful planning.

Three success factors:
1. Start small
2. Measure impact
3. Train thoroughly""",
            call_to_action="Share your thoughts",
            reasoning="Good format",
        )

        score, breakdown = _compute_variant_score(variant, "AI tools for marketing teams")

        assert 0 <= score <= 12
        assert "clarity" in breakdown
        assert "anchoring" in breakdown
        assert "channel_fit" in breakdown
        assert "cta" in breakdown

    def test_high_quality_variant_high_score(self):
        """High quality variant gets high score."""
        variant = RawVariant(
            channel="linkedin",
            body="""Here's what marketing teams need to know about AI tools:

The reality is that most teams struggle with AI adoption.

After working with dozens of CMOs on AI tools for marketing, we've identified three key success factors:

1. Start with one use case for your marketing team
2. Measure time saved with AI tools, not just accuracy
3. Train the team before launching AI solutions

The marketing teams that succeed treat AI tools as an enhancement, not a replacement.

What's been your experience with AI tools in marketing?""",
            call_to_action="Share your thoughts in the comments below",
            reasoning="Strong hook and clear takeaways",
        )

        score, breakdown = _compute_variant_score(variant, "AI tools for marketing teams")

        assert score >= 8  # High quality

    def test_low_quality_variant_low_score(self):
        """Low quality variant gets low score."""
        variant = RawVariant(
            channel="linkedin",
            body="Generic content about nothing specific that doesn't relate to the thesis at all and has no clear value.",
            call_to_action="",  # No CTA
            reasoning="Low quality",
        )

        score, breakdown = _compute_variant_score(variant, "AI tools for marketing teams")

        assert score <= 5  # Low quality


# =============================================================================
# CHANNEL CONSTRAINT TESTS
# =============================================================================


class TestChannelConstraints:
    """Tests for channel-specific constraints."""

    def test_linkedin_constraints_exist(self):
        """LinkedIn constraints are defined."""
        assert "linkedin" in CHANNEL_CONSTRAINTS
        constraints = CHANNEL_CONSTRAINTS["linkedin"]
        assert "min_chars" in constraints
        assert "max_chars" in constraints

    def test_x_constraints_exist(self):
        """X constraints are defined."""
        assert "x" in CHANNEL_CONSTRAINTS
        constraints = CHANNEL_CONSTRAINTS["x"]
        assert "min_chars" in constraints
        assert "max_chars" in constraints
        assert constraints["max_chars"] <= 600  # Hard limit for X

    def test_newsletter_constraints_exist(self):
        """Newsletter constraints are defined."""
        assert "newsletter" in CHANNEL_CONSTRAINTS
        constraints = CHANNEL_CONSTRAINTS["newsletter"]
        assert "min_chars" in constraints
        assert "max_chars" in constraints


# =============================================================================
# CONVERSION TESTS
# =============================================================================


class TestConvertToDraftDto:
    """Tests for _convert_to_draft_dto helper."""

    def test_converts_all_fields(self, sample_brand_snapshot):
        """All fields are converted correctly."""
        variant = RawVariant(
            channel="linkedin",
            title="Test Title",
            body="""This is test content for LinkedIn.

It has multiple paragraphs and structure.

Let's see how it converts.""",
            call_to_action="Learn more",
            pattern_hint="thought_leadership",
            reasoning="Test reasoning",
        )

        result = _convert_to_draft_dto(variant, "Test thesis content", sample_brand_snapshot)

        assert result.channel == Channel.LINKEDIN
        assert result.title == "Test Title"
        assert "test content" in result.body.lower()
        assert result.call_to_action == "Learn more"
        assert result.pattern_hint == "thought_leadership"

    def test_normalizes_channel_values(self, sample_brand_snapshot):
        """Channel strings are normalized to Channel enum."""
        variant = RawVariant(
            channel="LINKEDIN",  # Uppercase
            body="Test content that meets minimum length requirements for validation.",
            reasoning="Test",
        )

        result = _convert_to_draft_dto(variant, "Test thesis", sample_brand_snapshot)

        assert result.channel == Channel.LINKEDIN


# =============================================================================
# QUALITY BAND TESTS
# =============================================================================


class TestQualityBands:
    """Tests for quality band assignment."""

    def test_publish_ready_variant_valid(
        self,
        sample_run_id,
        sample_brand_snapshot,
        sample_package,
        fake_variants_output,
    ):
        """Publish-ready variant is valid and has high score."""
        fake_client = create_fake_llm_client(fake_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=sample_package,
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        for variant in result:
            if variant.quality_band == "publish_ready":
                assert variant.is_valid is True
                assert variant.variant_score >= 7

    def test_variant_rubric_produces_weak_band_for_mid_score(
        self,
        sample_run_id,
        sample_brand_snapshot,
    ):
        """Variant with mid-range score (valid but < 7) gets 'weak' quality band.

        Per 10-variant-rubric.md:
        - Score in [0, 12] total (4 dimensions × 3 max each)
        - Quality bands: invalid (is_valid=False), weak (score < 7), publish_ready (score >= 7)

        This test constructs output that:
        - Passes all hard validation rules (is_valid=True)
        - Has rubric scores that sum to a weak range (e.g., 4-6)

        Score breakdown targets:
        - clarity: <10 words = 0, 10-30 = 1, 30-100 = 2, 100+ = 3
        - anchoring: keyword overlap with thesis (<1 = 0, 1 = 1, 2-3 = 2, 4+ = 3)
        - channel_fit: depends on structure (linkedin needs line breaks for 3)
        - cta: <3 chars = 0, 3-15 = 1, 15-40 = 2, 40+ = 3
        """
        # Create a package with unique thesis keywords for low anchoring
        weak_package = ContentPackageDraftDTO(
            title="Blockchain Technology Guide",
            # Thesis with unique keywords unlikely to match body
            thesis="Explore decentralized ledger systems and cryptographic protocols for enterprise applications.",
            summary="Technical guide on blockchain infrastructure.",
            primary_channel=Channel.LINKEDIN,
            channels=[Channel.LINKEDIN],
            cta="Learn about blockchain",
            is_valid=True,
            quality_band="board_ready",
        )

        # Target scores:
        # - clarity: ~15 words = 1 (short body)
        # - anchoring: 0-1 keyword overlap with thesis = 0-1
        # - channel_fit: no line breaks for linkedin = 2
        # - cta: ~5 chars = 1
        # Total: 1 + 0 + 2 + 1 = 4 (weak band, clearly < 7)
        weak_variants_output = VariantsGenerationOutput(
            variants=[
                RawVariant(
                    channel="linkedin",
                    # Body: ~15 words = clarity 1
                    # No line breaks = channel_fit 2 (not 3)
                    # No thesis keywords (blockchain, decentralized, ledger, cryptographic, protocols, enterprise) = anchoring 0
                    body="Here is some generic content about business topics and marketing trends that meets minimum requirements but has no overlap with the specified package thesis whatsoever.",
                    call_to_action="Hi!",  # ~3 chars = cta score 1
                    reasoning="Minimal but valid variant with low anchoring",
                ),
            ]
        )

        fake_client = create_fake_llm_client(weak_variants_output)

        result = graph_hero_variants_from_package(
            run_id=sample_run_id,
            package=weak_package,  # Use the weak package with unique thesis
            brand_snapshot=sample_brand_snapshot,
            llm_client=fake_client,
        )

        assert len(result) == 1
        variant = result[0]

        # Assert weak band criteria
        assert variant.is_valid is True, f"Expected valid but got rejection: {variant.rejection_reasons}"
        assert variant.variant_score is not None
        assert 0 < variant.variant_score < 7, f"Expected score in weak range (0-7), got {variant.variant_score}. Breakdown: {variant.variant_score_breakdown}"
        assert variant.quality_band == "weak", f"Expected 'weak' band, got '{variant.quality_band}'"
        assert "invalid" not in [r.lower() for r in variant.rejection_reasons]
