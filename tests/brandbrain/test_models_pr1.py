"""
PR-1: Tests for BrandBrain data model + migrations + indexes.

These tests verify:
1. Migrations apply cleanly
2. Critical constraints exist (via introspection)
3. Required indexes exist per spec 1.2

All tests marked @pytest.mark.db as they require Django DB access.
"""

import pytest
from django.db import connection


def _get_tables() -> set[str]:
    """Get all table names in the database (PostgreSQL compatible)."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        return {row[0] for row in cursor.fetchall()}


def _get_columns(table_name: str) -> set[str]:
    """Get all column names for a table (PostgreSQL compatible)."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
        """, [table_name])
        return {row[0] for row in cursor.fetchall()}


def _get_indexes(table_name: str) -> set[str]:
    """Get all index names for a table (PostgreSQL compatible)."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = %s
        """, [table_name])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.db
@pytest.mark.django_db
class TestMigrationsApply:
    """Test that all migrations apply without errors."""

    def test_brandbrain_tables_exist(self):
        """All BrandBrain tables should exist after migrations."""
        tables = _get_tables()

        expected_tables = {
            "brandbrain_onboarding",
            "brandbrain_source_connection",
            "brandbrain_normalized_evidence_item",
            "brandbrain_evidence_bundle",
            "brandbrain_feature_report",
            "brandbrain_compile_run",
            "brandbrain_overrides",
            "brandbrain_snapshot",
        }

        for table in expected_tables:
            assert table in tables, f"Expected table '{table}' not found"

    def test_apify_run_extension_columns_exist(self):
        """ApifyRun should have PR-1 extension columns."""
        columns = _get_columns("apify_run")

        expected_columns = {
            "source_connection_id",
            "brand_id",
            "raw_item_count",
            "normalized_item_count",
        }

        for col in expected_columns:
            assert col in columns, f"Expected column '{col}' not found in apify_run"


@pytest.mark.db
@pytest.mark.django_db
class TestIndexesExist:
    """Test that required indexes exist per spec 1.2."""

    def test_snapshot_brand_latest_index(self):
        """Index for GET /latest: brand_id, created_at DESC."""
        indexes = _get_indexes("brandbrain_snapshot")
        assert "idx_snapshot_brand_latest" in indexes

    def test_compile_run_brand_latest_index(self):
        """Index for short-circuit check: brand_id, created_at DESC."""
        indexes = _get_indexes("brandbrain_compile_run")
        assert "idx_compile_brand_latest" in indexes

    def test_apify_run_brand_status_index(self):
        """Index for compile evidence gathering: brand_id, status."""
        indexes = _get_indexes("apify_run")
        assert "idx_apifyrun_brand_status" in indexes

    def test_apify_run_source_success_partial_index(self):
        """Partial index for TTL freshness check."""
        indexes = _get_indexes("apify_run")
        assert "idx_apifyrun_source_success" in indexes

    def test_nei_brand_recency_index(self):
        """Index for bundle selection by recency."""
        indexes = _get_indexes("brandbrain_normalized_evidence_item")
        assert "idx_nei_brand_recency" in indexes

    def test_nei_brand_published_index(self):
        """Index for bundler: (brand_id, platform, published_at) - Pattern C."""
        indexes = _get_indexes("brandbrain_normalized_evidence_item")
        assert "idx_nei_brand_published" in indexes

    def test_nei_brand_published_ct_index(self):
        """Index for bundler: (brand_id, platform, content_type, published_at) - Pattern B."""
        indexes = _get_indexes("brandbrain_normalized_evidence_item")
        assert "idx_nei_brand_published_ct" in indexes

    def test_source_connection_brand_enabled_index(self):
        """Index for enabled sources lookup."""
        indexes = _get_indexes("brandbrain_source_connection")
        assert "idx_source_brand_enabled" in indexes


@pytest.mark.db
@pytest.mark.django_db
class TestUniqueConstraintsExist:
    """Test that uniqueness constraints exist per spec 1.2."""

    def test_nei_external_id_partial_unique(self):
        """
        UNIQUE(brand_id, platform, content_type, external_id) WHERE external_id IS NOT NULL.
        """
        indexes = _get_indexes("brandbrain_normalized_evidence_item")
        assert "uniq_nei_external_id" in indexes

    def test_nei_web_canonical_url_partial_unique(self):
        """
        UNIQUE(brand_id, platform, content_type, canonical_url) WHERE platform='web'.
        """
        indexes = _get_indexes("brandbrain_normalized_evidence_item")
        assert "uniq_nei_web_canonical_url" in indexes

    def test_source_connection_unique_constraint(self):
        """UNIQUE(brand, platform, capability, identifier)."""
        indexes = _get_indexes("brandbrain_source_connection")
        assert "uniq_source_brand_platform_cap_id" in indexes


@pytest.mark.db
@pytest.mark.django_db
class TestModelCRUD:
    """Test basic CRUD operations on BrandBrain models."""

    def test_create_brand_onboarding(self, test_brand):
        """Should be able to create BrandOnboarding."""
        from kairo.brandbrain.models import BrandOnboarding

        onboarding = BrandOnboarding.objects.create(
            brand=test_brand,
            tier=0,
            answers_json={"tier0.what_we_do": "Test value"},
        )

        assert onboarding.id is not None
        assert onboarding.brand == test_brand
        assert onboarding.tier == 0

    def test_create_source_connection(self, test_brand):
        """Should be able to create SourceConnection."""
        from kairo.brandbrain.models import SourceConnection

        source = SourceConnection.objects.create(
            brand=test_brand,
            platform="instagram",
            capability="posts",
            identifier="testhandle",
            is_enabled=True,
        )

        assert source.id is not None
        assert source.brand == test_brand
        assert source.platform == "instagram"

    def test_create_normalized_evidence_item(self, test_brand):
        """Should be able to create NormalizedEvidenceItem."""
        from kairo.brandbrain.models import NormalizedEvidenceItem

        item = NormalizedEvidenceItem.objects.create(
            brand=test_brand,
            platform="instagram",
            content_type="post",
            external_id="123456789",
            canonical_url="https://instagram.com/p/abc123",
            author_ref="testhandle",
            text_primary="Test caption",
        )

        assert item.id is not None
        assert item.brand == test_brand
        assert item.external_id == "123456789"

    def test_create_evidence_bundle(self, test_brand):
        """Should be able to create EvidenceBundle."""
        from kairo.brandbrain.models import EvidenceBundle

        bundle = EvidenceBundle.objects.create(
            brand=test_brand,
            criteria_json={"max_items": 40},
            item_ids=[],
            summary_json={"total": 0},
        )

        assert bundle.id is not None
        assert bundle.brand == test_brand

    def test_create_compile_run(self, test_brand):
        """Should be able to create BrandBrainCompileRun."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        run = BrandBrainCompileRun.objects.create(
            brand=test_brand,
            status="PENDING",
            onboarding_snapshot_json={},
        )

        assert run.id is not None
        assert run.brand == test_brand
        assert run.status == "PENDING"

    def test_create_snapshot(self, test_brand):
        """Should be able to create BrandBrainSnapshot."""
        from kairo.brandbrain.models import BrandBrainCompileRun, BrandBrainSnapshot

        run = BrandBrainCompileRun.objects.create(
            brand=test_brand,
            status="SUCCEEDED",
        )

        snapshot = BrandBrainSnapshot.objects.create(
            brand=test_brand,
            compile_run=run,
            snapshot_json={"positioning": {}},
        )

        assert snapshot.id is not None
        assert snapshot.brand == test_brand
        assert snapshot.compile_run == run

    def test_create_overrides(self, test_brand):
        """Should be able to create BrandBrainOverrides (1:1)."""
        from kairo.brandbrain.models import BrandBrainOverrides

        overrides = BrandBrainOverrides.objects.create(
            brand=test_brand,
            overrides_json={"positioning.what_we_do": "Override value"},
            pinned_paths=["positioning.what_we_do"],
        )

        assert overrides.id is not None
        assert overrides.brand == test_brand
        assert len(overrides.pinned_paths) == 1


