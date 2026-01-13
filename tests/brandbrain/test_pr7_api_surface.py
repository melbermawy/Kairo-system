"""
PR-7 Tests: API Surface + Contract Tests + Performance Guards.

Tests for all read-path and work-path endpoints per spec Section 10.

Test Categories:
A) Contract Tests: Response shapes match spec interfaces
B) Include Params: ?include=evidence,qa,bundle,full
C) Overrides CRUD: GET/PATCH /overrides
D) Cross-Brand Data Isolation: brand_id scoping (NO auth enforcement)
E) Query Count: Bounded queries (no N+1)
F) Read-Path Boundary: No side effects on read endpoints

NOTE: Auth/ownership enforcement is NOT implemented (out of scope for PRD v1).
      All endpoints are publicly accessible. Tests verify data isolation by
      brand_id in the URL path only, not authorization.

Per spec Section 1.1 (Performance & Latency Contracts):
- GET /latest: P95 < 50ms, 1-2 queries
- GET /history: P95 < 100ms, 2-3 queries
- GET /status: P95 < 30ms, 1-2 queries
- GET /overrides: P95 < 30ms, 1-2 queries
- PATCH /overrides: P95 < 100ms
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="Test Tenant PR7",
        slug="test-tenant-pr7",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand PR7",
        slug="test-brand-pr7",
    )


@pytest.fixture
def brand_b(db, tenant):
    """Create a second test brand for cross-brand tests."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand B",
        slug="test-brand-b-pr7",
    )


@pytest.fixture
def brand_with_onboarding(db, brand):
    """Create a brand with complete Tier0 onboarding."""
    from kairo.brandbrain.models import BrandOnboarding

    BrandOnboarding.objects.create(
        brand=brand,
        tier=0,
        answers_json={
            "tier0.what_we_do": "We help businesses grow",
            "tier0.who_for": "Small business owners",
            "tier0.primary_goal": "brand_awareness",
            "tier0.cta_posture": "soft",
        },
    )
    return brand


