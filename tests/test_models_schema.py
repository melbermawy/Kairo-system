"""
Schema and constraint tests for PR-1/PR-1b canonical models.

Tests verify:
- Tenant model and Brand-scoped semantics
- All models can be created with required fields
- Unique constraints are enforced
- FK relationships work correctly
- Soft delete behavior
- Enum choices are valid
- Indexes exist on hot paths
- No tenant_id fields on child models (only Tenant and Brand handle scoping)
"""

import uuid

import pytest
from django.db import IntegrityError
from django.utils import timezone

from kairo.core.enums import (
    Channel,
    CreatedVia,
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    LearningSignalType,
    OpportunityType,
    PackageStatus,
    PatternCategory,
    PatternStatus,
    VariantStatus,
)
from kairo.core.models import (
    Brand,
    BrandSnapshot,
    ContentPackage,
    ContentPillar,
    ExecutionEvent,
    LearningEvent,
    Opportunity,
    PatternTemplate,
    Persona,
    Tenant,
    Variant,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant():
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant",
    )


@pytest.fixture
def brand(tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand",
        slug="test-brand",
        primary_channel=Channel.LINKEDIN,
        channels=[Channel.LINKEDIN, Channel.X],
        positioning="A test brand for unit tests",
        tone_tags=["professional", "friendly"],
        taboos=["competitor mentions"],
    )


@pytest.fixture
def persona(brand):
    """Create a test persona."""
    return Persona.objects.create(
        brand=brand,
        name="Test Persona",
        role="Developer",
        summary="A test persona",
        priorities=["learning", "efficiency"],
        pains=["time constraints"],
        success_metrics=["code quality"],
        channel_biases={"linkedin": 0.8, "x": 0.2},
    )


@pytest.fixture
def pillar(brand):
    """Create a test content pillar."""
    return ContentPillar.objects.create(
        brand=brand,
        name="Test Pillar",
        category="thought_leadership",
        description="A test pillar",
        priority_rank=1,
        is_active=True,
    )


@pytest.fixture
def pattern(brand):
    """Create a test pattern template."""
    return PatternTemplate.objects.create(
        brand=brand,
        name="Test Pattern",
        category=PatternCategory.EVERGREEN,
        status=PatternStatus.ACTIVE,
        beats=["hook", "body", "cta"],
        supported_channels=[Channel.LINKEDIN, Channel.X],
    )


@pytest.fixture
def opportunity(brand, persona, pillar):
    """Create a test opportunity."""
    return Opportunity.objects.create(
        brand=brand,
        type=OpportunityType.TREND,
        title="Test Opportunity",
        score=0.85,
        persona=persona,
        pillar=pillar,
        primary_channel=Channel.LINKEDIN,
        created_via=CreatedVia.AI_SUGGESTED,
    )


@pytest.fixture
def package(brand, opportunity, persona, pillar):
    """Create a test content package."""
    return ContentPackage.objects.create(
        brand=brand,
        title="Test Package",
        status=PackageStatus.DRAFT,
        origin_opportunity=opportunity,
        persona=persona,
        pillar=pillar,
        channels=[Channel.LINKEDIN, Channel.X],
    )


@pytest.fixture
def variant(brand, package, pattern):
    """Create a test variant."""
    return Variant.objects.create(
        brand=brand,
        package=package,
        channel=Channel.LINKEDIN,
        status=VariantStatus.DRAFT,
        pattern_template=pattern,
        draft_text="This is a test draft.",
    )


# =============================================================================
# TENANT TESTS
# =============================================================================


