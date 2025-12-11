"""
Content Engine integration tests for PR-9.

Tests verify:
- Engine calls package graph and persists ContentPackage rows
- Engine calls variants graph and persists Variant rows
- Idempotency: same brand+opportunity = same package
- No-regeneration: variants already exist → error
- Engine handles graph failures appropriately
- All invariants from rubrics are respected

Per PR-map-and-standards §PR-9:
- Patch graphs to return known draft sets
- Verify DB rows exist after call
- Verify DTOs match persisted data
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kairo.core.enums import Channel, CreatedVia, OpportunityType, PackageStatus, VariantStatus
from kairo.core.models import Brand, ContentPackage, ContentPillar, Opportunity, Persona, Tenant, Variant
from kairo.hero.dto import (
    ContentPackageDraftDTO,
    VariantDraftDTO,
)
from kairo.hero.engines import content_engine
from kairo.hero.engines.content_engine import (
    PackageCreationError,
    VariantGenerationError,
    VariantsAlreadyExistError,
)
from kairo.hero.graphs.package_graph import PackageGraphError
from kairo.hero.graphs.variants_graph import VariantsGraphError


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
        name="CMO",
        role="Marketing Executive",
        summary="Senior marketing leader",
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
        name="Thought Leadership",
        description="Industry insights and expertise",
        priority_rank=1,
    )
    ContentPillar.objects.create(
        brand=brand,
        name="Product Updates",
        description="New features and improvements",
        priority_rank=2,
    )

    return brand


@pytest.fixture
def opportunity(db, brand):
    """Create a test opportunity."""
    return Opportunity.objects.create(
        brand=brand,
        title="AI Marketing Trends: What CMOs Need to Know",
        angle="Emerging AI tools are transforming marketing teams.",
        type=OpportunityType.TREND,
        primary_channel=Channel.LINKEDIN,
        score=85.0,
        score_explanation="High relevance and timeliness",
        source="linkedin_trending",
        suggested_channels=[Channel.LINKEDIN.value, Channel.X.value],
        is_pinned=False,
        is_snoozed=False,
        created_via=CreatedVia.AI_SUGGESTED,
    )


@pytest.fixture
def sample_package_draft():
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
        notes_for_humans="Focus on practical, non-hype AI content",
        raw_reasoning="Aligned with thought leadership pillar and CMO priorities",
        is_valid=True,
        rejection_reasons=[],
        package_score=12.0,
        package_score_breakdown={
            "thesis": 3,
            "coherence": 3,
            "relevance": 3,
            "cta": 2,
            "brand_alignment": 1,
        },
        quality_band="board_ready",
    )


@pytest.fixture
def sample_variant_drafts():
    """Sample VariantDraftDTO list for testing."""
    return [
        VariantDraftDTO(
            channel=Channel.LINKEDIN,
            body="""Here's what we've learned about AI adoption in marketing teams:

The reality is that most marketing teams struggle with AI adoption.

After working with dozens of CMOs, we've identified three key success factors:
1. Start with one use case
2. Measure time saved
3. Train the team first

What's your experience?""",
            call_to_action="Share in comments",
            pattern_hint="thought_leadership",
            raw_reasoning="LinkedIn format with strong hook",
            is_valid=True,
            rejection_reasons=[],
            variant_score=10.0,
            variant_score_breakdown={
                "clarity": 3,
                "anchoring": 2,
                "channel_fit": 3,
                "cta": 2,
            },
            quality_band="publish_ready",
        ),
        VariantDraftDTO(
            channel=Channel.X,
            body="""AI adoption truth: most teams fail on implementation.

Three keys:
1. Start small
2. Measure time saved
3. Train first

Thread below.""",
            call_to_action="Follow for more",
            pattern_hint="thread_starter",
            raw_reasoning="X format - concise",
            is_valid=True,
            rejection_reasons=[],
            variant_score=9.0,
            variant_score_breakdown={
                "clarity": 2,
                "anchoring": 2,
                "channel_fit": 3,
                "cta": 2,
            },
            quality_band="publish_ready",
        ),
    ]