@pytest.fixture
def source_instagram_posts(db, brand):
    """Create an Instagram posts source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="instagram",
        capability="posts",
        identifier="testbrand",
        is_enabled=True,
    )


@pytest.fixture
def evidence_bundle(db, brand_with_onboarding):
    """Create an evidence bundle with summary."""
    from kairo.brandbrain.models import EvidenceBundle

    return EvidenceBundle.objects.create(
        brand=brand_with_onboarding,
        criteria_json={"max_items_per_platform": 50},
        item_ids=[str(uuid.uuid4()) for _ in range(10)],
        summary_json={
            "total_items": 10,
            "platforms": {"instagram": 5, "linkedin": 3, "web": 2},
            "coverage": {"posts": 8, "pages": 2},
        },
    )


@pytest.fixture
def compile_run_succeeded(db, brand_with_onboarding, evidence_bundle):
    """Create a succeeded compile run with bundle."""
    from kairo.brandbrain.models import BrandBrainCompileRun

    return BrandBrainCompileRun.objects.create(
        brand=brand_with_onboarding,
        bundle=evidence_bundle,
        status="SUCCEEDED",
        prompt_version="v1",
        model="gpt-4",
        evidence_status_json={
            "reused": [{"source": "instagram.posts", "count": 5}],
            "refreshed": [],
            "skipped": [{"source": "linkedin.profile_posts", "reason": "Disabled"}],
            "failed": [],
        },
        qa_report_json={
            "overall_score": 0.85,
            "sections_validated": 7,
            "warnings": [],
        },
    )


@pytest.fixture
def snapshot_with_full_data(db, brand_with_onboarding, compile_run_succeeded):
    """Create a snapshot linked to compile run with bundle."""
    from kairo.brandbrain.models import BrandBrainSnapshot

    return BrandBrainSnapshot.objects.create(
        brand=brand_with_onboarding,
        compile_run=compile_run_succeeded,
        snapshot_json={
            "positioning": {
                "what_we_do": {"value": "Test value", "confidence": 0.9, "locked": False},
            },
            "voice": {"tone": {"value": "Professional", "confidence": 0.8}},
            "pillars": [],
            "constraints": {},
            "platform_profiles": {},
            "examples": {},
            "meta": {
                "compiled_at": timezone.now().isoformat(),
                "missing_inputs": [],
                "confidence_summary": {"overall": 0.85},
            },
        },
        diff_from_previous_json={
            "changed": ["positioning.what_we_do"],
            "added": [],
            "removed": [],
        },
    )


# =============================================================================
# A) CONTRACT TESTS - RESPONSE SHAPES
# =============================================================================


LATEST_SNAPSHOT_REQUIRED_FIELDS = {
    "snapshot_id",
    "brand_id",
    "snapshot_json",
    "created_at",
    "compile_run_id",
}

LATEST_SNAPSHOT_FULL_ADDITIONAL_FIELDS = {
    "evidence_status",
    "qa_report",
    "bundle_summary",
}

OVERRIDES_REQUIRED_FIELDS = {
    "brand_id",
    "overrides_json",
    "pinned_paths",
    "updated_at",
}


def assert_has_required_fields(data: dict, required_fields: set, context: str = ""):
    """Assert that data dict contains all required fields."""
    missing = required_fields - set(data.keys())
    assert not missing, f"{context}Missing required fields: {missing}"


def assert_excludes_fields(data: dict, excluded_fields: set, context: str = ""):
    """Assert that data dict does NOT contain excluded fields."""
    present = excluded_fields & set(data.keys())
    assert not present, f"{context}Unexpected fields: {present}"


@pytest.mark.db
class TestLatestSnapshotContract:
    """Contract tests for GET /api/brands/:id/brandbrain/latest."""

    def test_compact_response_has_required_fields(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """Compact response (default) should have required fields."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest")

        assert response.status_code == 200
        data = response.json()
        assert_has_required_fields(data, LATEST_SNAPSHOT_REQUIRED_FIELDS, "GET /latest compact: ")

    def test_compact_response_excludes_verbose_fields(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """Compact response should NOT include verbose fields."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest")

        assert response.status_code == 200
        data = response.json()
        assert_excludes_fields(
            data, LATEST_SNAPSHOT_FULL_ADDITIONAL_FIELDS, "GET /latest compact: "
        )

    def test_full_response_includes_all_fields(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """Response with ?include=full should include all additional fields."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=full"
        )

        assert response.status_code == 200
        data = response.json()
        all_fields = LATEST_SNAPSHOT_REQUIRED_FIELDS | LATEST_SNAPSHOT_FULL_ADDITIONAL_FIELDS
        assert_has_required_fields(data, all_fields, "GET /latest?include=full: ")


@pytest.mark.db
class TestOverridesContract:
    """Contract tests for GET/PATCH /api/brands/:id/brandbrain/overrides."""

    def test_get_overrides_has_required_fields(self, client, db, brand):
        """GET /overrides should have required fields even when empty."""
        response = client.get(f"/api/brands/{brand.id}/brandbrain/overrides")

        assert response.status_code == 200
        data = response.json()
        assert_has_required_fields(data, OVERRIDES_REQUIRED_FIELDS, "GET /overrides: ")

    def test_patch_overrides_returns_updated_data(self, client, db, brand):
        """PATCH /overrides should return updated overrides."""
        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "overrides_json": {"positioning.what_we_do": "Custom value"},
                "pinned_paths": ["positioning.what_we_do"],
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert_has_required_fields(data, OVERRIDES_REQUIRED_FIELDS, "PATCH /overrides: ")
        assert data["overrides_json"]["positioning.what_we_do"] == "Custom value"
        assert "positioning.what_we_do" in data["pinned_paths"]


# =============================================================================
# B) INCLUDE PARAMS TESTS
# =============================================================================


