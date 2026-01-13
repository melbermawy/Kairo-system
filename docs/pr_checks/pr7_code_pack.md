# PR-7 Code Pack

Complete code for PR-7: API Surface + Contract Tests + Performance Guards.

## File: kairo/brandbrain/api/views.py

```python
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

# ... existing compile endpoints unchanged ...

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
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

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

    if include_full or "evidence" in include_parts:
        if snapshot.compile_run:
            response_data["evidence_status"] = snapshot.compile_run.evidence_status_json

    if include_full or "qa" in include_parts:
        if snapshot.compile_run:
            response_data["qa_report"] = snapshot.compile_run.qa_report_json

    if include_full or "bundle" in include_parts:
        if snapshot.compile_run and snapshot.compile_run.bundle:
            response_data["bundle_summary"] = snapshot.compile_run.bundle.summary_json

    return JsonResponse(response_data, status=200)


# =============================================================================
# OVERRIDES ENDPOINTS (Read-path GET + Work-path PATCH)
# =============================================================================


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def overrides_view(request, brand_id: str) -> JsonResponse:
    """GET/PATCH /api/brands/:id/brandbrain/overrides"""
    if request.method == "GET":
        return _get_overrides(request, brand_id)
    else:
        return _patch_overrides(request, brand_id)


def _get_overrides(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/overrides

    Get user overrides and pinned fields for a brand. Pure DB read.
    """
    from kairo.brandbrain.models import BrandBrainOverrides

    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    try:
        overrides = BrandBrainOverrides.objects.get(brand_id=parsed_brand_id)
        response_data = {
            "brand_id": str(parsed_brand_id),
            "overrides_json": overrides.overrides_json,
            "pinned_paths": overrides.pinned_paths,
            "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
        }
    except BrandBrainOverrides.DoesNotExist:
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

    Merge semantics:
    - overrides_json: merge with existing (null value removes key)
    - pinned_paths: replace entirely (not merged)
    """
    from kairo.brandbrain.models import BrandBrainOverrides

    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    new_overrides = body.get("overrides_json")
    new_pinned = body.get("pinned_paths")

    if new_overrides is not None and not isinstance(new_overrides, dict):
        return JsonResponse({"error": "overrides_json must be an object"}, status=400)
    if new_pinned is not None and not isinstance(new_pinned, list):
        return JsonResponse({"error": "pinned_paths must be an array"}, status=400)

    overrides, created = BrandBrainOverrides.objects.get_or_create(
        brand_id=parsed_brand_id,
        defaults={"overrides_json": {}, "pinned_paths": []},
    )

    if new_overrides is not None:
        merged = dict(overrides.overrides_json)
        for key, value in new_overrides.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        overrides.overrides_json = merged

    if new_pinned is not None:
        if not all(isinstance(p, str) for p in new_pinned):
            return JsonResponse({"error": "pinned_paths items must be strings"}, status=400)
        overrides.pinned_paths = new_pinned

    overrides.save()

    return JsonResponse({
        "brand_id": str(parsed_brand_id),
        "overrides_json": overrides.overrides_json,
        "pinned_paths": overrides.pinned_paths,
        "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
    }, status=200)
```

---

## File: kairo/brandbrain/api/urls.py

```python
"""
BrandBrain API URL routing.

PR-5: Compile Orchestration endpoints.
PR-7: API Surface + Overrides endpoints.

URL patterns follow spec Section 10:
- POST /api/brands/:id/brandbrain/compile
- GET /api/brands/:id/brandbrain/compile/:compile_run_id/status
- GET /api/brands/:id/brandbrain/latest
- GET /api/brands/:id/brandbrain/history
- GET/PATCH /api/brands/:id/brandbrain/overrides
"""

from django.urls import path

from kairo.brandbrain.api import views

app_name = "brandbrain"

urlpatterns = [
    path("compile", views.compile_kickoff, name="compile-kickoff"),
    path("compile/<str:compile_run_id>/status", views.compile_status, name="compile-status"),
    path("latest", views.latest_snapshot, name="latest-snapshot"),
    path("history", views.snapshot_history, name="snapshot-history"),
    path("overrides", views.overrides_view, name="overrides"),
]
```

---

## File: tests/brandbrain/test_pr7_api_surface.py

See full test file with 35 tests covering:
- A) Contract Tests: Response shapes match spec interfaces
- B) Include Params: ?include=evidence,qa,bundle,full
- C) Overrides CRUD: GET/PATCH /overrides
- D) Cross-Brand Security: Ownership enforcement
- E) Query Count: Bounded queries (no N+1)
- F) Read-Path Boundary: No side effects on read endpoints
- G) Error Handling: Invalid inputs

---

## Test Classes Summary

| Class | Tests | Purpose |
|-------|-------|---------|
| `TestLatestSnapshotContract` | 3 | Response shape validation |
| `TestOverridesContract` | 2 | Overrides response shape |
| `TestIncludeParams` | 5 | ?include= query param |
| `TestOverridesCRUD` | 8 | GET/PATCH operations |
| `TestCrossBrandSecurity` | 5 | Ownership enforcement |
| `TestQueryCount` | 4 | Query bounds |
| `TestReadPathBoundary` | 3 | No side effects |
| `TestErrorHandling` | 5 | Error responses |

**Total: 35 tests**
