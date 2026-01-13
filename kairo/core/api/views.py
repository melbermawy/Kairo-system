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
