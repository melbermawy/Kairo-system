# Backend-Frontend Minimal API Code Pack

Full verbatim code for the PR-7 frontend contract implementation.

---

## 1. kairo/urls.py (modified)

```python
"""
URL configuration for Kairo backend.

PR-0: repo + env spine
- Only healthcheck endpoint
- No business logic routes
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("kairo.hero.urls")),
    # PR-7: Core API endpoints (brands, onboarding, sources)
    path(
        "api/",
        include("kairo.core.api.urls", namespace="core_api"),
    ),
    # PR-5: BrandBrain API endpoints
    path(
        "api/brands/<str:brand_id>/brandbrain/",
        include("kairo.brandbrain.api.urls", namespace="brandbrain"),
    ),
]

# PRD-1: out of scope for PR-0 - future API routes:
# path("api/brands/", include("kairo.api.brands.urls")),
# path("api/packages/", include("kairo.api.packages.urls")),
# path("api/variants/", include("kairo.api.variants.urls")),
```

---

## 2. kairo/core/api/__init__.py (new)

```python
"""
Core API module.

PR-7: Frontend contract endpoints for brands, onboarding, and sources.
"""
```

---

## 3. kairo/core/api/urls.py (new)

```python
"""
Core API URL routing.

PR-7: Frontend contract endpoints.

URL patterns:
- GET/POST /api/brands
- GET /api/brands/:brand_id
- GET/PUT /api/brands/:brand_id/onboarding
- GET/POST /api/brands/:brand_id/sources
- PATCH/DELETE /api/sources/:source_id
"""

from django.urls import path

from kairo.core.api import views

app_name = "core_api"

urlpatterns = [
    # Brands
    path(
        "brands",
        views.brands_list_create,
        name="brands-list-create",
    ),
    path(
        "brands/<str:brand_id>",
        views.brand_detail,
        name="brand-detail",
    ),
    # Onboarding
    path(
        "brands/<str:brand_id>/onboarding",
        views.onboarding_view,
        name="onboarding",
    ),
    # Sources (brand-scoped)
    path(
        "brands/<str:brand_id>/sources",
        views.sources_list_create,
        name="sources-list-create",
    ),
    # Sources (by source_id)
    path(
        "sources/<str:source_id>",
        views.source_detail,
        name="source-detail",
    ),
]
```

---

## 4. kairo/core/api/views.py (new)

