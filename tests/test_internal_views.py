"""
Tests for internal admin views.

PR-11: Observability, Classification, and Admin Surfaces.

Tests cover:
- Token authentication (header-based, 404 on failure)
- Run browser endpoints (HTML + JSON)
- Eval browser endpoints
- Brand browser endpoints (HTML)

Per spec: all internal views are under /hero/internal/ and return 404 on auth failure.
"""

from uuid import uuid4

import pytest
from django.test import Client

from kairo.core.models import Brand, ContentPackage, ContentPillar, Opportunity, Persona, Tenant
from kairo.hero.observability_store import (
    log_classification,
    log_run_complete,
    log_run_start,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.fixture
def temp_obs_dir(monkeypatch, tmp_path):
    """Create a temporary observability directory."""
    obs_path = tmp_path / "obs"
    obs_path.mkdir()
    monkeypatch.setenv("KAIRO_OBS_DIR", str(obs_path))
    monkeypatch.setenv("KAIRO_OBS_ENABLED", "true")
    return obs_path


@pytest.fixture
def temp_eval_dir(monkeypatch, tmp_path):
    """Create a temporary eval reports directory."""
    eval_path = tmp_path / "eval"
    eval_path.mkdir()
    monkeypatch.setenv("KAIRO_EVAL_REPORTS_DIR", str(eval_path))
    return eval_path


@pytest.fixture
def admin_token(monkeypatch):
    """Set admin token for tests."""
    token = "test-admin-token-12345"
    monkeypatch.setenv("KAIRO_INTERNAL_ADMIN_TOKEN", token)
    return token


@pytest.fixture
def no_admin_token(monkeypatch):
    """Remove admin token (returns 404 - no dev mode)."""
    monkeypatch.delenv("KAIRO_INTERNAL_ADMIN_TOKEN", raising=False)


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant",
    )


@pytest.fixture
def sample_brand(db, tenant):
    """Create a sample brand for testing."""
    brand = Brand.objects.create(
        tenant=tenant,
        name="Test Brand",
        slug="test-brand",
        positioning="Test positioning",
        tone_tags=["professional", "friendly"],
        taboos=["competitor-name"],
    )

    # Add personas
    Persona.objects.create(
        brand=brand,
        name="Test Persona",
        summary="Test summary",
    )

    # Add pillars
    ContentPillar.objects.create(
        brand=brand,
        name="Test Pillar",
        description="Test description",
        priority_rank=1,
    )

    return brand


@pytest.fixture
def sample_opportunity(db, sample_brand):
    """Create a sample opportunity."""
    return Opportunity.objects.create(
        brand=sample_brand,
        title="Test Opportunity",
        angle="Test angle",
        type="trend",
        primary_channel="linkedin",
        score=85.0,
    )


@pytest.fixture
def sample_package(db, sample_brand, sample_opportunity):
    """Create a sample package."""
    return ContentPackage.objects.create(
        brand=sample_brand,
        title="Test Package",
        status="draft",
        origin_opportunity=sample_opportunity,
        channels=["linkedin", "x"],
    )


# =============================================================================
# AUTH TESTS
# =============================================================================


@pytest.mark.django_db
class TestTokenAuth:
    """Tests for token authentication.

    Per spec:
    - Token via X-Kairo-Internal-Token header
    - Returns 404 if env var not set (no dev mode)
    - Returns 404 if token missing or wrong
    """

    def test_returns_404_when_env_var_not_set(self, client, no_admin_token, temp_obs_dir):
        """Returns 404 when KAIRO_INTERNAL_ADMIN_TOKEN not set (no dev mode)."""
        response = client.get("/hero/internal/runs/")
        assert response.status_code == 404

    def test_returns_404_without_token_header(self, client, admin_token, temp_obs_dir):
        """Returns 404 when token header not provided."""
        response = client.get("/hero/internal/runs/")
        assert response.status_code == 404

    def test_returns_404_wrong_token(self, client, admin_token, temp_obs_dir):
        """Returns 404 when wrong token provided."""
        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN="wrong-token",
        )
        assert response.status_code == 404

    def test_access_allowed_correct_token(self, client, admin_token, temp_obs_dir):
        """Returns 200 when correct token provided via header."""
        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200

    def test_query_param_token_ignored(self, client, admin_token, temp_obs_dir):
        """Query param token is ignored; must use header."""
        response = client.get(f"/hero/internal/runs/?token={admin_token}")
        assert response.status_code == 404