@pytest.mark.db
@pytest.mark.django_db
class TestConstraintEnforcement:
    """Test that constraints are actually enforced."""

    def test_brand_onboarding_unique(self, test_brand):
        """BrandOnboarding should be 1:1 with Brand."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import BrandOnboarding

        BrandOnboarding.objects.create(brand=test_brand, tier=0)

        # Second onboarding for same brand should fail
        with pytest.raises(IntegrityError):
            BrandOnboarding.objects.create(brand=test_brand, tier=1)

    def test_brand_overrides_unique(self, test_brand):
        """BrandBrainOverrides should be 1:1 with Brand."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import BrandBrainOverrides

        BrandBrainOverrides.objects.create(brand=test_brand)

        # Second overrides for same brand should fail
        with pytest.raises(IntegrityError):
            BrandBrainOverrides.objects.create(brand=test_brand)

    def test_source_connection_unique(self, test_brand):
        """SourceConnection should be unique per brand/platform/capability/identifier."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import SourceConnection

        SourceConnection.objects.create(
            brand=test_brand,
            platform="instagram",
            capability="posts",
            identifier="testhandle",
        )

        # Duplicate should fail
        with pytest.raises(IntegrityError):
            SourceConnection.objects.create(
                brand=test_brand,
                platform="instagram",
                capability="posts",
                identifier="testhandle",
            )

    def test_nei_external_id_partial_unique_enforced(self, test_brand):
        """NEI with same external_id should fail (when not null)."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import NormalizedEvidenceItem

        NormalizedEvidenceItem.objects.create(
            brand=test_brand,
            platform="instagram",
            content_type="post",
            external_id="123",
            canonical_url="https://instagram.com/p/abc",
            author_ref="handle",
            text_primary="First",
        )

        # Same external_id should fail
        with pytest.raises(IntegrityError):
            NormalizedEvidenceItem.objects.create(
                brand=test_brand,
                platform="instagram",
                content_type="post",
                external_id="123",
                canonical_url="https://instagram.com/p/def",
                author_ref="handle",
                text_primary="Second",
            )

    def test_nei_null_external_id_allowed_duplicates(self, test_brand):
        """NEI with NULL external_id should allow duplicates (web pages)."""
        from kairo.brandbrain.models import NormalizedEvidenceItem

        # Both have null external_id - should be allowed
        NormalizedEvidenceItem.objects.create(
            brand=test_brand,
            platform="web",
            content_type="web_page",
            external_id=None,  # NULL
            canonical_url="https://example.com/page1",
            author_ref="example.com",
            text_primary="Page 1",
        )

        # Different URL, same brand/platform/type, null external_id - OK
        item2 = NormalizedEvidenceItem.objects.create(
            brand=test_brand,
            platform="web",
            content_type="web_page",
            external_id=None,
            canonical_url="https://example.com/page2",
            author_ref="example.com",
            text_primary="Page 2",
        )

        assert item2.id is not None


