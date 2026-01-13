"""
PR-5 Tests: Compile Orchestration Skeleton.

Tests for compile kickoff, status, gating, and short-circuit per spec Section 7.

Test Categories:
A) Compile gating - reject when Tier0 required fields missing
B) Compile gating - reject when no enabled sources
C) Short-circuit - returns UNCHANGED when no-op conditions hold
D) Normal kickoff - returns 202 and creates compile run in PENDING
E) Status endpoint - read-only, returns correct shape for all states
F) Evidence status - LinkedIn profile posts skipped by default
G) Query count - GET /status is bounded (small, constant)
H) Input hash - deterministic hashing for short-circuit
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from kairo.brandbrain.compile import (
    check_compile_gating,
    compile_brandbrain,
    compute_compile_input_hash,
    get_compile_status,
    should_short_circuit_compile,
)
from kairo.brandbrain.compile.service import (
    TIER0_REQUIRED_FIELDS,
    GatingResult,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="Test Tenant PR5",
        slug="test-tenant-pr5",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand PR5",
        slug="test-brand-pr5",
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
def source_linkedin_profile(db, brand):
    """Create a LinkedIn profile posts source (unvalidated)."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="linkedin",
        capability="profile_posts",
        identifier="testprofile",
        is_enabled=True,
    )


@pytest.fixture
def existing_snapshot(db, brand_with_onboarding, source_instagram_posts):
    """Create an existing snapshot for short-circuit tests."""
    from kairo.brandbrain.models import (
        BrandBrainCompileRun,
        BrandBrainSnapshot,
    )

    # Compute input hash for the current state
    input_hash = compute_compile_input_hash(brand_with_onboarding.id)

    compile_run = BrandBrainCompileRun.objects.create(
        brand=brand_with_onboarding,
        status="SUCCEEDED",
        prompt_version="v1",
        model="gpt-4",
        onboarding_snapshot_json={"input_hash": input_hash},
        evidence_status_json={
            "reused": [{"source": "instagram.posts", "reason": "Fresh"}],
            "refreshed": [],
            "skipped": [],
            "failed": [],
        },
    )

    snapshot = BrandBrainSnapshot.objects.create(
        brand=brand_with_onboarding,
        compile_run=compile_run,
        snapshot_json={"_stub": True},
    )

    return snapshot


@pytest.fixture
def existing_apify_run(db, source_instagram_posts):
    """Create a fresh ApifyRun for the source."""
    from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus

    return ApifyRun.objects.create(
        brand_id=source_instagram_posts.brand_id,
        source_connection_id=source_instagram_posts.id,
        actor_id="apify~instagram-scraper",
        apify_run_id="test-run-123",
        status=ApifyRunStatus.SUCCEEDED,
        input_json={},
        raw_item_count=5,
    )


# =============================================================================
# A) COMPILE GATING - MISSING TIER0 FIELDS
# =============================================================================


@pytest.mark.db
class TestCompileGatingTier0:
    """Test compile gating rejects when Tier0 required fields missing."""

    def test_gating_rejects_no_onboarding(self, db, brand, source_instagram_posts):
        """Compile fails when brand has no onboarding at all."""
        result = check_compile_gating(brand.id)

        assert not result.allowed
        assert any(e.code == "MISSING_TIER0_FIELDS" for e in result.errors)
        # Should mention all required fields
        error_msg = result.errors[0].message
        for field in TIER0_REQUIRED_FIELDS:
            assert field in error_msg

    def test_gating_rejects_partial_tier0(self, db, brand, source_instagram_posts):
        """Compile fails when only some Tier0 fields are present."""
        from kairo.brandbrain.models import BrandOnboarding

        BrandOnboarding.objects.create(
            brand=brand,
            tier=0,
            answers_json={
                "tier0.what_we_do": "We help businesses grow",
                # Missing: who_for, primary_goal, cta_posture
            },
        )

        result = check_compile_gating(brand.id)

        assert not result.allowed
        assert any(e.code == "MISSING_TIER0_FIELDS" for e in result.errors)

    def test_gating_rejects_empty_tier0_values(self, db, brand, source_instagram_posts):
        """Compile fails when Tier0 fields have empty values."""
        from kairo.brandbrain.models import BrandOnboarding

        BrandOnboarding.objects.create(
            brand=brand,
            tier=0,
            answers_json={
                "tier0.what_we_do": "",  # Empty string should fail
                "tier0.who_for": "Small business owners",
                "tier0.primary_goal": "brand_awareness",
                "tier0.cta_posture": "soft",
            },
        )

        result = check_compile_gating(brand.id)

        assert not result.allowed
        assert any("tier0.what_we_do" in e.message for e in result.errors)