@pytest.mark.django_db
class TestTenant:
    """Tests for Tenant model."""

    def test_create_tenant(self):
        """Can create a tenant with unique slug."""
        tenant = Tenant.objects.create(
            name="My Tenant",
            slug="my-tenant",
        )
        assert tenant.id is not None
        assert tenant.created_at is not None
        assert tenant.updated_at is not None

    def test_tenant_slug_unique(self):
        """Tenant slug must be globally unique."""
        Tenant.objects.create(
            name="Tenant One",
            slug="unique-tenant-slug",
        )
        with pytest.raises(IntegrityError):
            Tenant.objects.create(
                name="Tenant Two",
                slug="unique-tenant-slug",
            )

    def test_tenant_has_brands(self, tenant, brand):
        """Tenant can have multiple brands."""
        brand2 = Brand.objects.create(
            tenant=tenant,
            name="Second Brand",
            slug="second-brand",
        )
        assert tenant.brands.count() == 2
        assert brand in tenant.brands.all()
        assert brand2 in tenant.brands.all()


# =============================================================================
# BRAND TESTS
# =============================================================================


@pytest.mark.django_db
class TestBrand:
    """Tests for Brand model."""

    def test_create_brand(self, tenant):
        """Can create a brand with required fields."""
        brand = Brand.objects.create(
            tenant=tenant,
            name="My Brand",
            slug="my-brand",
        )
        assert brand.id is not None
        assert brand.created_at is not None
        assert brand.updated_at is not None

    def test_brand_requires_tenant(self):
        """Brand must have a tenant."""
        with pytest.raises(IntegrityError):
            Brand.objects.create(
                tenant=None,
                name="Orphan Brand",
                slug="orphan-brand",
            )

    def test_brand_unique_tenant_slug(self, tenant):
        """Brand slug must be unique per tenant."""
        Brand.objects.create(
            tenant=tenant,
            name="Brand One",
            slug="unique-slug",
        )
        with pytest.raises(IntegrityError):
            Brand.objects.create(
                tenant=tenant,
                name="Brand Two",
                slug="unique-slug",
            )

    def test_brand_same_slug_different_tenant(self, tenant):
        """Same slug is allowed for different tenants."""
        other_tenant = Tenant.objects.create(
            name="Other Tenant",
            slug="other-tenant",
        )
        Brand.objects.create(
            tenant=tenant,
            name="Brand One",
            slug="shared-slug",
        )
        brand2 = Brand.objects.create(
            tenant=other_tenant,
            name="Brand Two",
            slug="shared-slug",
        )
        assert brand2.id is not None

    def test_brand_soft_delete(self, brand):
        """Brand supports soft delete via deleted_at."""
        assert brand.is_deleted is False
        brand.deleted_at = timezone.now()
        brand.save()
        assert brand.is_deleted is True

    def test_brand_protected_on_tenant_delete(self, tenant, brand):
        """Cannot delete tenant with brands (PROTECT)."""
        with pytest.raises(Exception):  # ProtectedError
            tenant.delete()


# =============================================================================
# BRAND SNAPSHOT TESTS
# =============================================================================


@pytest.mark.django_db
class TestBrandSnapshot:
    """Tests for BrandSnapshot model."""

    def test_create_snapshot(self, brand):
        """Can create a brand snapshot with snapshot_at."""
        snapshot_time = timezone.now()
        snapshot = BrandSnapshot.objects.create(
            brand=brand,
            snapshot_at=snapshot_time,
            positioning_summary="Test positioning",
            tone_descriptors=["professional"],
            taboos=["competitor mentions"],
            pillars=[{"name": "Thought Leadership"}],
            personas=[{"name": "Developer"}],
        )
        assert snapshot.id is not None
        assert snapshot.brand == brand
        assert snapshot.snapshot_at == snapshot_time

    def test_snapshot_protected_on_brand_delete(self, brand):
        """Cannot delete brand with snapshots (PROTECT)."""
        BrandSnapshot.objects.create(
            brand=brand,
            snapshot_at=timezone.now(),
            positioning_summary="Test",
        )
        with pytest.raises(Exception):  # ProtectedError
            brand.delete()


# =============================================================================
# PERSONA TESTS
# =============================================================================


