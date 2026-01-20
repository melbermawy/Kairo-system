"""
PR-3 Invariant Tests.

Per opportunities_v1_prd.md Section D.3.2 + I.4 (PR-3 acceptance criteria).

These tests verify:
1. Migration applies cleanly (tables exist)
2. ActivationRun CRUD operations work
3. EvidenceItem CRUD operations work with FK to ActivationRun
4. Batch fetch by evidence_ids returns correct items in stable order
5. Query is single query (no N+1)
6. No references to Apify or source activation execution logic

PR-3 is schema-only + query helper. No execution logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand, Tenant
from kairo.hero.models import (
    ActivationRun,
    EvidenceItem,
    OpportunitiesBoard,
    OpportunitiesJob,
    OpportunitiesJobStatus,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="PR3 Test Tenant",
        slug="pr3-test-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    return Brand.objects.create(
        tenant=tenant,
        name="PR3 Test Brand",
        positioning="Testing PR-3 schema invariants",
    )


@pytest.fixture
def opportunities_job(db, brand):
    """Create an opportunities job for activation run tests."""
    return OpportunitiesJob.objects.create(
        brand=brand,
        status=OpportunitiesJobStatus.RUNNING,
        params_json={"force": False, "first_run": True},
    )


@pytest.fixture
def activation_run(db, brand, opportunities_job):
    """Create an activation run for evidence item tests."""
    return ActivationRun.objects.create(
        job=opportunities_job,
        brand_id=brand.id,
        snapshot_id=uuid.uuid4(),
        seed_pack_json={
            "brand_id": str(brand.id),
            "positioning": "Test positioning",
            "tone_tags": ["professional"],
            "seed_keywords": ["test", "pr3"],
        },
        recipes_selected=["IG-1", "TT-1"],
        recipes_executed=["IG-1"],
        item_count=5,
        items_with_transcript=2,
        estimated_cost_usd=Decimal("0.15"),
    )


def _create_evidence_item(
    activation_run: ActivationRun,
    brand_id: uuid.UUID,
    suffix: str,
    *,
    platform: str = "instagram",
    has_transcript: bool = False,
) -> EvidenceItem:
    """Helper to create an EvidenceItem with all required fields."""
    return EvidenceItem.objects.create(
        activation_run=activation_run,
        brand_id=brand_id,
        platform=platform,
        actor_id="apify/instagram-scraper",
        acquisition_stage=1,
        recipe_id="IG-1",
        canonical_url=f"https://instagram.com/p/{suffix}",
        external_id=f"ext_{suffix}",
        author_ref=f"author_{suffix}",
        title=f"Title for {suffix}",
        text_primary=f"Primary text content for {suffix} with enough detail to be meaningful",
        text_secondary="Transcript text" if has_transcript else "",
        hashtags=["test", "pr3"],
        view_count=1000,
        like_count=100,
        comment_count=10,
        share_count=5,
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        has_transcript=has_transcript,
        raw_json={"original": "data"},
    )


# =============================================================================
# Test 1 - Tables Exist (Migration Applied)
# Per PRD Section I.4: Migrations apply cleanly
# =============================================================================


@pytest.mark.django_db
class TestTablesExist:
    """Verify migration created all required tables."""

    def test_activation_run_table_exists(self, db):
        """ActivationRun table exists and is queryable."""
        # Should not raise
        count = ActivationRun.objects.count()
        assert count >= 0

    def test_evidence_item_table_exists(self, db):
        """EvidenceItem table exists and is queryable."""
        # Should not raise
        count = EvidenceItem.objects.count()
        assert count >= 0

    def test_existing_tables_still_work(self, db, brand):
        """Existing hero tables (OpportunitiesJob, OpportunitiesBoard) still work."""
        # Create job
        job = OpportunitiesJob.objects.create(
            brand=brand,
            status=OpportunitiesJobStatus.PENDING,
        )
        assert job.id is not None

        # Create board
        board = OpportunitiesBoard.objects.create(
            brand=brand,
            state=TodayBoardState.NOT_GENERATED_YET,
        )
        assert board.id is not None


# =============================================================================
# Test 2 - ActivationRun CRUD
# Per PRD Section D.3.2: ActivationRun model
# =============================================================================


@pytest.mark.django_db
class TestActivationRunCRUD:
    """Verify ActivationRun model CRUD operations."""

    def test_create_activation_run(self, brand, opportunities_job):
        """Can create ActivationRun with all required fields."""
        snapshot_id = uuid.uuid4()

        run = ActivationRun.objects.create(
            job=opportunities_job,
            brand_id=brand.id,
            snapshot_id=snapshot_id,
            seed_pack_json={
                "brand_id": str(brand.id),
                "positioning": "Test",
                "tone_tags": [],
                "seed_keywords": ["test"],
            },
            recipes_selected=["IG-1", "TT-1"],
            recipes_executed=[],
            estimated_cost_usd=Decimal("0.00"),
        )

        assert run.id is not None
        assert run.brand_id == brand.id
        assert run.snapshot_id == snapshot_id
        assert run.job_id == opportunities_job.id
        assert run.recipes_selected == ["IG-1", "TT-1"]
        assert run.recipes_executed == []
        assert run.item_count == 0
        assert run.items_with_transcript == 0
        assert run.estimated_cost_usd == Decimal("0.00")
        assert run.started_at is not None
        assert run.ended_at is None

    def test_update_activation_run(self, activation_run):
        """Can update ActivationRun fields."""
        activation_run.recipes_executed = ["IG-1", "TT-1"]
        activation_run.item_count = 10
        activation_run.items_with_transcript = 4
        activation_run.estimated_cost_usd = Decimal("0.21")
        activation_run.ended_at = datetime.now(timezone.utc)
        activation_run.save()

        # Reload from DB
        run = ActivationRun.objects.get(id=activation_run.id)
        assert run.recipes_executed == ["IG-1", "TT-1"]
        assert run.item_count == 10
        assert run.items_with_transcript == 4
        assert run.estimated_cost_usd == Decimal("0.21")
        assert run.ended_at is not None

    def test_activation_run_fk_to_job(self, brand, opportunities_job):
        """ActivationRun has valid FK to OpportunitiesJob."""
        run = ActivationRun.objects.create(
            job=opportunities_job,
            brand_id=brand.id,
            snapshot_id=uuid.uuid4(),
        )

        # Can traverse FK
        assert run.job.id == opportunities_job.id
        assert run.job.brand_id == brand.id

        # Reverse relation works
        assert opportunities_job.activation_runs.count() == 1
        assert opportunities_job.activation_runs.first().id == run.id

    def test_activation_run_cascade_delete(self, brand, opportunities_job):
        """Deleting job cascades to ActivationRun."""
        run = ActivationRun.objects.create(
            job=opportunities_job,
            brand_id=brand.id,
            snapshot_id=uuid.uuid4(),
        )
        run_id = run.id

        # Delete job
        opportunities_job.delete()

        # Run should be deleted
        assert not ActivationRun.objects.filter(id=run_id).exists()


# =============================================================================
# Test 3 - EvidenceItem CRUD
# Per PRD Section D.3.2: EvidenceItem model
# =============================================================================


@pytest.mark.django_db
class TestEvidenceItemCRUD:
    """Verify EvidenceItem model CRUD operations."""

    def test_create_evidence_item(self, brand, activation_run):
        """Can create EvidenceItem with all required fields."""
        item = EvidenceItem.objects.create(
            activation_run=activation_run,
            brand_id=brand.id,
            platform="instagram",
            actor_id="apify/instagram-scraper",
            acquisition_stage=1,
            recipe_id="IG-1",
            canonical_url="https://instagram.com/p/test123",
            external_id="test123",
            author_ref="test_author",
            title="Test Title",
            text_primary="This is the primary text content",
            text_secondary="This is the transcript",
            hashtags=["test", "content"],
            view_count=5000,
            like_count=500,
            comment_count=50,
            share_count=25,
            published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            has_transcript=True,
            raw_json={"raw": "payload"},
        )

        assert item.id is not None
        assert item.brand_id == brand.id
        assert item.activation_run_id == activation_run.id
        assert item.platform == "instagram"
        assert item.actor_id == "apify/instagram-scraper"
        assert item.acquisition_stage == 1
        assert item.recipe_id == "IG-1"
        assert item.canonical_url == "https://instagram.com/p/test123"
        assert item.has_transcript is True
        assert item.hashtags == ["test", "content"]
        assert item.view_count == 5000

    def test_create_evidence_item_minimal(self, brand, activation_run):
        """Can create EvidenceItem with only required fields."""
        item = EvidenceItem.objects.create(
            activation_run=activation_run,
            brand_id=brand.id,
            platform="tiktok",
            actor_id="clockworks/tiktok-scraper",
            acquisition_stage=1,
            recipe_id="TT-1",
            canonical_url="https://tiktok.com/@user/video/123",
            author_ref="user",
            text_primary="TikTok caption",
            fetched_at=datetime.now(timezone.utc),
        )

        assert item.id is not None
        assert item.external_id == ""
        assert item.title == ""
        assert item.text_secondary == ""
        assert item.has_transcript is False
        assert item.view_count is None

    def test_evidence_item_fk_to_activation_run(self, brand, activation_run):
        """EvidenceItem has valid FK to ActivationRun."""
        item = _create_evidence_item(activation_run, brand.id, "fk_test")

        # Can traverse FK
        assert item.activation_run.id == activation_run.id

        # Reverse relation works
        assert activation_run.items.count() == 1
        assert activation_run.items.first().id == item.id

    def test_evidence_item_cascade_delete(self, brand, activation_run):
        """Deleting ActivationRun cascades to EvidenceItems."""
        item = _create_evidence_item(activation_run, brand.id, "cascade_test")
        item_id = item.id

        # Delete activation run
        activation_run.delete()

        # Item should be deleted
        assert not EvidenceItem.objects.filter(id=item_id).exists()

    def test_evidence_item_supports_all_platforms(self, brand, activation_run):
        """EvidenceItem can be created for all supported platforms."""
        platforms = ["instagram", "tiktok", "youtube", "linkedin"]

        for platform in platforms:
            item = _create_evidence_item(
                activation_run,
                brand.id,
                f"platform_{platform}",
                platform=platform,
            )
            assert item.platform == platform


# =============================================================================
# Test 4 - Batch Fetch by IDs
# Per PRD Section I.4: Batch fetch returns correct items, one query, stable order
# =============================================================================


@pytest.mark.django_db
class TestBatchFetchByIds:
    """Verify batch fetch query helper."""

    def test_fetch_evidence_by_ids_returns_correct_items(self, brand, activation_run):
        """fetch_evidence_by_ids returns correct items."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_by_ids

        # Create items
        item1 = _create_evidence_item(activation_run, brand.id, "batch1")
        item2 = _create_evidence_item(activation_run, brand.id, "batch2")
        item3 = _create_evidence_item(activation_run, brand.id, "batch3")

        # Fetch by IDs
        ids = [item1.id, item2.id, item3.id]
        results = fetch_evidence_by_ids(ids)

        assert len(results) == 3
        assert {r.id for r in results} == {item1.id, item2.id, item3.id}

    def test_fetch_evidence_by_ids_preserves_order(self, brand, activation_run):
        """fetch_evidence_by_ids preserves input ID order."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_by_ids

        # Create items
        item1 = _create_evidence_item(activation_run, brand.id, "order1")
        item2 = _create_evidence_item(activation_run, brand.id, "order2")
        item3 = _create_evidence_item(activation_run, brand.id, "order3")

        # Fetch in specific order (not creation order)
        ids = [item3.id, item1.id, item2.id]
        results = fetch_evidence_by_ids(ids)

        assert len(results) == 3
        assert results[0].id == item3.id
        assert results[1].id == item1.id
        assert results[2].id == item2.id

    def test_fetch_evidence_by_ids_handles_missing(self, brand, activation_run):
        """fetch_evidence_by_ids skips missing IDs gracefully."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_by_ids

        # Create only one item
        item1 = _create_evidence_item(activation_run, brand.id, "exists")
        missing_id = uuid.uuid4()

        # Fetch with one valid and one missing ID
        ids = [item1.id, missing_id]
        results = fetch_evidence_by_ids(ids)

        # Should return only the existing item
        assert len(results) == 1
        assert results[0].id == item1.id

    def test_fetch_evidence_by_ids_empty_list(self):
        """fetch_evidence_by_ids handles empty list."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_by_ids

        results = fetch_evidence_by_ids([])
        assert results == []

    def test_fetch_evidence_by_ids_single_query(self, brand, activation_run):
        """fetch_evidence_by_ids uses single query (no N+1)."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        from kairo.hero.services.evidence_query_service import fetch_evidence_by_ids

        # Create multiple items
        items = [
            _create_evidence_item(activation_run, brand.id, f"n1_{i}")
            for i in range(10)
        ]
        ids = [item.id for item in items]

        # Capture queries during fetch
        with CaptureQueriesContext(connection) as context:
            results = fetch_evidence_by_ids(ids)

        # Should be exactly 1 query (the IN clause query)
        assert len(results) == 10
        assert len(context.captured_queries) == 1, (
            f"Expected 1 query, got {len(context.captured_queries)}: "
            f"{[q['sql'] for q in context.captured_queries]}"
        )


