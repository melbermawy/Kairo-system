# PR0 Review Document

**PR:** PR0 - Opportunities v2 Foundational Scaffolding
**Date:** 2026-01-18
**Status:** Ready for Review
**Author:** Claude Opus 4.5
**Spec Reference:** [opportunities_v1_prd.md](specs/opportunities_v1_prd.md) v1.2

---

## 1. Summary of What Changed

### Files Touched

| File | Change Type | Description |
|------|-------------|-------------|
| `kairo/core/enums.py` | Modified | Added `TodayBoardState` enum with 5 states |
| `kairo/hero/dto.py` | Modified | Updated `TodayBoardMetaDTO` with state machine fields, added `EvidenceShortfallDTO`, updated `RegenerateResponseDTO` |
| `kairo/hero/services/today_service.py` | Rewritten | Implemented read-only GET logic with state machine |
| `kairo/hero/api_views.py` | Modified | Updated endpoint docstrings and 202 response for regenerate |
| `kairo/core/api/views.py` | Modified | Added contract authority endpoints (health, openapi) |
| `kairo/core/api/urls.py` | Modified | Added routes for health and openapi endpoints |
| `tests/test_opportunities_v2_golden_path.py` | Created | Golden path test harness (structure only) |

### New Abstractions

1. **TodayBoardState Enum** - 5-state machine for board lifecycle
   - `not_generated_yet`: Brand exists, no generation run
   - `generating`: Background job running
   - `ready`: Board available with opportunities
   - `insufficient_evidence`: Evidence quality gates failed
   - `error`: Generation failed

2. **EvidenceShortfallDTO** - Details about evidence insufficiency
   - `required_items`, `found_items`
   - `required_platforms`, `found_platforms`, `missing_platforms`
   - `transcript_coverage`, `min_transcript_coverage`

3. **RegenerateResponseDTO (Updated)** - Async response pattern
   - `status: "accepted"` (always 202)
   - `job_id`: UUID for tracking
   - `poll_url`: Endpoint for polling status

4. **Contract Authority Constants**
   - `CONTRACT_VERSION = "1.0.0"`
   - `MIN_FRONTEND_VERSION = "1.0.0"`

5. **Cache Key Format**
   - Board: `today_board:v2:{brand_id}`
   - Job tracking: `today_job:v2:{brand_id}`

### What Intentionally Does NOT Work Yet

1. **Actual generation** - `_enqueue_generation_job()` is a stub that only sets cache keys
2. **Persisted OpportunitiesBoard** - `_get_persisted_board()` returns `None`
3. **Full OpenAPI schema generation** - `/api/openapi.json` returns minimal stub
4. **Evidence quality gates** - Only checks count, not full usability gates
5. **Anti-cheat tests** - Test structure exists but tests are skipped
6. **First-run auto-enqueue** - Depends on having actual evidence items

---

## 2. State Machine Walkthrough

### State Definitions

| State | Produced By | Response Shape |
|-------|-------------|----------------|
| `not_generated_yet` | GET on brand with no evidence and no generation history | `opportunities: []`, `remediation: "Connect sources..."` |
| `generating` | POST /regenerate/ or first-run auto-enqueue | `opportunities: []`, `job_id: "uuid"` |
| `ready` | Background job completed successfully | `opportunities: [...]`, `cache_hit: true/false` |
| `insufficient_evidence` | Background job found evidence gates failed | `opportunities: []`, `evidence_shortfall: {...}` |
| `error` | Background job failed (LLM error, timeout) | `opportunities: []` or stale cached |

### State Transitions

```
                                POST /regenerate/
                                       │
                                       ▼
┌──────────────────┐         ┌──────────────────┐
│ not_generated_yet│────────▶│    generating    │◀─┐
└──────────────────┘         └──────────────────┘  │
       │                              │            │
       │ First-run auto-enqueue      │            │ POST /regenerate/
       └──────────────────────────────┘            │
                                                   │
                    ┌──────────────────────────────┤
                    │                              │
                    ▼                              │
           ┌──────────────────┐                   │
           │      ready       │───────────────────┘
           └──────────────────┘
                    ▲
                    │ Success
                    │
┌──────────────────────────────┐
│    insufficient_evidence     │───────────────────┐
└──────────────────────────────┘                   │
           ▲                                       │
           │ Evidence gates failed                 │
           │                                       │ POST /regenerate/
┌──────────────────┐                              │
│      error       │───────────────────────────────┘
└──────────────────┘
           ▲
           │ LLM/timeout error
           │
           └──────────────── generating
```