@pytest.mark.db
class TestIncludeParams:
    """Test ?include= query param behavior for GET /latest."""

    def test_include_evidence_only(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """?include=evidence returns only evidence_status."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=evidence"
        )

        assert response.status_code == 200
        data = response.json()
        assert "evidence_status" in data
        assert "qa_report" not in data
        assert "bundle_summary" not in data

    def test_include_qa_only(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """?include=qa returns only qa_report."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=qa"
        )

        assert response.status_code == 200
        data = response.json()
        assert "qa_report" in data
        assert "evidence_status" not in data
        assert "bundle_summary" not in data

    def test_include_bundle_only(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """?include=bundle returns only bundle_summary."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=bundle"
        )

        assert response.status_code == 200
        data = response.json()
        assert "bundle_summary" in data
        assert "evidence_status" not in data
        assert "qa_report" not in data

    def test_include_comma_separated(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """?include=evidence,qa returns both fields."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=evidence,qa"
        )

        assert response.status_code == 200
        data = response.json()
        assert "evidence_status" in data
        assert "qa_report" in data
        assert "bundle_summary" not in data

    def test_include_full_returns_all(
        self, client, db, brand_with_onboarding, snapshot_with_full_data, source_instagram_posts
    ):
        """?include=full returns all additional fields."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=full"
        )

        assert response.status_code == 200
        data = response.json()
        assert "evidence_status" in data
        assert "qa_report" in data
        assert "bundle_summary" in data


# =============================================================================
# C) OVERRIDES CRUD TESTS
# =============================================================================


@pytest.mark.db
class TestOverridesCRUD:
    """Test GET/PATCH /overrides CRUD operations."""

    def test_get_overrides_empty_when_none_exist(self, client, db, brand):
        """GET /overrides returns empty when no overrides exist."""
        response = client.get(f"/api/brands/{brand.id}/brandbrain/overrides")

        assert response.status_code == 200
        data = response.json()
        assert data["overrides_json"] == {}
        assert data["pinned_paths"] == []
        assert data["updated_at"] is None

    def test_get_overrides_returns_existing(self, client, db, brand):
        """GET /overrides returns existing overrides."""
        from kairo.brandbrain.models import BrandBrainOverrides

        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={"voice.tone": "Casual"},
            pinned_paths=["voice.tone"],
        )

        response = client.get(f"/api/brands/{brand.id}/brandbrain/overrides")

        assert response.status_code == 200
        data = response.json()
        assert data["overrides_json"]["voice.tone"] == "Casual"
        assert "voice.tone" in data["pinned_paths"]

    def test_patch_creates_overrides_if_not_exist(self, client, db, brand):
        """PATCH /overrides creates new overrides if none exist."""
        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "overrides_json": {"positioning.what_we_do": "New value"},
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["overrides_json"]["positioning.what_we_do"] == "New value"

    def test_patch_merges_overrides(self, client, db, brand):
        """PATCH /overrides merges with existing overrides."""
        from kairo.brandbrain.models import BrandBrainOverrides

        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={"field_a": "value_a"},
            pinned_paths=[],
        )

        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "overrides_json": {"field_b": "value_b"},
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        # Both fields should exist
        assert data["overrides_json"]["field_a"] == "value_a"
        assert data["overrides_json"]["field_b"] == "value_b"

    def test_patch_null_removes_override(self, client, db, brand):
        """PATCH with null value removes the override key."""
        from kairo.brandbrain.models import BrandBrainOverrides

        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={"field_a": "value_a", "field_b": "value_b"},
            pinned_paths=[],
        )

        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "overrides_json": {"field_a": None},  # Remove field_a
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "field_a" not in data["overrides_json"]
        assert data["overrides_json"]["field_b"] == "value_b"

    def test_patch_replaces_pinned_paths(self, client, db, brand):
        """PATCH replaces (not merges) pinned_paths."""
        from kairo.brandbrain.models import BrandBrainOverrides

        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={},
            pinned_paths=["old_path"],
        )

        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "pinned_paths": ["new_path"],
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pinned_paths"] == ["new_path"]
        assert "old_path" not in data["pinned_paths"]

    def test_patch_rejects_invalid_overrides_type(self, client, db, brand):
        """PATCH rejects non-object overrides_json."""
        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "overrides_json": ["not", "an", "object"],
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "overrides_json must be an object" in data["error"]

    def test_patch_rejects_invalid_pinned_type(self, client, db, brand):
        """PATCH rejects non-array pinned_paths."""
        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({
                "pinned_paths": "not_an_array",
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "pinned_paths must be an array" in data["error"]


# =============================================================================
# D) CROSS-BRAND SECURITY TESTS
# =============================================================================


@pytest.mark.db
class TestCrossBrandDataIsolation:
    """Test data isolation by brand_id in URL path (no auth/ownership enforcement)."""

    def test_latest_returns_404_for_other_brands_snapshot(
        self, client, db, brand_with_onboarding, brand_b, snapshot_with_full_data, source_instagram_posts
    ):
        """GET /latest for Brand B returns 404 (Brand A has the snapshot)."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Brand B has no snapshot - should return 404
        response = client.get(f"/api/brands/{brand_b.id}/brandbrain/latest")

        assert response.status_code == 404
        assert "No snapshot found" in response.json()["error"]

    def test_history_returns_empty_for_other_brand(
        self, client, db, brand_with_onboarding, brand_b, snapshot_with_full_data, source_instagram_posts
    ):
        """GET /history for Brand B returns empty list (Brand A has the snapshot)."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(f"/api/brands/{brand_b.id}/brandbrain/history")

        assert response.status_code == 200
        data = response.json()
        assert data["snapshots"] == []
        assert data["total"] == 0

    def test_overrides_isolated_between_brands(self, client, db, brand, brand_b):
        """Overrides for Brand A are not visible to Brand B."""
        from kairo.brandbrain.models import BrandBrainOverrides

        # Create overrides for Brand A
        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={"secret": "brand_a_data"},
            pinned_paths=["secret"],
        )

        # Brand B should not see Brand A's overrides
        response = client.get(f"/api/brands/{brand_b.id}/brandbrain/overrides")

        assert response.status_code == 200
        data = response.json()
        assert data["overrides_json"] == {}
        assert data["pinned_paths"] == []

    def test_status_returns_404_for_other_brands_run(
        self, client, db, brand_with_onboarding, brand_b, compile_run_succeeded, source_instagram_posts
    ):
        """GET /status returns 404 when requesting another brand's compile run."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Try to access Brand A's run via Brand B's endpoint
        response = client.get(
            f"/api/brands/{brand_b.id}/brandbrain/compile/{compile_run_succeeded.id}/status"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    def test_patch_overrides_only_affects_own_brand(self, client, db, brand, brand_b):
        """PATCH /overrides on Brand A does not affect Brand B."""
        from kairo.brandbrain.models import BrandBrainOverrides

        # Create overrides for both brands
        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={"field": "brand_a"},
            pinned_paths=[],
        )
        BrandBrainOverrides.objects.create(
            brand=brand_b,
            overrides_json={"field": "brand_b"},
            pinned_paths=[],
        )

        # Patch Brand A
        client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data=json.dumps({"overrides_json": {"field": "modified_a"}}),
            content_type="application/json",
        )

        # Brand B should be unchanged
        response = client.get(f"/api/brands/{brand_b.id}/brandbrain/overrides")
        data = response.json()
        assert data["overrides_json"]["field"] == "brand_b"