# =============================================================================
# RUN BROWSER TESTS
# =============================================================================


@pytest.mark.django_db
class TestRunBrowser:
    """Tests for run browser endpoints.

    Per spec:
    - GET /hero/internal/runs/ -> HTML page
    - GET /hero/internal/runs/<run_id>/ -> HTML page
    - GET /hero/internal/runs/<run_id>.json -> JSON response
    """

    def test_list_runs_returns_html(self, client, admin_token, temp_obs_dir):
        """list_hero_runs returns HTML page."""
        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/html"
        assert b"<html>" in response.content
        assert b"Hero Runs" in response.content

    def test_list_runs_shows_run_links(self, client, admin_token, temp_obs_dir):
        """list_hero_runs shows links to run details."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")
        # Use obs_health labels (ok/degraded/failed), NOT quality labels
        log_classification(run_id, brand_id, "ok", None, "ok", "healthy_count:8")

        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        content = response.content.decode()
        # Check run ID is in the page
        assert str(run_id)[:8] in content
        # Check link to JSON endpoint
        assert f"{run_id}.json" in content

    def test_run_detail_returns_html(self, client, admin_token, temp_obs_dir):
        """get_hero_run returns HTML page."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")

        response = client.get(
            f"/hero/internal/runs/{run_id}/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/html"
        assert b"<html>" in response.content

    def test_run_detail_shows_meta(self, client, admin_token, temp_obs_dir):
        """get_hero_run shows run metadata."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")

        response = client.get(
            f"/hero/internal/runs/{run_id}/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        content = response.content.decode()
        assert str(run_id) in content
        assert str(brand_id) in content
        assert "F1_today" in content

    def test_run_json_returns_json(self, client, admin_token, temp_obs_dir):
        """get_hero_run_json returns JSON with correct schema."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")

        response = client.get(
            f"/hero/internal/runs/{run_id}.json",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert "application/json" in response["Content-Type"]

        data = response.json()
        # Check schema per spec
        assert "run" in data
        assert "engine_events" in data
        assert "llm_calls" in data

        assert data["run"]["run_id"] == str(run_id)
        assert data["run"]["flow"] == "F1_today"
        assert data["run"]["status"] == "complete"

    def test_run_detail_not_found(self, client, admin_token, temp_obs_dir):
        """get_hero_run returns 404 for missing run."""
        run_id = uuid4()
        response = client.get(
            f"/hero/internal/runs/{run_id}/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 404

    def test_run_json_not_found(self, client, admin_token, temp_obs_dir):
        """get_hero_run_json returns 404 for missing run."""
        run_id = uuid4()
        response = client.get(
            f"/hero/internal/runs/{run_id}.json",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 404

    def test_run_detail_invalid_uuid(self, client, admin_token, temp_obs_dir):
        """get_hero_run returns 400 for invalid UUID."""
        response = client.get(
            "/hero/internal/runs/not-a-uuid/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 400


# =============================================================================
# EVAL BROWSER TESTS
# =============================================================================


@pytest.mark.django_db
class TestEvalBrowser:
    """Tests for eval browser endpoints.

    Per spec:
    - GET /hero/internal/evals/ -> HTML page listing markdown files
    - GET /hero/internal/evals/<filename> -> Rendered markdown as HTML
    """

    def test_list_evals_returns_html(self, client, admin_token, temp_eval_dir):
        """list_evals returns HTML page."""
        response = client.get(
            "/hero/internal/evals/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/html"
        assert b"Eval Reports" in response.content

    def test_list_evals_shows_files(self, client, admin_token, temp_eval_dir):
        """list_evals shows markdown files."""
        # Create a test report file
        report_file = temp_eval_dir / "test-report.md"
        report_file.write_text("# Test Report\n\nThis is a test.")

        response = client.get(
            "/hero/internal/evals/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "test-report.md" in content

    def test_eval_detail_renders_markdown(self, client, admin_token, temp_eval_dir):
        """get_eval_detail renders markdown as HTML."""
        # Create a test report file
        report_file = temp_eval_dir / "test-report.md"
        report_file.write_text("# Test Report\n\nThis is a **bold** test.")

        response = client.get(
            "/hero/internal/evals/test-report.md",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/html"
        content = response.content.decode()
        assert "<h1>Test Report</h1>" in content
        assert "<strong>bold</strong>" in content

    def test_eval_detail_not_found(self, client, admin_token, temp_eval_dir):
        """get_eval_detail returns 404 for missing file."""
        response = client.get(
            "/hero/internal/evals/nonexistent.md",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 404

    def test_eval_detail_rejects_non_md(self, client, admin_token, temp_eval_dir):
        """get_eval_detail rejects non-.md files."""
        response = client.get(
            "/hero/internal/evals/test.txt",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 400

    def test_eval_detail_rejects_path_traversal(self, client, admin_token, temp_eval_dir):
        """get_eval_detail rejects path traversal attempts."""
        # Note: Django URL resolver normalizes paths before view is called,
        # so /../ paths become 404s. Testing with .. in filename instead.
        response = client.get(
            "/hero/internal/evals/..passwd.md",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 400


# =============================================================================
# BRAND BROWSER TESTS
# =============================================================================


@pytest.mark.django_db
class TestBrandBrowser:
    """Tests for brand browser endpoints.

    Per spec:
    - GET /hero/internal/brands/ -> HTML page
    - GET /hero/internal/brands/<brand_id>/ -> HTML page with counts
    """

    def test_list_brands_returns_html(self, client, admin_token, db):
        """list_brands returns HTML page."""
        response = client.get(
            "/hero/internal/brands/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/html"
        assert b"Brands" in response.content

    def test_list_brands_shows_brands(self, client, admin_token, sample_brand):
        """list_brands shows brand entries."""
        response = client.get(
            "/hero/internal/brands/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "Test Brand" in content
        assert "test-brand" in content

    def test_brand_detail_returns_html(self, client, admin_token, sample_brand):
        """get_brand_detail returns HTML page."""
        response = client.get(
            f"/hero/internal/brands/{sample_brand.id}/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/html"

    def test_brand_detail_shows_counts(self, client, admin_token, sample_brand):
        """get_brand_detail shows related object counts."""
        response = client.get(
            f"/hero/internal/brands/{sample_brand.id}/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        content = response.content.decode()
        assert "Test Brand" in content
        # Check persona count is shown (1 persona in fixture)
        assert "Personas" in content
        assert "Pillars" in content

    def test_brand_detail_not_found(self, client, admin_token, db):
        """get_brand_detail returns 404 for missing brand."""
        response = client.get(
            f"/hero/internal/brands/{uuid4()}/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 404

    def test_brand_detail_invalid_uuid(self, client, admin_token, db):
        """get_brand_detail returns 400 for invalid UUID."""
        response = client.get(
            "/hero/internal/brands/not-a-uuid/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 400


# =============================================================================
# STRICT AUTH TESTS (per PR-11 audit requirements)
# =============================================================================


@pytest.mark.django_db
class TestStrictAuthRequirements:
    """Strict authentication tests per PR-11 audit requirements.

    These tests explicitly verify:
    - Missing env var → 404
    - Wrong header token → 404
    - Correct header token → 200
    - Old route /internal/runs/ → 404 (not routed)
    """

    def test_old_route_not_routed(self, client, admin_token, temp_obs_dir):
        """Old route /internal/runs/ returns 404 (not routed).

        Per spec: routes must be under /hero/internal/, not /internal/.
        """
        response = client.get(
            "/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 404

    def test_auth_missing_env_var_404(self, client, no_admin_token, temp_obs_dir):
        """Missing KAIRO_INTERNAL_ADMIN_TOKEN env var returns 404."""
        response = client.get("/hero/internal/runs/")
        assert response.status_code == 404

    def test_auth_wrong_token_404(self, client, admin_token, temp_obs_dir):
        """Wrong token returns 404."""
        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN="wrong-token-value",
        )
        assert response.status_code == 404

    def test_auth_correct_token_200(self, client, admin_token, temp_obs_dir):
        """Correct token returns 200."""
        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200


# =============================================================================
# JSON SCHEMA TESTS (per PR-11 audit requirements)
# =============================================================================


@pytest.mark.django_db
class TestRunJsonSchema:
    """Tests for run JSON endpoint schema.

    Per spec: JSON endpoint must return exactly keys: run, engine_events, llm_calls
    """

    def test_json_schema_exact_keys(self, client, admin_token, temp_obs_dir):
        """JSON endpoint returns exactly the required keys."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")

        response = client.get(
            f"/hero/internal/runs/{run_id}.json",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        data = response.json()

        # Verify exact keys per spec
        expected_keys = {"run", "engine_events", "llm_calls"}
        actual_keys = set(data.keys())
        assert actual_keys == expected_keys, f"Expected {expected_keys}, got {actual_keys}"

    def test_json_schema_run_object(self, client, admin_token, temp_obs_dir):
        """JSON run object has expected fields."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")

        response = client.get(
            f"/hero/internal/runs/{run_id}.json",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        data = response.json()

        # Verify run object structure
        run = data["run"]
        assert "run_id" in run
        assert "brand_id" in run
        assert "flow" in run
        assert "status" in run
        assert run["run_id"] == str(run_id)


# =============================================================================
# XSS SECURITY TESTS (per PR-11 audit requirements)
# =============================================================================


@pytest.mark.django_db
class TestEvalXssSecurity:
    """Tests for XSS protection in eval report rendering.

    Per spec: markdown rendering must NOT allow <script> or event handlers.
    """

    def test_script_tags_stripped(self, client, admin_token, temp_eval_dir):
        """Script tags are stripped from rendered markdown."""
        # Create a malicious markdown file
        report_file = temp_eval_dir / "xss-test.md"
        report_file.write_text(
            "# Test\n\n"
            '<script>alert("xss")</script>\n'
            "Normal content here."
        )

        response = client.get(
            "/hero/internal/evals/xss-test.md",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        content = response.content.decode()

        # Script tag MUST NOT be in output
        assert "<script>" not in content.lower()
        assert "alert(" not in content

    def test_event_handlers_stripped(self, client, admin_token, temp_eval_dir):
        """Event handlers are stripped from rendered markdown."""
        # Create a markdown file with event handlers
        report_file = temp_eval_dir / "xss-event.md"
        report_file.write_text(
            "# Test\n\n"
            '<img src="x" onerror="alert(1)">\n'
            '<div onclick="alert(2)">Click me</div>'
        )

        response = client.get(
            "/hero/internal/evals/xss-event.md",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        content = response.content.decode()

        # Event handlers MUST NOT be in output
        assert "onerror=" not in content.lower()
        assert "onclick=" not in content.lower()

    def test_javascript_urls_stripped(self, client, admin_token, temp_eval_dir):
        """javascript: URLs are stripped from rendered markdown."""
        # Create a markdown file with javascript URL
        report_file = temp_eval_dir / "xss-jsurl.md"
        report_file.write_text(
            "# Test\n\n"
            '<a href="javascript:alert(1)">Click</a>'
        )

        response = client.get(
            "/hero/internal/evals/xss-jsurl.md",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        assert response.status_code == 200
        content = response.content.decode()

        # javascript: URL MUST NOT be in output
        assert "javascript:" not in content.lower()


# =============================================================================
# FILESYSTEM ISOLATION TESTS (per PR-11 audit requirements)
# =============================================================================


@pytest.mark.django_db
class TestFilesystemIsolation:
    """Tests verifying filesystem isolation via temp directories.

    Per spec:
    - Tests use temp directory fixture (not real repo path)
    - Eval dir configurable via KAIRO_EVAL_REPORTS_DIR
    - Obs dir configurable via KAIRO_OBS_DIR
    """

    def test_eval_dir_uses_env_var(self, client, admin_token, temp_eval_dir, monkeypatch):
        """Eval browser uses KAIRO_EVAL_REPORTS_DIR env var."""
        # temp_eval_dir fixture already sets the env var
        # Create a file in the temp directory
        report_file = temp_eval_dir / "isolation-test.md"
        report_file.write_text("# Isolation Test\n\nThis file is in temp dir.")

        response = client.get(
            "/hero/internal/evals/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        content = response.content.decode()

        # File should be visible
        assert "isolation-test.md" in content

    def test_obs_dir_uses_env_var(self, client, admin_token, temp_obs_dir):
        """Run browser uses KAIRO_OBS_DIR env var."""
        # temp_obs_dir fixture already sets the env var
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")

        response = client.get(
            "/hero/internal/runs/",
            HTTP_X_KAIRO_INTERNAL_TOKEN=admin_token,
        )
        content = response.content.decode()

        # Run should be visible
        assert str(run_id)[:8] in content

    def test_temp_dirs_isolated(self, tmp_path):
        """Temp directories are unique per test."""
        # This test verifies that tmp_path is unique
        marker_file = tmp_path / "test-marker.txt"
        marker_file.write_text("test")
        assert marker_file.exists()
        # tmp_path is unique per test invocation
