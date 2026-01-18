"""
BrandBrain API Views.

PR-5: Compile Orchestration Skeleton.
PR-7: API Surface + Contract Tests + Performance Guards.

Implements:
- POST /api/brands/:id/brandbrain/compile - kickoff (work-path)
- GET /api/brands/:id/brandbrain/compile/:compile_run_id/status - status poll (read-path)
- GET /api/brands/:id/brandbrain/latest - latest snapshot (read-path)
- GET /api/brands/:id/brandbrain/history - snapshot history (read-path)
- GET /api/brands/:id/brandbrain/overrides - get user overrides (read-path)
- PATCH /api/brands/:id/brandbrain/overrides - update user overrides (work-path)

Per spec Section 1.1 Performance Contracts:
- POST /compile: <200ms (kickoff only, async work)
- GET /status: <30ms (pure DB read)
- GET /latest: <50ms (2 queries with select_related)
- GET /history: <100ms (3 queries paginated)
- GET /overrides: <30ms (2 queries)
- PATCH /overrides: <100ms (work-path)

Read-path endpoints are DB reads only. No side effects.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from kairo.brandbrain.compile import (
    compile_brandbrain,
    get_compile_status,
    check_compile_gating,
)

logger = logging.getLogger(__name__)


def _parse_uuid(value: str) -> UUID | None:
    """Parse a string to UUID, returning None on failure."""
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def _brand_exists(brand_id: UUID) -> bool:
    """Check if brand exists."""
    from kairo.core.models import Brand
    return Brand.objects.filter(id=brand_id).exists()


# =============================================================================
# COMPILE ENDPOINTS (Work-path + Status read-path)
# =============================================================================


@csrf_exempt
@require_http_methods(["POST"])
def compile_kickoff(request, brand_id: str) -> JsonResponse:
    """
    POST /api/brands/:id/brandbrain/compile

    Kicks off a BrandBrain compile. Returns immediately with compile_run_id.
    Actual compilation happens asynchronously.

    Request body (optional):
        {
            "force_refresh": false  // Skip short-circuit check
        }

    Response (202 Accepted):
        {
            "compile_run_id": "uuid",
            "status": "PENDING",
            "poll_url": "/api/brands/:id/brandbrain/compile/:run_id/status"
        }

    Response (200 OK - short-circuit):
        {
            "compile_run_id": "uuid",
            "status": "UNCHANGED",
            "snapshot": {...}
        }

    Response (400/422 - gating failure):
        {
            "error": "message",
            "errors": [{"code": "...", "message": "..."}]
        }

    Response (404 - brand not found):
        {"error": "Brand not found"}

    Response (500 - internal error):
        {"error": "Internal server error"}  # Stack hidden when DEBUG off
    """
    from django.conf import settings

    try:
        # Parse brand_id
        parsed_brand_id = _parse_uuid(brand_id)
        if not parsed_brand_id:
            return JsonResponse({"error": "Invalid brand_id"}, status=400)

        # Check brand exists
        if not _brand_exists(parsed_brand_id):
            return JsonResponse({"error": "Brand not found"}, status=404)

        # Parse request body
        force_refresh = False
        if request.body:
            try:
                body = json.loads(request.body)
                force_refresh = body.get("force_refresh", False)
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON body"}, status=400)

        # Check gating first for better error messages
        gating = check_compile_gating(parsed_brand_id)
        if not gating.allowed:
            return JsonResponse({
                "error": "Compile gating failed",
                "errors": [{"code": e.code, "message": e.message} for e in gating.errors],
            }, status=422)

        # Kick off compile
        result = compile_brandbrain(
            brand_id=parsed_brand_id,
            force_refresh=force_refresh,
        )

        # Handle result
        if result.status == "FAILED":
            return JsonResponse({
                "error": result.error,
            }, status=422)

        if result.status == "UNCHANGED":
            # Short-circuit - return existing snapshot
            response_data = {
                "compile_run_id": str(result.compile_run_id),
                "status": "UNCHANGED",
            }
            if result.snapshot:
                response_data["snapshot"] = {
                    "snapshot_id": str(result.snapshot.id),
                    "brand_id": str(result.snapshot.brand_id),
                    "created_at": result.snapshot.created_at.isoformat(),
                    "snapshot_json": result.snapshot.snapshot_json,
                }
            return JsonResponse(response_data, status=200)

        # Normal kickoff - return 202
        return JsonResponse({
            "compile_run_id": str(result.compile_run_id),
            "status": result.status,
            "poll_url": result.poll_url,
        }, status=202)

    except Exception as e:
        # Log full exception with stack trace
        logger.exception("Unhandled exception in compile_kickoff for brand %s", brand_id)

        # Return sanitized error - hide stack trace in production
        if settings.DEBUG:
            return JsonResponse({
                "error": f"Internal server error: {str(e)}",
            }, status=500)
        else:
            return JsonResponse({
                "error": "Internal server error",
            }, status=500)


@require_http_methods(["GET"])
def compile_status(request, brand_id: str, compile_run_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/compile/:compile_run_id/status

    Get the status of a compile run. Pure DB read, no side effects.

    SECURITY: Enforces brand ownership - compile run must belong to the
    brand specified in the URL. Returns 404 if run belongs to different brand.

    Response shape varies by status:

    PENDING/RUNNING:
        {
            "compile_run_id": "uuid",
            "status": "PENDING" | "RUNNING",
            "progress": {  // only when RUNNING
                "stage": "bundling",
                "sources_completed": 2,
                "sources_total": 4
            }
        }

    SUCCEEDED:
        {
            "compile_run_id": "uuid",
            "status": "SUCCEEDED",
            "evidence_status": {...},
            "snapshot": {
                "snapshot_id": "uuid",
                "created_at": "iso-datetime",
                "snapshot_json": {...}
            }
        }

    FAILED:
        {
            "compile_run_id": "uuid",
            "status": "FAILED",
            "error": "message",
            "evidence_status": {...}
        }
    """
    # Parse UUIDs
    parsed_brand_id = _parse_uuid(brand_id)
    parsed_run_id = _parse_uuid(compile_run_id)

    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)
    if not parsed_run_id:
        return JsonResponse({"error": "Invalid compile_run_id"}, status=400)

    # Get status (pure DB read)
    # SECURITY: Pass brand_id to enforce ownership check
    status = get_compile_status(parsed_run_id, parsed_brand_id)

    if not status:
        return JsonResponse({"error": "Compile run not found"}, status=404)

    return JsonResponse(status.to_dict(), status=200)