# =============================================================================
# E) QUERY COUNT / PERFORMANCE TESTS
# =============================================================================


@pytest.mark.db
class TestQueryCount:
    """Test query count bounds for read endpoints (no N+1)."""

    def test_latest_query_count_compact(
        self, client, db, brand_with_onboarding, snapshot_with_full_data,
        source_instagram_posts, django_assert_num_queries
    ):
        """GET /latest (compact) should be 2 queries (brand check + snapshot with select_related)."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # 2 queries: brand exists check, snapshot + compile_run + bundle (via select_related)
        with django_assert_num_queries(2):
            response = client.get(
                f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest"
            )

        assert response.status_code == 200

    def test_latest_query_count_full(
        self, client, db, brand_with_onboarding, snapshot_with_full_data,
        source_instagram_posts, django_assert_num_queries
    ):
        """GET /latest?include=full should be 2 queries (uses select_related)."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Should be same query count - uses select_related for compile_run and bundle
        with django_assert_num_queries(2):
            response = client.get(
                f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest?include=full"
            )

        assert response.status_code == 200
        data = response.json()
        assert "evidence_status" in data
        assert "qa_report" in data
        assert "bundle_summary" in data

    def test_history_query_count(
        self, client, db, brand_with_onboarding, source_instagram_posts, django_assert_num_queries
    ):
        """GET /history should be 3 queries (brand check, count, paginated list)."""
        from kairo.brandbrain.models import BrandBrainSnapshot, BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Create multiple snapshots
        for i in range(15):
            cr = BrandBrainCompileRun.objects.create(
                brand=brand_with_onboarding,
                status="SUCCEEDED",
            )
            BrandBrainSnapshot.objects.create(
                brand=brand_with_onboarding,
                compile_run=cr,
                snapshot_json={"index": i},
            )

        # 3 queries: brand check, count, paginated fetch
        with django_assert_num_queries(3):
            response = client.get(
                f"/api/brands/{brand_with_onboarding.id}/brandbrain/history?page_size=5"
            )

        assert response.status_code == 200
        assert len(response.json()["snapshots"]) == 5

    def test_overrides_get_query_count(self, client, db, brand, django_assert_num_queries):
        """GET /overrides should be 2 queries (brand check, overrides fetch)."""
        from kairo.brandbrain.models import BrandBrainOverrides

        BrandBrainOverrides.objects.create(
            brand=brand,
            overrides_json={"field": "value"},
            pinned_paths=["field"],
        )

        with django_assert_num_queries(2):
            response = client.get(f"/api/brands/{brand.id}/brandbrain/overrides")

        assert response.status_code == 200