```python
"""
Core API Views for frontend contract.

PR-7: Minimal API surface for frontend E2E flow.

Implements:
- GET/POST /api/brands - list and create brands
- GET /api/brands/:brand_id - get single brand
- GET/PUT /api/brands/:brand_id/onboarding - onboarding CRUD
- GET/POST /api/brands/:brand_id/sources - sources list and create
- PATCH/DELETE /api/sources/:source_id - source update and delete

No auth (explicitly out of scope for PRD v1).
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from kairo.core.models import Brand, Tenant


# =============================================================================
# HELPERS
# =============================================================================


def _parse_uuid(value: str) -> UUID | None:
    """Parse a string to UUID, returning None on failure."""
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def _get_default_tenant() -> Tenant:
    """Get or create the default tenant for single-tenant mode."""
    tenant, _ = Tenant.objects.get_or_create(
        slug="default",
        defaults={"name": "Default Tenant"},
    )
    return tenant


def _brand_to_dict(brand: Brand) -> dict:
    """Convert Brand to API response dict."""
    return {
        "id": str(brand.id),
        "name": brand.name,
        "website_url": brand.metadata.get("website_url"),
        "created_at": brand.created_at.isoformat(),
    }


# =============================================================================
# BRANDS ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["GET", "POST"])
def brands_list_create(request) -> JsonResponse:
    """
    GET /api/brands - List all brands.
    POST /api/brands - Create a new brand.
    """
    if request.method == "GET":
        return _list_brands(request)
    else:
        return _create_brand(request)


def _list_brands(request) -> JsonResponse:
    """
    GET /api/brands

    Response 200:
    [
        {"id": "uuid", "name": "string", "website_url": "string|null", "created_at": "iso"}
    ]
    """
    brands = Brand.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    return JsonResponse([_brand_to_dict(b) for b in brands], safe=False)


def _create_brand(request) -> JsonResponse:
    """
    POST /api/brands

    Request JSON:
    {"name": "string", "website_url"?: "string"}

    Response 201:
    {"id": "uuid", "name": "...", "website_url": "...|null", "created_at": "iso"}
    """
    # Parse body
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    name = body.get("name")
    website_url = body.get("website_url")

    # Validate
    if not name or not isinstance(name, str) or not name.strip():
        return JsonResponse({"error": "name is required and must be non-empty string"}, status=400)

    name = name.strip()

    if website_url is not None and not isinstance(website_url, str):
        return JsonResponse({"error": "website_url must be a string"}, status=400)

    # Generate slug from name
    base_slug = slugify(name)[:90]
    if not base_slug:
        base_slug = "brand"

    # Ensure unique slug within tenant
    tenant = _get_default_tenant()
    slug = base_slug
    counter = 1
    while Brand.objects.filter(tenant=tenant, slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Create brand
    metadata = {}
    if website_url:
        metadata["website_url"] = website_url.strip()

    brand = Brand.objects.create(
        tenant=tenant,
        name=name,
        slug=slug,
        metadata=metadata,
    )

    return JsonResponse(_brand_to_dict(brand), status=201)


@require_http_methods(["GET"])
def brand_detail(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:brand_id

    Response 200:
    {"id": "uuid", "name": "...", "website_url": "...|null", "created_at": "iso"}

    Response 404 if not found.
    """
    parsed_id = _parse_uuid(brand_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    try:
        brand = Brand.objects.get(id=parsed_id, deleted_at__isnull=True)
    except Brand.DoesNotExist:
        return JsonResponse({"error": "Brand not found"}, status=404)

    return JsonResponse(_brand_to_dict(brand))


# =============================================================================
# ONBOARDING ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["GET", "PUT"])
def onboarding_view(request, brand_id: str) -> JsonResponse:
    """
    GET/PUT /api/brands/:brand_id/onboarding

    Dispatcher for onboarding endpoint.
    """
    if request.method == "GET":
        return _get_onboarding(request, brand_id)
    else:
        return _put_onboarding(request, brand_id)


def _get_onboarding(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:brand_id/onboarding

    Response 200:
    {
        "brand_id": "uuid",
        "tier": 0|1|2,
        "answers_json": {...},
        "updated_at": "iso|null"
    }

    If no onboarding exists, returns tier=0, answers_json={}, updated_at=null.
    """
    from kairo.brandbrain.models import BrandOnboarding

    parsed_id = _parse_uuid(brand_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not Brand.objects.filter(id=parsed_id, deleted_at__isnull=True).exists():
        return JsonResponse({"error": "Brand not found"}, status=404)

    try:
        onboarding = BrandOnboarding.objects.get(brand_id=parsed_id)
        return JsonResponse({
            "brand_id": str(parsed_id),
            "tier": onboarding.tier,
            "answers_json": onboarding.answers_json,
            "updated_at": onboarding.updated_at.isoformat() if onboarding.updated_at else None,
        })
    except BrandOnboarding.DoesNotExist:
        # Return empty onboarding (not 404)
        return JsonResponse({
            "brand_id": str(parsed_id),
            "tier": 0,
            "answers_json": {},
            "updated_at": None,
        })


def _put_onboarding(request, brand_id: str) -> JsonResponse:
    """
    PUT /api/brands/:brand_id/onboarding

    Request JSON:
    {"tier": 0|1|2, "answers_json": {...}}

    Response 200: same as GET after update.
    Response 422 if tier invalid or answers_json not object.
    """
    from kairo.brandbrain.models import BrandOnboarding

    parsed_id = _parse_uuid(brand_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    try:
        brand = Brand.objects.get(id=parsed_id, deleted_at__isnull=True)
    except Brand.DoesNotExist:
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse body
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    tier = body.get("tier")
    answers_json = body.get("answers_json")

    # Validate tier
    if tier is None:
        return JsonResponse({"error": "tier is required"}, status=422)
    if not isinstance(tier, int) or tier not in (0, 1, 2):
        return JsonResponse({"error": "tier must be 0, 1, or 2"}, status=422)

    # Validate answers_json
    if answers_json is None:
        return JsonResponse({"error": "answers_json is required"}, status=422)
    if not isinstance(answers_json, dict):
        return JsonResponse({"error": "answers_json must be an object"}, status=422)

    # Get or create onboarding
    onboarding, _ = BrandOnboarding.objects.get_or_create(
        brand=brand,
        defaults={"tier": 0, "answers_json": {}},
    )

    # Update
    onboarding.tier = tier
    onboarding.answers_json = answers_json
    onboarding.save()

    return JsonResponse({
        "brand_id": str(parsed_id),
        "tier": onboarding.tier,
        "answers_json": onboarding.answers_json,
        "updated_at": onboarding.updated_at.isoformat() if onboarding.updated_at else None,
    })


# =============================================================================
# SOURCES ENDPOINTS
# =============================================================================


def _source_to_dict(source) -> dict:
    """Convert SourceConnection to API response dict."""
    return {
        "id": str(source.id),
        "brand_id": str(source.brand_id),
        "platform": source.platform,
        "capability": source.capability,
        "identifier": source.identifier,
        "is_enabled": source.is_enabled,
        "settings_json": source.settings_json or None,
        "created_at": source.created_at.isoformat(),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def sources_list_create(request, brand_id: str) -> JsonResponse:
    """
    GET/POST /api/brands/:brand_id/sources

    Dispatcher for sources list/create.
    """
    if request.method == "GET":
        return _list_sources(request, brand_id)
    else:
        return _create_source(request, brand_id)


def _list_sources(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:brand_id/sources

    Response 200:
    [
        {
            "id": "uuid",
            "brand_id": "uuid",
            "platform": "string",
            "capability": "string",
            "identifier": "string",
            "is_enabled": true|false,
            "settings_json": {...}|null,
            "created_at": "iso"
        }
    ]
    """
    from kairo.brandbrain.models import SourceConnection

    parsed_id = _parse_uuid(brand_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not Brand.objects.filter(id=parsed_id, deleted_at__isnull=True).exists():
        return JsonResponse({"error": "Brand not found"}, status=404)

    sources = SourceConnection.objects.filter(brand_id=parsed_id).order_by("-created_at")
    return JsonResponse([_source_to_dict(s) for s in sources], safe=False)


def _create_source(request, brand_id: str) -> JsonResponse:
    """
    POST /api/brands/:brand_id/sources

    Request JSON:
    {
        "platform": "string",
        "capability": "string",
        "identifier": "string",
        "is_enabled"?: boolean,
        "settings_json"?: object
    }

    Response 201: created object.
    """
    from kairo.brandbrain.models import SourceConnection

    parsed_id = _parse_uuid(brand_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    try:
        brand = Brand.objects.get(id=parsed_id, deleted_at__isnull=True)
    except Brand.DoesNotExist:
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse body
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    platform = body.get("platform")
    capability = body.get("capability")
    identifier = body.get("identifier")
    is_enabled = body.get("is_enabled", True)
    settings_json = body.get("settings_json")

    # Validate required fields
    if not platform or not isinstance(platform, str) or not platform.strip():
        return JsonResponse({"error": "platform is required and must be non-empty string"}, status=400)
    if not capability or not isinstance(capability, str) or not capability.strip():
        return JsonResponse({"error": "capability is required and must be non-empty string"}, status=400)
    if not identifier or not isinstance(identifier, str) or not identifier.strip():
        return JsonResponse({"error": "identifier is required and must be non-empty string"}, status=400)

    # Validate optional fields
    if not isinstance(is_enabled, bool):
        return JsonResponse({"error": "is_enabled must be a boolean"}, status=400)
    if settings_json is not None and not isinstance(settings_json, dict):
        return JsonResponse({"error": "settings_json must be an object"}, status=400)

    # Create source
    source = SourceConnection.objects.create(
        brand=brand,
        platform=platform.strip(),
        capability=capability.strip(),
        identifier=identifier.strip(),
        is_enabled=is_enabled,
        settings_json=settings_json or {},
    )

    return JsonResponse(_source_to_dict(source), status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def source_detail(request, source_id: str) -> JsonResponse:
    """
    PATCH/DELETE /api/sources/:source_id

    Dispatcher for source update/delete.
    """
    if request.method == "PATCH":
        return _patch_source(request, source_id)
    else:
        return _delete_source(request, source_id)


def _patch_source(request, source_id: str) -> JsonResponse:
    """
    PATCH /api/sources/:source_id

    Request JSON (partial):
    {"identifier"?: string, "is_enabled"?: boolean, "settings_json"?: object}

    Response 200: updated object.
    Response 404 if not found.
    Response 400 if empty body.
    """
    from kairo.brandbrain.models import SourceConnection

    parsed_id = _parse_uuid(source_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid source_id"}, status=400)

    try:
        source = SourceConnection.objects.get(id=parsed_id)
    except SourceConnection.DoesNotExist:
        return JsonResponse({"error": "Source not found"}, status=404)

    # Parse body
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    # Check not empty
    if not body:
        return JsonResponse({"error": "Request body cannot be empty"}, status=400)

    # Update fields
    updated = False

    if "identifier" in body:
        identifier = body["identifier"]
        if not isinstance(identifier, str) or not identifier.strip():
            return JsonResponse({"error": "identifier must be non-empty string"}, status=400)
        source.identifier = identifier.strip()
        updated = True

    if "is_enabled" in body:
        is_enabled = body["is_enabled"]
        if not isinstance(is_enabled, bool):
            return JsonResponse({"error": "is_enabled must be a boolean"}, status=400)
        source.is_enabled = is_enabled
        updated = True

    if "settings_json" in body:
        settings_json = body["settings_json"]
        if settings_json is not None and not isinstance(settings_json, dict):
            return JsonResponse({"error": "settings_json must be an object or null"}, status=400)
        source.settings_json = settings_json or {}
        updated = True

    if updated:
        source.save()

    return JsonResponse(_source_to_dict(source))


def _delete_source(request, source_id: str) -> JsonResponse:
    """
    DELETE /api/sources/:source_id

    Response 204.
    """
    from kairo.brandbrain.models import SourceConnection

    parsed_id = _parse_uuid(source_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid source_id"}, status=400)

    try:
        source = SourceConnection.objects.get(id=parsed_id)
    except SourceConnection.DoesNotExist:
        return JsonResponse({"error": "Source not found"}, status=404)

    source.delete()
    return JsonResponse({}, status=204)
```