# =============================================================================
# READ ENDPOINTS (Read-path only)
# =============================================================================


@require_http_methods(["GET"])
def latest_snapshot(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/latest

    Get the latest BrandBrain snapshot. Pure DB read.

    Query params:
        ?include=evidence,qa,bundle  (comma-separated, or 'full' for all)

    Response (200 OK - compact):
        {
            "snapshot_id": "uuid",
            "brand_id": "uuid",
            "snapshot_json": {...},
            "created_at": "iso-datetime",
            "compile_run_id": "uuid"
        }

    Response (200 OK - with include=full):
        {
            ... base fields ...
            "evidence_status": {...},
            "qa_report": {...},
            "bundle_summary": {...}
        }

    Response (404 - no snapshot):
        {"error": "No snapshot found"}

    Per spec Section 1.1:
    - P95 target: 50ms
    - Read-path only: DB reads, no side effects
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Get latest snapshot (indexed lookup)
    # Use select_related to minimize queries
    snapshot = (
        BrandBrainSnapshot.objects
        .filter(brand_id=parsed_brand_id)
        .select_related("compile_run", "compile_run__bundle")
        .order_by("-created_at")
        .first()
    )

    if not snapshot:
        return JsonResponse({"error": "No snapshot found"}, status=404)

    # Build response
    response_data = {
        "snapshot_id": str(snapshot.id),
        "brand_id": str(snapshot.brand_id),
        "snapshot_json": snapshot.snapshot_json,
        "created_at": snapshot.created_at.isoformat(),
        "compile_run_id": str(snapshot.compile_run_id) if snapshot.compile_run_id else None,
    }

    # Parse include params (comma-separated or 'full')
    include_param = request.GET.get("include", "")
    include_parts = {p.strip().lower() for p in include_param.split(",") if p.strip()}
    include_full = "full" in include_parts

    # Add evidence_status if requested
    if include_full or "evidence" in include_parts:
        if snapshot.compile_run:
            response_data["evidence_status"] = snapshot.compile_run.evidence_status_json

    # Add qa_report if requested
    if include_full or "qa" in include_parts:
        if snapshot.compile_run:
            response_data["qa_report"] = snapshot.compile_run.qa_report_json

    # Add bundle_summary if requested
    if include_full or "bundle" in include_parts:
        if snapshot.compile_run and snapshot.compile_run.bundle:
            response_data["bundle_summary"] = snapshot.compile_run.bundle.summary_json

    return JsonResponse(response_data, status=200)


@require_http_methods(["GET"])
def snapshot_history(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/history

    Get paginated snapshot history. Pure DB read.

    Query params:
        ?page=1 (default)
        ?page_size=10 (default, max 50)

    Response (200 OK):
        {
            "snapshots": [
                {
                    "snapshot_id": "uuid",
                    "created_at": "iso-datetime",
                    "diff_summary": {...}  // compact diff
                }
            ],
            "page": 1,
            "page_size": 10,
            "total": 25
        }
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse pagination params
    try:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 10))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid pagination params"}, status=400)

    # Enforce limits
    page = max(1, page)
    page_size = min(max(1, page_size), 50)  # max 50 per spec

    # Get total count
    total = BrandBrainSnapshot.objects.filter(brand_id=parsed_brand_id).count()

    # Get paginated snapshots
    offset = (page - 1) * page_size
    snapshots = (
        BrandBrainSnapshot.objects
        .filter(brand_id=parsed_brand_id)
        .order_by("-created_at")
        [offset:offset + page_size]
    )

    # Build compact response (no full snapshot_json)
    snapshot_list = []
    for snapshot in snapshots:
        snapshot_list.append({
            "snapshot_id": str(snapshot.id),
            "created_at": snapshot.created_at.isoformat(),
            "diff_summary": _extract_diff_summary(snapshot.diff_from_previous_json),
        })

    return JsonResponse({
        "snapshots": snapshot_list,
        "page": page,
        "page_size": page_size,
        "total": total,
    }, status=200)