# =============================================================================
# B) COMPILE GATING - NO ENABLED SOURCES
# =============================================================================


@pytest.mark.db
class TestCompileGatingSources:
    """Test compile gating rejects when no enabled sources."""

    def test_gating_rejects_no_sources(self, db, brand_with_onboarding):
        """Compile fails when brand has no source connections."""
        result = check_compile_gating(brand_with_onboarding.id)

        assert not result.allowed
        assert any(e.code == "NO_ENABLED_SOURCES" for e in result.errors)

    def test_gating_rejects_only_disabled_sources(self, db, brand_with_onboarding):
        """Compile fails when all source connections are disabled."""
        from kairo.brandbrain.models import SourceConnection

        SourceConnection.objects.create(
            brand=brand_with_onboarding,
            platform="instagram",
            capability="posts",
            identifier="testbrand",
            is_enabled=False,  # Disabled
        )

        result = check_compile_gating(brand_with_onboarding.id)

        assert not result.allowed
        assert any(e.code == "NO_ENABLED_SOURCES" for e in result.errors)

    def test_gating_passes_with_enabled_source(
        self, db, brand_with_onboarding, source_instagram_posts
    ):
        """Compile is allowed when Tier0 complete and ≥1 enabled source."""
        # Re-associate source with brand_with_onboarding
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        result = check_compile_gating(brand_with_onboarding.id)

        assert result.allowed
        assert len(result.errors) == 0


# =============================================================================
# C) SHORT-CIRCUIT - RETURNS UNCHANGED WHEN NO-OP
# =============================================================================


@pytest.mark.db
class TestShortCircuit:
    """Test short-circuit detection returns UNCHANGED when inputs unchanged."""

    def test_short_circuit_when_no_snapshot(self, db, brand_with_onboarding):
        """No short-circuit when no existing snapshot."""
        result = should_short_circuit_compile(brand_with_onboarding.id)

        assert not result.is_noop
        assert "No existing snapshot" in result.reason

    def test_short_circuit_when_inputs_unchanged(
        self,
        db,
        brand_with_onboarding,
        source_instagram_posts,
        existing_snapshot,
        existing_apify_run,
    ):
        """Short-circuit when all inputs unchanged."""
        # Re-associate source with brand_with_onboarding
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()
        existing_apify_run.source_connection = source_instagram_posts
        existing_apify_run.brand_id = brand_with_onboarding.id
        existing_apify_run.save()

        result = should_short_circuit_compile(brand_with_onboarding.id)

        assert result.is_noop
        assert result.snapshot is not None
        assert "unchanged" in result.reason.lower()

    def test_short_circuit_fails_when_onboarding_changed(
        self,
        db,
        brand_with_onboarding,
        source_instagram_posts,
        existing_snapshot,
        existing_apify_run,
    ):
        """No short-circuit when onboarding answers changed."""
        from kairo.brandbrain.models import BrandOnboarding

        # Re-associate
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()
        existing_apify_run.source_connection = source_instagram_posts
        existing_apify_run.brand_id = brand_with_onboarding.id
        existing_apify_run.save()

        # Modify onboarding
        onboarding = BrandOnboarding.objects.get(brand=brand_with_onboarding)
        onboarding.answers_json["tier0.what_we_do"] = "Changed description"
        onboarding.save()

        result = should_short_circuit_compile(brand_with_onboarding.id)

        assert not result.is_noop
        assert "hash changed" in result.reason.lower()


# =============================================================================
# D) NORMAL KICKOFF - RETURNS 202 WITH PENDING
# =============================================================================