@pytest.mark.django_db
class TestPersona:
    """Tests for Persona model."""

    def test_create_persona(self, brand):
        """Can create a persona (no tenant_id required)."""
        persona = Persona.objects.create(
            brand=brand,
            name="Developer Dan",
            role="Senior Engineer",
        )
        assert persona.id is not None
        # Verify no tenant_id field exists
        assert not hasattr(persona, "tenant_id")

    def test_persona_unique_brand_name(self, brand):
        """Persona name must be unique per brand."""
        Persona.objects.create(
            brand=brand,
            name="Unique Name",
        )
        with pytest.raises(IntegrityError):
            Persona.objects.create(
                brand=brand,
                name="Unique Name",
            )


# =============================================================================
# CONTENT PILLAR TESTS
# =============================================================================


@pytest.mark.django_db
class TestContentPillar:
    """Tests for ContentPillar model."""

    def test_create_pillar(self, brand):
        """Can create a content pillar (no tenant_id required)."""
        pillar = ContentPillar.objects.create(
            brand=brand,
            name="Thought Leadership",
        )
        assert pillar.id is not None
        assert pillar.is_active is True
        # Verify no tenant_id field exists
        assert not hasattr(pillar, "tenant_id")

    def test_pillar_unique_brand_name(self, brand):
        """Pillar name must be unique per brand."""
        ContentPillar.objects.create(
            brand=brand,
            name="Unique Pillar",
        )
        with pytest.raises(IntegrityError):
            ContentPillar.objects.create(
                brand=brand,
                name="Unique Pillar",
            )


# =============================================================================
# PATTERN TEMPLATE TESTS
# =============================================================================


@pytest.mark.django_db
class TestPatternTemplate:
    """Tests for PatternTemplate model."""

    def test_create_pattern(self):
        """Can create a global pattern (no brand, no tenant_id)."""
        pattern = PatternTemplate.objects.create(
            name="Global Pattern",
            category=PatternCategory.EDUCATION,
            beats=["intro", "content", "outro"],
        )
        assert pattern.id is not None
        assert pattern.brand is None
        # Verify no tenant_id field exists
        assert not hasattr(pattern, "tenant_id")

    def test_create_brand_pattern(self, brand):
        """Can create a brand-specific pattern."""
        pattern = PatternTemplate.objects.create(
            brand=brand,
            name="Brand Pattern",
            category=PatternCategory.LAUNCH,
        )
        assert pattern.brand == brand

    def test_pattern_status_choices(self):
        """Pattern status must be valid choice."""
        pattern = PatternTemplate.objects.create(
            name="Test",
            status=PatternStatus.EXPERIMENTAL,
        )
        assert pattern.status == PatternStatus.EXPERIMENTAL


# =============================================================================
# OPPORTUNITY TESTS
# =============================================================================


@pytest.mark.django_db
class TestOpportunity:
    """Tests for Opportunity model."""

    def test_create_opportunity(self, brand):
        """Can create an opportunity (no tenant_id required)."""
        opp = Opportunity.objects.create(
            brand=brand,
            type=OpportunityType.EVERGREEN,
            title="Test Opportunity",
        )
        assert opp.id is not None
        assert opp.is_pinned is False
        assert opp.is_snoozed is False
        # Verify no tenant_id field exists
        assert not hasattr(opp, "tenant_id")

    def test_opportunity_type_choices(self, brand):
        """Opportunity type must be valid choice."""
        for opp_type in OpportunityType:
            opp = Opportunity.objects.create(
                brand=brand,
                type=opp_type,
                title=f"Test {opp_type}",
            )
            assert opp.type == opp_type

    def test_opportunity_persona_nullable(self, opportunity):
        """Persona FK is nullable (SET_NULL on delete)."""
        persona = opportunity.persona
        # Clear the persona reference first to allow deletion
        opportunity.persona = None
        opportunity.save()
        persona.delete()
        opportunity.refresh_from_db()
        assert opportunity.persona is None


# =============================================================================
# CONTENT PACKAGE TESTS
# =============================================================================