def _extract_diff_summary(diff_json: dict) -> dict:
    """
    Extract a compact summary from diff_from_previous_json.

    PR-5: Returns minimal info since diff not computed yet.
    """
    if not diff_json:
        return {}

    # For PR-5 stubs, just return what we have
    if diff_json.get("_note"):
        return {"note": diff_json["_note"]}

    # Future: Extract changed field paths, counts, etc.
    return {
        "fields_changed": len(diff_json.get("changed", [])),
        "fields_added": len(diff_json.get("added", [])),
        "fields_removed": len(diff_json.get("removed", [])),
    }


# =============================================================================
# OVERRIDES ENDPOINTS (Read-path GET + Work-path PATCH)
# =============================================================================


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def overrides_view(request, brand_id: str) -> JsonResponse:
    """
    GET/PATCH /api/brands/:id/brandbrain/overrides

    Dispatcher for overrides endpoint.
    """
    if request.method == "GET":
        return _get_overrides(request, brand_id)
    else:  # PATCH
        return _patch_overrides(request, brand_id)


def _get_overrides(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/overrides

    Get user overrides and pinned fields for a brand. Pure DB read.

    Response (200 OK):
        {
            "brand_id": "uuid",
            "overrides_json": {
                "positioning.what_we_do": "Custom value",
                ...
            },
            "pinned_paths": [
                "positioning.what_we_do",
                "voice.tone"
            ],
            "updated_at": "iso-datetime"
        }

    Response (200 OK - no overrides exist):
        {
            "brand_id": "uuid",
            "overrides_json": {},
            "pinned_paths": [],
            "updated_at": null
        }

    Per spec Section 1.1:
    - P95 target: 30ms
    - Read-path only: DB reads, no side effects
    """
    from kairo.brandbrain.models import BrandBrainOverrides

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Get overrides (may not exist)
    try:
        overrides = BrandBrainOverrides.objects.get(brand_id=parsed_brand_id)
        response_data = {
            "brand_id": str(parsed_brand_id),
            "overrides_json": overrides.overrides_json,
            "pinned_paths": overrides.pinned_paths,
            "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
        }
    except BrandBrainOverrides.DoesNotExist:
        # Return empty overrides (not 404 - brand exists, just no overrides yet)
        response_data = {
            "brand_id": str(parsed_brand_id),
            "overrides_json": {},
            "pinned_paths": [],
            "updated_at": None,
        }

    return JsonResponse(response_data, status=200)


def _patch_overrides(request, brand_id: str) -> JsonResponse:
    """
    PATCH /api/brands/:id/brandbrain/overrides

    Update user overrides and pinned fields. Work-path (mutates state).

    Request body:
        {
            "overrides_json": {
                "positioning.what_we_do": "Custom value"
            },
            "pinned_paths": ["positioning.what_we_do"]
        }

    Merge semantics:
    - overrides_json: merge with existing (null value removes key)
    - pinned_paths: replace entirely (not merged)

    Response (200 OK):
        {
            "brand_id": "uuid",
            "overrides_json": {...},  # after merge
            "pinned_paths": [...],
            "updated_at": "iso-datetime"
        }

    Per spec Section 1.1:
    - P95 target: 100ms (work-path)
    - Work-path: mutates state
    """
    from kairo.brandbrain.models import BrandBrainOverrides

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse request body
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Validate body structure
    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    new_overrides = body.get("overrides_json")
    new_pinned = body.get("pinned_paths")

    # Validate types if provided
    if new_overrides is not None and not isinstance(new_overrides, dict):
        return JsonResponse({"error": "overrides_json must be an object"}, status=400)
    if new_pinned is not None and not isinstance(new_pinned, list):
        return JsonResponse({"error": "pinned_paths must be an array"}, status=400)

    # Get or create overrides
    overrides, created = BrandBrainOverrides.objects.get_or_create(
        brand_id=parsed_brand_id,
        defaults={
            "overrides_json": {},
            "pinned_paths": [],
        },
    )

    # Merge overrides_json if provided
    if new_overrides is not None:
        merged = dict(overrides.overrides_json)  # copy
        for key, value in new_overrides.items():
            if value is None:
                # null value removes the key
                merged.pop(key, None)
            else:
                merged[key] = value
        overrides.overrides_json = merged

    # Replace pinned_paths if provided
    if new_pinned is not None:
        # Validate all items are strings
        if not all(isinstance(p, str) for p in new_pinned):
            return JsonResponse({"error": "pinned_paths items must be strings"}, status=400)
        overrides.pinned_paths = new_pinned

    # Save
    overrides.save()

    return JsonResponse({
        "brand_id": str(parsed_brand_id),
        "overrides_json": overrides.overrides_json,
        "pinned_paths": overrides.pinned_paths,
        "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
    }, status=200)