# =============================================================================
# PACKAGE CREATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestPackageCreation:
    """Tests for package creation via engine."""

    def test_engine_calls_graph_and_returns_package(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Engine calls graph and returns ContentPackage."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            result = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            assert isinstance(result, ContentPackage)
            assert result.brand_id == brand.id
            mock_graph.assert_called_once()

    def test_engine_persists_package_row(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Engine creates ContentPackage row in database."""
        initial_count = ContentPackage.objects.filter(brand=brand).count()

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            final_count = ContentPackage.objects.filter(brand=brand).count()
            assert final_count == initial_count + 1

    def test_persisted_package_has_correct_fields(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Persisted ContentPackage has correct field values."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            result = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            assert result.title == sample_package_draft.title
            assert result.status == PackageStatus.DRAFT.value
            assert result.origin_opportunity_id == opportunity.id
            assert sample_package_draft.thesis in result.notes
            assert Channel.LINKEDIN.value in result.channels
            assert Channel.X.value in result.channels


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================


@pytest.mark.django_db
class TestIdempotency:
    """Tests for idempotency per rubric §8.2."""

    def test_same_opportunity_returns_same_package(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Same brand+opportunity returns same package (idempotent)."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            # First call
            result1 = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            # Second call - should return existing
            result2 = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            assert result1.id == result2.id

    def test_idempotent_call_does_not_call_graph(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Second call for same opportunity does not call graph."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            # First call - calls graph
            content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            # Reset mock call count
            mock_graph.reset_mock()

            # Second call - should not call graph
            content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            mock_graph.assert_not_called()

    def test_no_duplicate_packages_created(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Multiple calls don't create duplicate packages."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            # Multiple calls
            for _ in range(3):
                content_engine.create_package_from_opportunity(
                    brand_id=brand.id,
                    opportunity_id=opportunity.id,
                )

            # Should only have one package
            count = ContentPackage.objects.filter(
                brand=brand,
                origin_opportunity=opportunity,
            ).count()
            assert count == 1


# =============================================================================
# VARIANT GENERATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantGeneration:
    """Tests for variant generation via engine."""

    def test_engine_calls_graph_and_returns_variants(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """Engine calls graph and returns Variant list."""
        # First create a package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Then generate variants
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts

            result = content_engine.generate_variants_for_package(package.id)

            assert isinstance(result, list)
            assert len(result) == 2
            for variant in result:
                assert isinstance(variant, Variant)
            mock_var_graph.assert_called_once()

    def test_engine_persists_variant_rows(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """Engine creates Variant rows in database."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        initial_count = Variant.objects.filter(package=package).count()

        # Generate variants
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts

            content_engine.generate_variants_for_package(package.id)

            final_count = Variant.objects.filter(package=package).count()
            assert final_count == initial_count + 2

    def test_persisted_variants_have_correct_fields(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """Persisted Variant rows have correct field values."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Generate variants
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts

            result = content_engine.generate_variants_for_package(package.id)

            linkedin_variant = next(v for v in result if v.channel == Channel.LINKEDIN.value)
            assert linkedin_variant.status == VariantStatus.DRAFT.value
            assert linkedin_variant.package_id == package.id
            assert linkedin_variant.brand_id == brand.id
            assert "AI adoption" in linkedin_variant.draft_text


# =============================================================================
# NO-REGENERATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestNoRegeneration:
    """Tests for no-regeneration rule per rubric §8.2."""

    def test_regeneration_raises_error(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """Regenerating variants for package with existing variants raises error."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # First variant generation
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts
            content_engine.generate_variants_for_package(package.id)

        # Second attempt should fail
        with pytest.raises(VariantsAlreadyExistError) as exc_info:
            content_engine.generate_variants_for_package(package.id)

        assert "already has" in str(exc_info.value)
        assert "Regeneration is not supported" in str(exc_info.value)

    def test_no_regeneration_doesnt_call_graph(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """When variants exist, graph is not called."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # First generation
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts
            content_engine.generate_variants_for_package(package.id)

            mock_var_graph.reset_mock()

            # Second attempt - should fail before calling graph
            with pytest.raises(VariantsAlreadyExistError):
                content_engine.generate_variants_for_package(package.id)

            mock_var_graph.assert_not_called()


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


@pytest.mark.django_db
class TestErrorHandling:
    """Tests for error handling."""

    def test_package_graph_error_raises_package_creation_error(
        self,
        brand,
        opportunity,
    ):
        """PackageGraphError is wrapped in PackageCreationError."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.side_effect = PackageGraphError("LLM timeout")

            with pytest.raises(PackageCreationError) as exc_info:
                content_engine.create_package_from_opportunity(
                    brand_id=brand.id,
                    opportunity_id=opportunity.id,
                )

            assert "Graph failed" in str(exc_info.value)

    def test_variants_graph_error_raises_variant_generation_error(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """VariantsGraphError is wrapped in VariantGenerationError."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Variant graph fails
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.side_effect = VariantsGraphError("LLM timeout")

            with pytest.raises(VariantGenerationError) as exc_info:
                content_engine.generate_variants_for_package(package.id)

            assert "Graph failed" in str(exc_info.value)

    def test_invalid_package_draft_raises_error(
        self,
        brand,
        opportunity,
    ):
        """Invalid package draft raises PackageCreationError."""
        invalid_draft = ContentPackageDraftDTO(
            title="Invalid Package",
            thesis="Write a post about something",  # Vacuous
            summary="Generic content.",
            primary_channel=Channel.LINKEDIN,
            channels=[Channel.LINKEDIN],
            is_valid=False,
            rejection_reasons=["thesis is vacuous (§5.1)"],
            quality_band="invalid",
        )

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = invalid_draft

            with pytest.raises(PackageCreationError) as exc_info:
                content_engine.create_package_from_opportunity(
                    brand_id=brand.id,
                    opportunity_id=opportunity.id,
                )

            assert "rubric validation" in str(exc_info.value)

    def test_all_invalid_variants_raises_error(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """All variants failing validation raises error."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # All variants invalid
        invalid_variants = [
            VariantDraftDTO(
                channel=Channel.LINKEDIN,
                body="Short",  # Too short
                is_valid=False,
                rejection_reasons=["body too short (§3.1)"],
                quality_band="invalid",
            ),
        ]

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = invalid_variants

            with pytest.raises(VariantGenerationError) as exc_info:
                content_engine.generate_variants_for_package(package.id)

            assert "failed rubric validation" in str(exc_info.value)

    def test_brand_not_found_raises(self, db):
        """Missing brand raises Brand.DoesNotExist."""
        fake_brand_id = uuid4()
        fake_opp_id = uuid4()

        with pytest.raises(Brand.DoesNotExist):
            content_engine.create_package_from_opportunity(
                brand_id=fake_brand_id,
                opportunity_id=fake_opp_id,
            )

    def test_opportunity_not_found_raises(self, brand):
        """Missing opportunity raises Opportunity.DoesNotExist."""
        fake_opp_id = uuid4()

        with pytest.raises(Opportunity.DoesNotExist):
            content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=fake_opp_id,
            )

    def test_package_not_found_raises(self, db):
        """Missing package raises ContentPackage.DoesNotExist."""
        fake_package_id = uuid4()

        with pytest.raises(ContentPackage.DoesNotExist):
            content_engine.generate_variants_for_package(fake_package_id)


# =============================================================================
# HINT RESOLUTION TESTS
# =============================================================================


@pytest.mark.django_db
class TestHintResolution:
    """Tests for persona/pillar hint resolution."""

    def test_persona_hint_resolved_to_id(
        self,
        brand_with_personas_and_pillars,
        sample_package_draft,
    ):
        """Persona hint is resolved to actual persona ID."""
        # Create opportunity for this brand
        opp = Opportunity.objects.create(
            brand=brand_with_personas_and_pillars,
            title="Test Opportunity",
            angle="Testing persona resolution",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_via=CreatedVia.AI_SUGGESTED,
        )

        # Draft with persona hint
        sample_package_draft.persona_hint = "CMO"

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            result = content_engine.create_package_from_opportunity(
                brand_id=brand_with_personas_and_pillars.id,
                opportunity_id=opp.id,
            )

            assert result.persona_id is not None

    def test_pillar_hint_resolved_to_id(
        self,
        brand_with_personas_and_pillars,
        sample_package_draft,
    ):
        """Pillar hint is resolved to actual pillar ID."""
        # Create opportunity for this brand
        opp = Opportunity.objects.create(
            brand=brand_with_personas_and_pillars,
            title="Test Opportunity",
            angle="Testing pillar resolution",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_via=CreatedVia.AI_SUGGESTED,
        )

        # Draft with pillar hint
        sample_package_draft.pillar_hint = "Thought Leadership"

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            result = content_engine.create_package_from_opportunity(
                brand_id=brand_with_personas_and_pillars.id,
                opportunity_id=opp.id,
            )

            assert result.pillar_id is not None


# =============================================================================
# INVALID VARIANT FILTERING TESTS
# =============================================================================


@pytest.mark.django_db
class TestInvalidVariantFiltering:
    """Tests for filtering invalid variants per rubric §3."""

    def test_invalid_variants_not_persisted(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Invalid variants (is_valid=False) are not persisted."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Mix of valid and invalid variants
        mixed_variants = [
            VariantDraftDTO(
                channel=Channel.LINKEDIN,
                body="""Valid LinkedIn content about AI adoption.

This has multiple paragraphs and is long enough.

Key points:
1. Point one
2. Point two""",
                call_to_action="Share thoughts",
                is_valid=True,
                rejection_reasons=[],
                variant_score=9.0,
                quality_band="publish_ready",
            ),
            VariantDraftDTO(
                channel=Channel.X,
                body="Too short",  # Invalid
                is_valid=False,
                rejection_reasons=["body too short (§3.1)"],
                variant_score=0.0,
                quality_band="invalid",
            ),
        ]

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = mixed_variants

            result = content_engine.generate_variants_for_package(package.id)

            # Only valid variant should be returned
            assert len(result) == 1
            assert result[0].channel == Channel.LINKEDIN.value


# =============================================================================
# DTO CONVERSION TESTS
# =============================================================================


@pytest.mark.django_db
class TestDtoConversion:
    """Tests for DTO conversion helpers."""

    def test_package_to_dto_roundtrip(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Package can be converted to DTO correctly."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            dto = content_engine.package_to_dto(package)

            assert dto.id == package.id
            assert dto.brand_id == brand.id
            assert dto.title == sample_package_draft.title
            assert dto.status == PackageStatus.DRAFT
            assert dto.origin_opportunity_id == opportunity.id

    def test_variant_to_dto_roundtrip(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """Variant can be converted to DTO correctly."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Generate variants
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts

            variants = content_engine.generate_variants_for_package(package.id)

            for variant in variants:
                dto = content_engine.variant_to_dto(variant)

                assert dto.id == variant.id
                assert dto.package_id == package.id
                assert dto.brand_id == brand.id
                assert dto.status == VariantStatus.DRAFT


# =============================================================================
# TABOO ENFORCEMENT TESTS
# =============================================================================


@pytest.mark.django_db
class TestTabooEnforcement:
    """Tests for engine-level taboo enforcement per rubric §5.5 / §7."""

    def test_package_with_taboo_in_thesis_rejected(
        self,
        brand,
        opportunity,
    ):
        """Package with taboo violation in thesis is rejected by engine."""
        # Set taboos on brand
        brand.taboos = ["competitor mentions"]
        brand.save()

        # Create draft with taboo violation
        taboo_draft = ContentPackageDraftDTO(
            title="Marketing Strategy Guide",
            thesis="Compare competitor mentions to our platform and show why we're better.",
            summary="A guide about marketing strategies.",
            primary_channel=Channel.LINKEDIN,
            channels=[Channel.LINKEDIN],
            is_valid=True,  # Graph thinks it's valid
            rejection_reasons=[],
            package_score=10.0,
            quality_band="board_ready",
        )

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = taboo_draft

            with pytest.raises(PackageCreationError) as exc_info:
                content_engine.create_package_from_opportunity(
                    brand_id=brand.id,
                    opportunity_id=opportunity.id,
                )

            assert "taboos" in str(exc_info.value).lower()

    def test_package_without_taboos_passes(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Package without taboo violations passes engine check."""
        # Set taboos on brand
        brand.taboos = ["competitor mentions", "controversial politics"]
        brand.save()

        # sample_package_draft should not contain taboos
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            # Should not raise
            result = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            assert result is not None
            assert result.brand_id == brand.id

    def test_variant_with_taboo_in_body_filtered(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Variant with taboo violation in body is filtered by engine."""
        # Set taboos on brand
        brand.taboos = ["competitor mentions"]
        brand.save()

        # Create package first
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Variants with one containing taboo
        mixed_variants = [
            VariantDraftDTO(
                channel=Channel.LINKEDIN,
                body="""Valid LinkedIn content about AI adoption.

This has multiple paragraphs and is clean.

Key points:
1. Point one
2. Point two""",
                call_to_action="Share thoughts",
                is_valid=True,
                rejection_reasons=[],
                variant_score=9.0,
                quality_band="publish_ready",
            ),
            VariantDraftDTO(
                channel=Channel.X,
                body="Check out how competitor mentions compare to our platform. We're better!",
                call_to_action="Follow us",
                is_valid=True,  # Graph thinks it's valid
                rejection_reasons=[],
                variant_score=8.0,
                quality_band="publish_ready",
            ),
        ]

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = mixed_variants

            result = content_engine.generate_variants_for_package(package.id)

            # Only the clean variant should be persisted
            assert len(result) == 1
            assert result[0].channel == Channel.LINKEDIN.value

    def test_all_variants_with_taboos_raises_error(
        self,
        db,
        tenant,
    ):
        """All variants having taboo violations raises error."""
        # Create brand with taboos
        brand = Brand.objects.create(
            tenant=tenant,
            name="Strict Brand",
            slug="strict-brand",
            taboos=["banned phrase"],
        )

        opp = Opportunity.objects.create(
            brand=brand,
            title="Test Opportunity",
            angle="Testing taboo enforcement",
            type=OpportunityType.TREND,
            primary_channel=Channel.LINKEDIN,
            score=80.0,
            created_via=CreatedVia.AI_SUGGESTED,
        )

        pkg_draft = ContentPackageDraftDTO(
            title="Test Package",
            thesis="Clean thesis without any issues at all for marketing teams.",
            summary="Clean summary without issues.",
            primary_channel=Channel.LINKEDIN,
            channels=[Channel.LINKEDIN, Channel.X],
            is_valid=True,
            package_score=10.0,
            quality_band="board_ready",
        )

        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = pkg_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opp.id,
            )

        # All variants contain the taboo
        all_taboo_variants = [
            VariantDraftDTO(
                channel=Channel.LINKEDIN,
                body="This contains the banned phrase for testing purposes.",
                is_valid=True,
                variant_score=8.0,
                quality_band="publish_ready",
            ),
            VariantDraftDTO(
                channel=Channel.X,
                body="Another banned phrase mention here too.",
                is_valid=True,
                variant_score=8.0,
                quality_band="publish_ready",
            ),
        ]

        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = all_taboo_variants

            with pytest.raises(VariantGenerationError) as exc_info:
                content_engine.generate_variants_for_package(package.id)

            assert "failed" in str(exc_info.value).lower()


# =============================================================================
# METRICS SNAPSHOT TESTS
# =============================================================================


@pytest.mark.django_db
class TestMetricsSnapshot:
    """Tests for quality metrics stored in metrics_snapshot/metadata."""

    def test_package_stores_quality_metrics(
        self,
        brand,
        opportunity,
        sample_package_draft,
    ):
        """Package stores quality metrics in metrics_snapshot."""
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_graph:
            mock_graph.return_value = sample_package_draft

            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

            assert package.metrics_snapshot is not None
            assert "package_score" in package.metrics_snapshot
            assert "quality_band" in package.metrics_snapshot
            assert package.metrics_snapshot["quality_band"] == "board_ready"

    def test_variant_stores_quality_metrics(
        self,
        brand,
        opportunity,
        sample_package_draft,
        sample_variant_drafts,
    ):
        """Variant stores quality metrics in metadata."""
        # Create package
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_package_from_opportunity"
        ) as mock_pkg_graph:
            mock_pkg_graph.return_value = sample_package_draft
            package = content_engine.create_package_from_opportunity(
                brand_id=brand.id,
                opportunity_id=opportunity.id,
            )

        # Generate variants
        with patch(
            "kairo.hero.engines.content_engine.graph_hero_variants_from_package"
        ) as mock_var_graph:
            mock_var_graph.return_value = sample_variant_drafts

            variants = content_engine.generate_variants_for_package(package.id)

            for variant in variants:
                assert variant.raw_prompt_context is not None
                assert "variant_score" in variant.raw_prompt_context
                assert "quality_band" in variant.raw_prompt_context