@pytest.mark.db
class TestCompileKickoff:
    """Test normal compile kickoff creates run and returns PENDING."""

    def test_kickoff_creates_compile_run(
        self, db, brand_with_onboarding, source_instagram_posts
    ):
        """POST /compile creates a BrandBrainCompileRun in PENDING."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        # Re-associate
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        result = compile_brandbrain(brand_with_onboarding.id)

        assert result.status == "PENDING"
        assert result.compile_run_id is not None
        assert result.poll_url is not None

        # Verify compile run exists
        compile_run = BrandBrainCompileRun.objects.get(id=result.compile_run_id)
        assert compile_run.status == "PENDING"
        assert compile_run.brand_id == brand_with_onboarding.id

    def test_kickoff_with_force_refresh_skips_short_circuit(
        self,
        db,
        brand_with_onboarding,
        source_instagram_posts,
        existing_snapshot,
        existing_apify_run,
    ):
        """force_refresh=True skips short-circuit check."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        # Re-associate
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()
        existing_apify_run.source_connection = source_instagram_posts
        existing_apify_run.brand_id = brand_with_onboarding.id
        existing_apify_run.save()

        # Without force_refresh, would short-circuit
        result_no_force = compile_brandbrain(brand_with_onboarding.id, force_refresh=False)
        assert result_no_force.status == "UNCHANGED"

        # With force_refresh, creates new run
        result_force = compile_brandbrain(brand_with_onboarding.id, force_refresh=True)
        assert result_force.status == "PENDING"
        assert result_force.compile_run_id != result_no_force.compile_run_id

    def test_kickoff_returns_gating_error(self, db, brand, source_instagram_posts):
        """Compile kickoff returns error when gating fails."""
        # Brand has no onboarding - gating will fail
        result = compile_brandbrain(brand.id)

        assert result.status == "FAILED"
        assert result.error is not None
        assert "Tier0" in result.error or "required" in result.error.lower()


# =============================================================================
# E) STATUS ENDPOINT - READ-ONLY, CORRECT SHAPE
# =============================================================================


@pytest.mark.db
class TestCompileStatus:
    """Test GET /status returns correct shape for all states."""

    def test_status_pending(self, db, brand_with_onboarding, source_instagram_posts):
        """GET /status returns PENDING shape."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        compile_run = BrandBrainCompileRun.objects.create(
            brand=brand_with_onboarding,
            status="PENDING",
        )

        status = get_compile_status(compile_run.id, brand_with_onboarding.id)

        assert status is not None
        assert status.status == "PENDING"
        assert status.error is None
        assert status.snapshot is None

    def test_status_running(self, db, brand_with_onboarding, source_instagram_posts):
        """GET /status returns RUNNING shape with progress."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        compile_run = BrandBrainCompileRun.objects.create(
            brand=brand_with_onboarding,
            status="RUNNING",
        )

        status = get_compile_status(compile_run.id, brand_with_onboarding.id)

        assert status is not None
        assert status.status == "RUNNING"
        assert status.progress is not None
        assert "stage" in status.progress

    def test_status_succeeded(
        self, db, brand_with_onboarding, source_instagram_posts, existing_snapshot
    ):
        """GET /status returns SUCCEEDED shape with snapshot."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        compile_run = existing_snapshot.compile_run

        status = get_compile_status(compile_run.id, brand_with_onboarding.id)

        assert status is not None
        assert status.status == "SUCCEEDED"
        assert status.snapshot is not None
        assert status.evidence_status is not None

    def test_status_failed(self, db, brand_with_onboarding, source_instagram_posts):
        """GET /status returns FAILED shape with error."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        compile_run = BrandBrainCompileRun.objects.create(
            brand=brand_with_onboarding,
            status="FAILED",
            error="Test error message",
            evidence_status_json={"reused": [], "refreshed": [], "skipped": [], "failed": []},
        )

        status = get_compile_status(compile_run.id, brand_with_onboarding.id)

        assert status is not None
        assert status.status == "FAILED"
        assert status.error == "Test error message"
        assert status.evidence_status is not None

    def test_status_not_found(self, db, brand_with_onboarding):
        """GET /status returns None for non-existent run."""
        fake_id = uuid.uuid4()
        status = get_compile_status(fake_id, brand_with_onboarding.id)
        assert status is None


# =============================================================================
# F) EVIDENCE STATUS - LINKEDIN PROFILE POSTS SKIPPED
# =============================================================================