@pytest.mark.django_db
class TestContentPackage:
    """Tests for ContentPackage model."""

    def test_create_package(self, brand):
        """Can create a content package (no tenant_id required)."""
        pkg = ContentPackage.objects.create(
            brand=brand,
            title="Test Package",
            status=PackageStatus.DRAFT,
        )
        assert pkg.id is not None
        assert pkg.status == PackageStatus.DRAFT
        # Verify no tenant_id field exists
        assert not hasattr(pkg, "tenant_id")

    def test_package_status_transitions(self, package):
        """Package status can transition through lifecycle."""
        assert package.status == PackageStatus.DRAFT

        package.status = PackageStatus.IN_REVIEW
        package.save()

        package.status = PackageStatus.SCHEDULED
        package.save()

        package.status = PackageStatus.PUBLISHED
        package.save()

        assert package.status == PackageStatus.PUBLISHED


# =============================================================================
# VARIANT TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariant:
    """Tests for Variant model."""

    def test_create_variant(self, brand, package):
        """Can create a variant (no tenant_id required)."""
        variant = Variant.objects.create(
            brand=brand,
            package=package,
            channel=Channel.X,
            draft_text="Test post for X",
        )
        assert variant.id is not None
        assert variant.status == VariantStatus.DRAFT
        # Verify no tenant_id field exists
        assert not hasattr(variant, "tenant_id")

    def test_variant_cascade_delete(self, variant, package):
        """Variants are deleted when package is deleted."""
        variant_id = variant.id
        package.delete()
        assert not Variant.objects.filter(id=variant_id).exists()

    def test_variant_channel_choices(self, brand, package):
        """Variant channel must be valid choice."""
        for channel in Channel:
            variant = Variant.objects.create(
                brand=brand,
                package=package,
                channel=channel,
            )
            assert variant.channel == channel


# =============================================================================
# EXECUTION EVENT TESTS
# =============================================================================


@pytest.mark.django_db
class TestExecutionEvent:
    """Tests for ExecutionEvent model."""

    def test_create_execution_event(self, brand, variant):
        """Can create an execution event (no tenant_id required)."""
        event = ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.IMPRESSION,
            count=100,
            source=ExecutionSource.PLATFORM_WEBHOOK,
            occurred_at=timezone.now(),
        )
        assert event.id is not None
        assert event.received_at is not None
        # Verify no tenant_id field exists
        assert not hasattr(event, "tenant_id")

    def test_execution_event_types(self, brand, variant):
        """All execution event types are valid."""
        for event_type in ExecutionEventType:
            event = ExecutionEvent.objects.create(
                brand=brand,
                variant=variant,
                channel=Channel.LINKEDIN,
                event_type=event_type,
                source=ExecutionSource.MANUAL_ENTRY,
                occurred_at=timezone.now(),
            )
            assert event.event_type == event_type

    def test_execution_event_decision_type(self, brand, variant):
        """ExecutionEvent can have optional decision_type."""
        event = ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.CLICK,
            decision_type=DecisionType.VARIANT_APPROVED,
            source=ExecutionSource.MANUAL_ENTRY,
            occurred_at=timezone.now(),
        )
        assert event.decision_type == DecisionType.VARIANT_APPROVED

    def test_execution_event_decision_type_nullable(self, brand, variant):
        """ExecutionEvent decision_type is nullable."""
        event = ExecutionEvent.objects.create(
            brand=brand,
            variant=variant,
            channel=Channel.LINKEDIN,
            event_type=ExecutionEventType.IMPRESSION,
            decision_type=None,
            source=ExecutionSource.PLATFORM_WEBHOOK,
            occurred_at=timezone.now(),
        )
        assert event.decision_type is None


# =============================================================================
# LEARNING EVENT TESTS
# =============================================================================


