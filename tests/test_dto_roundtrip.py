"""
DTO round-trip tests for PR-2.

Tests verify:
- All DTOs can be constructed with valid sample data
- Serialization via .model_dump(mode="json") works
- Deserialization via DTO.model_validate() works
- Key invariants are preserved through round-trip
- Invalid data raises validation errors
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from kairo.hero.dto import (
    BrandSnapshotDTO,
    Channel,
    CompetitorPostSignalDTO,
    ContentPackageDTO,
    CreatePackageResponseDTO,
    CreatedVia,
    DecisionRequestDTO,
    DecisionResponseDTO,
    DecisionType,
    ExecutionEventDTO,
    ExecutionEventType,
    ExecutionSource,
    ExternalSignalBundleDTO,
    GenerateVariantsResponseDTO,
    LearningEventDTO,
    LearningSignalType,
    OpportunityDTO,
    OpportunityDraftDTO,
    OpportunityType,
    PackageStatus,
    PatternCategory,
    PatternStatus,
    PatternTemplateDTO,
    PersonaDTO,
    PillarDTO,
    RegenerateResponseDTO,
    SocialMomentSignalDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
    TrendSignalDTO,
    VariantDTO,
    VariantDraftDTO,
    VariantListDTO,
    VariantStatus,
    VariantUpdateDTO,
    WebMentionSignalDTO,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================


@pytest.fixture
def sample_uuid() -> UUID:
    """A consistent sample UUID for testing."""
    return UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def sample_datetime() -> datetime:
    """A consistent sample datetime for testing."""
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_persona(sample_uuid: UUID) -> PersonaDTO:
    """A sample persona DTO."""
    return PersonaDTO(
        id=sample_uuid,
        name="RevOps Director",
        role="Director of Revenue Operations",
        summary="Senior revenue operations leader",
        priorities=["pipeline accuracy", "data hygiene"],
        pains=["tool sprawl"],
        success_metrics=["forecast accuracy"],
        channel_biases={"linkedin": "professional only"},
    )


@pytest.fixture
def sample_pillar(sample_uuid: UUID) -> PillarDTO:
    """A sample pillar DTO."""
    return PillarDTO(
        id=sample_uuid,
        name="Attribution Reality",
        category="authority",
        description="Content about B2B attribution",
        priority_rank=1,
        is_active=True,
    )


@pytest.fixture
def sample_brand_snapshot(
    sample_uuid: UUID, sample_persona: PersonaDTO, sample_pillar: PillarDTO
) -> BrandSnapshotDTO:
    """A sample brand snapshot DTO."""
    return BrandSnapshotDTO(
        brand_id=sample_uuid,
        brand_name="Acme Analytics",
        positioning="The attribution platform that tells the truth",
        pillars=[sample_pillar],
        personas=[sample_persona],
        voice_tone_tags=["direct", "data-driven"],
        taboos=["never bash competitors"],
    )


@pytest.fixture
def sample_opportunity(sample_uuid: UUID, sample_datetime: datetime) -> OpportunityDTO:
    """A sample opportunity DTO."""
    return OpportunityDTO(
        id=sample_uuid,
        brand_id=sample_uuid,
        title="LinkedIn attribution debate",
        angle="Hot take on attribution models",
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=85,
        score_explanation="High relevance",
        source="LinkedIn trending",
        source_url="https://linkedin.com/posts/example",
        persona_id=sample_uuid,
        pillar_id=sample_uuid,
        suggested_channels=[Channel.LINKEDIN, Channel.X],
        is_pinned=True,
        is_snoozed=False,
        created_via=CreatedVia.AI_SUGGESTED,
        created_at=sample_datetime,
        updated_at=sample_datetime,
    )


@pytest.fixture
def sample_package(sample_uuid: UUID, sample_datetime: datetime) -> ContentPackageDTO:
    """A sample content package DTO."""
    return ContentPackageDTO(
        id=sample_uuid,
        brand_id=sample_uuid,
        title="Attribution Reality Check",
        status=PackageStatus.DRAFT,
        origin_opportunity_id=sample_uuid,
        persona_id=sample_uuid,
        pillar_id=sample_uuid,
        channels=[Channel.LINKEDIN, Channel.X],
        created_via=CreatedVia.AI_SUGGESTED,
        created_at=sample_datetime,
        updated_at=sample_datetime,
    )


@pytest.fixture
def sample_variant(sample_uuid: UUID, sample_datetime: datetime) -> VariantDTO:
    """A sample variant DTO."""
    return VariantDTO(
        id=sample_uuid,
        package_id=sample_uuid,
        brand_id=sample_uuid,
        channel=Channel.LINKEDIN,
        status=VariantStatus.DRAFT,
        pattern_template_id=sample_uuid,
        body="This is a test post body",
        call_to_action="Share your thoughts",
        generated_by_model="gpt-4",
        proposed_at=sample_datetime,
        created_at=sample_datetime,
        updated_at=sample_datetime,
    )


# =============================================================================
# PERSONA & PILLAR TESTS
# =============================================================================


class TestPersonaDTO:
    """Tests for PersonaDTO."""

    def test_roundtrip(self, sample_persona: PersonaDTO):
        """PersonaDTO serializes and deserializes correctly."""
        serialized = sample_persona.model_dump(mode="json")
        deserialized = PersonaDTO.model_validate(serialized)

        assert deserialized.id == sample_persona.id
        assert deserialized.name == sample_persona.name
        assert deserialized.role == sample_persona.role
        assert deserialized.priorities == sample_persona.priorities

    def test_minimal_fields(self, sample_uuid: UUID):
        """PersonaDTO works with minimal required fields."""
        persona = PersonaDTO(id=sample_uuid, name="Test Persona")
        serialized = persona.model_dump(mode="json")
        deserialized = PersonaDTO.model_validate(serialized)

        assert deserialized.id == sample_uuid
        assert deserialized.name == "Test Persona"
        assert deserialized.role is None


class TestPillarDTO:
    """Tests for PillarDTO."""

    def test_roundtrip(self, sample_pillar: PillarDTO):
        """PillarDTO serializes and deserializes correctly."""
        serialized = sample_pillar.model_dump(mode="json")
        deserialized = PillarDTO.model_validate(serialized)

        assert deserialized.id == sample_pillar.id
        assert deserialized.name == sample_pillar.name
        assert deserialized.is_active == sample_pillar.is_active


# =============================================================================
# BRAND SNAPSHOT TESTS
# =============================================================================


class TestBrandSnapshotDTO:
    """Tests for BrandSnapshotDTO."""

    def test_roundtrip(self, sample_brand_snapshot: BrandSnapshotDTO):
        """BrandSnapshotDTO serializes and deserializes correctly."""
        serialized = sample_brand_snapshot.model_dump(mode="json")
        deserialized = BrandSnapshotDTO.model_validate(serialized)

        assert deserialized.brand_id == sample_brand_snapshot.brand_id
        assert deserialized.brand_name == sample_brand_snapshot.brand_name
        assert len(deserialized.pillars) == len(sample_brand_snapshot.pillars)
        assert len(deserialized.personas) == len(sample_brand_snapshot.personas)
        assert deserialized.voice_tone_tags == sample_brand_snapshot.voice_tone_tags
        assert deserialized.taboos == sample_brand_snapshot.taboos

    def test_nested_objects_preserved(self, sample_brand_snapshot: BrandSnapshotDTO):
        """Nested PersonaDTO and PillarDTO are preserved through round-trip."""
        serialized = sample_brand_snapshot.model_dump(mode="json")
        deserialized = BrandSnapshotDTO.model_validate(serialized)

        assert deserialized.pillars[0].name == sample_brand_snapshot.pillars[0].name
        assert deserialized.personas[0].name == sample_brand_snapshot.personas[0].name


# =============================================================================
# OPPORTUNITY TESTS
# =============================================================================


class TestOpportunityDTO:
    """Tests for OpportunityDTO."""

    def test_roundtrip(self, sample_opportunity: OpportunityDTO):
        """OpportunityDTO serializes and deserializes correctly."""
        serialized = sample_opportunity.model_dump(mode="json")
        deserialized = OpportunityDTO.model_validate(serialized)

        assert deserialized.id == sample_opportunity.id
        assert deserialized.title == sample_opportunity.title
        assert deserialized.type == sample_opportunity.type
        assert deserialized.primary_channel == sample_opportunity.primary_channel
        assert deserialized.score == sample_opportunity.score
        assert deserialized.is_pinned == sample_opportunity.is_pinned

    def test_score_bounds(self, sample_uuid: UUID, sample_datetime: datetime):
        """Score must be between 0 and 100."""
        # Valid score
        opp = OpportunityDTO(
            id=sample_uuid,
            brand_id=sample_uuid,
            title="Test",
            angle="Test angle",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=50,
            created_at=sample_datetime,
            updated_at=sample_datetime,
        )
        assert opp.score == 50

        # Invalid score (too high)
        with pytest.raises(ValidationError):
            OpportunityDTO(
                id=sample_uuid,
                brand_id=sample_uuid,
                title="Test",
                angle="Test angle",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=150,  # Invalid
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )

        # Invalid score (negative)
        with pytest.raises(ValidationError):
            OpportunityDTO(
                id=sample_uuid,
                brand_id=sample_uuid,
                title="Test",
                angle="Test angle",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=-10,  # Invalid
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )

    def test_enum_validation(self, sample_uuid: UUID, sample_datetime: datetime):
        """Invalid enum values raise validation errors."""
        with pytest.raises(ValidationError):
            OpportunityDTO(
                id=sample_uuid,
                brand_id=sample_uuid,
                title="Test",
                angle="Test angle",
                type="invalid_type",  # Invalid
                primary_channel=Channel.LINKEDIN,
                score=50,
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )


class TestOpportunityDraftDTO:
    """Tests for OpportunityDraftDTO."""

    def test_roundtrip(self):
        """OpportunityDraftDTO serializes and deserializes correctly."""
        draft = OpportunityDraftDTO(
            proposed_title="Test Opportunity",
            proposed_angle="Why this matters now",
            type=OpportunityType.EVERGREEN,
            primary_channel=Channel.X,
            suggested_channels=[Channel.X, Channel.LINKEDIN],
            score=75,
            persona_hint="RevOps Director",
            pillar_hint="Attribution",
            raw_reasoning="This is the LLM reasoning",
        )

        serialized = draft.model_dump(mode="json")
        deserialized = OpportunityDraftDTO.model_validate(serialized)

        assert deserialized.proposed_title == draft.proposed_title
        assert deserialized.raw_reasoning == draft.raw_reasoning


# =============================================================================
# CONTENT PACKAGE TESTS
# =============================================================================


class TestContentPackageDTO:
    """Tests for ContentPackageDTO."""

    def test_roundtrip(self, sample_package: ContentPackageDTO):
        """ContentPackageDTO serializes and deserializes correctly."""
        serialized = sample_package.model_dump(mode="json")
        deserialized = ContentPackageDTO.model_validate(serialized)

        assert deserialized.id == sample_package.id
        assert deserialized.title == sample_package.title
        assert deserialized.status == sample_package.status
        assert deserialized.channels == sample_package.channels

    def test_all_statuses_valid(self, sample_uuid: UUID, sample_datetime: datetime):
        """All PackageStatus values are valid."""
        for status in PackageStatus:
            pkg = ContentPackageDTO(
                id=sample_uuid,
                brand_id=sample_uuid,
                title="Test",
                status=status,
                channels=[Channel.LINKEDIN],
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )
            assert pkg.status == status


# =============================================================================
# VARIANT TESTS
# =============================================================================


class TestVariantDTO:
    """Tests for VariantDTO."""

    def test_roundtrip(self, sample_variant: VariantDTO):
        """VariantDTO serializes and deserializes correctly."""
        serialized = sample_variant.model_dump(mode="json")
        deserialized = VariantDTO.model_validate(serialized)

        assert deserialized.id == sample_variant.id
        assert deserialized.channel == sample_variant.channel
        assert deserialized.body == sample_variant.body
        assert deserialized.status == sample_variant.status

    def test_all_channels_valid(self, sample_uuid: UUID, sample_datetime: datetime):
        """All Channel values are valid for variants."""
        for channel in Channel:
            variant = VariantDTO(
                id=sample_uuid,
                package_id=sample_uuid,
                brand_id=sample_uuid,
                channel=channel,
                status=VariantStatus.DRAFT,
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )
            assert variant.channel == channel


class TestVariantDraftDTO:
    """Tests for VariantDraftDTO."""

    def test_roundtrip(self):
        """VariantDraftDTO serializes and deserializes correctly."""
        draft = VariantDraftDTO(
            channel=Channel.LINKEDIN,
            body="This is the draft body",
            call_to_action="Comment below",
            pattern_hint="Confessional story",
            raw_reasoning="LLM reasoning here",
        )

        serialized = draft.model_dump(mode="json")
        deserialized = VariantDraftDTO.model_validate(serialized)

        assert deserialized.channel == draft.channel
        assert deserialized.body == draft.body
        assert deserialized.raw_reasoning == draft.raw_reasoning


class TestVariantUpdateDTO:
    """Tests for VariantUpdateDTO."""

    def test_partial_update(self):
        """VariantUpdateDTO allows partial updates."""
        # Only body
        update = VariantUpdateDTO(body="New body")
        assert update.body == "New body"
        assert update.status is None

        # Only status
        update = VariantUpdateDTO(status=VariantStatus.EDITED)
        assert update.body is None
        assert update.status == VariantStatus.EDITED


class TestVariantListDTO:
    """Tests for VariantListDTO."""

    def test_roundtrip(self, sample_variant: VariantDTO, sample_uuid: UUID):
        """VariantListDTO serializes and deserializes correctly."""
        dto = VariantListDTO(
            package_id=sample_uuid,
            variants=[sample_variant],
            count=1,
        )

        serialized = dto.model_dump(mode="json")
        deserialized = VariantListDTO.model_validate(serialized)

        assert deserialized.package_id == sample_uuid
        assert len(deserialized.variants) == 1
        assert deserialized.count == 1


# =============================================================================
# EXECUTION & LEARNING EVENT TESTS
# =============================================================================


class TestExecutionEventDTO:
    """Tests for ExecutionEventDTO."""

    def test_roundtrip(self, sample_uuid: UUID, sample_datetime: datetime):
        """ExecutionEventDTO serializes and deserializes correctly."""
        event = ExecutionEventDTO(
            id=sample_uuid,
            brand_id=sample_uuid,
            variant_id=sample_uuid,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.IMPRESSION,
            decision_type=DecisionType.VARIANT_APPROVED,
            count=100,
            source=ExecutionSource.PLATFORM_WEBHOOK,
            occurred_at=sample_datetime,
            received_at=sample_datetime,
            metadata={"platform_id": "123"},
            created_at=sample_datetime,
        )

        serialized = event.model_dump(mode="json")
        deserialized = ExecutionEventDTO.model_validate(serialized)

        assert deserialized.id == sample_uuid
        assert deserialized.event_type == ExecutionEventType.IMPRESSION
        assert deserialized.decision_type == DecisionType.VARIANT_APPROVED

    def test_all_event_types_valid(self, sample_uuid: UUID, sample_datetime: datetime):
        """All ExecutionEventType values are valid."""
        for event_type in ExecutionEventType:
            event = ExecutionEventDTO(
                id=sample_uuid,
                brand_id=sample_uuid,
                variant_id=sample_uuid,
                channel=Channel.LINKEDIN,
                event_type=event_type,
                source=ExecutionSource.MANUAL_ENTRY,
                occurred_at=sample_datetime,
                received_at=sample_datetime,
                created_at=sample_datetime,
            )
            assert event.event_type == event_type


class TestLearningEventDTO:
    """Tests for LearningEventDTO."""

    def test_roundtrip(self, sample_uuid: UUID, sample_datetime: datetime):
        """LearningEventDTO serializes and deserializes correctly."""
        event = LearningEventDTO(
            id=sample_uuid,
            brand_id=sample_uuid,
            signal_type=LearningSignalType.PATTERN_PERFORMANCE_UPDATE,
            pattern_id=sample_uuid,
            payload={"avg_score": 0.85, "sample_size": 10},
            derived_from=[sample_uuid],
            effective_at=sample_datetime,
            created_at=sample_datetime,
        )

        serialized = event.model_dump(mode="json")
        deserialized = LearningEventDTO.model_validate(serialized)

        assert deserialized.id == sample_uuid
        assert deserialized.signal_type == LearningSignalType.PATTERN_PERFORMANCE_UPDATE
        assert deserialized.payload["avg_score"] == 0.85


# =============================================================================
# EXTERNAL SIGNALS BUNDLE TESTS
# =============================================================================


class TestExternalSignalBundleDTO:
    """Tests for ExternalSignalBundleDTO and nested signal types."""

    def test_trend_signal_roundtrip(self):
        """TrendSignalDTO serializes and deserializes correctly."""
        signal = TrendSignalDTO(
            id="trend_001",
            topic="B2B Attribution",
            source="linkedin_trending",
            relevance_score=85,
            recency_days=2,
            url="https://example.com",
            snippet="Trending discussion about attribution",
        )

        serialized = signal.model_dump(mode="json")
        deserialized = TrendSignalDTO.model_validate(serialized)

        assert deserialized.topic == signal.topic
        assert deserialized.relevance_score == 85

    def test_web_mention_signal_roundtrip(self, sample_datetime: datetime):
        """WebMentionSignalDTO serializes and deserializes correctly."""
        signal = WebMentionSignalDTO(
            id="mention_001",
            title="New Report on Attribution",
            source="techcrunch",
            url="https://techcrunch.com/article",
            snippet="A new report shows...",
            published_at=sample_datetime,
            relevance_score=70,
        )

        serialized = signal.model_dump(mode="json")
        deserialized = WebMentionSignalDTO.model_validate(serialized)

        assert deserialized.title == signal.title

    def test_competitor_post_signal_roundtrip(self, sample_datetime: datetime):
        """CompetitorPostSignalDTO serializes and deserializes correctly."""
        signal = CompetitorPostSignalDTO(
            id="comp_001",
            competitor_name="CompetitorCo",
            channel=Channel.LINKEDIN,
            post_url="https://linkedin.com/post/123",
            post_snippet="Our new feature...",
            engagement_hint="high engagement",
            published_at=sample_datetime,
        )

        serialized = signal.model_dump(mode="json")
        deserialized = CompetitorPostSignalDTO.model_validate(serialized)

        assert deserialized.competitor_name == signal.competitor_name
        assert deserialized.channel == Channel.LINKEDIN

    def test_social_moment_signal_roundtrip(self):
        """SocialMomentSignalDTO serializes and deserializes correctly."""
        signal = SocialMomentSignalDTO(
            id="moment_001",
            description="Viral meme about sales teams",
            channel=Channel.X,
            relevance_hint="Could be adapted for B2B humor",
            recency_hours=6,
        )

        serialized = signal.model_dump(mode="json")
        deserialized = SocialMomentSignalDTO.model_validate(serialized)

        assert deserialized.description == signal.description

    def test_full_bundle_roundtrip(self, sample_uuid: UUID, sample_datetime: datetime):
        """ExternalSignalBundleDTO serializes and deserializes correctly."""
        bundle = ExternalSignalBundleDTO(
            brand_id=sample_uuid,
            fetched_at=sample_datetime,
            trends=[
                TrendSignalDTO(
                    id="trend_001",
                    topic="Attribution",
                    source="linkedin",
                    relevance_score=80,
                )
            ],
            web_mentions=[
                WebMentionSignalDTO(
                    id="mention_001",
                    title="Article",
                    source="blog",
                    url="https://example.com",
                    relevance_score=70,
                )
            ],
            competitor_posts=[
                CompetitorPostSignalDTO(
                    id="comp_001",
                    competitor_name="Rival Inc",
                    channel=Channel.LINKEDIN,
                )
            ],
            social_moments=[
                SocialMomentSignalDTO(
                    id="moment_001",
                    description="Viral moment",
                    channel=Channel.X,
                )
            ],
        )

        serialized = bundle.model_dump(mode="json")
        deserialized = ExternalSignalBundleDTO.model_validate(serialized)

        assert deserialized.brand_id == sample_uuid
        assert len(deserialized.trends) == 1
        assert len(deserialized.web_mentions) == 1
        assert len(deserialized.competitor_posts) == 1
        assert len(deserialized.social_moments) == 1


# =============================================================================
# TODAY BOARD TESTS
# =============================================================================


class TestTodayBoardDTO:
    """Tests for TodayBoardDTO."""

    def test_roundtrip(
        self,
        sample_uuid: UUID,
        sample_datetime: datetime,
        sample_brand_snapshot: BrandSnapshotDTO,
        sample_opportunity: OpportunityDTO,
    ):
        """TodayBoardDTO serializes and deserializes correctly."""
        meta = TodayBoardMetaDTO(
            generated_at=sample_datetime,
            source="hero_f1",
            degraded=False,
            notes=["Test note"],
            opportunity_count=1,
            dominant_pillar="Attribution Reality",
            dominant_persona="RevOps Director",
            channel_mix={"linkedin": 1},
        )

        board = TodayBoardDTO(
            brand_id=sample_uuid,
            snapshot=sample_brand_snapshot,
            opportunities=[sample_opportunity],
            meta=meta,
        )

        serialized = board.model_dump(mode="json")
        deserialized = TodayBoardDTO.model_validate(serialized)

        assert deserialized.brand_id == sample_uuid
        assert len(deserialized.opportunities) == 1
        assert deserialized.meta.source == "hero_f1"
        assert deserialized.snapshot.brand_name == sample_brand_snapshot.brand_name


# =============================================================================
# DECISION TESTS
# =============================================================================


class TestDecisionDTOs:
    """Tests for decision request/response DTOs."""

    def test_decision_request_roundtrip(self):
        """DecisionRequestDTO serializes and deserializes correctly."""
        request = DecisionRequestDTO(
            decision_type=DecisionType.OPPORTUNITY_PINNED,
            reason="High priority for next week",
            metadata={"source": "today_board"},
        )

        serialized = request.model_dump(mode="json")
        deserialized = DecisionRequestDTO.model_validate(serialized)

        assert deserialized.decision_type == DecisionType.OPPORTUNITY_PINNED
        assert deserialized.reason == request.reason

    def test_decision_response_roundtrip(self, sample_uuid: UUID, sample_datetime: datetime):
        """DecisionResponseDTO serializes and deserializes correctly."""
        response = DecisionResponseDTO(
            status="accepted",
            decision_type=DecisionType.VARIANT_APPROVED,
            object_type="variant",
            object_id=sample_uuid,
            recorded_at=sample_datetime,
        )

        serialized = response.model_dump(mode="json")
        deserialized = DecisionResponseDTO.model_validate(serialized)

        assert deserialized.status == "accepted"
        assert deserialized.decision_type == DecisionType.VARIANT_APPROVED
        assert deserialized.object_type == "variant"

    def test_all_decision_types_valid(self, sample_uuid: UUID, sample_datetime: datetime):
        """All DecisionType values are valid."""
        for decision_type in DecisionType:
            response = DecisionResponseDTO(
                decision_type=decision_type,
                object_type="opportunity",
                object_id=sample_uuid,
                recorded_at=sample_datetime,
            )
            assert response.decision_type == decision_type

    def test_invalid_object_type(self, sample_uuid: UUID, sample_datetime: datetime):
        """Invalid object_type raises validation error."""
        with pytest.raises(ValidationError):
            DecisionResponseDTO(
                decision_type=DecisionType.OPPORTUNITY_PINNED,
                object_type="invalid_type",  # Not in Literal
                object_id=sample_uuid,
                recorded_at=sample_datetime,
            )


# =============================================================================
# RESPONSE WRAPPER TESTS
# =============================================================================


class TestResponseWrappers:
    """Tests for API response wrapper DTOs."""

    def test_regenerate_response_roundtrip(
        self, sample_uuid: UUID, sample_datetime: datetime, sample_brand_snapshot: BrandSnapshotDTO
    ):
        """RegenerateResponseDTO serializes and deserializes correctly."""
        today_board = TodayBoardDTO(
            brand_id=sample_uuid,
            snapshot=sample_brand_snapshot,
            opportunities=[],
            meta=TodayBoardMetaDTO(
                generated_at=sample_datetime,
                source="hero_f1",
            ),
        )

        response = RegenerateResponseDTO(
            status="regenerated",
            today_board=today_board,
        )

        serialized = response.model_dump(mode="json")
        deserialized = RegenerateResponseDTO.model_validate(serialized)

        assert deserialized.status == "regenerated"
        assert deserialized.today_board.brand_id == sample_uuid

    def test_create_package_response_roundtrip(self, sample_package: ContentPackageDTO):
        """CreatePackageResponseDTO serializes and deserializes correctly."""
        response = CreatePackageResponseDTO(
            status="created",
            package=sample_package,
        )

        serialized = response.model_dump(mode="json")
        deserialized = CreatePackageResponseDTO.model_validate(serialized)

        assert deserialized.status == "created"
        assert deserialized.package.title == sample_package.title

    def test_generate_variants_response_roundtrip(
        self, sample_uuid: UUID, sample_variant: VariantDTO
    ):
        """GenerateVariantsResponseDTO serializes and deserializes correctly."""
        response = GenerateVariantsResponseDTO(
            status="generated",
            package_id=sample_uuid,
            variants=[sample_variant],
            count=1,
        )

        serialized = response.model_dump(mode="json")
        deserialized = GenerateVariantsResponseDTO.model_validate(serialized)

        assert deserialized.status == "generated"
        assert len(deserialized.variants) == 1
        assert deserialized.count == 1


# =============================================================================
# PATTERN TEMPLATE TESTS
# =============================================================================


class TestPatternTemplateDTO:
    """Tests for PatternTemplateDTO."""

    def test_roundtrip(self, sample_uuid: UUID):
        """PatternTemplateDTO serializes and deserializes correctly."""
        pattern = PatternTemplateDTO(
            id=sample_uuid,
            name="Confessional Story",
            category=PatternCategory.EVERGREEN,
            status=PatternStatus.ACTIVE,
            beats=["Hook", "Context", "Lesson", "CTA"],
            supported_channels=[Channel.LINKEDIN, Channel.X],
            example_snippet="Here's what I learned...",
            performance_hint="Works best for long-form",
            usage_count=42,
            avg_engagement_score=78.5,
        )

        serialized = pattern.model_dump(mode="json")
        deserialized = PatternTemplateDTO.model_validate(serialized)

        assert deserialized.name == pattern.name
        assert deserialized.beats == pattern.beats
        assert deserialized.usage_count == 42


# =============================================================================
# NEGATIVE TESTS (VALIDATION ERRORS)
# =============================================================================


# =============================================================================
# ENUM ALIGNMENT TESTS
# =============================================================================


class TestEnumAlignment:
    """Tests to ensure DTO enums match core enums (single source of truth)."""

    def test_dto_enums_are_core_enums(self):
        """DTOs import enums directly from core, no duplication."""
        # Import from both locations
        from kairo.hero import dto as dto_module
        from kairo.core import enums as core_enums

        # These should be the exact same classes, not copies
        assert dto_module.Channel is core_enums.Channel
        assert dto_module.OpportunityType is core_enums.OpportunityType
        assert dto_module.PackageStatus is core_enums.PackageStatus
        assert dto_module.VariantStatus is core_enums.VariantStatus
        assert dto_module.PatternStatus is core_enums.PatternStatus
        assert dto_module.PatternCategory is core_enums.PatternCategory
        assert dto_module.ExecutionEventType is core_enums.ExecutionEventType
        assert dto_module.ExecutionSource is core_enums.ExecutionSource
        assert dto_module.LearningSignalType is core_enums.LearningSignalType
        assert dto_module.DecisionType is core_enums.DecisionType
        assert dto_module.CreatedVia is core_enums.CreatedVia

    def test_channel_values_match(self):
        """Channel enum values are consistent."""
        from kairo.core.enums import Channel

        expected = {"linkedin", "x", "youtube", "instagram", "tiktok", "newsletter"}
        actual = {c.value for c in Channel}
        assert actual == expected

    def test_decision_type_values_match(self):
        """DecisionType enum values are consistent."""
        from kairo.core.enums import DecisionType

        expected = {
            "opportunity_pinned",
            "opportunity_snoozed",
            "opportunity_ignored",
            "package_created",
            "package_approved",
            "variant_edited",
            "variant_approved",
            "variant_rejected",
        }
        actual = {d.value for d in DecisionType}
        assert actual == expected


class TestValidationErrors:
    """Tests for validation error handling."""

    def test_missing_required_field(self, sample_uuid: UUID, sample_datetime: datetime):
        """Missing required field raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            OpportunityDTO(
                id=sample_uuid,
                brand_id=sample_uuid,
                # title is missing
                angle="Test angle",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                score=50,
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )

        assert "title" in str(exc_info.value)

    def test_invalid_uuid_format(self):
        """Invalid UUID format raises validation error."""
        with pytest.raises(ValidationError):
            PersonaDTO(
                id="not-a-uuid",  # Invalid
                name="Test",
            )

    def test_invalid_enum_value(self, sample_uuid: UUID, sample_datetime: datetime):
        """Invalid enum value raises validation error."""
        with pytest.raises(ValidationError):
            VariantDTO(
                id=sample_uuid,
                package_id=sample_uuid,
                brand_id=sample_uuid,
                channel="invalid_channel",  # Invalid
                status=VariantStatus.DRAFT,
                created_at=sample_datetime,
                updated_at=sample_datetime,
            )

    def test_score_out_of_range(self):
        """Score out of range raises validation error."""
        with pytest.raises(ValidationError):
            TrendSignalDTO(
                id="test",
                topic="Test",
                source="test",
                relevance_score=150,  # Out of range
            )
