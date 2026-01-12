"""
Tests for TTL freshness decision logic.

PR-2: Tests for freshness.py.

Contains both unit tests (mocked) and DB tests (real DB queries).
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch
import uuid

import pytest
from django.utils import timezone

from kairo.brandbrain.freshness import (
    FreshnessResult,
    check_source_freshness,
    any_source_stale,
)
from kairo.brandbrain.caps import clear_caps_cache
from kairo.integrations.apify.models import ApifyRunStatus


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    """Clear caps cache and reset TTL to default."""
    clear_caps_cache()
    monkeypatch.delenv("BRANDBRAIN_APIFY_RUN_TTL_HOURS", raising=False)
    yield
    clear_caps_cache()


@pytest.mark.unit
class TestFreshnessResultDataclass:
    """Tests for FreshnessResult dataclass."""

    def test_should_refresh_when_true(self):
        """FreshnessResult should correctly store should_refresh=True."""
        result = FreshnessResult(
            should_refresh=True,
            cached_run=None,
            reason="Test reason",
            run_age_hours=None,
        )
        assert result.should_refresh is True
        assert result.cached_run is None
        assert result.reason == "Test reason"
        assert result.run_age_hours is None

    def test_should_reuse_when_false(self):
        """FreshnessResult should correctly store should_refresh=False with cached run."""
        mock_run = MagicMock()
        result = FreshnessResult(
            should_refresh=False,
            cached_run=mock_run,
            reason="Cached run is fresh",
            run_age_hours=12.5,
        )
        assert result.should_refresh is False
        assert result.cached_run is mock_run
        assert result.run_age_hours == 12.5


@pytest.mark.unit
class TestCheckSourceFreshnessUnit:
    """Unit tests for check_source_freshness() with mocked DB."""

    def test_force_refresh_always_returns_should_refresh(self):
        """force_refresh=True should always return should_refresh=True."""
        source_id = uuid.uuid4()

        with patch("kairo.brandbrain.freshness.ApifyRun") as mock_apify:
            # Even if there's a fresh cached run, force_refresh should override
            result = check_source_freshness(source_id, force_refresh=True)

        assert result.should_refresh is True
        assert result.cached_run is None
        assert result.reason == "force_refresh=True"
        # DB should not even be queried
        mock_apify.objects.filter.assert_not_called()

    def test_no_cached_run_returns_should_refresh(self):
        """Should return should_refresh=True when no cached run exists."""
        source_id = uuid.uuid4()

        with patch("kairo.brandbrain.freshness.ApifyRun") as mock_apify:
            mock_apify.objects.filter.return_value.order_by.return_value.first.return_value = None
            result = check_source_freshness(source_id)

        assert result.should_refresh is True
        assert result.cached_run is None
        assert "No successful run exists" in result.reason
        assert result.run_age_hours is None

    def test_cached_run_within_ttl_returns_reuse(self):
        """Should return should_refresh=False when cached run is within TTL."""
        source_id = uuid.uuid4()
        now = timezone.now()

        mock_run = MagicMock()
        mock_run.created_at = now - timedelta(hours=12)  # 12 hours old, TTL is 24

        with patch("kairo.brandbrain.freshness.ApifyRun") as mock_apify:
            mock_apify.objects.filter.return_value.order_by.return_value.first.return_value = mock_run
            result = check_source_freshness(source_id)

        assert result.should_refresh is False
        assert result.cached_run is mock_run
        assert "fresh" in result.reason.lower()
        assert result.run_age_hours is not None
        assert 11.9 < result.run_age_hours < 12.1  # Approximately 12 hours

    def test_cached_run_older_than_ttl_returns_should_refresh(self):
        """Should return should_refresh=True when cached run is older than TTL."""
        source_id = uuid.uuid4()
        now = timezone.now()

        mock_run = MagicMock()
        mock_run.created_at = now - timedelta(hours=30)  # 30 hours old, TTL is 24

        with patch("kairo.brandbrain.freshness.ApifyRun") as mock_apify:
            mock_apify.objects.filter.return_value.order_by.return_value.first.return_value = mock_run
            result = check_source_freshness(source_id)

        assert result.should_refresh is True
        assert result.cached_run is None
        assert "stale" in result.reason.lower()
        assert result.run_age_hours is not None
        assert 29.9 < result.run_age_hours < 30.1

    def test_respects_custom_ttl_from_env(self, monkeypatch):
        """Should respect BRANDBRAIN_APIFY_RUN_TTL_HOURS env var."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_APIFY_RUN_TTL_HOURS", "48")

        source_id = uuid.uuid4()
        now = timezone.now()

        mock_run = MagicMock()
        mock_run.created_at = now - timedelta(hours=30)  # 30 hours old, TTL is now 48

        with patch("kairo.brandbrain.freshness.ApifyRun") as mock_apify:
            mock_apify.objects.filter.return_value.order_by.return_value.first.return_value = mock_run
            result = check_source_freshness(source_id)

        # 30 hours < 48 hours TTL, so should reuse
        assert result.should_refresh is False
        assert result.cached_run is mock_run

    def test_age_equals_ttl_exactly_reuses(self):
        """When age == TTL exactly, should reuse (not refresh)."""
        source_id = uuid.uuid4()
        now = timezone.now()

        mock_run = MagicMock()
        mock_run.created_at = now - timedelta(hours=24)  # Exactly 24 hours old, TTL is 24

        with patch("kairo.brandbrain.freshness.ApifyRun") as mock_apify:
            with patch("kairo.brandbrain.freshness.timezone") as mock_tz:
                mock_tz.now.return_value = now
                mock_apify.objects.filter.return_value.order_by.return_value.first.return_value = mock_run
                result = check_source_freshness(source_id)

        # age <= TTL means reuse
        assert result.should_refresh is False
        assert result.cached_run is mock_run
        assert "fresh" in result.reason.lower()


