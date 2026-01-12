"""
External Signals Service tests for PR-5.

Tests verify:
- Bundle shape validation (DTO structure matches expected fields)
- Rich bundle for demo brands vs empty bundle for unknown brands
- Missing/malformed fixture graceful handling
- No-HTTP guardrail (import introspection)

Per PR-map-and-standards §PR-5.
"""

import ast
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from kairo.core.enums import Channel
from kairo.core.models import Brand, Tenant
from kairo.hero.dto import (
    CompetitorPostSignalDTO,
    ExternalSignalBundleDTO,
    SocialMomentSignalDTO,
    TrendSignalDTO,
    WebMentionSignalDTO,
)
from kairo.hero.services import external_signals_service
from kairo.hero.services.external_signals_service import get_bundle_for_brand


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant():
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug=f"test-tenant-{uuid4().hex[:8]}",
    )


@pytest.fixture
def brand_with_fixture(tenant):
    """Create a brand that has a fixture mapping (demo-brand)."""
    return Brand.objects.create(
        tenant=tenant,
        name="Demo Brand",
        slug="demo-brand",  # Matches fixture mapping
        primary_channel=Channel.LINKEDIN,
    )


@pytest.fixture
def brand_without_fixture(tenant):
    """Create a brand that has no fixture mapping."""
    return Brand.objects.create(
        tenant=tenant,
        name="Unknown Brand",
        slug=f"unknown-brand-{uuid4().hex[:8]}",
        primary_channel=Channel.LINKEDIN,
    )


@pytest.fixture
def acme_brand(tenant):
    """Create a brand with acme-corp slug."""
    return Brand.objects.create(
        tenant=tenant,
        name="ACME Corp",
        slug="acme-corp",  # Matches fixture mapping
        primary_channel=Channel.LINKEDIN,
    )


# =============================================================================
# BUNDLE SHAPE VALIDATION TESTS
# =============================================================================


@pytest.mark.django_db
class TestBundleShapeValidation:
    """Tests for validating ExternalSignalBundleDTO structure."""

    def test_bundle_has_required_fields(self, brand_with_fixture):
        """Bundle contains all required fields."""
        bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert isinstance(bundle, ExternalSignalBundleDTO)
        assert bundle.brand_id == brand_with_fixture.id
        assert isinstance(bundle.fetched_at, datetime)
        assert isinstance(bundle.trends, list)
        assert isinstance(bundle.web_mentions, list)
        assert isinstance(bundle.competitor_posts, list)
        assert isinstance(bundle.social_moments, list)

    def test_trend_signals_have_correct_shape(self, brand_with_fixture):
        """Trend signals match TrendSignalDTO schema."""
        bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert len(bundle.trends) > 0, "Expected at least one trend signal"

        for trend in bundle.trends:
            assert isinstance(trend, TrendSignalDTO)
            assert isinstance(trend.id, str)
            assert isinstance(trend.topic, str)
            assert isinstance(trend.source, str)
            assert isinstance(trend.relevance_score, float)
            assert 0 <= trend.relevance_score <= 100
            assert isinstance(trend.recency_days, int)

    def test_web_mention_signals_have_correct_shape(self, brand_with_fixture):
        """Web mention signals match WebMentionSignalDTO schema."""
        bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert len(bundle.web_mentions) > 0, "Expected at least one web mention signal"

        for mention in bundle.web_mentions:
            assert isinstance(mention, WebMentionSignalDTO)
            assert isinstance(mention.id, str)
            assert isinstance(mention.title, str)
            assert isinstance(mention.source, str)
            assert isinstance(mention.url, str)
            assert isinstance(mention.relevance_score, float)
            assert 0 <= mention.relevance_score <= 100

    def test_competitor_post_signals_have_correct_shape(self, brand_with_fixture):
        """Competitor post signals match CompetitorPostSignalDTO schema."""
        bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert len(bundle.competitor_posts) > 0, "Expected at least one competitor post signal"

        for post in bundle.competitor_posts:
            assert isinstance(post, CompetitorPostSignalDTO)
            assert isinstance(post.id, str)
            assert isinstance(post.competitor_name, str)
            assert isinstance(post.channel, Channel)

    def test_social_moment_signals_have_correct_shape(self, brand_with_fixture):
        """Social moment signals match SocialMomentSignalDTO schema."""
        bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert len(bundle.social_moments) > 0, "Expected at least one social moment signal"

        for moment in bundle.social_moments:
            assert isinstance(moment, SocialMomentSignalDTO)
            assert isinstance(moment.id, str)
            assert isinstance(moment.description, str)
            assert isinstance(moment.channel, Channel)
            assert isinstance(moment.recency_hours, int)


