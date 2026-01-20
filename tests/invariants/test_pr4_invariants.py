"""
PR-4 Invariant Tests.

Per opportunities_v1_prd.md and PR-4 requirements:
- SourceActivation fixture-only mode end-to-end
- ActivationRun and EvidenceItem creation
- Deterministic evidence IDs across runs
- evidence_ids propagation to opportunities

Test Categories:
1. Fixture loading and EvidenceBundle creation
2. Deterministic UUID generation
3. ActivationRun persistence
4. EvidenceItem persistence
5. Evidence to signals conversion
6. evidence_ids propagation to opportunities
7. No Apify calls (guardrails)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

import pytest

from kairo.core.models import Brand
from kairo.hero.models import ActivationRun, EvidenceItem, OpportunitiesJob


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="PR4 Test Tenant",
        slug="pr4-test-tenant",
    )


@pytest.fixture
def brand(tenant) -> Brand:
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="PR4 Test Brand",
        slug="pr4-test-brand",
        positioning="Test positioning for PR-4",
    )


@pytest.fixture
def job(brand: Brand) -> OpportunitiesJob:
    """Create a test job."""
    return OpportunitiesJob.objects.create(
        brand=brand,
        status="running",
    )


# =============================================================================
# Test 1 - Deterministic UUID Generation
# =============================================================================


class TestDeterministicUUIDs:
    """Test that evidence IDs are deterministic and stable."""

    def test_same_inputs_produce_same_id(self, brand: Brand):
        """Same brand + platform + URL = same evidence ID."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        url = "https://instagram.com/p/test123"

        id1 = generate_evidence_id(brand.id, "instagram", url)
        id2 = generate_evidence_id(brand.id, "instagram", url)

        assert id1 == id2
        assert isinstance(id1, UUID)

    def test_different_urls_produce_different_ids(self, brand: Brand):
        """Different URLs = different evidence IDs."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        id1 = generate_evidence_id(brand.id, "instagram", "https://instagram.com/p/test1")
        id2 = generate_evidence_id(brand.id, "instagram", "https://instagram.com/p/test2")

        assert id1 != id2

    def test_different_platforms_produce_different_ids(self, brand: Brand):
        """Different platforms = different evidence IDs."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        url = "https://example.com/content"
        id1 = generate_evidence_id(brand.id, "instagram", url)
        id2 = generate_evidence_id(brand.id, "tiktok", url)

        assert id1 != id2

    def test_different_brands_produce_different_ids(self, tenant):
        """Different brands = different evidence IDs."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        brand1 = Brand.objects.create(tenant=tenant, name="Brand1", slug="brand1")
        brand2 = Brand.objects.create(tenant=tenant, name="Brand2", slug="brand2")
        url = "https://instagram.com/p/test123"

        id1 = generate_evidence_id(brand1.id, "instagram", url)
        id2 = generate_evidence_id(brand2.id, "instagram", url)

        assert id1 != id2


# =============================================================================
# Test 2 - SeedPack Derivation
# =============================================================================


@pytest.mark.django_db
class TestSeedPackDerivation:
    """Test SeedPack derivation from brand context."""

    def test_derive_seed_pack_from_brand(self, brand: Brand):
        """SeedPack is derived correctly from brand."""
        from kairo.sourceactivation.services import derive_seed_pack

        seed_pack = derive_seed_pack(brand.id)

        assert seed_pack.brand_id == brand.id
        assert seed_pack.brand_name == brand.name
        assert seed_pack.positioning == brand.positioning
        assert brand.name in seed_pack.search_terms

    def test_seed_pack_includes_pillars(self, brand: Brand):
        """SeedPack includes pillar keywords."""
        from kairo.core.models import ContentPillar
        from kairo.sourceactivation.services import derive_seed_pack

        pillar = ContentPillar.objects.create(
            brand=brand,
            name="Test Pillar",
            description="Pillar description",
            is_active=True,
        )

        seed_pack = derive_seed_pack(brand.id)

        assert pillar.name in seed_pack.pillar_keywords

    def test_seed_pack_includes_personas(self, brand: Brand):
        """SeedPack includes persona contexts."""
        from kairo.core.models import Persona
        from kairo.sourceactivation.services import derive_seed_pack

        persona = Persona.objects.create(
            brand=brand,
            name="Test Persona",
            summary="A test persona for content",
        )

        seed_pack = derive_seed_pack(brand.id)

        assert any("Test Persona" in ctx for ctx in seed_pack.persona_contexts)


# =============================================================================
# Test 3 - Fixture Loading
# =============================================================================


@pytest.mark.django_db
class TestFixtureLoading:
    """Test fixture loading behavior."""

    def test_load_default_fixtures(self, brand: Brand):
        """Default fixtures are loaded when no brand-specific fixture exists."""
        from kairo.sourceactivation.fixtures.loader import load_fixtures_for_brand
        from kairo.sourceactivation.services import derive_seed_pack

        seed_pack = derive_seed_pack(brand.id)
        items = load_fixtures_for_brand(brand.id, seed_pack)

        # Default fixtures should have items
        assert len(items) > 0
        # Items should have required fields
        for item in items:
            assert item.platform
            assert item.canonical_url
            assert item.actor_id == "FIXTURE"  # Fixture mode marker

    def test_fixture_items_have_correct_structure(self, brand: Brand):
        """Fixture items have all expected fields."""
        from kairo.sourceactivation.fixtures.loader import load_fixtures_for_brand
        from kairo.sourceactivation.services import derive_seed_pack

        seed_pack = derive_seed_pack(brand.id)
        items = load_fixtures_for_brand(brand.id, seed_pack)

        assert len(items) > 0
        item = items[0]

        # Check structure
        assert hasattr(item, "platform")
        assert hasattr(item, "canonical_url")
        assert hasattr(item, "text_primary")
        assert hasattr(item, "has_transcript")
        assert hasattr(item, "view_count")


# =============================================================================
# Test 4 - EvidenceBundle Creation
# =============================================================================


@pytest.mark.django_db
class TestEvidenceBundleCreation:
    """Test EvidenceBundle creation via get_or_create_evidence_bundle."""

    def test_creates_activation_run(self, brand: Brand, job: OpportunitiesJob):
        """get_or_create_evidence_bundle creates an ActivationRun."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # ActivationRun should be created
        assert bundle.activation_run_id is not None
        run = ActivationRun.objects.get(id=bundle.activation_run_id)
        assert run.brand_id == brand.id
        assert run.job_id == job.id

    def test_creates_evidence_items(self, brand: Brand, job: OpportunitiesJob):
        """get_or_create_evidence_bundle creates EvidenceItems."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # EvidenceItems should be created
        items = EvidenceItem.objects.filter(
            brand_id=brand.id,
            activation_run_id=bundle.activation_run_id,
        )
        assert items.count() == len(bundle.items)

    def test_bundle_mode_is_fixture_only(self, brand: Brand, job: OpportunitiesJob):
        """Bundle mode is fixture_only in PR-4."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        assert bundle.mode == "fixture_only"
        assert "FIXTURE" in bundle.recipes_executed

    def test_live_mode_requires_apify_enabled(self, brand: Brand, job: OpportunitiesJob):
        """live_cap_limited mode requires APIFY_ENABLED=true.

        PR-6: live mode is now supported but guarded by APIFY_ENABLED.
        When APIFY_ENABLED=false (default), ApifyDisabledError is raised.
        """
        from kairo.core.guardrails import ApifyDisabledError
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)

        # APIFY_ENABLED defaults to False in tests, so this should raise
        with pytest.raises(ApifyDisabledError):
            get_or_create_evidence_bundle(
                brand_id=brand.id,
                seed_pack=seed_pack,
                job_id=job.id,
                mode="live_cap_limited",
            )