@pytest.mark.db
class TestEvidenceStatusLinkedIn:
    """Test LinkedIn profile posts is skipped by default (feature flag off)."""

    def test_linkedin_profile_posts_in_skipped(
        self, db, brand_with_onboarding, source_linkedin_profile
    ):
        """LinkedIn profile posts appears in evidence_status.skipped."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_linkedin_profile.brand = brand_with_onboarding
        source_linkedin_profile.save()

        # Also need a valid enabled source for gating to pass
        from kairo.brandbrain.models import SourceConnection
        SourceConnection.objects.create(
            brand=brand_with_onboarding,
            platform="instagram",
            capability="posts",
            identifier="testbrand",
            is_enabled=True,
        )

        # Use sync=True for test (SQLite in-memory doesn't share between threads)
        result = compile_brandbrain(brand_with_onboarding.id, sync=True)

        # Ensure compile run was created
        assert result.compile_run_id and result.compile_run_id.int != 0, \
            f"Expected compile run to be created, got status={result.status}"

        compile_run = BrandBrainCompileRun.objects.get(id=result.compile_run_id)
        evidence = compile_run.evidence_status_json
        skipped_sources = [s["source"] for s in evidence.get("skipped", [])]
        assert "linkedin.profile_posts" in skipped_sources, \
            f"Expected linkedin.profile_posts in skipped, got {evidence}"


# =============================================================================
# G) QUERY COUNT - GET /STATUS IS BOUNDED
# =============================================================================


@pytest.mark.db
class TestQueryCount:
    """Test GET /status has bounded query count."""

    def test_status_query_count(
        self, db, brand_with_onboarding, source_instagram_posts, existing_snapshot, django_assert_num_queries
    ):
        """GET /status should be 1-2 queries (compile_run + optional snapshot)."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        compile_run_id = existing_snapshot.compile_run.id
        brand_id = brand_with_onboarding.id

        # Should be max 2 queries: 1 for compile_run, 1 for snapshot
        with django_assert_num_queries(2):
            status = get_compile_status(compile_run_id, brand_id)

        assert status is not None


# =============================================================================
# H) INPUT HASH - DETERMINISTIC
# =============================================================================


@pytest.mark.db
class TestInputHash:
    """Test input hash is deterministic."""

    def test_hash_deterministic(self, db, brand_with_onboarding, source_instagram_posts):
        """Same inputs produce same hash."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        hash1 = compute_compile_input_hash(brand_with_onboarding.id)
        hash2 = compute_compile_input_hash(brand_with_onboarding.id)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest

    def test_hash_changes_with_onboarding(self, db, brand_with_onboarding, source_instagram_posts):
        """Hash changes when onboarding changes."""
        from kairo.brandbrain.models import BrandOnboarding

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        hash1 = compute_compile_input_hash(brand_with_onboarding.id)

        onboarding = BrandOnboarding.objects.get(brand=brand_with_onboarding)
        onboarding.answers_json["tier0.what_we_do"] = "Changed"
        onboarding.save()

        hash2 = compute_compile_input_hash(brand_with_onboarding.id)

        assert hash1 != hash2

    def test_hash_changes_with_source(self, db, brand_with_onboarding, source_instagram_posts):
        """Hash changes when sources change."""
        from kairo.brandbrain.models import SourceConnection

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        hash1 = compute_compile_input_hash(brand_with_onboarding.id)

        # Add another source
        SourceConnection.objects.create(
            brand=brand_with_onboarding,
            platform="linkedin",
            capability="company_posts",
            identifier="testcompany",
            is_enabled=True,
        )

        hash2 = compute_compile_input_hash(brand_with_onboarding.id)

        assert hash1 != hash2

    def test_hash_changes_with_prompt_version(
        self, db, brand_with_onboarding, source_instagram_posts
    ):
        """Hash changes when prompt_version changes."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        hash1 = compute_compile_input_hash(brand_with_onboarding.id, prompt_version="v1")
        hash2 = compute_compile_input_hash(brand_with_onboarding.id, prompt_version="v2")

        assert hash1 != hash2


# =============================================================================
# API VIEW TESTS
# =============================================================================


