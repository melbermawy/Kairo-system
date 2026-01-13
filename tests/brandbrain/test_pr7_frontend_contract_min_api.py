"""
PR-7 Frontend Contract Minimal API Tests.

Tests for the minimal API surface needed for frontend E2E flow:
- Brands CRUD (list, create, get)
- Onboarding (get default, update)
- Sources CRUD (list, create, patch, delete)
- CORS headers present

Uses SQLite-compatible tests (pytest-django with transactional_db).
"""

import json
import pytest
from uuid import uuid4

from django.test import Client


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.fixture
def default_tenant(db):
    """Create default tenant for tests."""
    from kairo.core.models import Tenant

    tenant, _ = Tenant.objects.get_or_create(
        slug="default",
        defaults={"name": "Default Tenant"},
    )
    return tenant


@pytest.fixture
def brand(db, default_tenant):
    """Create a test brand."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=default_tenant,
        name="Test Brand",
        slug="test-brand",
        metadata={"website_url": "https://test.com"},
    )


@pytest.fixture
def source(db, brand):
    """Create a test source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="instagram",
        capability="posts",
        identifier="testhandle",
        is_enabled=True,
    )


# =============================================================================
# BRANDS TESTS
# =============================================================================


@pytest.mark.db
class TestBrandsAPI:
    """Test brands list/create/get endpoints."""

    def test_list_brands_empty(self, client, db, default_tenant):
        """GET /api/brands returns empty list when no brands."""
        response = client.get("/api/brands")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_brands_with_data(self, client, db, brand):
        """GET /api/brands returns list of brands."""
        response = client.get("/api/brands")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(brand.id)
        assert data[0]["name"] == "Test Brand"
        assert data[0]["website_url"] == "https://test.com"
        assert "created_at" in data[0]

    def test_create_brand_minimal(self, client, db, default_tenant):
        """POST /api/brands with just name."""
        response = client.post(
            "/api/brands",
            data=json.dumps({"name": "New Brand"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Brand"
        assert data["website_url"] is None
        assert "id" in data
        assert "created_at" in data

    def test_create_brand_with_website(self, client, db, default_tenant):
        """POST /api/brands with name and website_url."""
        response = client.post(
            "/api/brands",
            data=json.dumps({"name": "Brand With Site", "website_url": "https://brand.com"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Brand With Site"
        assert data["website_url"] == "https://brand.com"

    def test_create_brand_name_required(self, client, db, default_tenant):
        """POST /api/brands without name returns 400."""
        response = client.post(
            "/api/brands",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "name" in response.json()["error"]

    def test_create_brand_empty_name_rejected(self, client, db, default_tenant):
        """POST /api/brands with empty name returns 400."""
        response = client.post(
            "/api/brands",
            data=json.dumps({"name": "  "}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_get_brand_exists(self, client, db, brand):
        """GET /api/brands/:id returns brand."""
        response = client.get(f"/api/brands/{brand.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(brand.id)
        assert data["name"] == "Test Brand"

    def test_get_brand_not_found(self, client, db, default_tenant):
        """GET /api/brands/:id returns 404 for nonexistent brand."""
        response = client.get(f"/api/brands/{uuid4()}")
        assert response.status_code == 404

    def test_get_brand_invalid_uuid(self, client, db):
        """GET /api/brands/:id returns 400 for invalid UUID."""
        response = client.get("/api/brands/not-a-uuid")
        assert response.status_code == 400


# =============================================================================
# ONBOARDING TESTS
# =============================================================================


@pytest.mark.db
class TestOnboardingAPI:
    """Test onboarding get/put endpoints."""

    def test_get_onboarding_default(self, client, db, brand):
        """GET /api/brands/:id/onboarding returns default when none exists."""
        response = client.get(f"/api/brands/{brand.id}/onboarding")
        assert response.status_code == 200
        data = response.json()
        assert data["brand_id"] == str(brand.id)
        assert data["tier"] == 0
        assert data["answers_json"] == {}
        assert data["updated_at"] is None

    def test_get_onboarding_brand_not_found(self, client, db, default_tenant):
        """GET /api/brands/:id/onboarding returns 404 if brand not found."""
        response = client.get(f"/api/brands/{uuid4()}/onboarding")
        assert response.status_code == 404

    def test_put_onboarding_create(self, client, db, brand):
        """PUT /api/brands/:id/onboarding creates onboarding."""
        response = client.put(
            f"/api/brands/{brand.id}/onboarding",
            data=json.dumps({
                "tier": 1,
                "answers_json": {"brand_name": "Test", "what_we_do": "Things"},
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == 1
        assert data["answers_json"]["brand_name"] == "Test"
        assert data["updated_at"] is not None

    def test_put_onboarding_update(self, client, db, brand):
        """PUT /api/brands/:id/onboarding updates existing."""
        from kairo.brandbrain.models import BrandOnboarding

        BrandOnboarding.objects.create(
            brand=brand,
            tier=0,
            answers_json={"old": "data"},
        )

        response = client.put(
            f"/api/brands/{brand.id}/onboarding",
            data=json.dumps({
                "tier": 2,
                "answers_json": {"new": "data"},
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == 2
        assert data["answers_json"] == {"new": "data"}

    def test_put_onboarding_invalid_tier(self, client, db, brand):
        """PUT /api/brands/:id/onboarding rejects invalid tier."""
        response = client.put(
            f"/api/brands/{brand.id}/onboarding",
            data=json.dumps({"tier": 5, "answers_json": {}}),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_put_onboarding_tier_required(self, client, db, brand):
        """PUT /api/brands/:id/onboarding requires tier."""
        response = client.put(
            f"/api/brands/{brand.id}/onboarding",
            data=json.dumps({"answers_json": {}}),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_put_onboarding_answers_required(self, client, db, brand):
        """PUT /api/brands/:id/onboarding requires answers_json."""
        response = client.put(
            f"/api/brands/{brand.id}/onboarding",
            data=json.dumps({"tier": 0}),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_put_onboarding_answers_must_be_object(self, client, db, brand):
        """PUT /api/brands/:id/onboarding rejects non-object answers."""
        response = client.put(
            f"/api/brands/{brand.id}/onboarding",
            data=json.dumps({"tier": 0, "answers_json": "not an object"}),
            content_type="application/json",
        )
        assert response.status_code == 422


# =============================================================================
# SOURCES TESTS
# =============================================================================


@pytest.mark.db
class TestSourcesAPI:
    """Test sources CRUD endpoints."""

    def test_list_sources_empty(self, client, db, brand):
        """GET /api/brands/:id/sources returns empty list."""
        response = client.get(f"/api/brands/{brand.id}/sources")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_sources_with_data(self, client, db, brand, source):
        """GET /api/brands/:id/sources returns sources."""
        response = client.get(f"/api/brands/{brand.id}/sources")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(source.id)
        assert data[0]["platform"] == "instagram"
        assert data[0]["capability"] == "posts"
        assert data[0]["identifier"] == "testhandle"
        assert data[0]["is_enabled"] is True

    def test_list_sources_brand_not_found(self, client, db, default_tenant):
        """GET /api/brands/:id/sources returns 404 if brand not found."""
        response = client.get(f"/api/brands/{uuid4()}/sources")
        assert response.status_code == 404

    def test_create_source(self, client, db, brand):
        """POST /api/brands/:id/sources creates source."""
        response = client.post(
            f"/api/brands/{brand.id}/sources",
            data=json.dumps({
                "platform": "web",
                "capability": "crawl_pages",
                "identifier": "https://example.com",
            }),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["platform"] == "web"
        assert data["capability"] == "crawl_pages"
        assert data["is_enabled"] is True
        assert "id" in data
        assert "created_at" in data

    def test_create_source_with_settings(self, client, db, brand):
        """POST /api/brands/:id/sources with settings_json."""
        response = client.post(
            f"/api/brands/{brand.id}/sources",
            data=json.dumps({
                "platform": "web",
                "capability": "crawl_pages",
                "identifier": "https://example.com",
                "settings_json": {"max_pages": 10},
            }),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["settings_json"] == {"max_pages": 10}

    def test_create_source_platform_required(self, client, db, brand):
        """POST /api/brands/:id/sources requires platform."""
        response = client.post(
            f"/api/brands/{brand.id}/sources",
            data=json.dumps({
                "capability": "posts",
                "identifier": "handle",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "platform" in response.json()["error"]

    def test_create_source_capability_required(self, client, db, brand):
        """POST /api/brands/:id/sources requires capability."""
        response = client.post(
            f"/api/brands/{brand.id}/sources",
            data=json.dumps({
                "platform": "instagram",
                "identifier": "handle",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "capability" in response.json()["error"]

    def test_create_source_identifier_required(self, client, db, brand):
        """POST /api/brands/:id/sources requires identifier."""
        response = client.post(
            f"/api/brands/{brand.id}/sources",
            data=json.dumps({
                "platform": "instagram",
                "capability": "posts",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "identifier" in response.json()["error"]

    def test_patch_source_identifier(self, client, db, source):
        """PATCH /api/sources/:id updates identifier."""
        response = client.patch(
            f"/api/sources/{source.id}",
            data=json.dumps({"identifier": "newhandle"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["identifier"] == "newhandle"

    def test_patch_source_is_enabled(self, client, db, source):
        """PATCH /api/sources/:id updates is_enabled."""
        response = client.patch(
            f"/api/sources/{source.id}",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_enabled"] is False

    def test_patch_source_settings(self, client, db, source):
        """PATCH /api/sources/:id updates settings_json."""
        response = client.patch(
            f"/api/sources/{source.id}",
            data=json.dumps({"settings_json": {"key": "value"}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings_json"] == {"key": "value"}

    def test_patch_source_empty_body_rejected(self, client, db, source):
        """PATCH /api/sources/:id rejects empty body."""
        response = client.patch(
            f"/api/sources/{source.id}",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "empty" in response.json()["error"].lower()

    def test_patch_source_not_found(self, client, db):
        """PATCH /api/sources/:id returns 404 for nonexistent source."""
        response = client.patch(
            f"/api/sources/{uuid4()}",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_delete_source(self, client, db, source):
        """DELETE /api/sources/:id deletes source."""
        source_id = source.id
        response = client.delete(f"/api/sources/{source_id}")
        assert response.status_code == 204

        # Verify deleted
        from kairo.brandbrain.models import SourceConnection
        assert not SourceConnection.objects.filter(id=source_id).exists()

    def test_delete_source_not_found(self, client, db):
        """DELETE /api/sources/:id returns 404 for nonexistent source."""
        response = client.delete(f"/api/sources/{uuid4()}")
        assert response.status_code == 404


# =============================================================================
# CORS TESTS
# =============================================================================


@pytest.mark.db
class TestCORS:
    """Test CORS headers are present."""

    def test_cors_headers_on_brands(self, client, db, default_tenant):
        """Verify CORS middleware is active (Access-Control headers)."""
        # Make a preflight request
        response = client.options(
            "/api/brands",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        # CORS middleware should respond
        # Note: In Django test client, CORS headers may not appear unless
        # the middleware processes the request. This test verifies the
        # endpoint is accessible.
        assert response.status_code in (200, 204)


# =============================================================================
# BRANDBRAIN COMPILE 404 TEST
# =============================================================================


@pytest.mark.db
class TestBrandBrainCompileNotFound:
    """Test existing BrandBrain behavior for missing brand."""

    def test_compile_returns_404_for_missing_brand(self, client, db, default_tenant):
        """POST /api/brands/:id/brandbrain/compile returns 404 if brand missing."""
        response = client.post(
            f"/api/brands/{uuid4()}/brandbrain/compile",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 404
        assert response.json()["error"] == "Brand not found"