# =============================================================================
# Test 5 - Determinism Across Runs
# =============================================================================


@pytest.mark.django_db
class TestDeterminismAcrossRuns:
    """Test that repeated runs produce stable IDs."""

    def test_repeated_runs_produce_same_evidence_ids(self, brand: Brand):
        """Running twice with same fixtures produces same EvidenceItem IDs."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)

        # First run
        job1 = OpportunitiesJob.objects.create(brand=brand, status="running")
        bundle1 = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job1.id,
            mode="fixture_only",
        )
        ids1 = set(
            EvidenceItem.objects.filter(activation_run_id=bundle1.activation_run_id)
            .values_list("id", flat=True)
        )

        # Second run
        job2 = OpportunitiesJob.objects.create(brand=brand, status="running")
        bundle2 = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job2.id,
            mode="fixture_only",
        )
        ids2 = set(
            EvidenceItem.objects.filter(activation_run_id=bundle2.activation_run_id)
            .values_list("id", flat=True)
        )

        # IDs should be the same
        assert ids1 == ids2

    def test_idempotent_evidence_item_creation(self, brand: Brand, job: OpportunitiesJob):
        """Multiple calls don't create duplicate EvidenceItems."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)

        # First call
        bundle1 = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # Create new job for second call
        job2 = OpportunitiesJob.objects.create(brand=brand, status="running")
        bundle2 = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job2.id,
            mode="fixture_only",
        )

        # Total items should be same as single bundle (idempotent by ID)
        # Note: Each bundle creates new items linked to its activation_run,
        # but items with same ID get updated (update_or_create)
        total_items = EvidenceItem.objects.filter(brand_id=brand.id).count()
        # Should be same as bundle size since IDs are deterministic
        assert total_items == len(bundle2.items)