@pytest.mark.db
@pytest.mark.django_db
class TestApifyRunExtension:
    """Test ApifyRun extension fields."""

    def test_apify_run_new_fields_nullable(self):
        """New ApifyRun fields should be nullable for backwards compat."""
        from kairo.integrations.apify.models import ApifyRun

        # Create without new fields (legacy behavior)
        run = ApifyRun.objects.create(
            actor_id="apify/instagram-scraper",
            apify_run_id="test-run-123",
        )

        assert run.source_connection_id is None
        assert run.brand_id is None
        assert run.raw_item_count == 0
        assert run.normalized_item_count == 0

    def test_apify_run_with_brandbrain_fields(self, test_brand):
        """ApifyRun should accept BrandBrain integration fields."""
        import uuid
        from kairo.integrations.apify.models import ApifyRun

        source_id = uuid.uuid4()

        run = ApifyRun.objects.create(
            actor_id="apify/instagram-scraper",
            apify_run_id="test-run-456",
            source_connection_id=source_id,
            brand_id=test_brand.id,
            raw_item_count=10,
            normalized_item_count=8,
        )

        assert run.source_connection_id == source_id
        assert run.brand_id == test_brand.id
        assert run.raw_item_count == 10
        assert run.normalized_item_count == 8


@pytest.mark.db
@pytest.mark.django_db
class TestIdentifierNormalization:
    """Test that identifier normalization prevents duplicates."""

    def test_instagram_url_trailing_slash_normalized(self, test_brand):
        """Instagram URLs with/without trailing slash should conflict."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import SourceConnection

        SourceConnection.objects.create(
            brand=test_brand,
            platform="instagram",
            capability="posts",
            identifier="https://www.instagram.com/nogood.io/",
        )

        # Same URL without trailing slash should fail (normalized to same value)
        with pytest.raises(IntegrityError):
            SourceConnection.objects.create(
                brand=test_brand,
                platform="instagram",
                capability="posts",
                identifier="https://www.instagram.com/nogood.io",
            )

    def test_tiktok_handle_at_sign_normalized(self, test_brand):
        """TikTok handles with/without @ should conflict."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import SourceConnection

        SourceConnection.objects.create(
            brand=test_brand,
            platform="tiktok",
            capability="profile_videos",
            identifier="@nogood.io",
        )

        # Same handle without @ should fail
        with pytest.raises(IntegrityError):
            SourceConnection.objects.create(
                brand=test_brand,
                platform="tiktok",
                capability="profile_videos",
                identifier="nogood.io",
            )

    def test_linkedin_company_url_variants_normalized(self, test_brand):
        """LinkedIn company URL variants should all normalize to slug."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import SourceConnection

        # Full URL with www and trailing slash
        source = SourceConnection.objects.create(
            brand=test_brand,
            platform="linkedin",
            capability="company_posts",
            identifier="https://www.linkedin.com/company/nogood/",
        )
        # Should normalize to just "nogood"
        assert source.identifier == "nogood"

        # Same company without www - should fail
        with pytest.raises(IntegrityError):
            SourceConnection.objects.create(
                brand=test_brand,
                platform="linkedin",
                capability="company_posts",
                identifier="https://linkedin.com/company/nogood",
            )

    def test_linkedin_company_slug_stays_as_slug(self, test_brand):
        """LinkedIn company slug without URL should stay as-is."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import SourceConnection

        source = SourceConnection.objects.create(
            brand=test_brand,
            platform="linkedin",
            capability="company_posts",
            identifier="acme-corp",
        )
        # Should stay as "acme-corp" (lowercased)
        assert source.identifier == "acme-corp"

        # Same slug should fail
        with pytest.raises(IntegrityError):
            SourceConnection.objects.create(
                brand=test_brand,
                platform="linkedin",
                capability="company_posts",
                identifier="ACME-CORP",  # different case, normalized to same
            )

    def test_identifier_whitespace_stripped(self, test_brand):
        """Whitespace should be stripped from identifiers."""
        from django.db import IntegrityError
        from kairo.brandbrain.models import SourceConnection

        SourceConnection.objects.create(
            brand=test_brand,
            platform="instagram",
            capability="posts",
            identifier="  testhandle  ",
        )

        # Same handle without whitespace should fail
        with pytest.raises(IntegrityError):
            SourceConnection.objects.create(
                brand=test_brand,
                platform="instagram",
                capability="posts",
                identifier="testhandle",
            )