@pytest.mark.db
class TestAPIViews:
    """Integration tests for API views."""

    def test_compile_kickoff_view_gating_failure(self, client, db, brand):
        """POST /compile returns 422 when gating fails."""
        response = client.post(
            f"/api/brands/{brand.id}/brandbrain/compile",
            content_type="application/json",
        )

        assert response.status_code == 422
        data = response.json()
        assert "error" in data
        assert "errors" in data

    def test_compile_kickoff_view_success(
        self, client, db, brand_with_onboarding, source_instagram_posts
    ):
        """POST /compile returns 202 when gating passes."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.post(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/compile",
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.json()
        assert "compile_run_id" in data
        assert data["status"] == "PENDING"
        assert "poll_url" in data

    def test_compile_status_view_not_found(self, client, db, brand_with_onboarding):
        """GET /status returns 404 for non-existent run."""
        fake_id = uuid.uuid4()
        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/compile/{fake_id}/status"
        )

        assert response.status_code == 404

    def test_latest_snapshot_view_not_found(
        self, client, db, brand_with_onboarding, source_instagram_posts
    ):
        """GET /latest returns 404 when no snapshot exists."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest"
        )

        assert response.status_code == 404
        data = response.json()
        assert "No snapshot found" in data["error"]

    def test_latest_snapshot_view_success(
        self, client, db, brand_with_onboarding, source_instagram_posts, existing_snapshot
    ):
        """GET /latest returns snapshot when it exists."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/latest"
        )

        assert response.status_code == 200
        data = response.json()
        assert "snapshot_id" in data
        assert "snapshot_json" in data

    def test_history_view_empty(
        self, client, db, brand_with_onboarding, source_instagram_posts
    ):
        """GET /history returns empty list when no snapshots."""
        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["snapshots"] == []
        assert data["total"] == 0

    def test_history_view_pagination(
        self, client, db, brand_with_onboarding, source_instagram_posts
    ):
        """GET /history respects pagination params."""
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

        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/history?page=1&page_size=5"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["snapshots"]) == 5
        assert data["total"] == 15
        assert data["page"] == 1
        assert data["page_size"] == 5


# =============================================================================
# I) CROSS-BRAND SECURITY - PREVENT DATA LEAKAGE
# =============================================================================


@pytest.fixture
def brand_b(db, tenant):
    """Create a second test brand for cross-brand tests."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand B",
        slug="test-brand-b",
    )


@pytest.mark.db
class TestCrossBrandSecurity:
    """Test that compile status enforces brand ownership (no cross-brand leakage)."""

    def test_status_returns_404_for_other_brands_run(
        self, client, db, brand_with_onboarding, brand_b, source_instagram_posts
    ):
        """
        SECURITY: GET /status returns 404 when requesting a compile run
        that belongs to a different brand.

        Scenario:
        - Brand A has a compile run
        - Request Brand B's status endpoint with Brand A's run_id
        - Should return 404 (not the run data)
        """
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Create a compile run for Brand A
        compile_run_brand_a = BrandBrainCompileRun.objects.create(
            brand=brand_with_onboarding,
            status="SUCCEEDED",
            evidence_status_json={"reused": [], "refreshed": [], "skipped": [], "failed": []},
        )

        # Try to access Brand A's run via Brand B's endpoint
        response = client.get(
            f"/api/brands/{brand_b.id}/brandbrain/compile/{compile_run_brand_a.id}/status"
        )

        # Should return 404 - run belongs to different brand
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["error"].lower()

    def test_status_function_returns_none_for_wrong_brand(
        self, db, brand_with_onboarding, brand_b, source_instagram_posts
    ):
        """
        SECURITY: get_compile_status() returns None when brand_id doesn't match.
        """
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        # Create a compile run for Brand A
        compile_run_brand_a = BrandBrainCompileRun.objects.create(
            brand=brand_with_onboarding,
            status="PENDING",
        )

        # Try to get status with wrong brand_id
        status = get_compile_status(compile_run_brand_a.id, brand_b.id)

        # Should return None - brand mismatch
        assert status is None

        # Verify it works with correct brand
        status_correct = get_compile_status(compile_run_brand_a.id, brand_with_onboarding.id)
        assert status_correct is not None
        assert status_correct.status == "PENDING"

    def test_status_works_for_correct_brand(
        self, client, db, brand_with_onboarding, source_instagram_posts
    ):
        """Verify GET /status works when brand_id matches the compile run."""
        from kairo.brandbrain.models import BrandBrainCompileRun

        source_instagram_posts.brand = brand_with_onboarding
        source_instagram_posts.save()

        compile_run = BrandBrainCompileRun.objects.create(
            brand=brand_with_onboarding,
            status="PENDING",
        )

        # Access via correct brand endpoint
        response = client.get(
            f"/api/brands/{brand_with_onboarding.id}/brandbrain/compile/{compile_run.id}/status"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING"