# =============================================================================
# Test 6 - Evidence to Signals Conversion
# =============================================================================


@pytest.mark.django_db
class TestEvidenceToSignalsConversion:
    """Test conversion of EvidenceBundle to ExternalSignalBundleDTO."""

    def test_converts_to_signal_bundle(self, brand: Brand, job: OpportunitiesJob):
        """EvidenceBundle converts to ExternalSignalBundleDTO."""
        from kairo.sourceactivation.adapters import convert_evidence_bundle_to_signals
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        signals = convert_evidence_bundle_to_signals(bundle)

        # Should produce signals
        assert signals.brand_id == brand.id
        total_signals = (
            len(signals.trends) +
            len(signals.web_mentions) +
            len(signals.social_moments)
        )
        assert total_signals > 0

    def test_transcript_items_become_web_mentions(self, brand: Brand, job: OpportunitiesJob):
        """Items with transcripts are converted to WebMentionSignalDTO."""
        from kairo.sourceactivation.adapters import convert_evidence_bundle_to_signals
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        signals = convert_evidence_bundle_to_signals(bundle)

        # Count transcript items in bundle
        transcript_count = sum(1 for item in bundle.items if item.has_transcript)

        # Web mentions should include transcript items
        if transcript_count > 0:
            assert len(signals.web_mentions) > 0


# =============================================================================
# Test 7 - Evidence Selection for Opportunities
# =============================================================================


@pytest.mark.django_db
class TestEvidenceSelectionForOpportunities:
    """Test evidence selection logic for opportunities."""

    def test_selects_top_k_evidence(self, brand: Brand, job: OpportunitiesJob):
        """Selects top K evidence items based on scoring."""
        from kairo.sourceactivation.adapters import select_evidence_for_opportunity
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        selected = select_evidence_for_opportunity(bundle, max_items=3)

        assert len(selected) <= 3
        assert len(selected) <= len(bundle.items)

    def test_selection_is_deterministic(self, brand: Brand, job: OpportunitiesJob):
        """Same bundle produces same selection."""
        from kairo.sourceactivation.adapters import select_evidence_for_opportunity
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        selection1 = select_evidence_for_opportunity(bundle, max_items=3)
        selection2 = select_evidence_for_opportunity(bundle, max_items=3)

        assert selection1 == selection2

    def test_prefers_transcript_items(self, brand: Brand, job: OpportunitiesJob):
        """Selection prefers items with transcripts."""
        from kairo.sourceactivation.adapters import select_evidence_for_opportunity
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        selected = select_evidence_for_opportunity(bundle, max_items=3)

        # Get the selected items
        transcript_items = [
            item for item in bundle.items
            if item.has_transcript
        ]

        # If there are transcript items, at least one should be selected
        if transcript_items and len(selected) > 0:
            # Check that transcript items are in the selection
            # (they should score higher)
            from kairo.sourceactivation.fixtures.loader import generate_evidence_id

            transcript_ids = {
                generate_evidence_id(brand.id, item.platform, item.canonical_url)
                for item in transcript_items
            }
            selected_set = set(selected)

            # At least one transcript item should be selected if any exist
            assert bool(transcript_ids & selected_set) or len(transcript_items) == 0


# =============================================================================
# Test 8 - No Apify Calls (Guardrails)
# =============================================================================