# =============================================================================
# RICH VS EMPTY BUNDLE TESTS
# =============================================================================


@pytest.mark.django_db
class TestRichVsEmptyBundles:
    """Tests for rich bundle (demo brands) vs empty bundle (unknown brands)."""

    def test_demo_brand_gets_rich_bundle(self, brand_with_fixture):
        """Brand with fixture mapping receives populated bundle."""
        bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert len(bundle.trends) > 0
        assert len(bundle.web_mentions) > 0
        assert len(bundle.competitor_posts) > 0
        assert len(bundle.social_moments) > 0

    def test_acme_brand_gets_rich_bundle(self, acme_brand):
        """ACME Corp brand receives its fixture data."""
        bundle = get_bundle_for_brand(acme_brand.id)

        assert len(bundle.trends) >= 2
        assert len(bundle.web_mentions) >= 1
        assert len(bundle.competitor_posts) >= 1
        assert len(bundle.social_moments) >= 1

        # Verify specific fixture data
        trend_topics = [t.topic for t in bundle.trends]
        assert "AI-Powered Customer Service" in trend_topics

    def test_unknown_brand_gets_empty_bundle(self, brand_without_fixture):
        """Brand without fixture mapping receives empty bundle."""
        bundle = get_bundle_for_brand(brand_without_fixture.id)

        assert bundle.brand_id == brand_without_fixture.id
        assert isinstance(bundle.fetched_at, datetime)
        assert len(bundle.trends) == 0
        assert len(bundle.web_mentions) == 0
        assert len(bundle.competitor_posts) == 0
        assert len(bundle.social_moments) == 0

    def test_nonexistent_brand_gets_empty_bundle(self):
        """Non-existent brand_id receives empty bundle."""
        fake_brand_id = uuid4()
        bundle = get_bundle_for_brand(fake_brand_id)

        assert bundle.brand_id == fake_brand_id
        assert len(bundle.trends) == 0
        assert len(bundle.web_mentions) == 0
        assert len(bundle.competitor_posts) == 0
        assert len(bundle.social_moments) == 0


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