# =============================================================================
# F) READ-PATH BOUNDARY TESTS
# =============================================================================


@pytest.mark.db
class TestReadPathBoundary:
    """Test that read-path endpoints don't trigger work or mutations."""

    def test_get_latest_no_side_effects(
        self, client, db, brand_with_onboarding, source_instagram_posts
    ):
        """GET /latest returns 404 without triggering any compile work."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        initial_count = BrandBrainCompileRun.objects.count()

        # Multiple requests should not create any compile runs
        for _ in range(3):
            response = client.get(
                f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest"
            )
            assert response.status_code == 404

        assert BrandBrainCompileRun.objects.count() == initial_count

    def test_get_history_no_side_effects(self, client, db, brand_with_onboarding, source_instagram_posts):
        """GET /history returns empty without triggering any work."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        initial_count = BrandBrainCompileRun.objects.count()

        response = client.get(f"/api/brands/{brand_with_onboarding.id}/brandbrain/history")
        assert response.status_code == 200
        assert response.json()["total"] == 0

        assert BrandBrainCompileRun.objects.count() == initial_count

    def test_get_overrides_no_side_effects(self, client, db, brand):
        """GET /overrides does not create overrides if none exist."""
        from kairo.brandbrain.models import BrandBrainOverrides

        initial_count = BrandBrainOverrides.objects.count()

        response = client.get(f"/api/brands/{brand.id}/brandbrain/overrides")
        assert response.status_code == 200

        # Should NOT have created an overrides record
        assert BrandBrainOverrides.objects.count() == initial_count


# =============================================================================
# G) ERROR HANDLING TESTS
# =============================================================================


@pytest.mark.db
class TestErrorHandling:
    """Test error responses for invalid inputs."""

    def test_latest_invalid_brand_id(self, client, db):
        """GET /latest returns 400 for invalid UUID."""
        response = client.get("/api/brands/not-a-uuid/brandbrain/latest")
        assert response.status_code == 400
        assert "Invalid brand_id" in response.json()["error"]

    def test_latest_nonexistent_brand(self, client, db):
        """GET /latest returns 404 for nonexistent brand."""
        fake_id = uuid.uuid4()
        response = client.get(f"/api/brands/{fake_id}/brandbrain/latest")
        assert response.status_code == 404
        assert "Brand not found" in response.json()["error"]

    def test_overrides_patch_invalid_json(self, client, db, brand):
        """PATCH /overrides returns 400 for invalid JSON."""
        response = client.patch(
            f"/api/brands/{brand.id}/brandbrain/overrides",
            data="not valid json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["error"]

    def test_overrides_patch_nonexistent_brand(self, client, db):
        """PATCH /overrides returns 404 for nonexistent brand."""
        fake_id = uuid.uuid4()
        response = client.patch(
            f"/api/brands/{fake_id}/brandbrain/overrides",
            data=json.dumps({"overrides_json": {}}),
            content_type="application/json",
        )
        assert response.status_code == 404
        assert "Brand not found" in response.json()["error"]

    def test_history_invalid_pagination(self, client, db, brand):
        """GET /history handles invalid pagination gracefully."""
        # Invalid page should default to 1
        response = client.get(f"/api/brands/{brand.id}/brandbrain/history?page=abc")
        assert response.status_code == 400
        assert "Invalid pagination" in response.json()["error"]