@pytest.mark.django_db
class TestNoApifyCalls:
    """Test that PR-4 fixture-only mode makes no Apify calls."""

    def test_fixture_mode_default(self):
        """Default SourceActivation mode is fixture_only."""
        from kairo.core.guardrails import get_sourceactivation_mode

        mode = get_sourceactivation_mode()
        assert mode == "fixture_only"

    def test_no_apify_client_in_fixture_mode(self, brand: Brand, job: OpportunitiesJob):
        """Fixture mode doesn't instantiate Apify client."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)

        # This should not raise any Apify-related errors
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # Should complete successfully without Apify
        assert bundle is not None
        assert bundle.mode == "fixture_only"


# =============================================================================
# Test 9 - ActivationRun Tracking
# =============================================================================


@pytest.mark.django_db
class TestActivationRunTracking:
    """Test ActivationRun record tracking."""

    def test_activation_run_has_correct_fields(self, brand: Brand, job: OpportunitiesJob):
        """ActivationRun has all expected fields populated."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        run = ActivationRun.objects.get(id=bundle.activation_run_id)

        assert run.brand_id == brand.id
        assert run.job_id == job.id
        assert "FIXTURE" in run.recipes_executed
        assert run.item_count == len(bundle.items)
        assert run.estimated_cost_usd == 0  # Fixtures have no cost

    def test_activation_run_tracks_timing(self, brand: Brand, job: OpportunitiesJob):
        """ActivationRun tracks start and end times."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        run = ActivationRun.objects.get(id=bundle.activation_run_id)

        assert run.started_at is not None
        assert run.ended_at is not None
        assert run.ended_at >= run.started_at

    def test_activation_run_tracks_transcript_count(self, brand: Brand, job: OpportunitiesJob):
        """ActivationRun tracks items_with_transcript."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        run = ActivationRun.objects.get(id=bundle.activation_run_id)

        # Count transcript items
        transcript_count = sum(1 for item in bundle.items if item.has_transcript)
        assert run.items_with_transcript == transcript_count


# =============================================================================
# Test 10 - EvidenceItem Persistence
# =============================================================================


@pytest.mark.django_db
class TestEvidenceItemPersistence:
    """Test EvidenceItem persistence behavior."""

    def test_evidence_item_has_correct_fields(self, brand: Brand, job: OpportunitiesJob):
        """EvidenceItem has all expected fields populated."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        items = EvidenceItem.objects.filter(activation_run_id=bundle.activation_run_id)
        assert items.count() > 0

        item = items.first()
        assert item.brand_id == brand.id
        assert item.platform in ["instagram", "tiktok", "linkedin", "youtube"]
        assert item.canonical_url
        assert item.actor_id == "FIXTURE"
        assert item.recipe_id == "FIXTURE"

    def test_evidence_item_has_deterministic_id(self, brand: Brand, job: OpportunitiesJob):
        """EvidenceItem IDs are deterministic."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        items = EvidenceItem.objects.filter(activation_run_id=bundle.activation_run_id)

        for item in items:
            expected_id = generate_evidence_id(
                brand_id=brand.id,
                platform=item.platform,
                canonical_url=item.canonical_url,
            )
            assert item.id == expected_id


# =============================================================================
# PR-4b INVARIANT TESTS
# =============================================================================
# These tests enforce strict PRD compliance per PR-4b patch requirements:
# 1. PRD §C.1: Signals come only from EvidenceBundle (no merge with legacy)
# 2. PRD §D.3.2: ActivationRun.job is required FK (not nullable)
# 3. PRD §F.1: evidence_ids min_length=1 for READY opportunities
# =============================================================================


@pytest.mark.django_db
class TestPR4bNoSignalMerge:
    """
    PR-4b §1: Signals come only from EvidenceBundle (no merge with legacy).

    Per PRD §C.1: BrandBrainSnapshot -> SeedPack -> EvidenceBundle -> signals.
    The graph receives ONLY signals from EvidenceBundle, not merged with legacy.
    """

    def test_convert_evidence_to_signals_returns_evidence_only(self, brand: Brand, job: OpportunitiesJob):
        """_convert_evidence_to_signals returns only evidence-derived signals."""
        from kairo.hero.engines.opportunities_engine import _convert_evidence_to_signals
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        signals = _convert_evidence_to_signals(brand.id, job.id, bundle)

        # Signals should exist and come from evidence
        total_signals = len(signals.trends) + len(signals.web_mentions) + len(signals.social_moments)
        assert total_signals > 0

        # All signal IDs should start with "evidence:" (from EvidenceBundle adapter)
        for trend in signals.trends:
            assert trend.id.startswith("evidence:")
        for mention in signals.web_mentions:
            assert mention.id.startswith("evidence:")
        for moment in signals.social_moments:
            assert moment.id.startswith("evidence:")

    def test_convert_evidence_to_signals_empty_bundle_returns_empty(self, brand: Brand, job: OpportunitiesJob):
        """_convert_evidence_to_signals with empty bundle returns empty signals."""
        from kairo.hero.engines.opportunities_engine import _convert_evidence_to_signals

        signals = _convert_evidence_to_signals(brand.id, job.id, None)

        assert signals.brand_id == brand.id
        assert len(signals.trends) == 0
        assert len(signals.web_mentions) == 0
        assert len(signals.competitor_posts) == 0
        assert len(signals.social_moments) == 0