### Allowed Code Paths for State Transitions

| Transition | Allowed Trigger | Code Path |
|------------|-----------------|-----------|
| any → `generating` | POST /regenerate/ | `today_service.regenerate_today_board()` |
| `not_generated_yet` → `generating` | First-run auto-enqueue | `today_service.get_today_board()` with sufficient evidence |
| `generating` → `ready` | Background job success | Future: `generate_today_board_task.complete()` |
| `generating` → `insufficient_evidence` | Evidence gates fail | Future: `generate_today_board_task.complete()` |
| `generating` → `error` | Job failure | Future: `generate_today_board_task.fail()` |

---

## 3. Endpoint Guarantees

### GET /api/brands/{brand_id}/today/

**Allowed:**
- Read from cache (Redis)
- Read from DB (OpportunitiesBoard)
- Check if generation job is running
- Check evidence count (for first-run auto-enqueue)
- Auto-enqueue ONE generation job (first-run only)

**Forbidden:**
- Call LLMs
- Block on generation
- Call Apify actors
- Enqueue multiple jobs
- Modify board state directly

**What Would Constitute a Regression:**
- Adding LLM calls inside `get_today_board()`
- Adding synchronous evidence fetching
- Returning fabricated/stub opportunities
- Blocking the request on generation completion

### POST /api/brands/{brand_id}/today/regenerate/

**Allowed:**
- Validate brand exists
- Invalidate cache
- Enqueue background job
- Return immediately with job_id

**Forbidden:**
- Call LLMs synchronously
- Wait for generation to complete
- Return opportunities in response

**What Would Constitute a Regression:**
- Adding synchronous generation
- Returning full TodayBoardDTO in response (except legacy mode)
- Not invalidating cache before enqueue

### GET /api/health/

**Allowed:**
- Return contract version info
- Return health status

**Forbidden:**
- Heavy computation
- Database queries (should be instant)

### GET /api/openapi.json

**Allowed:**
- Return OpenAPI schema
- Set X-Contract-Version header

**Forbidden:**
- Dynamic schema generation on every request (should be cached)

---

## 4. Contract Authority Confirmation

### Where DTOs Live

All DTOs are defined in **`kairo/hero/dto.py`**:
- `TodayBoardDTO` - Main board response
- `TodayBoardMetaDTO` - Board metadata with state machine
- `OpportunityDTO` - Single opportunity
- `EvidenceShortfallDTO` - Evidence insufficiency details
- `RegenerateResponseDTO` - Async regenerate response

### How OpenAPI Is Generated

**Current (PR0):** Stub implementation returns minimal schema structure.

**Future (later PRs):**
1. DTOs will be registered with Django Ninja or drf-spectacular
2. `python manage.py export_openapi > openapi.json` generates schema
3. CI validates schema matches committed `openapi.json`
4. Frontend fetches from `/api/openapi.json` at build time

### How Contract Versioning Works

```python
# kairo/core/api/views.py
CONTRACT_VERSION = "1.0.0"      # Bump on breaking DTO changes
MIN_FRONTEND_VERSION = "1.0.0"  # Minimum compatible frontend
```

**Versioning Rules:**
- Add optional field → No bump
- Add required field → **Version bump**
- Remove field → **Version bump** + deprecation period
- Rename field → **Forbidden** (add new, deprecate old)
- Change field type → **Version bump**

**Runtime Verification:**
- Frontend calls `/api/health/` at startup
- Compares `contract_version` with its `MIN_BACKEND_VERSION`
- Compares its version with backend's `min_frontend_version`
- Shows warning/blocking modal on mismatch

### What Breaks If Someone Violates This

1. **If someone edits DTO fields without version bump:**
   - Frontend TypeScript types won't match
   - Runtime errors on field access
   - CI should catch via schema diff (when implemented)

2. **If someone adds LLM calls to GET endpoint:**
   - 500ms budget violated
   - User sees slow load times
   - Potential billing spikes

3. **If someone returns stubs in v2 path:**
   - Frontend treats fake data as real
   - Downstream flows (F2, concepts) break
   - Analytics become meaningless

---

## 5. Known Gaps (INTENTIONAL)

### Deferred to Later PRs

| Gap | Why Deferred | Which PR |
|-----|--------------|----------|
| Actual generation logic | Out of scope for PR0 | PR1 |
| OpportunitiesBoard model | Needs schema design | PR1 |
| Evidence quality gates | Needs full EvidenceDTO pipeline | PR1 |
| Full OpenAPI generation | Needs Django Ninja setup | PR1 or PR2 |
| Anti-cheat test assertions | Needs generation to test | PR1+ |
| First-run auto-enqueue with evidence | Needs evidence fixtures | PR1 |
| Celery/RQ task integration | Needs task queue setup | PR1 |
| Cache TTL tuning | Performance optimization | PR2+ |

