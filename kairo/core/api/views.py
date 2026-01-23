"""
Core API Views for frontend contract.

PR-7: Minimal API surface for frontend E2E flow.
PR0: Added contract authority endpoints per opportunities_v1_prd.md §4.

Implements:
- GET/POST /api/brands - list and create brands
- GET /api/brands/:brand_id - get single brand
- GET/PUT /api/brands/:brand_id/onboarding - onboarding CRUD
- GET/POST /api/brands/:brand_id/sources - sources list and create
- PATCH/DELETE /api/sources/:source_id - source update and delete
- GET /api/health - contract authority health check (PR0)
- GET /api/openapi.json - versioned OpenAPI schema (PR0)

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
# CONTRACT AUTHORITY CONSTANTS
# Per opportunities_v1_prd.md §4 - Runtime Contract Authority
# =============================================================================

# Bump CONTRACT_VERSION on breaking changes to DTOs
CONTRACT_VERSION = "1.0.0"

# Minimum frontend version this backend is compatible with
MIN_FRONTEND_VERSION = "1.0.0"


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

    Filters by owner if authenticated, otherwise returns all (for backward compat).
    """
    queryset = Brand.objects.filter(deleted_at__isnull=True)

    # Filter by owner if user is authenticated
    kairo_user = getattr(request, "kairo_user", None)
    if kairo_user is not None:
        queryset = queryset.filter(owner=kairo_user)

    brands = queryset.order_by("-created_at")
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

    # Set owner if user is authenticated
    kairo_user = getattr(request, "kairo_user", None)

    brand = Brand.objects.create(
        tenant=tenant,
        name=name,
        slug=slug,
        metadata=metadata,
        owner=kairo_user,
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


def _source_to_dict(source, include_evidence_status: bool = False) -> dict:
    """Convert SourceConnection to API response dict.

    Args:
        source: SourceConnection instance
        include_evidence_status: If True, include latest ApifyRun age/status
    """
    result = {
        "id": str(source.id),
        "brand_id": str(source.brand_id),
        "platform": source.platform,
        "capability": source.capability,
        "identifier": source.identifier,
        "is_enabled": source.is_enabled,
        "settings_json": source.settings_json or None,
        "created_at": source.created_at.isoformat(),
    }

    if include_evidence_status:
        result["evidence_status"] = _get_source_evidence_status(source.id)

    return result


def _get_source_evidence_status(source_connection_id) -> dict:
    """Get latest ApifyRun status for a source connection.

    Returns dict with:
    - has_evidence: bool - whether any successful run exists
    - latest_run_id: str|null - UUID of latest successful run
    - latest_run_status: str|null - status of latest run
    - latest_run_age_hours: float|null - age in hours
    - next_action: "reuse"|"refresh" - what compile would do
    - ttl_hours: int - configured TTL
    """
    from django.utils import timezone
    from kairo.brandbrain.caps import apify_run_ttl_hours
    from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus

    ttl_hours = apify_run_ttl_hours()

    # Find latest successful run
    latest_run = (
        ApifyRun.objects.filter(
            source_connection_id=source_connection_id,
            status=ApifyRunStatus.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )

    if not latest_run:
        return {
            "has_evidence": False,
            "latest_run_id": None,
            "latest_run_status": None,
            "latest_run_age_hours": None,
            "next_action": "refresh",
            "ttl_hours": ttl_hours,
        }

    # Calculate age
    now = timezone.now()
    age = now - latest_run.created_at
    age_hours = round(age.total_seconds() / 3600, 1)

    # Determine next action
    next_action = "reuse" if age_hours <= ttl_hours else "refresh"

    return {
        "has_evidence": True,
        "latest_run_id": str(latest_run.id),
        "latest_run_status": latest_run.status,
        "latest_run_age_hours": age_hours,
        "next_action": next_action,
        "ttl_hours": ttl_hours,
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

    Query params:
        ?include_evidence=true  Include ApifyRun age/status per source

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
            "created_at": "iso",
            "evidence_status": {  // only if ?include_evidence=true
                "has_evidence": true,
                "latest_run_id": "uuid",
                "latest_run_status": "succeeded",
                "latest_run_age_hours": 12.5,
                "next_action": "reuse"|"refresh",
                "ttl_hours": 24
            }
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

    # Check if evidence status requested
    include_evidence = request.GET.get("include_evidence", "").lower() in ("true", "1", "yes")

    sources = SourceConnection.objects.filter(brand_id=parsed_id).order_by("-created_at")
    return JsonResponse(
        [_source_to_dict(s, include_evidence_status=include_evidence) for s in sources],
        safe=False,
    )


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

    Response 201: created object (new source).
    Response 200: existing object (idempotent - duplicate detected).

    PR-7: Idempotency guard - normalizes identifier and returns existing source
    if (brand_id, platform, capability, normalized_identifier) already exists.
    """
    from kairo.brandbrain.identifiers import normalize_source_identifier
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

    # Normalize identifier for idempotency check
    platform_clean = platform.strip()
    capability_clean = capability.strip()
    identifier_clean = identifier.strip()
    normalized_identifier = normalize_source_identifier(
        platform_clean, capability_clean, identifier_clean
    )

    # Idempotency guard: get_or_create with normalized identifier
    # Note: SourceConnection.save() also normalizes, so we pre-normalize for lookup
    source, created = SourceConnection.objects.get_or_create(
        brand=brand,
        platform=platform_clean,
        capability=capability_clean,
        identifier=normalized_identifier,
        defaults={
            "is_enabled": is_enabled,
            "settings_json": settings_json or {},
        },
    )

    # Return 201 for new, 200 for existing (idempotent)
    response = _source_to_dict(source)
    if not created:
        response["_note"] = "existing_source_returned"
    return JsonResponse(response, status=201 if created else 200)


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


# =============================================================================
# BOOTSTRAP ENDPOINT
# =============================================================================


@require_http_methods(["GET"])
def brand_bootstrap(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:brand_id/bootstrap

    Returns all data needed to initialize a brand page in a single request:
    - brand: basic brand info
    - onboarding: tier + answers_json
    - sources: list of source connections
    - overrides: user overrides + pinned_paths
    - latest: compact latest snapshot (id, created_at, has_data flag)

    This eliminates 5 separate requests, reducing latency by ~4x for remote DB.

    Response 200:
    {
        "brand": {"id", "name", "website_url", "created_at"},
        "onboarding": {"tier", "answers_json", "updated_at"},
        "sources": [{"id", "platform", "capability", "identifier", "is_enabled", ...}],
        "overrides": {"overrides_json", "pinned_paths", "updated_at"},
        "latest": {"snapshot_id", "created_at", "has_data"} | null
    }

    Response 404 if brand not found.
    """
    from kairo.brandbrain.models import (
        BrandOnboarding,
        BrandBrainOverrides,
        BrandBrainSnapshot,
        SourceConnection,
    )

    parsed_id = _parse_uuid(brand_id)
    if not parsed_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Get brand (required)
    try:
        brand = Brand.objects.get(id=parsed_id, deleted_at__isnull=True)
    except Brand.DoesNotExist:
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Get onboarding (optional - return defaults if not exists)
    try:
        onboarding = BrandOnboarding.objects.get(brand_id=parsed_id)
        onboarding_data = {
            "tier": onboarding.tier,
            "answers_json": onboarding.answers_json,
            "updated_at": onboarding.updated_at.isoformat() if onboarding.updated_at else None,
        }
    except BrandOnboarding.DoesNotExist:
        onboarding_data = {
            "tier": 0,
            "answers_json": {},
            "updated_at": None,
        }

    # Get sources
    sources = SourceConnection.objects.filter(brand_id=parsed_id).order_by("-created_at")
    sources_data = [_source_to_dict(s) for s in sources]

    # Get overrides (optional - return defaults if not exists)
    try:
        overrides = BrandBrainOverrides.objects.get(brand_id=parsed_id)
        overrides_data = {
            "overrides_json": overrides.overrides_json,
            "pinned_paths": overrides.pinned_paths,
            "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
        }
    except BrandBrainOverrides.DoesNotExist:
        overrides_data = {
            "overrides_json": {},
            "pinned_paths": [],
            "updated_at": None,
        }

    # Get latest snapshot (compact - just id, created_at, has_data)
    latest_snapshot = (
        BrandBrainSnapshot.objects
        .filter(brand_id=parsed_id)
        .order_by("-created_at")
        .values("id", "created_at", "snapshot_json")
        .first()
    )

    if latest_snapshot:
        latest_data = {
            "snapshot_id": str(latest_snapshot["id"]),
            "created_at": latest_snapshot["created_at"].isoformat(),
            "has_data": bool(latest_snapshot["snapshot_json"]),
        }
    else:
        latest_data = None

    return JsonResponse({
        "brand": _brand_to_dict(brand),
        "onboarding": onboarding_data,
        "sources": sources_data,
        "overrides": overrides_data,
        "latest": latest_data,
    })


# =============================================================================
# CONTRACT AUTHORITY ENDPOINTS
# Per opportunities_v1_prd.md §4 - Runtime Contract Authority
# =============================================================================


@require_http_methods(["GET"])
def health_check(request) -> JsonResponse:
    """
    GET /api/health

    PR0: Contract authority health check endpoint.
    Per opportunities_v1_prd.md §4.

    Returns:
    - status: "healthy" (or "degraded" if issues detected)
    - contract_version: Current backend contract version
    - min_frontend_version: Minimum compatible frontend version

    Frontend MUST call this at startup to verify compatibility.
    If frontend version < min_frontend_version, show blocking modal.
    If backend contract_version < frontend MIN_BACKEND_VERSION, show warning.

    Response 200:
    {
        "status": "healthy",
        "contract_version": "1.0.0",
        "min_frontend_version": "1.0.0"
    }
    """
    return JsonResponse({
        "status": "healthy",
        "contract_version": CONTRACT_VERSION,
        "min_frontend_version": MIN_FRONTEND_VERSION,
    })


@require_http_methods(["GET"])
def openapi_schema(request) -> JsonResponse:
    """
    GET /api/openapi.json

    PR0: Versioned OpenAPI schema endpoint.
    Per opportunities_v1_prd.md §4.

    Returns OpenAPI 3.1 schema generated from Pydantic DTOs.
    Includes X-Contract-Version header for runtime verification.

    Frontend MUST fetch schema from this endpoint, not from file.

    Response 200: OpenAPI JSON schema
    Headers:
        X-Contract-Version: {CONTRACT_VERSION}
        Cache-Control: public, max-age=3600
    """
    # PR0 STUB: Return minimal schema structure
    # Full schema generation will be implemented in a later PR
    # using Django Ninja or drf-spectacular
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "Kairo API",
            "version": CONTRACT_VERSION,
            "description": "Kairo backend API - contract authority endpoint",
        },
        "paths": {},
        "components": {
            "schemas": {}
        },
        "_meta": {
            "contract_version": CONTRACT_VERSION,
            "min_frontend_version": MIN_FRONTEND_VERSION,
            "note": "PR0 stub - full schema generation not yet implemented",
        }
    }

    response = JsonResponse(schema)
    response["X-Contract-Version"] = CONTRACT_VERSION
    response["Cache-Control"] = "public, max-age=3600"
    return response