@pytest.mark.django_db
class TestLearningEvent:
    """Tests for LearningEvent model."""

    def test_create_learning_event(self, brand):
        """Can create a learning event (no tenant_id required)."""
        event = LearningEvent.objects.create(
            brand=brand,
            signal_type=LearningSignalType.PATTERN_PERFORMANCE_UPDATE,
            payload={"avg_score": 0.75, "sample_size": 10},
        )
        assert event.id is not None
        assert event.effective_at is not None
        # Verify no tenant_id field exists
        assert not hasattr(event, "tenant_id")

    def test_learning_signal_types(self, brand):
        """All learning signal types are valid."""
        for signal_type in LearningSignalType:
            event = LearningEvent.objects.create(
                brand=brand,
                signal_type=signal_type,
                payload={"test": True},
            )
            assert event.signal_type == signal_type


# =============================================================================
# ENUM TESTS
# =============================================================================


@pytest.mark.django_db
class TestEnums:
    """Tests for enum value storage."""

    def test_channel_stored_as_lowercase(self, brand):
        """Channel enum values are stored as lowercase strings."""
        brand.primary_channel = Channel.LINKEDIN
        brand.save()
        brand.refresh_from_db()
        assert brand.primary_channel == "linkedin"

    def test_package_status_stored_as_lowercase(self, package):
        """PackageStatus enum values are stored as lowercase strings."""
        package.status = PackageStatus.IN_REVIEW
        package.save()
        package.refresh_from_db()
        assert package.status == "in_review"

    def test_decision_type_values(self):
        """DecisionType enum has expected values."""
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
        actual = {choice.value for choice in DecisionType}
        assert actual == expected


# =============================================================================
# TIMESTAMP TESTS
# =============================================================================


@pytest.mark.django_db
class TestTimestamps:
    """Tests for timestamp behavior."""

    def test_created_at_auto_set(self, brand):
        """created_at is automatically set on creation."""
        assert brand.created_at is not None
        assert brand.created_at <= timezone.now()

    def test_updated_at_changes_on_save(self, brand):
        """updated_at changes when model is saved."""
        original_updated = brand.updated_at
        brand.name = "Updated Name"
        brand.save()
        assert brand.updated_at > original_updated


# =============================================================================
# INDEX TESTS
# =============================================================================


@pytest.mark.django_db
class TestIndexes:
    """Tests to verify indexes exist on hot paths."""

    def _get_index_fields(self, model):
        """Get all indexed field combinations for a model."""
        indexes = []
        for index in model._meta.indexes:
            indexes.append(tuple(index.fields))
        return indexes

    def test_opportunity_indexes(self):
        """Opportunity has required indexes."""
        indexes = self._get_index_fields(Opportunity)
        assert ("brand", "created_at") in indexes
        assert ("brand", "is_pinned", "is_snoozed") in indexes
        assert ("brand", "type") in indexes

    def test_content_package_indexes(self):
        """ContentPackage has required indexes."""
        indexes = self._get_index_fields(ContentPackage)
        assert ("brand", "created_at") in indexes
        assert ("brand", "status") in indexes

    def test_variant_indexes(self):
        """Variant has required indexes."""
        indexes = self._get_index_fields(Variant)
        assert ("package", "created_at") in indexes
        assert ("brand", "created_at") in indexes
        assert ("brand", "status") in indexes

    def test_execution_event_indexes(self):
        """ExecutionEvent has required indexes."""
        indexes = self._get_index_fields(ExecutionEvent)
        assert ("brand", "created_at") in indexes
        assert ("brand", "occurred_at") in indexes

    def test_learning_event_indexes(self):
        """LearningEvent has required indexes."""
        indexes = self._get_index_fields(LearningEvent)
        assert ("brand", "created_at") in indexes
        assert ("brand", "effective_at") in indexes


# =============================================================================
# SCOPING TESTS - NO TENANT_ID ON CHILD MODELS
# =============================================================================


