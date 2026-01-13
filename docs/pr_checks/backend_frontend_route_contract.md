# Backend-Frontend Route Contract

Verbatim code for BrandBrain API routes.

---

## 1. kairo/urls.py (BrandBrain-related urlpattern)

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("kairo.hero.urls")),
    # PR-5: BrandBrain API endpoints
    path(
        "api/brands/<str:brand_id>/brandbrain/",
        include("kairo.brandbrain.api.urls", namespace="brandbrain"),
    ),
]
```

---

## 2. kairo/brandbrain/api/urls.py (entire file)

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
    # Work-path: compile kickoff
    path(
        "compile",
        views.compile_kickoff,
        name="compile-kickoff",
    ),
    # Read-path: compile status
    path(
        "compile/<str:compile_run_id>/status",
        views.compile_status,
        name="compile-status",
    ),
    # Read-path: latest snapshot
    path(
        "latest",
        views.latest_snapshot,
        name="latest-snapshot",
    ),
    # Read-path: snapshot history
    path(
        "history",
        views.snapshot_history,
        name="snapshot-history",
    ),
    # Overrides: GET (read-path) + PATCH (work-path)
    path(
        "overrides",
        views.overrides_view,
        name="overrides",
    ),
]
```

---

## 3. kairo/brandbrain/api/views.py

### 3.1 compile_kickoff (POST /compile)

```python
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
    """
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
```

### 3.2 compile_status (GET /compile/:compile_run_id/status)

```python
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
```

### 3.3 latest_snapshot (GET /latest)

```python
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
```

### 3.4 snapshot_history (GET /history)

```python
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
```

### 3.5 overrides_view (GET/PATCH /overrides)

```python
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
```

---

## 4. Example curl Commands

### 4.1 Trigger Compile

```bash
curl -X POST http://localhost:8000/api/brands/12345678-1234-5678-1234-567812345678/brandbrain/compile \
  -H "Content-Type: application/json" \
  -d '{"force_refresh": false}'
```

### 4.2 Poll Status

```bash
curl http://localhost:8000/api/brands/12345678-1234-5678-1234-567812345678/brandbrain/compile/abcd1234-abcd-1234-abcd-1234abcd5678/status
```

### 4.3 Get Latest (compact)

```bash
curl http://localhost:8000/api/brands/12345678-1234-5678-1234-567812345678/brandbrain/latest
```

### 4.4 Get Latest (with include=full)

```bash
curl "http://localhost:8000/api/brands/12345678-1234-5678-1234-567812345678/brandbrain/latest?include=full"
```