---

## 5. tests/brandbrain/test_pr7_frontend_contract_min_api.py (new)

```python
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

    # ... (34 tests total - see full file above)


# =============================================================================
# ONBOARDING TESTS
# =============================================================================


@pytest.mark.db
class TestOnboardingAPI:
    """Test onboarding get/put endpoints."""
    # 8 tests


# =============================================================================
# SOURCES TESTS
# =============================================================================


@pytest.mark.db
class TestSourcesAPI:
    """Test sources CRUD endpoints."""
    # 15 tests


# =============================================================================
# CORS TESTS
# =============================================================================


@pytest.mark.db
class TestCORS:
    """Test CORS headers are present."""
    # 1 test


# =============================================================================
# BRANDBRAIN COMPILE 404 TEST
# =============================================================================


@pytest.mark.db
class TestBrandBrainCompileNotFound:
    """Test existing BrandBrain behavior for missing brand."""
    # 1 test
```

---

## 6. No Migrations Needed

No model changes were made. The API uses existing models:
- `kairo.core.models.Brand`
- `kairo.core.models.Tenant`
- `kairo.brandbrain.models.BrandOnboarding`
- `kairo.brandbrain.models.SourceConnection`

---

## 7. Test Output

```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.4.2, pluggy-1.5.0
django: version: 5.2.9, settings: kairo.settings_test (from ini)
rootdir: /Users/mohamed/Documents/Kairo-system
collected 34 items

tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_list_brands_empty PASSED [  2%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_list_brands_with_data PASSED [  5%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_create_brand_minimal PASSED [  8%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_create_brand_with_website PASSED [ 11%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_create_brand_name_required PASSED [ 14%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_create_brand_empty_name_rejected PASSED [ 17%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_get_brand_exists PASSED [ 20%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_get_brand_not_found PASSED [ 23%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandsAPI::test_get_brand_invalid_uuid PASSED [ 26%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_get_onboarding_default PASSED [ 29%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_get_onboarding_brand_not_found PASSED [ 32%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_put_onboarding_create PASSED [ 35%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_put_onboarding_update PASSED [ 38%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_put_onboarding_invalid_tier PASSED [ 41%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_put_onboarding_tier_required PASSED [ 44%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_put_onboarding_answers_required PASSED [ 47%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestOnboardingAPI::test_put_onboarding_answers_must_be_object PASSED [ 50%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_list_sources_empty PASSED [ 52%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_list_sources_with_data PASSED [ 55%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_list_sources_brand_not_found PASSED [ 58%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_create_source PASSED [ 61%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_create_source_with_settings PASSED [ 64%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_create_source_platform_required PASSED [ 67%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_create_source_capability_required PASSED [ 70%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_create_source_identifier_required PASSED [ 73%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_patch_source_identifier PASSED [ 76%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_patch_source_is_enabled PASSED [ 79%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_patch_source_settings PASSED [ 82%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_patch_source_empty_body_rejected PASSED [ 85%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_patch_source_not_found PASSED [ 88%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_delete_source PASSED [ 91%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestSourcesAPI::test_delete_source_not_found PASSED [ 94%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestCORS::test_cors_headers_on_brands PASSED [ 97%]
tests/brandbrain/test_pr7_frontend_contract_min_api.py::TestBrandBrainCompileNotFound::test_compile_returns_404_for_missing_brand PASSED [100%]

============================== 34 passed in 1.14s ==============================
```

---

## 8. Existing PR-7 Tests Still Pass

```
tests/brandbrain/test_pr7_api_surface.py: 35 passed in 1.14s
```