@pytest.mark.django_db
class TestPR4bActivationRunJobRequired:
    """
    PR-4b §2: ActivationRun.job is required FK (not nullable).

    Per PRD §D.3.2: ActivationRun must link to OpportunitiesJob for ledger traceability.
    """

    def test_activation_run_requires_job(self, brand: Brand):
        """Creating ActivationRun without job raises error."""
        from kairo.sourceactivation.services import _persist_evidence, derive_seed_pack
        from kairo.sourceactivation.types import EvidenceItemData

        seed_pack = derive_seed_pack(brand.id)
        items = [
            EvidenceItemData(
                platform="instagram",
                actor_id="FIXTURE",
                acquisition_stage=1,
                recipe_id="FIXTURE",
                canonical_url="https://instagram.com/p/test123",
                external_id="test123",
                author_ref="test_author",
                text_primary="Test content",
            )
        ]

        # Passing None job_id should raise ValueError
        with pytest.raises(ValueError, match="job_id is required"):
            _persist_evidence(brand.id, None, seed_pack, items)

    def test_activation_run_requires_real_job(self, brand: Brand):
        """Creating ActivationRun with fake job_id raises error."""
        from kairo.sourceactivation.services import _persist_evidence, derive_seed_pack
        from kairo.sourceactivation.types import EvidenceItemData

        seed_pack = derive_seed_pack(brand.id)
        items = [
            EvidenceItemData(
                platform="instagram",
                actor_id="FIXTURE",
                acquisition_stage=1,
                recipe_id="FIXTURE",
                canonical_url="https://instagram.com/p/test123",
                external_id="test123",
                author_ref="test_author",
                text_primary="Test content",
            )
        ]

        # Passing fake job_id should raise ValueError
        fake_job_id = uuid.uuid4()
        with pytest.raises(ValueError, match="does not reference a real OpportunitiesJob"):
            _persist_evidence(brand.id, fake_job_id, seed_pack, items)

    def test_activation_run_with_real_job_succeeds(self, brand: Brand, job: OpportunitiesJob):
        """Creating ActivationRun with real job succeeds."""
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # Should succeed
        assert bundle.activation_run_id is not None

        # ActivationRun should have job FK
        run = ActivationRun.objects.get(id=bundle.activation_run_id)
        assert run.job_id == job.id
        assert run.job == job