# =============================================================================
# Test 5 - Evidence Preview Helper
# Per PRD Section F.1: EvidencePreviewDTO fields
# =============================================================================


@pytest.mark.django_db
class TestEvidencePreviewHelper:
    """Verify evidence preview query helper."""

    def test_fetch_evidence_previews_returns_correct_fields(self, brand, activation_run):
        """fetch_evidence_previews returns all required preview fields."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_previews

        item = _create_evidence_item(
            activation_run,
            brand.id,
            "preview_test",
            has_transcript=True,
        )

        previews = fetch_evidence_previews([item.id])

        assert len(previews) == 1
        preview = previews[0]

        # Check all required fields
        assert preview.id == item.id
        assert preview.platform == item.platform
        assert preview.canonical_url == item.canonical_url
        assert preview.author_ref == item.author_ref
        assert preview.has_transcript is True
        assert len(preview.text_snippet) > 0

    def test_fetch_evidence_previews_truncates_text(self, brand, activation_run):
        """fetch_evidence_previews truncates text_primary to 200 chars."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_previews

        # Create item with long text
        long_text = "A" * 500
        item = EvidenceItem.objects.create(
            activation_run=activation_run,
            brand_id=brand.id,
            platform="instagram",
            actor_id="test",
            acquisition_stage=1,
            recipe_id="IG-1",
            canonical_url="https://example.com",
            author_ref="author",
            text_primary=long_text,
            fetched_at=datetime.now(timezone.utc),
        )

        previews = fetch_evidence_previews([item.id])

        assert len(previews) == 1
        # Should be truncated to 200 + "..."
        assert len(previews[0].text_snippet) <= 203
        assert previews[0].text_snippet.endswith("...")

    def test_fetch_evidence_previews_preserves_order(self, brand, activation_run):
        """fetch_evidence_previews preserves input ID order."""
        from kairo.hero.services.evidence_query_service import fetch_evidence_previews

        item1 = _create_evidence_item(activation_run, brand.id, "prev1")
        item2 = _create_evidence_item(activation_run, brand.id, "prev2")

        # Reverse order
        previews = fetch_evidence_previews([item2.id, item1.id])

        assert previews[0].id == item2.id
        assert previews[1].id == item1.id