# =============================================================================
# DB Tests - require actual database
# =============================================================================


@pytest.mark.db
class TestCheckSourceFreshnessDB:
    """Database tests for check_source_freshness()."""

    @pytest.fixture
    def brand(self, db):
        """Create a test brand."""
        from kairo.core.models import Brand, Tenant
        tenant = Tenant.objects.create(name="Test Tenant")
        return Brand.objects.create(tenant=tenant, name="Test Brand")

    @pytest.fixture
    def source_connection(self, db, brand):
        """Create a test source connection."""
        from kairo.brandbrain.models import SourceConnection
        return SourceConnection.objects.create(
            brand=brand,
            platform="instagram",
            capability="posts",
            identifier="https://instagram.com/test/",
            is_enabled=True,
        )

    def test_no_runs_returns_should_refresh(self, source_connection):
        """Should refresh when no ApifyRun exists for source."""
        result = check_source_freshness(source_connection.id)

        assert result.should_refresh is True
        assert result.cached_run is None
        assert "No successful run exists" in result.reason

    def test_failed_run_not_used_for_cache(self, db, source_connection):
        """Failed runs should not be used as cache."""
        from kairo.integrations.apify.models import ApifyRun

        # Create a failed run
        ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=source_connection.brand_id,
            status=ApifyRunStatus.FAILED,
        )

        result = check_source_freshness(source_connection.id)

        assert result.should_refresh is True
        assert result.cached_run is None

    def test_succeeded_run_within_ttl_reused(self, db, source_connection):
        """Succeeded run within TTL should be reused."""
        from kairo.integrations.apify.models import ApifyRun

        run = ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=source_connection.brand_id,
            status=ApifyRunStatus.SUCCEEDED,
        )

        result = check_source_freshness(source_connection.id)

        assert result.should_refresh is False
        assert result.cached_run is not None
        assert result.cached_run.id == run.id

    def test_old_succeeded_run_triggers_refresh(self, db, source_connection):
        """Succeeded run older than TTL should trigger refresh."""
        from kairo.integrations.apify.models import ApifyRun

        # Create an old run (manually set created_at)
        run = ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=source_connection.brand_id,
            status=ApifyRunStatus.SUCCEEDED,
        )
        # Update created_at to be 30 hours ago
        ApifyRun.objects.filter(id=run.id).update(
            created_at=timezone.now() - timedelta(hours=30)
        )

        result = check_source_freshness(source_connection.id)

        assert result.should_refresh is True
        assert "stale" in result.reason.lower()

    def test_force_refresh_ignores_fresh_run(self, db, source_connection):
        """force_refresh should ignore fresh cached run."""
        from kairo.integrations.apify.models import ApifyRun

        ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=source_connection.brand_id,
            status=ApifyRunStatus.SUCCEEDED,
        )

        result = check_source_freshness(source_connection.id, force_refresh=True)

        assert result.should_refresh is True
        assert result.cached_run is None
        assert result.reason == "force_refresh=True"

    def test_latest_succeeded_run_used(self, db, source_connection):
        """Should use the most recent succeeded run."""
        from kairo.integrations.apify.models import ApifyRun

        # Create an old succeeded run
        old_run = ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=source_connection.brand_id,
            status=ApifyRunStatus.SUCCEEDED,
        )
        ApifyRun.objects.filter(id=old_run.id).update(
            created_at=timezone.now() - timedelta(hours=30)
        )

        # Create a fresh succeeded run
        fresh_run = ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=source_connection.brand_id,
            status=ApifyRunStatus.SUCCEEDED,
        )

        result = check_source_freshness(source_connection.id)

        assert result.should_refresh is False
        assert result.cached_run.id == fresh_run.id