@pytest.mark.django_db
class TestPR4bEvidenceIdsRequired:
    """
    PR-4b §3: evidence_ids min_length=1 for READY opportunities.

    Per PRD §F.1: OpportunityDTO.evidence_ids is REQUIRED with min_length=1.
    If evidence_ids is empty, opportunities should NOT be persisted.
    """

    def test_persist_opportunities_requires_evidence_ids(self, brand: Brand):
        """_persist_opportunities with empty evidence_ids returns empty list."""
        from kairo.core.enums import Channel, OpportunityType
        from kairo.hero.dto import OpportunityDraftDTO
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        run_id = uuid.uuid4()
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Test Opportunity",
                proposed_angle="Test angle for this opportunity",
                why_now="Market trends show high engagement with this topic area.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                suggested_channels=[Channel.LINKEDIN],
                score=80.0,
                score_explanation="High relevance",
                source="test",
                is_valid=True,
                rejection_reasons=[],
            )
        ]

        # Passing empty evidence_ids should return empty list
        result = _persist_opportunities(brand, drafts, run_id, evidence_ids=[])
        assert result == []

        # Passing None evidence_ids should return empty list
        result = _persist_opportunities(brand, drafts, run_id, evidence_ids=None)
        assert result == []

    def test_persist_opportunities_with_evidence_ids_succeeds(self, brand: Brand):
        """_persist_opportunities with evidence_ids persists opportunities."""
        from kairo.core.enums import Channel, OpportunityType
        from kairo.core.models import Opportunity
        from kairo.hero.dto import OpportunityDraftDTO
        from kairo.hero.engines.opportunities_engine import _persist_opportunities

        run_id = uuid.uuid4()
        evidence_ids = [uuid.uuid4(), uuid.uuid4()]
        drafts = [
            OpportunityDraftDTO(
                proposed_title="Test Opportunity With Evidence",
                proposed_angle="Test angle for this opportunity",
                why_now="Market trends show high engagement with this topic area.",
                type=OpportunityType.TREND,
                primary_channel=Channel.LINKEDIN,
                suggested_channels=[Channel.LINKEDIN],
                score=80.0,
                score_explanation="High relevance",
                source="test",
                is_valid=True,
                rejection_reasons=[],
            )
        ]

        # Passing evidence_ids should succeed
        result = _persist_opportunities(brand, drafts, run_id, evidence_ids=evidence_ids)
        assert len(result) == 1

        # Check persisted opportunity has evidence_ids
        opp = result[0]
        assert opp.metadata is not None
        assert "evidence_ids" in opp.metadata
        assert len(opp.metadata["evidence_ids"]) == 2

    def test_ready_board_requires_evidence_ids_in_opportunities(self, brand: Brand, job: OpportunitiesJob):
        """READY board opportunities must have evidence_ids >= 1."""
        from kairo.sourceactivation.adapters import select_evidence_for_opportunity
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # Selection should produce at least 1 evidence ID
        selected = select_evidence_for_opportunity(bundle, max_items=3)
        assert len(selected) >= 1, "PRD §F.1 requires at least 1 evidence_id for READY opportunities"


@pytest.mark.django_db
class TestPR4bIntegration:
    """
    PR-4b integration tests: Full pipeline compliance.
    """

    def test_full_sourceactivation_pipeline_compliance(self, brand: Brand, job: OpportunitiesJob):
        """
        Full SourceActivation pipeline produces compliant output.

        Verifies:
        1. Signals come from EvidenceBundle only
        2. ActivationRun has required job FK
        3. Evidence selection produces at least 1 ID
        """
        from kairo.hero.engines.opportunities_engine import _convert_evidence_to_signals
        from kairo.sourceactivation.adapters import select_evidence_for_opportunity
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        # Step 1: Derive SeedPack (per PRD §A.3)
        seed_pack = derive_seed_pack(brand.id)
        assert seed_pack.brand_id == brand.id

        # Step 2: Get EvidenceBundle (per PRD §B)
        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )
        assert bundle.mode == "fixture_only"
        assert len(bundle.items) > 0

        # Step 3: Verify ActivationRun has job FK (per PRD §D.3.2)
        run = ActivationRun.objects.get(id=bundle.activation_run_id)
        assert run.job_id == job.id, "PR-4b: ActivationRun.job is required FK"

        # Step 4: Convert to signals (per PRD §C.1 - pure, no merge)
        signals = _convert_evidence_to_signals(brand.id, job.id, bundle)
        total_signals = len(signals.trends) + len(signals.web_mentions) + len(signals.social_moments)
        assert total_signals > 0, "Signals should be produced from evidence"

        # Step 5: Select evidence for opportunities (per PRD §F.1)
        selected = select_evidence_for_opportunity(bundle, max_items=3)
        assert len(selected) >= 1, "PR-4b: evidence_ids min_length=1 for READY opportunities"

    def test_sourceactivation_only_from_job_context(self, brand: Brand):
        """
        SourceActivation should only be invoked from job execution context.

        This test verifies that attempting to call get_or_create_evidence_bundle
        without a real job fails as expected.
        """
        from kairo.sourceactivation.services import derive_seed_pack, get_or_create_evidence_bundle

        seed_pack = derive_seed_pack(brand.id)

        # Calling without a real job should fail
        fake_job_id = uuid.uuid4()
        with pytest.raises(ValueError, match="does not reference a real OpportunitiesJob"):
            get_or_create_evidence_bundle(
                brand_id=brand.id,
                seed_pack=seed_pack,
                job_id=fake_job_id,
                mode="fixture_only",
            )