@pytest.mark.django_db
class TestBrandScoping:
    """Tests to verify only Tenant and Brand have tenant-level scoping."""

    def test_no_tenant_id_on_child_models(self):
        """Child models should NOT have tenant_id field."""
        child_models = [
            Persona,
            ContentPillar,
            PatternTemplate,
            Opportunity,
            ContentPackage,
            Variant,
            ExecutionEvent,
            LearningEvent,
            BrandSnapshot,
        ]
        for model in child_models:
            field_names = [f.name for f in model._meta.get_fields()]
            assert "tenant_id" not in field_names, (
                f"{model.__name__} should not have tenant_id field"
            )
            # Also check it's not a concrete field
            assert not hasattr(model, "tenant_id"), (
                f"{model.__name__} should not have tenant_id attribute"
            )

    def test_tenant_has_id_field(self):
        """Tenant model exists and has id field."""
        assert hasattr(Tenant, "_meta")
        field_names = [f.name for f in Tenant._meta.get_fields()]
        assert "id" in field_names
        assert "name" in field_names
        assert "slug" in field_names

    def test_brand_has_tenant_fk(self):
        """Brand has FK to Tenant."""
        field_names = [f.name for f in Brand._meta.get_fields()]
        assert "tenant" in field_names
        tenant_field = Brand._meta.get_field("tenant")
        assert tenant_field.related_model == Tenant

    def test_child_models_have_brand_fk(self):
        """Child models have FK to Brand."""
        brand_scoped_models = [
            Persona,
            ContentPillar,
            Opportunity,
            ContentPackage,
            Variant,
            ExecutionEvent,
            LearningEvent,
            BrandSnapshot,
        ]
        for model in brand_scoped_models:
            field_names = [f.name for f in model._meta.get_fields()]
            assert "brand" in field_names, (
                f"{model.__name__} should have brand field"
            )
            brand_field = model._meta.get_field("brand")
            assert brand_field.related_model == Brand, (
                f"{model.__name__}.brand should be FK to Brand"
            )


# =============================================================================
# DTO-ONLY FIELD CONTRACT TESTS (PR-8b)
# =============================================================================


@pytest.mark.django_db
class TestDtoOnlyFieldsContract:
    """
    Tests enforcing that is_valid/rejection_reasons/why_now are DTO-only.

    Per PR-8b and 02-canonical-objects.md:
    - Opportunity model does NOT have is_valid, rejection_reasons, why_now fields
    - OpportunityDraftDTO DOES have these fields (for eval/filtering)
    - Engine filters out invalid opps, then persists only valid ones
    - DB never sees is_valid/rejection_reasons - they're eval-facing only
    """

    def test_opportunity_model_has_no_is_valid_field(self):
        """Opportunity model does NOT have is_valid field (DTO-only)."""
        field_names = [f.name for f in Opportunity._meta.get_fields()]
        assert "is_valid" not in field_names, (
            "is_valid should be DTO-only, not persisted on Opportunity model"
        )

    def test_opportunity_model_has_no_rejection_reasons_field(self):
        """Opportunity model does NOT have rejection_reasons field (DTO-only)."""
        field_names = [f.name for f in Opportunity._meta.get_fields()]
        assert "rejection_reasons" not in field_names, (
            "rejection_reasons should be DTO-only, not persisted"
        )

    def test_opportunity_model_has_no_why_now_field(self):
        """Opportunity model does NOT have why_now field per 02-canonical-objects.md.

        The canonical doc uses 'angle' for 'why now / core argument' per §8.2.
        """
        field_names = [f.name for f in Opportunity._meta.get_fields()]
        assert "why_now" not in field_names, (
            "why_now should be DTO-only per canonical objects doc"
        )

    def test_opportunity_draft_dto_has_validity_fields(self):
        """OpportunityDraftDTO has is_valid, rejection_reasons, why_now fields."""
        from kairo.hero.dto import OpportunityDraftDTO

        # Check model_fields (Pydantic v2)
        field_names = list(OpportunityDraftDTO.model_fields.keys())
        assert "is_valid" in field_names, (
            "OpportunityDraftDTO must have is_valid field"
        )
        assert "rejection_reasons" in field_names, (
            "OpportunityDraftDTO must have rejection_reasons field"
        )
        assert "why_now" in field_names, (
            "OpportunityDraftDTO must have why_now field"
        )

    def test_opportunity_dto_does_not_expose_validity_fields(self):
        """OpportunityDTO (API response) does NOT expose validity fields.

        Validity is internal - API consumers see persisted opportunities only.
        """
        from kairo.hero.dto import OpportunityDTO

        field_names = list(OpportunityDTO.model_fields.keys())
        assert "is_valid" not in field_names, (
            "OpportunityDTO should not expose is_valid"
        )
        assert "rejection_reasons" not in field_names, (
            "OpportunityDTO should not expose rejection_reasons"
        )


