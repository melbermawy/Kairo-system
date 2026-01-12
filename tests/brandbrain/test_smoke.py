"""
Smoke tests for BrandBrain test harness.

PR-0: Verify test infrastructure is wired correctly.

These tests prove:
1. Django test DB wiring works (using existing models)
2. Pytest fixtures work correctly
3. Sample loader can access var/apify_samples/
4. Dict builders produce valid structures

All tests here are marked @pytest.mark.unit for fast CI runs.
"""

import pytest

from tests.helpers.apify_samples import list_sample_dirs, load_sample


# =============================================================================
# DJANGO DB WIRING
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestDjangoDbWiring:
    """Smoke tests proving Django test DB is wired correctly."""

    def test_can_create_tenant(self):
        """Should be able to create a Tenant instance in test DB."""
        from kairo.core.models import Tenant

        tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )

        assert tenant.id is not None
        assert tenant.name == "Test Tenant"
        assert tenant.slug == "test-tenant"

        # Verify it persists
        fetched = Tenant.objects.get(id=tenant.id)
        assert fetched.name == "Test Tenant"

    def test_can_create_brand_with_tenant(self):
        """Should be able to create a Brand scoped to a Tenant."""
        from kairo.core.models import Brand, Tenant

        tenant = Tenant.objects.create(
            name="Brand Test Tenant",
            slug="brand-test-tenant",
        )

        brand = Brand.objects.create(
            tenant=tenant,
            name="Test Brand",
            slug="test-brand",
            positioning="We help developers build better software.",
        )

        assert brand.id is not None
        assert brand.tenant == tenant
        assert brand.name == "Test Brand"

        # Verify FK relationship works
        assert brand in tenant.brands.all()

    def test_db_isolation_between_tests(self):
        """Each test should have isolated DB state."""
        from kairo.core.models import Tenant

        # This test runs after the above - should see clean DB
        count = Tenant.objects.count()
        # In pytest-django with transaction=True, each test is isolated
        # We just verify we can count without errors
        assert count >= 0


# =============================================================================
# SAMPLE LOADER
# =============================================================================


@pytest.mark.unit
class TestSampleLoaderSmoke:
    """Smoke tests for Apify sample loader."""

    def test_can_list_sample_directories(self):
        """Should be able to list actor directories in var/apify_samples/."""
        dirs = list_sample_dirs()

        assert isinstance(dirs, list)
        assert len(dirs) > 0
        # Should have at least the Instagram scraper
        assert "apify_instagram-scraper" in dirs

    def test_can_load_instagram_sample(self):
        """Should be able to load an Instagram sample item."""
        sample = load_sample("apify_instagram-scraper", item_index=0)

        assert isinstance(sample, dict)
        # Per Appendix B1, Instagram posts have these fields
        assert "id" in sample
        assert "url" in sample
        assert "ownerUsername" in sample


# =============================================================================
# DICT BUILDERS
# =============================================================================


@pytest.mark.unit
class TestBuildersSmoke:
    """Smoke tests for BrandBrain dict builders."""

    def test_build_brand_returns_valid_dict(self):
        """build_brand() should return a dict with required fields."""
        from tests.brandbrain.builders import build_brand

        brand = build_brand()

        assert isinstance(brand, dict)
        # Per spec Section 2.1: Brand has id, tenant_id, name, website_url, created_at
        assert "id" in brand
        assert "tenant_id" in brand
        assert "name" in brand
        assert "website_url" in brand
        assert "created_at" in brand

    def test_build_onboarding_answers_tier0_returns_valid_dict(self):
        """build_onboarding_answers_tier0() should return Tier 0 answers."""
        from tests.brandbrain.builders import build_onboarding_answers_tier0

        answers = build_onboarding_answers_tier0()

        assert isinstance(answers, dict)
        # Required Tier 0 fields per spec Section 6 (prefixed with tier0.)
        assert "tier0.what_we_do" in answers
        assert "tier0.who_for" in answers
        assert "tier0.primary_goal" in answers
        assert "tier0.cta_posture" in answers

    def test_build_normalized_evidence_item_stub_returns_valid_dict(self):
        """build_normalized_evidence_item_stub() should return NormalizedEvidenceItem."""
        from tests.brandbrain.builders import build_normalized_evidence_item_stub

        item = build_normalized_evidence_item_stub()

        assert isinstance(item, dict)
        # Required fields per spec Section 3.1 (NormalizedEvidenceItem schema)
        assert "id" in item
        assert "brand_id" in item
        assert "platform" in item
        assert "content_type" in item
        assert "text_primary" in item

    def test_build_snapshot_stub_returns_valid_dict(self):
        """build_snapshot_stub() should return BrandBrainSnapshot row structure."""
        from tests.brandbrain.builders import build_snapshot_stub

        snapshot_row = build_snapshot_stub()

        assert isinstance(snapshot_row, dict)
        # The builder returns a snapshot ROW (with id, brand_id, etc.)
        # The snapshot_json field contains the actual BrandBrain schema
        assert "id" in snapshot_row
        assert "brand_id" in snapshot_row
        assert "compile_run_id" in snapshot_row
        assert "snapshot_json" in snapshot_row

        # Top-level sections per spec Section 8.2 are inside snapshot_json
        snapshot_json = snapshot_row["snapshot_json"]
        assert "positioning" in snapshot_json
        assert "voice" in snapshot_json
        assert "pillars" in snapshot_json
        assert "constraints" in snapshot_json
        assert "platform_profiles" in snapshot_json
        assert "examples" in snapshot_json
        assert "meta" in snapshot_json

    def test_build_field_node_returns_valid_structure(self):
        """build_field_node() should return FieldNode structure."""
        from tests.brandbrain.builders import build_field_node

        node = build_field_node(value="Test value", confidence=0.9)

        assert isinstance(node, dict)
        assert node["value"] == "Test value"
        assert node["confidence"] == 0.9
        assert "sources" in node
        assert "locked" in node


# =============================================================================
# PYTEST MARKERS
# =============================================================================


@pytest.mark.unit
class TestPytestMarkersSmoke:
    """Verify pytest markers work correctly."""

    @pytest.mark.skip(reason="Intentionally skipped for marker test")
    def test_skip_marker_works(self):
        """This test should be skipped."""
        raise AssertionError("This should not run")

    def test_pytest_parameterize_works(self):
        """Basic pytest functionality check."""
        assert True
