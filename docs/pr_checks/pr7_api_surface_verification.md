# PR-7 API Surface + Contract Tests + Performance Guards

API surface completion with contract tests and performance guardrails.

---

## Authentication / Authorization Status

**Auth is NOT enforced on BrandBrain endpoints.**

| Aspect | Status |
|--------|--------|
| User authentication | NOT IMPLEMENTED |
| API token/session auth | NOT IMPLEMENTED |
| Brand ownership enforcement | NOT IMPLEMENTED |
| Data isolation by brand_id | IMPLEMENTED |

**Implications:**
- All endpoints are publicly accessible
- Knowledge of a brand UUID grants full read/write access to that brand's data
- Tests in this PR verify **data isolation by brand_id in URL path only**
- Auth/permissions are explicitly out of scope for PRD v1 (see `kairo-v1-prd.md:47`)

---

## Summary

PR-7 completes the BrandBrain API surface per spec Section 10:
1. **Enhanced GET /latest**: Comma-separated `include` params (evidence, qa, bundle, full)
2. **GET/PATCH /overrides**: User overrides CRUD with merge semantics
3. **Contract tests**: Response shape validation for all endpoints
4. **Cross-brand data isolation**: Tests verify brand_id scoping (no auth)
5. **Query count guards**: Bounded queries (no N+1)

---

## Diff Summary

| File | Change |
|------|--------|
| `kairo/brandbrain/api/views.py` | Enhanced `/latest` with include params, added overrides endpoints |
| `kairo/brandbrain/api/urls.py` | Added `/overrides` route |
| `tests/brandbrain/test_pr7_api_surface.py` | 35 tests covering contracts, security, performance |
| `tests/brandbrain/contracts/test_brandbrain_read_endpoints_contracts.py` | Updated docstring |

---

## Code Changes

### 1. Enhanced GET /latest with include params

**File**: `kairo/brandbrain/api/views.py:224-296`

```python
@require_http_methods(["GET"])
def latest_snapshot(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/latest

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
    """
    # Uses select_related for compile_run and bundle (single query)
    snapshot = (
        BrandBrainSnapshot.objects
        .filter(brand_id=parsed_brand_id)
        .select_related("compile_run", "compile_run__bundle")
        .order_by("-created_at")
        .first()
    )

    # Parse include params (comma-separated or 'full')
    include_param = request.GET.get("include", "")
    include_parts = {p.strip().lower() for p in include_param.split(",") if p.strip()}
    include_full = "full" in include_parts

    # Add fields based on include params
    if include_full or "evidence" in include_parts:
        response_data["evidence_status"] = snapshot.compile_run.evidence_status_json
    if include_full or "qa" in include_parts:
        response_data["qa_report"] = snapshot.compile_run.qa_report_json
    if include_full or "bundle" in include_parts:
        response_data["bundle_summary"] = snapshot.compile_run.bundle.summary_json
```

---

### 2. GET/PATCH /overrides endpoints

**File**: `kairo/brandbrain/api/views.py:409-550`

```python
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

    Response:
        {
            "brand_id": "uuid",
            "overrides_json": {...},
            "pinned_paths": [...],
            "updated_at": "iso-datetime"
        }
    """


def _patch_overrides(request, brand_id: str) -> JsonResponse:
    """
    PATCH /api/brands/:id/brandbrain/overrides

    Merge semantics:
    - overrides_json: merge with existing (null value removes key)
    - pinned_paths: replace entirely (not merged)
    """
    # Merge overrides_json if provided
    if new_overrides is not None:
        merged = dict(overrides.overrides_json)
        for key, value in new_overrides.items():
            if value is None:
                merged.pop(key, None)  # null removes key
            else:
                merged[key] = value
        overrides.overrides_json = merged

    # Replace pinned_paths if provided
    if new_pinned is not None:
        overrides.pinned_paths = new_pinned
```

---

### 3. URL routing

**File**: `kairo/brandbrain/api/urls.py:44-48`

```python
# Overrides: GET (read-path) + PATCH (work-path)
path(
    "overrides",
    views.overrides_view,
    name="overrides",
),
```

---

## Test Results

### PR-7 Tests

```bash
pytest tests/brandbrain/test_pr7_api_surface.py -v --tb=short
```