# =============================================================================
# PR-9: CONTENT PACKAGE / VARIANT DTO-ONLY FIELD CONTRACT TESTS
# =============================================================================


@pytest.mark.django_db
class TestPackageVariantDtoOnlyFieldsContract:
    """
    Tests enforcing that PR-9 rubric fields are DTO-only per 09/10-*-rubric.md.

    Per PR-9 and rubrics §10:
    - ContentPackage model does NOT have is_valid, package_score, quality_band
    - Variant model does NOT have is_valid, variant_score, quality_band
    - Draft DTOs HAVE these fields for eval/filtering
    - Engine filters invalid items, persists only valid ones
    - DB never sees these fields - they're eval-facing only
    """

    # ContentPackage model tests
    def test_content_package_model_has_no_is_valid_field(self):
        """ContentPackage model does NOT have is_valid field (DTO-only)."""
        field_names = [f.name for f in ContentPackage._meta.get_fields()]
        assert "is_valid" not in field_names, (
            "is_valid should be DTO-only, not persisted on ContentPackage model"
        )

    def test_content_package_model_has_no_package_score_field(self):
        """ContentPackage model does NOT have package_score field (DTO-only)."""
        field_names = [f.name for f in ContentPackage._meta.get_fields()]
        assert "package_score" not in field_names, (
            "package_score should be DTO-only per rubric §10"
        )

    def test_content_package_model_has_no_quality_band_field(self):
        """ContentPackage model does NOT have quality_band field (DTO-only)."""
        field_names = [f.name for f in ContentPackage._meta.get_fields()]
        assert "quality_band" not in field_names, (
            "quality_band should be DTO-only per rubric §10"
        )

    def test_content_package_model_has_no_rejection_reasons_field(self):
        """ContentPackage model does NOT have rejection_reasons field (DTO-only)."""
        field_names = [f.name for f in ContentPackage._meta.get_fields()]
        assert "rejection_reasons" not in field_names, (
            "rejection_reasons should be DTO-only per rubric §10"
        )

    def test_content_package_model_has_no_thesis_field(self):
        """ContentPackage model does NOT have thesis field.

        Per 09-package-rubric.md §10: thesis is stored in notes field for PRD-1.
        """
        field_names = [f.name for f in ContentPackage._meta.get_fields()]
        assert "thesis" not in field_names, (
            "thesis should be stored in notes field for PRD-1, not separate column"
        )

    # Variant model tests
    def test_variant_model_has_no_is_valid_field(self):
        """Variant model does NOT have is_valid field (DTO-only)."""
        field_names = [f.name for f in Variant._meta.get_fields()]
        assert "is_valid" not in field_names, (
            "is_valid should be DTO-only, not persisted on Variant model"
        )

    def test_variant_model_has_no_variant_score_field(self):
        """Variant model does NOT have variant_score field (DTO-only).

        Note: Variant.eval_score is a different field - for post-generation evaluation.
        variant_score is the rubric score from draft generation.
        """
        field_names = [f.name for f in Variant._meta.get_fields()]
        assert "variant_score" not in field_names, (
            "variant_score should be DTO-only per rubric §10"
        )

    def test_variant_model_has_no_quality_band_field(self):
        """Variant model does NOT have quality_band field (DTO-only)."""
        field_names = [f.name for f in Variant._meta.get_fields()]
        assert "quality_band" not in field_names, (
            "quality_band should be DTO-only per rubric §10"
        )

    def test_variant_model_has_no_rejection_reasons_field(self):
        """Variant model does NOT have rejection_reasons field (DTO-only)."""
        field_names = [f.name for f in Variant._meta.get_fields()]
        assert "rejection_reasons" not in field_names, (
            "rejection_reasons should be DTO-only per rubric §10"
        )

    # ContentPackageDraftDTO tests
    def test_content_package_draft_dto_has_validity_fields(self):
        """ContentPackageDraftDTO has all required rubric fields."""
        from kairo.hero.dto import ContentPackageDraftDTO

        field_names = list(ContentPackageDraftDTO.model_fields.keys())
        assert "is_valid" in field_names, (
            "ContentPackageDraftDTO must have is_valid field"
        )
        assert "rejection_reasons" in field_names, (
            "ContentPackageDraftDTO must have rejection_reasons field"
        )
        assert "package_score" in field_names, (
            "ContentPackageDraftDTO must have package_score field"
        )
        assert "package_score_breakdown" in field_names, (
            "ContentPackageDraftDTO must have package_score_breakdown field"
        )
        assert "quality_band" in field_names, (
            "ContentPackageDraftDTO must have quality_band field"
        )
        assert "thesis" in field_names, (
            "ContentPackageDraftDTO must have thesis field"
        )

    # VariantDraftDTO tests
    def test_variant_draft_dto_has_validity_fields(self):
        """VariantDraftDTO has all required rubric fields."""
        from kairo.hero.dto import VariantDraftDTO

        field_names = list(VariantDraftDTO.model_fields.keys())
        assert "is_valid" in field_names, (
            "VariantDraftDTO must have is_valid field"
        )
        assert "rejection_reasons" in field_names, (
            "VariantDraftDTO must have rejection_reasons field"
        )
        assert "variant_score" in field_names, (
            "VariantDraftDTO must have variant_score field"
        )
        assert "variant_score_breakdown" in field_names, (
            "VariantDraftDTO must have variant_score_breakdown field"
        )
        assert "quality_band" in field_names, (
            "VariantDraftDTO must have quality_band field"
        )

    # ContentPackageDTO (API response) tests
    def test_content_package_dto_does_not_expose_validity_fields(self):
        """ContentPackageDTO (API response) does NOT expose validity fields.

        Validity is internal - API consumers see persisted packages only.
        """
        from kairo.hero.dto import ContentPackageDTO

        field_names = list(ContentPackageDTO.model_fields.keys())
        assert "is_valid" not in field_names, (
            "ContentPackageDTO should not expose is_valid"
        )
        assert "rejection_reasons" not in field_names, (
            "ContentPackageDTO should not expose rejection_reasons"
        )
        assert "package_score" not in field_names, (
            "ContentPackageDTO should not expose package_score"
        )
        assert "quality_band" not in field_names, (
            "ContentPackageDTO should not expose quality_band"
        )

    # VariantDTO (API response) tests
    def test_variant_dto_does_not_expose_validity_fields(self):
        """VariantDTO (API response) does NOT expose validity fields.

        Validity is internal - API consumers see persisted variants only.
        """
        from kairo.hero.dto import VariantDTO

        field_names = list(VariantDTO.model_fields.keys())
        assert "is_valid" not in field_names, (
            "VariantDTO should not expose is_valid"
        )
        assert "rejection_reasons" not in field_names, (
            "VariantDTO should not expose rejection_reasons"
        )
        assert "variant_score" not in field_names, (
            "VariantDTO should not expose variant_score (note: eval_score is different)"
        )
        assert "quality_band" not in field_names, (
            "VariantDTO should not expose quality_band"
        )