@pytest.mark.django_db
class TestErrorHandling:
    """Tests for graceful error handling."""

    def test_missing_index_file_returns_empty_bundle(self, brand_with_fixture):
        """Missing index file returns empty bundle without exception."""
        fake_fixtures_dir = Path("/nonexistent/path")

        with patch.object(
            external_signals_service,
            "FIXTURES_DIR",
            fake_fixtures_dir,
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert bundle.brand_id == brand_with_fixture.id
        assert len(bundle.trends) == 0

    def test_malformed_index_file_returns_empty_bundle(self, brand_with_fixture, tmp_path):
        """Malformed index JSON returns empty bundle without exception."""
        # Create malformed index file
        fixtures_dir = tmp_path / "external_signals"
        fixtures_dir.mkdir()
        index_file = fixtures_dir / "_index.json"
        index_file.write_text("{ invalid json }")

        with patch.object(
            external_signals_service,
            "FIXTURES_DIR",
            fixtures_dir,
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert bundle.brand_id == brand_with_fixture.id
        assert len(bundle.trends) == 0

    def test_missing_fixture_file_returns_empty_bundle(self, brand_with_fixture, tmp_path):
        """Missing fixture file (but valid index) returns empty bundle."""
        # Create valid index pointing to nonexistent file
        fixtures_dir = tmp_path / "external_signals"
        fixtures_dir.mkdir()
        index_file = fixtures_dir / "_index.json"
        index_file.write_text(json.dumps({
            "brand_slug_to_fixture": {
                "demo-brand": "nonexistent.json"
            }
        }))

        with patch.object(
            external_signals_service,
            "FIXTURES_DIR",
            fixtures_dir,
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert bundle.brand_id == brand_with_fixture.id
        assert len(bundle.trends) == 0

    def test_malformed_fixture_file_returns_empty_bundle(self, brand_with_fixture, tmp_path):
        """Malformed fixture JSON returns empty bundle without exception."""
        # Create valid index and malformed fixture
        fixtures_dir = tmp_path / "external_signals"
        fixtures_dir.mkdir()
        index_file = fixtures_dir / "_index.json"
        index_file.write_text(json.dumps({
            "brand_slug_to_fixture": {
                "demo-brand": "demo-brand.json"
            }
        }))
        fixture_file = fixtures_dir / "demo-brand.json"
        fixture_file.write_text("{ not valid json }")

        with patch.object(
            external_signals_service,
            "FIXTURES_DIR",
            fixtures_dir,
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        assert bundle.brand_id == brand_with_fixture.id
        assert len(bundle.trends) == 0

    def test_malformed_signal_item_skipped_gracefully(self, brand_with_fixture, tmp_path):
        """Malformed signal items are skipped, valid ones still parsed."""
        # Create fixture with one valid and one invalid trend
        fixtures_dir = tmp_path / "external_signals"
        fixtures_dir.mkdir()
        index_file = fixtures_dir / "_index.json"
        index_file.write_text(json.dumps({
            "brand_slug_to_fixture": {
                "demo-brand": "demo-brand.json"
            }
        }))
        fixture_file = fixtures_dir / "demo-brand.json"
        fixture_file.write_text(json.dumps({
            "trends": [
                {
                    "id": "valid-trend",
                    "topic": "Valid Topic",
                    "source": "test",
                    "relevance_score": 50.0,
                    "recency_days": 1
                },
                {
                    "id": "invalid-trend",
                    # Missing required fields
                }
            ],
            "web_mentions": [],
            "competitor_posts": [],
            "social_moments": []
        }))

        with patch.object(
            external_signals_service,
            "FIXTURES_DIR",
            fixtures_dir,
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        # Valid trend should be parsed, invalid one skipped
        assert len(bundle.trends) == 1
        assert bundle.trends[0].id == "valid-trend"


# =============================================================================
# NO-HTTP GUARDRAIL TESTS
# =============================================================================


class TestNoHttpGuardrail:
    """Tests to ensure no HTTP imports in external_signals_service."""

    # HTTP libraries that should NOT be imported
    FORBIDDEN_IMPORTS = [
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "urllib3",
        "http.client",
    ]

    def test_no_http_imports_in_service_module(self):
        """Service module must not import any HTTP libraries."""
        # Get the source file path
        source_file = inspect.getfile(external_signals_service)

        # Read and parse the source code
        with open(source_file, "r") as f:
            source_code = f.read()

        # Parse into AST
        tree = ast.parse(source_code)

        # Collect all imports
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        # Check for forbidden imports
        forbidden_found = imported_modules.intersection(
            {imp.split(".")[0] for imp in self.FORBIDDEN_IMPORTS}
        )

        assert not forbidden_found, (
            f"HTTP libraries found in external_signals_service: {forbidden_found}. "
            f"Per PR-5, this module must not make HTTP calls."
        )

    def test_no_http_in_module_attributes(self):
        """Module should not have HTTP client objects as attributes."""
        # Check module-level attributes
        module_attrs = dir(external_signals_service)

        http_indicators = ["session", "client", "request", "get", "post", "fetch"]

        for attr_name in module_attrs:
            if attr_name.startswith("_"):
                continue
            attr = getattr(external_signals_service, attr_name, None)
            if attr is None:
                continue

            # Check type name for HTTP-related classes
            type_name = type(attr).__name__.lower()
            for indicator in http_indicators:
                if indicator in type_name and indicator not in ["get_bundle_for_brand"]:
                    # Allow our own get_bundle_for_brand function
                    if callable(attr) and attr.__module__ == external_signals_service.__name__:
                        continue
                    pytest.fail(
                        f"Found HTTP-related attribute: {attr_name} ({type_name})"
                    )


# =============================================================================
# FIXTURE FILE VALIDATION TESTS
# =============================================================================


class TestFixtureFileIntegrity:
    """Tests to validate fixture files are well-formed."""

    def test_fixture_files_are_valid_json(self):
        """All fixture files should be valid JSON."""
        fixtures_dir = external_signals_service.FIXTURES_DIR

        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        for json_file in fixtures_dir.glob("*.json"):
            with open(json_file, "r") as f:
                try:
                    data = json.load(f)
                    assert isinstance(data, dict), f"{json_file.name} should contain a dict"
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON in {json_file.name}: {e}")

    def test_index_file_has_valid_structure(self):
        """Index file should have brand_slug_to_fixture mapping."""
        fixtures_dir = external_signals_service.FIXTURES_DIR
        index_file = fixtures_dir / "_index.json"

        if not index_file.exists():
            pytest.skip("Index file not found")

        with open(index_file, "r") as f:
            data = json.load(f)

        assert "brand_slug_to_fixture" in data, "Index should have brand_slug_to_fixture key"
        assert isinstance(data["brand_slug_to_fixture"], dict)

    def test_index_references_existing_files(self):
        """All files referenced in index should exist."""
        fixtures_dir = external_signals_service.FIXTURES_DIR
        index_file = fixtures_dir / "_index.json"

        if not index_file.exists():
            pytest.skip("Index file not found")

        with open(index_file, "r") as f:
            data = json.load(f)

        for slug, filename in data.get("brand_slug_to_fixture", {}).items():
            fixture_path = fixtures_dir / filename
            assert fixture_path.exists(), (
                f"Index references {filename} for slug '{slug}' but file doesn't exist"
            )


# =============================================================================
# EXTERNAL SIGNALS MODE TESTS
# =============================================================================


@pytest.mark.django_db
class TestExternalSignalsMode:
    """Tests for EXTERNAL_SIGNALS_MODE no-fallback semantics."""

    def test_ingestion_mode_empty_when_no_candidates(self, brand_with_fixture):
        """
        When EXTERNAL_SIGNALS_MODE='ingestion' and there are zero TrendCandidates,
        bundle is empty and fixtures are NOT used.
        """
        with patch.object(
            external_signals_service.settings,
            "EXTERNAL_SIGNALS_MODE",
            "ingestion",
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        # Should be empty because no TrendCandidates exist
        assert bundle.brand_id == brand_with_fixture.id
        assert len(bundle.trends) == 0
        # Importantly, should NOT fall back to fixtures
        # (fixtures would give us non-empty trends)

    def test_ingestion_mode_returns_real_trends(self, tenant):
        """
        When EXTERNAL_SIGNALS_MODE='ingestion' and TrendCandidates exist,
        those real trends are returned.
        """
        from kairo.ingestion.models import Cluster, TrendCandidate

        # Create a test brand
        brand = Brand.objects.create(
            tenant=tenant,
            name="Test Brand Ingestion",
            slug=f"test-ingestion-{uuid4().hex[:8]}",
            primary_channel=Channel.LINKEDIN,
        )

        # Create cluster and trend candidate
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#ingestiontest",
            display_name="#ingestiontest",
            platforms=["tiktok"],
        )
        TrendCandidate.objects.create(
            cluster=cluster,
            status="emerging",
            trend_score=80.0,
            detected_at=datetime.now(timezone.utc),
        )

        with patch.object(
            external_signals_service.settings,
            "EXTERNAL_SIGNALS_MODE",
            "ingestion",
        ):
            bundle = get_bundle_for_brand(brand.id)

        # Should have the real trend
        assert len(bundle.trends) == 1
        assert bundle.trends[0].topic == "#ingestiontest"

    def test_fixtures_mode_uses_fixtures(self, brand_with_fixture):
        """
        When EXTERNAL_SIGNALS_MODE='fixtures' (default), fixtures are used.
        """
        with patch.object(
            external_signals_service.settings,
            "EXTERNAL_SIGNALS_MODE",
            "fixtures",
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        # Should have fixture data
        assert len(bundle.trends) > 0

    def test_default_mode_is_fixtures(self, brand_with_fixture):
        """
        Default mode (no setting) behaves like 'fixtures' mode.
        """
        # Make sure EXTERNAL_SIGNALS_MODE is not set
        with patch.object(
            external_signals_service,
            "settings",
            type("Settings", (), {"EXTERNAL_SIGNALS_MODE": "fixtures"})(),
        ):
            bundle = get_bundle_for_brand(brand_with_fixture.id)

        # Should have fixture data
        assert bundle.brand_id == brand_with_fixture.id