# =============================================================================
# Test 6 - Indexes Defined in Model Meta
# Per PRD Section D.3.2: Required indexes
# =============================================================================


@pytest.mark.django_db
class TestIndexesExist:
    """Verify required indexes are defined in model Meta."""

    def test_evidence_item_brand_created_index(self):
        """Index (brand_id, created_at) is defined on EvidenceItem."""
        # Check model Meta.indexes directly - DB-agnostic approach
        index_names = [idx.name for idx in EvidenceItem._meta.indexes]
        assert "idx_evidence_brand_created" in index_names, (
            f"idx_evidence_brand_created not in model indexes: {index_names}"
        )

    def test_evidence_item_platform_fetched_index(self):
        """Index (platform, fetched_at) is defined on EvidenceItem."""
        index_names = [idx.name for idx in EvidenceItem._meta.indexes]
        assert "idx_evidence_platform_fetched" in index_names, (
            f"idx_evidence_platform_fetched not in model indexes: {index_names}"
        )

    def test_evidence_item_brand_id_index(self):
        """Index (brand_id, id) is defined on EvidenceItem for join queries."""
        index_names = [idx.name for idx in EvidenceItem._meta.indexes]
        assert "idx_evidence_brand_id" in index_names, (
            f"idx_evidence_brand_id not in model indexes: {index_names}"
        )

    def test_activation_run_brand_started_index(self):
        """Index (brand_id, started_at) is defined on ActivationRun."""
        index_names = [idx.name for idx in ActivationRun._meta.indexes]
        assert "idx_actrun_brand_started" in index_names, (
            f"idx_actrun_brand_started not in model indexes: {index_names}"
        )

    def test_activation_run_job_started_index(self):
        """Index (job, started_at) is defined on ActivationRun."""
        index_names = [idx.name for idx in ActivationRun._meta.indexes]
        assert "idx_actrun_job_started" in index_names, (
            f"idx_actrun_job_started not in model indexes: {index_names}"
        )


# =============================================================================
# Test 7 - No Execution Logic (Schema Only)
# Per PRD Section I.4: No references to Apify or source activation execution
# =============================================================================


@pytest.mark.django_db
class TestNoExecutionLogic:
    """Verify PR-3 is schema-only with no execution logic."""

    def test_activation_run_has_no_execute_method(self):
        """ActivationRun model has no execute/run method."""
        assert not hasattr(ActivationRun, "execute")
        assert not hasattr(ActivationRun, "run")
        assert not hasattr(ActivationRun, "call_apify")

    def test_evidence_item_has_no_fetch_method(self):
        """EvidenceItem model has no fetch method."""
        assert not hasattr(EvidenceItem, "fetch")
        assert not hasattr(EvidenceItem, "scrape")
        assert not hasattr(EvidenceItem, "call_apify")

    def test_no_apify_imports_in_models(self):
        """Model files don't import Apify-related modules."""
        import kairo.hero.models.activation_run as ar_module
        import kairo.hero.models.evidence_item as ei_module

        # Check module doesn't have apify in its namespace
        assert "apify" not in dir(ar_module)
        assert "apify" not in dir(ei_module)