@pytest.mark.db
class TestAnySourceStaleDB:
    """Database tests for any_source_stale()."""

    @pytest.fixture
    def brand(self, db):
        """Create a test brand."""
        from kairo.core.models import Brand, Tenant
        tenant = Tenant.objects.create(name="Test Tenant")
        return Brand.objects.create(tenant=tenant, name="Test Brand")

    def test_returns_true_when_no_sources(self, brand):
        """Should return False when brand has no source connections."""
        result = any_source_stale(brand.id)
        # No sources = nothing stale
        assert result is False

    def test_returns_true_when_source_has_no_runs(self, db, brand):
        """Should return True when a source has no cached runs."""
        from kairo.brandbrain.models import SourceConnection

        SourceConnection.objects.create(
            brand=brand,
            platform="instagram",
            capability="posts",
            identifier="https://instagram.com/test/",
            is_enabled=True,
        )

        result = any_source_stale(brand.id)
        assert result is True

    def test_returns_false_when_all_sources_fresh(self, db, brand):
        """Should return False when all sources have fresh runs."""
        from kairo.brandbrain.models import SourceConnection
        from kairo.integrations.apify.models import ApifyRun

        source = SourceConnection.objects.create(
            brand=brand,
            platform="instagram",
            capability="posts",
            identifier="https://instagram.com/test/",
            is_enabled=True,
        )

        ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source.id,
            brand_id=brand.id,
            status=ApifyRunStatus.SUCCEEDED,
        )

        result = any_source_stale(brand.id)
        assert result is False

    def test_returns_true_when_one_source_stale(self, db, brand):
        """Should return True when at least one source is stale."""
        from kairo.brandbrain.models import SourceConnection
        from kairo.integrations.apify.models import ApifyRun

        # Fresh source
        source1 = SourceConnection.objects.create(
            brand=brand,
            platform="instagram",
            capability="posts",
            identifier="https://instagram.com/test1/",
            is_enabled=True,
        )
        ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source1.id,
            brand_id=brand.id,
            status=ApifyRunStatus.SUCCEEDED,
        )

        # Stale source (no runs)
        SourceConnection.objects.create(
            brand=brand,
            platform="linkedin",
            capability="company_posts",
            identifier="test-company",
            is_enabled=True,
        )

        result = any_source_stale(brand.id)
        assert result is True

    def test_ignores_disabled_sources(self, db, brand):
        """Should ignore disabled source connections."""
        from kairo.brandbrain.models import SourceConnection

        # Disabled source with no runs - should be ignored
        SourceConnection.objects.create(
            brand=brand,
            platform="instagram",
            capability="posts",
            identifier="https://instagram.com/test/",
            is_enabled=False,  # DISABLED
        )

        result = any_source_stale(brand.id)
        # No enabled sources = nothing stale
        assert result is False
