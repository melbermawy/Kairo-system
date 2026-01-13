# PR-7 Truthfulness Patch

Patches PR-7 to use accurate language: tests verify **data isolation by brand_id**, NOT ownership/auth enforcement.

---

## Diff Summary

| File | Change |
|------|--------|
| `tests/brandbrain/test_pr7_api_surface.py` | Renamed class, updated docstrings |
| `docs/pr_checks/pr7_api_surface_verification.md` | Added auth status section, fixed wording |

---

## 1. Test File Changes

### File: `tests/brandbrain/test_pr7_api_surface.py`

#### Module docstring (lines 1-23)

**Before:**
```python
"""
PR-7 Tests: API Surface + Contract Tests + Performance Guards.

Tests for all read-path and work-path endpoints per spec Section 10.

Test Categories:
A) Contract Tests: Response shapes match spec interfaces
B) Include Params: ?include=evidence,qa,bundle,full
C) Overrides CRUD: GET/PATCH /overrides
D) Cross-Brand Security: Ownership enforcement
E) Query Count: Bounded queries (no N+1)
F) Read-Path Boundary: No side effects on read endpoints

Per spec Section 1.1 (Performance & Latency Contracts):
...
"""
```

**After:**
```python
"""
PR-7 Tests: API Surface + Contract Tests + Performance Guards.

Tests for all read-path and work-path endpoints per spec Section 10.

Test Categories:
A) Contract Tests: Response shapes match spec interfaces
B) Include Params: ?include=evidence,qa,bundle,full
C) Overrides CRUD: GET/PATCH /overrides
D) Cross-Brand Data Isolation: brand_id scoping (NO auth enforcement)
E) Query Count: Bounded queries (no N+1)
F) Read-Path Boundary: No side effects on read endpoints

NOTE: Auth/ownership enforcement is NOT implemented (out of scope for PRD v1).
      All endpoints are publicly accessible. Tests verify data isolation by
      brand_id in the URL path only, not authorization.

Per spec Section 1.1 (Performance & Latency Contracts):
...
"""
```

#### Class rename (line 545-546)

**Before:**
```python
class TestCrossBrandSecurity:
    """Test brand ownership enforcement across all endpoints."""
```

**After:**
```python
class TestCrossBrandDataIsolation:
    """Test data isolation by brand_id in URL path (no auth/ownership enforcement)."""
```

---

## 2. Verification Doc Changes

### File: `docs/pr_checks/pr7_api_surface_verification.md`

#### New section added after title

```markdown
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
```

#### Summary section (line 4 changed)

**Before:**
```markdown
4. **Cross-brand security**: Ownership enforcement tests
```

**After:**
```markdown
4. **Cross-brand data isolation**: Tests verify brand_id scoping (no auth)
```

#### Invariants table (line 233 changed)

**Before:**
```markdown
| Cross-brand data isolation | 5 security tests verify 404/empty responses |
```

**After:**
```markdown
| Cross-brand data isolation | 5 tests verify brand_id scoping (404/empty for other brands) |
```

---

## 3. Test Output

```
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.4.2, pluggy-1.5.0
django: version: 5.2.9, settings: kairo.settings_test (from ini)
rootdir: /Users/mohamed/Documents/Kairo-system
collected 35 items

tests/brandbrain/test_pr7_api_surface.py::TestLatestSnapshotContract::test_compact_response_has_required_fields PASSED [  2%]
tests/brandbrain/test_pr7_api_surface.py::TestLatestSnapshotContract::test_compact_response_excludes_verbose_fields PASSED [  5%]
tests/brandbrain/test_pr7_api_surface.py::TestLatestSnapshotContract::test_full_response_includes_all_fields PASSED [  8%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesContract::test_get_overrides_has_required_fields PASSED [ 11%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesContract::test_patch_overrides_returns_updated_data PASSED [ 14%]
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_evidence_only PASSED [ 17%]
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_qa_only PASSED [ 20%]
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_bundle_only PASSED [ 22%]
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_comma_separated PASSED [ 25%]
tests/brandbrain/test_pr7_api_surface.py::TestIncludeParams::test_include_full_returns_all PASSED [ 28%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_get_overrides_empty_when_none_exist PASSED [ 31%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_get_overrides_returns_existing PASSED [ 34%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_creates_overrides_if_not_exist PASSED [ 37%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_merges_overrides PASSED [ 40%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_null_removes_override PASSED [ 42%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_replaces_pinned_paths PASSED [ 45%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_rejects_invalid_overrides_type PASSED [ 48%]
tests/brandbrain/test_pr7_api_surface.py::TestOverridesCRUD::test_patch_rejects_invalid_pinned_type PASSED [ 51%]
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandDataIsolation::test_latest_returns_404_for_other_brands_snapshot PASSED [ 54%]
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandDataIsolation::test_history_returns_empty_for_other_brand PASSED [ 57%]
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandDataIsolation::test_overrides_isolated_between_brands PASSED [ 60%]
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandDataIsolation::test_status_returns_404_for_other_brands_run PASSED [ 62%]
tests/brandbrain/test_pr7_api_surface.py::TestCrossBrandDataIsolation::test_patch_overrides_only_affects_own_brand PASSED [ 65%]
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_latest_query_count_compact PASSED [ 68%]
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_latest_query_count_full PASSED [ 71%]
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_history_query_count PASSED [ 74%]
tests/brandbrain/test_pr7_api_surface.py::TestQueryCount::test_overrides_get_query_count PASSED [ 77%]
tests/brandbrain/test_pr7_api_surface.py::TestReadPathBoundary::test_get_latest_no_side_effects PASSED [ 80%]
tests/brandbrain/test_pr7_api_surface.py::TestReadPathBoundary::test_get_history_no_side_effects PASSED [ 82%]
tests/brandbrain/test_pr7_api_surface.py::TestReadPathBoundary::test_get_overrides_no_side_effects PASSED [ 85%]
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_latest_invalid_brand_id PASSED [ 88%]
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_latest_nonexistent_brand PASSED [ 91%]
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_overrides_patch_invalid_json PASSED [ 94%]
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_overrides_patch_nonexistent_brand PASSED [ 97%]
tests/brandbrain/test_pr7_api_surface.py::TestErrorHandling::test_history_invalid_pagination PASSED [100%]

============================== 35 passed in 0.96s ==============================
```

---

## 4. What Changed

| Before | After |
|--------|-------|
| `TestCrossBrandSecurity` | `TestCrossBrandDataIsolation` |
| "Ownership enforcement" | "Data isolation by brand_id" |
| Implied auth exists | Explicit: auth NOT implemented |

---

## 5. What Did NOT Change

- No endpoint behavior changes
- No query logic changes
- No new auth/middleware/decorators added
- Test assertions unchanged
- All 35 tests pass identically