```
============================= test session starts ==============================
tests/brandbrain/test_pr7_api_surface.py::TestLatestSnapshotContract::test_compact_response_has_required_fields PASSED
tests/brandbrain/test_pr7_api_surface.py::TestLatestSnapshotContract::test_compact_response_excludes_verbose_fields PASSED
tests/brandbrain/test_pr7_api_surface.py::TestLatestSnapshotContract::test_full_response_includes_all_fields PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesContract::test_get_overrides_has_required_fields PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesContract::test_patch_overrides_returns_updated_data PASSED
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_evidence_only PASSED
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_qa_only PASSED
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_bundle_only PASSED
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_comma_separated PASSED
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_full_returns_all PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_get_overrides_empty_when_none_exist PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_get_overrides_returns_existing PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_creates_overrides_if_not_exist PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_merges_overrides PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_null_removes_override PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_replaces_pinned_paths PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_rejects_invalid_overrides_type PASSED
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_rejects_invalid_pinned_type PASSED
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandSecurity::test_latest_returns_404_for_other_brands_snapshot PASSED
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandSecurity::test_history_returns_empty_for_other_brand PASSED
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandSecurity::test_overrides_isolated_between_brands PASSED
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandSecurity::test_status_returns_404_for_other_brands_run PASSED
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandSecurity::test_patch_overrides_only_affects_own_brand PASSED
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_latest_query_count_compact PASSED
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_latest_query_count_full PASSED
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_history_query_count PASSED
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_overrides_get_query_count PASSED
tests/brandbrain/test_pr7_api_surface.py::TestReadPathBoundary::test_get_latest_no_side_effects PASSED
tests/brandbrain/test_pr7_api_surface.py::TestReadPathBoundary::test_get_history_no_side_effects PASSED
tests/brandbrain/test_pr7_api_surface.py::TestReadPathBoundary::test_get_overrides_no_side_effects PASSED
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_latest_invalid_brand_id PASSED
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_latest_nonexistent_brand PASSED
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_overrides_patch_invalid_json PASSED
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_overrides_patch_nonexistent_brand PASSED
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_history_invalid_pagination PASSED

============================== 35 passed in 0.90s ==============================
```

### Full BrandBrain Test Suite

```bash
pytest tests/brandbrain/ -v --tb=short
```

```
======================= 379 passed, 41 skipped in 1.70s ========================
```

---

## API Endpoint Summary

| Endpoint | Method | Type | Queries | Description |
|----------|--------|------|---------|-------------|
| `/api/brands/:id/brandbrain/latest` | GET | Read | 2 | Latest snapshot with optional include |
| `/api/brands/:id/brandbrain/history` | GET | Read | 3 | Paginated snapshot history |
| `/api/brands/:id/brandbrain/compile` | POST | Work | N/A | Kick off compile |
| `/api/brands/:id/brandbrain/compile/:id/status` | GET | Read | 2 | Compile status |
| `/api/brands/:id/brandbrain/overrides` | GET | Read | 2 | Get user overrides |
| `/api/brands/:id/brandbrain/overrides` | PATCH | Work | 2-3 | Update user overrides |

---

## Invariants

| Invariant | Enforced By |
|-----------|-------------|
| Compact response excludes verbose fields | Tests verify exclude behavior |
| include=full returns all additional fields | `TestIncludeParams::test_include_full_returns_all` |
| Cross-brand data isolation | 5 tests verify brand_id scoping (404/empty for other brands) |
| No N+1 queries on /latest | Query count test: 2 queries with select_related |
| Read-path endpoints have no side effects | `TestReadPathBoundary` tests |
| PATCH /overrides merges, not replaces | `TestOverridesCRUD::test_patch_merges_overrides` |
| null value in overrides removes key | `TestOverridesCRUD::test_patch_null_removes_override` |
| pinned_paths is replaced, not merged | `TestOverridesCRUD::test_patch_replaces_pinned_paths` |

---

## Performance Contracts

Per spec Section 1.1:

| Endpoint | P95 Target | Actual Queries |
|----------|------------|----------------|
| GET /latest | 50ms | 2 queries |
| GET /latest?include=full | 50ms | 2 queries (same - select_related) |
| GET /history | 100ms | 3 queries |
| GET /overrides | 30ms | 2 queries |

---

## No New Dependencies

- Uses only Django ORM features (select_related)
- No external services
- SQLite compatible

---

## Response Shape Contracts

### GET /latest (compact)

```json
{
    "snapshot_id": "uuid",
    "brand_id": "uuid",
    "snapshot_json": {...},
    "created_at": "iso-datetime",
    "compile_run_id": "uuid"
}
```

### GET /latest?include=full

```json
{
    "snapshot_id": "uuid",
    "brand_id": "uuid",
    "snapshot_json": {...},
    "created_at": "iso-datetime",
    "compile_run_id": "uuid",
    "evidence_status": {...},
    "qa_report": {...},
    "bundle_summary": {...}
}
```

### GET /overrides

```json
{
    "brand_id": "uuid",
    "overrides_json": {
        "positioning.what_we_do": "Custom value"
    },
    "pinned_paths": ["positioning.what_we_do"],
    "updated_at": "iso-datetime"
}
```

### PATCH /overrides request

```json
{
    "overrides_json": {
        "field_to_update": "new value",
        "field_to_remove": null
    },
    "pinned_paths": ["new_path"]
}
```