### Stub Implementations

```python
# today_service.py

def _get_persisted_board(brand_id: UUID) -> TodayBoardDTO | None:
    """PR0 STUB: Returns None - no OpportunitiesBoard model yet."""
    return None

def _enqueue_generation_job(brand_id: UUID, ...) -> str:
    """PR0 STUB: Creates job_id but does NOT actually enqueue work."""
    # Just sets cache key with job_id
    # Actual Celery/RQ integration in PR1
```

---

## 6. Ways This Could Break If Someone Is Careless

### Concrete Failure Scenarios

| Scenario | What Would Happen | Guardrails |
|----------|-------------------|------------|
| Add `llm_client.call()` inside `get_today_board()` | 10+ second response times, billing spikes | Code review, test for response time |
| Return stub opportunities in v2 path | Frontend shows fake data, F2 breaks | Test: `test_empty_brand_returns_empty_opportunities` |
| Forget to invalidate cache on regenerate | Stale data returned forever | Test: `test_regenerate_invalidates_cache` |
| Add Apify import in hero/engines | Evidence fetched on request path | CI: `test_no_apify_imports_in_hero_engine` (future) |
| Change DTO field without version bump | Frontend type errors at runtime | CI schema diff (future) |
| Remove `?legacy=true` support too early | Existing frontend calls break | Deprecation period + changelog |

### What Guardrails Exist

1. **Type System** - Pydantic DTOs enforce field types
2. **Tests** - `test_opportunities_v2_golden_path.py` validates invariants
3. **State Machine** - Explicit enum prevents invalid states
4. **Docstrings** - Critical functions have "MUST NOT" warnings
5. **Code Comments** - `# PR0 STUB` marks incomplete implementations

### What Is Still Relying on Discipline

1. **No CI enforcement yet** for:
   - Response time budgets
   - No-Apify-imports rule
   - Schema drift detection

2. **No automated checks** for:
   - LLM calls in GET path
   - Stub generation in v2 path

3. **Manual review required** for:
   - All changes to `today_service.get_today_board()`
   - All changes to TodayBoardDTO fields
   - Any imports added to `kairo/hero/engines/`

---

## 7. Verification Checklist

### PR0 Success Criteria

- [x] System compiles
- [x] Endpoints exist and return correct empty/degraded states
- [x] Nothing expensive runs accidentally
- [x] GET /today/ returns state-based responses
- [x] POST /regenerate/ returns 202 with job_id
- [x] Contract authority endpoints exist
- [x] Test harness structure created

### How to Verify

```bash
# Run tests
pytest tests/test_opportunities_v2_golden_path.py -v

# Check endpoints manually
curl http://localhost:8000/api/health
curl http://localhost:8000/api/openapi.json
curl http://localhost:8000/api/brands/{brand_id}/today
curl -X POST http://localhost:8000/api/brands/{brand_id}/today/regenerate
```

### Expected Responses

**GET /api/health:**
```json
{
  "status": "healthy",
  "contract_version": "1.0.0",
  "min_frontend_version": "1.0.0"
}
```

**GET /api/brands/{brand_id}/today (new brand, no evidence):**
```json
{
  "brand_id": "...",
  "snapshot": {...},
  "opportunities": [],
  "meta": {
    "state": "not_generated_yet",
    "remediation": "Connect Instagram or TikTok sources...",
    "evidence_shortfall": {
      "required_items": 8,
      "found_items": 0,
      ...
    }
  }
}
```

**POST /api/brands/{brand_id}/today/regenerate:**
```json
{
  "status": "accepted",
  "job_id": "abc-123-...",
  "poll_url": "/api/brands/{brand_id}/today/"
}
```

---

## 8. Next Steps

After this PR merges:

1. **PR1:** Implement actual generation logic
   - Add OpportunitiesBoard model
   - Implement background task
   - Wire up evidence pipeline

2. **PR2:** Add full evidence quality gates
   - Usability checks (text length, distinct authors, duplicates)
   - Anti-cheat validation

3. **PR3:** Full OpenAPI generation
   - Django Ninja or drf-spectacular integration
   - CI schema validation

4. **PR4:** Performance optimization
   - Cache TTL tuning
   - Response time monitoring
