# Opportunity + Concept Spec v1

**Version:** 1.2
**Last Updated:** 2026-01-18
**Author:** Claude Opus 4.5
**Status:** Draft for Review
**Revision:** Hardens trigger model, adds TodayBoard state machine, runtime contract authority, evidence usability gates, golden path anti-cheat enforcement

---

## 0. Purpose and Non-Goals

### What This Spec Covers

This document defines the complete implementation for Opportunities and Concept (v1):

1. **Opportunities Engine Refactor** - Transform the existing LinkedIn-centric stub system into a production-ready IG/TikTok-first opportunity generation system with real external signals.

2. **Evidence-First Architecture** - Normalize external data (from Apify actors) into a stable `EvidenceDTO` contract that insulates the LLM pipeline from source schema churn.

3. **Concept Builder (v1)** - A structured intermediate artifact between opportunity selection and content package generation, capturing user intent before expensive downstream work.

4. **Contract Authority** - Establish backend DTOs as the single source of truth with enforced OpenAPI contracts to prevent `kairo-frontend` drift.

### What This Spec Does NOT Cover

- **Content Package Engine (F2)** - Variant generation, editing, and publishing workflows are out of scope. The existing F2 pipeline remains unchanged.
- **Editor/Composer UI** - No changes to content editing experience.
- **Full Growth Loop** - Post-publish analytics, learning engine refinements, and A/B testing are future work.
- **Frontend Implementation** - We define API contracts and UX states; `kairo-frontend` implementation details are separate.

### Definition of Done (v1)

1. GET `/api/brands/{brand_id}/today/` is **strictly read-only** - returns cached/persisted board or status state, **NEVER triggers LLM generation**.
2. POST `/api/brands/{brand_id}/today/regenerate/` is the **ONLY endpoint** that triggers LLM-based generation.
3. Evidence is read from existing BrandBrain `NormalizedEvidenceItem` records - **NO Apify calls on request path**.
4. Build Concept flow persists a ConceptDTO linked to opportunity + brand.
5. All DTOs are exported via OpenAPI with `kairo-frontend` type generation.
6. Hard performance budgets enforced with fail-fast behavior.
7. Evidence quality gates prevent synthesis from thin/low-signal data.
8. Golden path integration test validates end-to-end with realistic fixtures (including adversarial fixtures).

---

## 0.1 Critical Invariants (Non-Negotiable)

These invariants prevent repeating BrandBrain v1 mistakes. Each has an enforcement mechanism and explicit failure behavior.

### INV-1: GET /today is Strictly Read-Only (CRITICAL)

**Rationale:** BrandBrain v1 suffered from slow load times because generation happened on the request path. GET must be instant.

**Enforcement:**
- GET `/api/brands/{brand_id}/today/` MUST NEVER:
  - Call LLMs
  - Trigger synchronous generation
  - Call Apify actors
  - Enqueue background jobs (except first-run auto-enqueue, see §0.2)
- GET MUST ONLY:
  - Read from cache (Redis)
  - Read from DB (persisted `OpportunitiesBoard`)
  - Return a status state if no board exists

**Failure Behavior:** If no cached/persisted board exists:
- Return `state: "not_generated_yet"` (NOT an error)
- Include `meta.remediation` with instructions to POST /regenerate/
- Return zero opportunities (empty list)

### INV-2: No Apify Calls on Request Path

**Rationale:** BrandBrain v1 suffered from surprise billing because evidence ingestion happened on the request path. Opportunities must read pre-computed evidence only.

**Enforcement:**
- `opportunities_engine.py` MUST NOT import or call any Apify client code
- `evidence_service.get_evidence_for_brand()` reads from `NormalizedEvidenceItem` table only
- CI test: `test_no_apify_imports_in_hero_engine` asserts no `kairo.integrations.apify` imports in `kairo/hero/engines/`

**Failure Behavior:** If evidence is missing or stale:
- Return `meta.degraded = true` with `meta.reason = "insufficient_evidence"`
- Include `meta.remediation` with actionable instructions: "Connect Instagram or TikTok sources in Settings, then run BrandBrain compile"
- Return zero opportunities (empty list), NOT fabricated/stub opportunities

```python
# kairo/hero/engines/opportunities_engine.py

# FORBIDDEN - these imports must never appear:
# from kairo.integrations.apify import ...
# from kairo.brandbrain.ingestion import ...

# ALLOWED - read-only evidence access:
from kairo.hero.services.evidence_service import get_evidence_for_brand
```

### INV-3: No Fabricated Data

**Rationale:** BrandBrain v1 returned stub/mock data that frontend treated as real, causing confusion and broken UI states.

**Enforcement:**
- Remove all `_generate_stub_opportunities()` logic from v2 path
- If evidence quality gates fail, return honest empty state
- `meta.degraded` + `meta.reason` must explain the real situation
- CI test: `test_no_stub_generation_in_v2_path` asserts stub code is not reachable in v2

**Failure Behavior:** When synthesis cannot run:
```json
{
  "opportunities": [],
  "meta": {
    "degraded": true,
    "reason": "insufficient_evidence",
    "evidence_shortfall": {
      "required_items": 8,
      "found_items": 2,
      "missing_platforms": ["tiktok"]
    },
    "remediation": "Connect TikTok source and run BrandBrain compile to generate opportunities."
  }
}
```

### INV-4: Optional Fields Are Truly Optional

**Rationale:** `kairo-frontend` built UI logic dependent on `thumbnail_url` and other best-effort fields, causing crashes when they were missing.

**Enforcement:**
- All optional fields documented with explicit "MAY BE NULL/MISSING" in DTO docstrings
- `kairo-frontend` contract note in this spec (see §5.6)
- OpenAPI schema marks optional fields as `nullable: true`
- Golden test includes fixtures with missing optional fields

**Failure Behavior:** `kairo-frontend` must:
- Render evidence preview cards without thumbnails (text-only fallback)
- Display "—" or empty state for missing metrics
- Never call `.thumbnail_url.startsWith()` without null check

---

## 0.2 TodayBoard State Machine (Generation Trigger Model)

This section defines when and how opportunity generation happens. This is **the most critical behavior to understand**.

### State Machine

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      TODAYBOARD STATE MACHINE                            │
│                                                                          │
│  ┌──────────────────┐                                                   │
│  │ not_generated_yet│◄─────────── Brand created, no generation run      │
│  └────────┬─────────┘                                                   │
│           │                                                              │
│           │ POST /regenerate/ OR first-run auto-enqueue                 │
│           ▼                                                              │
│  ┌──────────────────┐                                                   │
│  │    generating    │◄─────────── Background job running                │
│  └────────┬─────────┘                                                   │
│           │                                                              │
│           ├──────────────────────┬──────────────────────────────────────┤
│           │ Success              │ Evidence insufficient   │ Error      │
│           ▼                      ▼                         ▼            │
│  ┌──────────────────┐  ┌────────────────────────┐  ┌─────────────────┐ │
│  │      ready       │  │ insufficient_evidence  │  │      error      │ │
│  └──────────────────┘  └────────────────────────┘  └─────────────────┘ │
│           │                                                              │
│           │ POST /regenerate/ (user-initiated refresh)                  │
│           │                                                              │
│           └──────────────────────► generating                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### State Definitions

| State | Meaning | GET /today/ Response |
|-------|---------|---------------------|
| `not_generated_yet` | Brand exists, but no generation has ever run | `state: "not_generated_yet"`, `opportunities: []` |
| `generating` | Background job is running | `state: "generating"`, `opportunities: []` (or stale cached if exists) |
| `ready` | Board available with opportunities | `state: "ready"`, `opportunities: [...]` |
| `insufficient_evidence` | Evidence quality gates failed | `state: "insufficient_evidence"`, `opportunities: []`, remediation included |
| `error` | Generation failed (LLM error, timeout, etc.) | `state: "error"`, `opportunities: []` (or stale cached if exists) |

### Endpoint Behavior (BINDING)

**GET `/api/brands/{brand_id}/today/`**

```
ALWAYS:
  - Read-only (no side effects except first-run auto-enqueue)
  - Returns within 500ms (cache hit) or 2s (DB read)
  - NEVER calls LLMs
  - NEVER blocks on generation

IF board exists in cache (Redis):
  - Return cached board with state: "ready"
  - Set meta.cache_hit = true

ELSE IF board exists in DB:
  - Return persisted board with state: "ready"
  - Populate cache for next request

ELSE IF generation job is running:
  - Return state: "generating"
  - Include job_id for polling
  - Return empty opportunities OR stale cached board (if exists)

ELSE IF brand has valid evidence but no board:
  - FIRST TIME ONLY: Auto-enqueue generation job
  - Return state: "generating"
  - This is the ONLY case where GET has a side effect

ELSE (no evidence, no board):
  - Return state: "not_generated_yet"
  - Include remediation: "Connect sources and run BrandBrain compile"
```

**POST `/api/brands/{brand_id}/today/regenerate/`**

```
ALWAYS:
  - The ONLY way to explicitly trigger generation
  - Enqueues background job (does not block)
  - Returns immediately with job_id

BEHAVIOR:
  - Invalidate cache
  - Enqueue generation job (Celery/RQ)
  - Return 202 Accepted with job_id
  - Client polls GET /today/ for completion

RESPONSE:
{
  "status": "accepted",
  "job_id": "abc-123",
  "poll_url": "/api/brands/{brand_id}/today/"
}
```

### First-Run Behavior (Auto-Enqueue)

When a brand has valid evidence but no `OpportunitiesBoard`:
1. GET /today/ detects this condition
2. System auto-enqueues ONE generation job
3. GET returns `state: "generating"` immediately (no blocking)
4. Subsequent GETs return `state: "generating"` until job completes
5. After completion, GETs return the board

**This is the ONLY case where GET triggers work, and it is:**
- Non-blocking (returns immediately)
- Idempotent (only enqueues if no job running)
- One-time per brand (subsequent refreshes require POST)

### Implementation

```python
# kairo/hero/services/today_service.py

class TodayBoardState(str, Enum):
    NOT_GENERATED_YET = "not_generated_yet"
    GENERATING = "generating"
    READY = "ready"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ERROR = "error"


def get_today_board(brand_id: UUID) -> TodayBoardDTO:
    """
    GET /today/ implementation.

    CRITICAL: This function MUST NOT call LLMs or block on generation.
    """

    # 1. Check cache first (fast path)
    cached = cache.get(f"today_board:v2:{brand_id}")
    if cached:
        board = TodayBoardDTO.model_validate_json(cached)
        board.meta.cache_hit = True
        return board

    # 2. Check for persisted board
    persisted = OpportunitiesBoard.objects.filter(brand_id=brand_id).first()
    if persisted and persisted.state == TodayBoardState.READY:
        board = persisted.to_dto()
        board.meta.cache_hit = False
        _populate_cache(brand_id, board)
        return board

    # 3. Check if generation job is running
    if is_generation_job_running(brand_id):
        return TodayBoardDTO(
            brand_id=brand_id,
            state=TodayBoardState.GENERATING,
            opportunities=[],
            meta=TodayBoardMetaDTO(
                state=TodayBoardState.GENERATING,
                job_id=get_running_job_id(brand_id),
            ),
        )

    # 4. Check if evidence exists (for first-run auto-enqueue)
    evidence_count = NormalizedEvidenceItem.objects.filter(brand_id=brand_id).count()
    if evidence_count >= MIN_EVIDENCE_ITEMS:
        # First-run: auto-enqueue generation
        job_id = enqueue_generation_job(brand_id)
        return TodayBoardDTO(
            brand_id=brand_id,
            state=TodayBoardState.GENERATING,
            opportunities=[],
            meta=TodayBoardMetaDTO(
                state=TodayBoardState.GENERATING,
                job_id=job_id,
            ),
        )

    # 5. No evidence, no board
    return TodayBoardDTO(
        brand_id=brand_id,
        state=TodayBoardState.NOT_GENERATED_YET,
        opportunities=[],
        meta=TodayBoardMetaDTO(
            state=TodayBoardState.NOT_GENERATED_YET,
            remediation="Connect Instagram or TikTok sources in Settings, then run BrandBrain compile.",
        ),
    )


def regenerate_today_board(brand_id: UUID) -> RegenerateResponseDTO:
    """
    POST /regenerate/ implementation.

    This is the ONLY endpoint that triggers generation.
    """

    # Invalidate cache
    cache.delete(f"today_board:v2:{brand_id}")

    # Enqueue background job
    job_id = enqueue_generation_job(brand_id, force=True)

    return RegenerateResponseDTO(
        status="accepted",
        job_id=job_id,
        poll_url=f"/api/brands/{brand_id}/today/",
    )
```

---

## 1. Current World Model (Phase 0 Reality)

This section anchors the refactor in what actually exists today, verified by codebase inspection.

### Backend: What's Real

| Component | Status | Location |
|-----------|--------|----------|
| Opportunity Model | REAL - persisted with deterministic IDs | [models.py:318-388](kairo/core/models.py#L318-L388) |
| OpportunityDTO | REAL - canonical API contract | [dto.py:123-149](kairo/hero/dto.py#L123-L149) |
| OpportunityDraftDTO | REAL - graph→engine internal contract | [dto.py:151-181](kairo/hero/dto.py#L151-L181) |
| TodayBoardDTO | REAL - complete board response shape | [dto.py:475-484](kairo/hero/dto.py#L475-L484) |
| Opportunities Engine | REAL - full orchestration | [opportunities_engine.py:65-261](kairo/hero/engines/opportunities_engine.py#L65-L261) |
| Opportunities Graph | REAL - 2-node LLM synthesis + scoring | [opportunities_graph.py:724-856](kairo/hero/graphs/opportunities_graph.py#L724-L856) |
| Deduplication | REAL - Jaccard similarity ≥0.75 | [opportunities_engine.py:402-459](kairo/hero/engines/opportunities_engine.py#L402-L459) |
| Degraded Mode | REAL - stub fallback persisted for F2 continuity | [opportunities_engine.py:543-703](kairo/hero/engines/opportunities_engine.py#L543-L703) |
| Validation (Rubric §4) | REAL - why_now, title, angle, taboo checks | [opportunities_graph.py:584-632](kairo/hero/graphs/opportunities_graph.py#L584-L632) |
| NormalizedEvidenceItem | REAL - in BrandBrain module | [kairo/brandbrain/models.py:161-250](kairo/brandbrain/models.py#L161-L250) |

### Backend: What's Stubbed (Must Be Replaced)

| Component | Status | Evidence |
|-----------|--------|----------|
| External Signals | STUB - fixture files or empty bundle | [opportunities_engine.py:340-366](kairo/hero/engines/opportunities_engine.py#L340-L366) returns empty bundle by default |
| Signal Types | LINKEDIN-CENTRIC | [opportunities_graph.py:659-662](kairo/hero/graphs/opportunities_graph.py#L659-L662) only maps `linkedin` and `x` channels |
| Learning Summary | IN-MEMORY DEFAULT | [opportunities_engine.py:311-337](kairo/hero/engines/opportunities_engine.py#L311-L337) returns default summary |
| Evidence Bridge | MISSING | No connection between BrandBrain `NormalizedEvidenceItem` and opportunities graph |
| Stub Opportunities | HARMFUL | `_generate_stub_opportunities()` creates fake data that pollutes the system |

### Frontend (`kairo-frontend`): Current State

- **Today page exists** but renders mock data or fixture-based opportunities
- No Build Concept flow implemented
- UI components are visual reference only - not wired to real endpoints
- **Known issue:** Some components assume `thumbnail_url` is always present

### Key Gaps Driving This Spec

1. **No real signals** - ExternalSignalBundleDTO is populated from fixtures, not BrandBrain evidence
2. **LinkedIn-only channels** - Graph prompts and validation hardcode LinkedIn/X; IG/TikTok missing
3. **No evidence traceability** - Opportunities don't link back to specific evidence items
4. **No caching** - Every GET /today triggers full LLM pipeline (2 calls)
5. **No Concept artifact** - User goes directly from opportunity to content package (too big a leap)
6. **Stub pollution** - Fake opportunities persist to DB and confuse downstream flows

---

## 2. Product Vision Lock (What an Opportunity Is)

### Definition

An **opportunity** is a brand-relevant external signal distilled into an actionable creative angle. It is NOT:

- A random post we scraped
- A generic content idea
- A platform-specific format suggestion
- A fabricated stub to make the UI look populated

An opportunity answers: "Given what's happening in the world right now, what should this brand say and why does it matter now?"

### v1 Opportunity Types

| Type | Definition | Evidence Requirement |
|------|------------|---------------------|
| `trend` | Timely topic gaining traction on target platforms | Must cite specific trending hashtag, audio, or topic with recency < 7 days |
| `competitive` | Angle that differentiates from competitor activity | Must cite competitor post or category pattern |
| `evergreen` | Pillar-aligned topic with recurring relevance | Must explain enduring customer need (not "always relevant") |
| `community_signal` | Emerging theme from audience engagement patterns | Must cite engagement pattern or UGC signal |

Note: `campaign` type exists in the model but is user-initiated (manual opportunity creation), not AI-generated in v1.

### What Qualifies (Acceptance Criteria)

An opportunity is valid if:

1. **Specific title** - Not "Leverage X for engagement" but "The $9 coffee trick blowing up on TikTok"
2. **Grounded why_now** - References evidence timestamp, trend velocity, or specific event
3. **Actionable angle** - A human can understand what content to create
4. **Brand-safe** - Passes taboo checks, tone-appropriate
5. **Evidence-backed** - Links to ≥1 EvidenceItem with valid `evidence_ids` (REQUIRED, not optional)

### What Disqualifies

- Generic marketing speak ("Drive engagement with thought leadership")
- Vacuous timing ("always relevant", "timeless insight")
- Platform-agnostic fluff (must specify channel fit)
- Taboo violations (score = 0)
- Missing evidence citations (`evidence_ids` empty)

---

## 3. User Flow and UX States (Today → Opportunity → Concept)

### Primary Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TODAY BOARD                                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐   │
│  │ Opportunity  │ │ Opportunity  │ │ Opportunity  │ │ Opportunity  │   │
│  │    Card 1    │ │    Card 2    │ │    Card 3    │ │    Card 4    │   │
│  │              │ │              │ │              │ │              │   │
│  │  [Build →]   │ │  [Build →]   │ │  [Build →]   │ │  [Build →]   │   │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Click card
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      OPPORTUNITY DETAIL (Page)                           │
│                                                                          │
│  Title: "The $9 coffee trick blowing up on TikTok"                      │
│  Type: trend                                                            │
│  Angle: Gen Z baristas sharing markup breakdowns...                     │
│  Why Now: 12M views this week, 847 creator videos...                    │
│                                                                          │
│  Evidence:                                                               │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ @barista_sam (TikTok) - 2.1M views - "POV: I show you..."      │    │
│  │ @coffeewithkate (IG Reel) - 891K views - "The math isn't..."   │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  [ ◀ Back ]                              [ Build Concept → ] (PRIMARY)  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Click "Build Concept"
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       CONCEPT BUILDER (Modal/Page)                       │
│                                                                          │
│  REQUIRED:                                                               │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ What's your take? (angle/hook)                                  │    │
│  │ [We'll reveal our actual cost breakdown and compare to...]     │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Format: [ Short Video ▼ ]                                       │    │
│  │         (IG Reels / TikTok / YT Shorts)                        │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Who is this for?                                                │    │
│  │ [ ] Coffee enthusiasts discovering local roasters              │    │
│  │ [x] Budget-conscious millennials                                │    │
│  │ [ ] B2B cafe owners                                            │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  OPTIONAL (collapsed by default):                                        │
│  + Add proof points                                                      │
│  + Add CTA preference                                                    │
│  + Add constraints                                                       │
│                                                                          │
│  [ Cancel ]                                    [ Save Concept → ]        │
└─────────────────────────────────────────────────────────────────────────┘
```

### UX States (Aligned with State Machine §0.2)

| Backend State | UI State | UI Treatment |
|---------------|----------|--------------|
| `ready` + fresh cache | **Cached Fresh** | Instant render, show "Last updated X hours ago" |
| `ready` + stale cache | **Cached Stale** | Render cached, show "Refresh available" badge |
| `generating` | **Generating** | Show skeleton/spinner, poll every 2s |
| `insufficient_evidence` | **Insufficient Evidence** | Show empty state with remediation: "Connect Instagram or TikTok in Settings → Run BrandBrain compile" |
| `error` | **Generation Failed** | Show error banner with retry option, render stale cached if available |
| `not_generated_yet` | **First Run** | Show onboarding: "Your opportunities are being prepared..." (auto-enqueued) |

### State-to-UI Mapping

```typescript
// kairo-frontend/src/pages/Today.tsx

function TodayPage({ board }: { board: TodayBoardDTO }) {
  switch (board.meta.state) {
    case "ready":
      return <OpportunitiesGrid opportunities={board.opportunities} />;

    case "generating":
      return (
        <div>
          <Skeleton count={4} />
          <p>Generating your opportunities... (polling)</p>
        </div>
      );

    case "not_generated_yet":
      return (
        <EmptyState
          title="Preparing your first opportunities"
          description="We're analyzing your content sources. This usually takes 30-60 seconds."
          showSpinner
        />
      );

    case "insufficient_evidence":
      return (
        <EmptyState
          title="Not enough content to analyze"
          description={board.meta.remediation}
          action={<Button href="/settings/sources">Connect Sources</Button>}
        />
      );

    case "error":
      return (
        <ErrorState
          title="Generation failed"
          description="We couldn't generate opportunities. Please try again."
          action={<Button onClick={handleRegenerate}>Retry</Button>}
          // Show stale cached opportunities if available
          fallback={board.opportunities.length > 0 && (
            <OpportunitiesGrid
              opportunities={board.opportunities}
              stale
            />
          )}
        />
      );
  }
}
```

### Removed States (v1)

- ~~**First Run (cold start with LLM)**~~ - Now handled by `generating` state with auto-enqueue (see §0.2)
- ~~**Degraded (stub fallback)**~~ - Removed. We no longer fabricate stub opportunities.

### Key Principles

1. **Page, not drawer** - Opportunity detail is a full page for focus
2. **Primary CTA is Build Concept** - Not save, not dismiss, not "explore more"
3. **Evidence is visible** - Users should see what informed the opportunity
4. **Honest empty states** - If we can't generate, we say so with remediation steps
5. **No fake data** - Empty is better than fabricated

---

## 4. Contract Authority Strategy (How We Stop Drift)

### Hard Rule

**Backend DTOs (Pydantic) are the single source of truth.** `kairo-frontend` types are generated, never hand-authored.

### Contract Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CONTRACT AUTHORITY FLOW                          │
│                                                                          │
│  1. DEFINE (Backend: kairo-backend)                                     │
│     kairo/hero/dto.py                                                    │
│     └── OpportunityDTO, ConceptDTO, EvidenceDTO, etc.                   │
│         └── Pydantic v2 with Field constraints                          │
│                                                                          │
│  2. EXPORT (CI: kairo-backend)                                          │
│     python manage.py export_openapi > openapi.json                      │
│     └── Generates OpenAPI 3.1 schema from Pydantic models               │
│                                                                          │
│  3. GENERATE (CI: kairo-frontend)                                       │
│     npx openapi-typescript openapi.json -o src/api/generated/types.ts   │
│     └── TypeScript types from OpenAPI spec                              │
│                                                                          │
│  4. VALIDATE (CI Gate: both repos)                                      │
│     - openapi.json must be committed (no drift)                         │
│     - kairo-frontend build must pass with generated types               │
│     - Breaking changes require version bump + migration                 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Versioning Rules

| Change Type | Action Required |
|-------------|-----------------|
| Add optional field | No version bump. `kairo-frontend` ignores unknown fields. |
| Add required field | **Version bump** (v2). Migration plan required. |
| Remove field | **Version bump**. Deprecation period (2 releases). |
| Rename field | **Forbidden**. Add new field, deprecate old. |
| Change field type | **Version bump**. Migration plan required. |

### CI Gate Implementation

```yaml
# kairo-backend/.github/workflows/contract-check.yml
name: Contract Validation

on: [push, pull_request]

jobs:
  validate-contracts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Generate OpenAPI
        run: python manage.py export_openapi > openapi-generated.json

      - name: Check for drift
        run: diff openapi.json openapi-generated.json

      - name: Upload OpenAPI artifact
        uses: actions/upload-artifact@v4
        with:
          name: openapi-spec
          path: openapi.json
```

```yaml
# kairo-frontend/.github/workflows/type-check.yml
name: Type Validation

on: [push, pull_request]

jobs:
  validate-types:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download OpenAPI from backend
        # Fetch from backend repo or shared artifact
        run: curl -o openapi.json $BACKEND_OPENAPI_URL

      - name: Generate TypeScript types
        run: npx openapi-typescript openapi.json -o src/api/generated/types.ts

      - name: Type check
        run: npm run typecheck

      - name: Fail if types changed
        run: git diff --exit-code src/api/generated/types.ts
```

### Runtime Contract Authority (CRITICAL)

The CI-time contract generation above ensures types are synchronized at build time. However, this does NOT prevent:
- Frontend built against `main` branch schema
- Backend deployed with incompatible DTOs
- Runtime version mismatch between deployed frontend and backend

This section specifies **runtime guarantees** to prevent these failures.

#### Contract Versioning Strategy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    RUNTIME CONTRACT AUTHORITY                            │
│                                                                          │
│  Backend (kairo-backend)                  Frontend (kairo-frontend)      │
│  ────────────────────────                 ─────────────────────────      │
│                                                                          │
│  1. /api/openapi.json                     1. Build-time: fetch schema    │
│     - Versioned endpoint                     from release tag            │
│     - Returns schema version                                             │
│                                            2. Runtime: fetch version     │
│  2. /api/health/                              from /api/health/          │
│     - Returns contract_version                                           │
│     - Returns min_frontend_version         3. Compare versions           │
│                                               - Warn if mismatch         │
│  3. Response header:                          - Block if incompatible    │
│     X-Contract-Version: v1.2                                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Backend: Versioned Schema Endpoint

```python
# kairo/core/api/views.py

CONTRACT_VERSION = "1.2"  # Bump on breaking changes
MIN_FRONTEND_VERSION = "1.0"  # Minimum compatible frontend

@api_view(["GET"])
def openapi_schema(request) -> Response:
    """
    Versioned OpenAPI schema endpoint.

    Frontend MUST fetch schema from this endpoint, not from file.
    """
    schema = get_openapi_schema()
    return Response(
        schema,
        headers={
            "X-Contract-Version": CONTRACT_VERSION,
            "Cache-Control": "public, max-age=3600",
        }
    )


@api_view(["GET"])
def health_check(request) -> Response:
    """
    Health check with contract version info.

    Frontend uses this to verify compatibility at startup.
    """
    return Response({
        "status": "healthy",
        "contract_version": CONTRACT_VERSION,
        "min_frontend_version": MIN_FRONTEND_VERSION,
    })
```

#### Frontend: Version Compatibility Check

```typescript
// kairo-frontend/src/api/contract.ts

const MIN_BACKEND_VERSION = "1.0";  // Minimum compatible backend
const CURRENT_FRONTEND_VERSION = "1.2";

interface HealthResponse {
  status: string;
  contract_version: string;
  min_frontend_version: string;
}

export async function checkContractCompatibility(): Promise<void> {
  const response = await fetch("/api/health/");
  const health: HealthResponse = await response.json();

  // Check if backend is too old for this frontend
  if (compareVersions(health.contract_version, MIN_BACKEND_VERSION) < 0) {
    console.error(
      `Backend contract version ${health.contract_version} is below ` +
      `minimum required ${MIN_BACKEND_VERSION}. App may not work correctly.`
    );
    // Show warning banner to user
    showVersionMismatchWarning("backend_too_old");
  }

  // Check if frontend is too old for this backend
  if (compareVersions(CURRENT_FRONTEND_VERSION, health.min_frontend_version) < 0) {
    console.error(
      `Frontend version ${CURRENT_FRONTEND_VERSION} is below ` +
      `minimum required ${health.min_frontend_version}. Please refresh.`
    );
    // Force refresh or show blocking modal
    showVersionMismatchWarning("frontend_too_old", { blocking: true });
  }
}

// Call on app initialization
checkContractCompatibility();
```

#### Release Workflow

```yaml
# .github/workflows/release.yml (both repos)

name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Backend: Export and publish schema
      - name: Export OpenAPI schema (backend only)
        if: github.repository == 'your-org/kairo-backend'
        run: |
          python manage.py export_openapi > openapi.json
          # Publish to known location (S3, GitHub release asset, etc.)
          aws s3 cp openapi.json s3://kairo-schemas/${GITHUB_REF_NAME}/openapi.json

      # Frontend: Fetch schema from matching release tag
      - name: Fetch OpenAPI schema (frontend only)
        if: github.repository == 'your-org/kairo-frontend'
        run: |
          BACKEND_VERSION=$(cat .backend-version)  # e.g., "v1.2.0"
          curl -o openapi.json https://kairo-schemas.s3.amazonaws.com/${BACKEND_VERSION}/openapi.json
          npm run generate:types
```

#### Acceptable Strategies Summary

| Strategy | Pros | Cons | Recommended |
|----------|------|------|-------------|
| **Versioned `/openapi.json` endpoint** | Live schema, always current | Requires backend to be up | ✅ Primary |
| **Release-tag-pinned schema (S3/CDN)** | Immutable, auditable | May be stale | ✅ Backup |
| **Explicit contract versioning header** | Simple to implement | Requires client cooperation | ✅ Required |
| **Schema hash validation** | Cryptographic guarantee | Complex to implement | Optional |

#### What This Prevents

1. **Frontend built against `main` schema, backend on `release-1.0`** - Version check fails at runtime
2. **Backend deployed with breaking DTO change, frontend not updated** - Frontend detects version mismatch
3. **Stale types in frontend** - CI forces regeneration on every build
4. **Silent contract drift** - Response headers expose version for debugging

---

## 5. vNext Data Contracts

### 5.1 TodayBoardDTO vNext

```python
# kairo/hero/dto.py - TodayBoardDTO vNext

class TodayBoardDTO(BaseModel):
    """Complete Today board response. Per PRD-1 §3.3.6."""

    brand_id: UUID
    snapshot: BrandSnapshotDTO
    opportunities: list[OpportunityDTO] = Field(default_factory=list)
    meta: TodayBoardMetaDTO
    evidence_summary: EvidenceSummaryDTO | None = None  # MAY BE NULL if no evidence


class TodayBoardMetaDTO(BaseModel):
    """Board metadata with diagnostic information."""

    generated_at: datetime
    source: str = "hero_f1_v2"

    # STATE MACHINE (CRITICAL - see §0.2)
    state: Literal[
        "not_generated_yet",
        "generating",
        "ready",
        "insufficient_evidence",
        "error"
    ]
    job_id: str | None = None  # Present when state == "generating"

    # Cache information
    cache_hit: bool = False
    cache_key: str | None = None  # e.g., "today_board:brand_id:v2"
    cache_ttl_seconds: int | None = None

    # Generation status (legacy, preserved for backwards compat)
    degraded: bool = False  # True if state in {"insufficient_evidence", "error"}
    reason: str | None = None  # Degradation reason code
    remediation: str | None = None  # User-facing action to fix degraded state

    # Evidence quality indicators
    evidence_shortfall: EvidenceShortfallDTO | None = None  # Present if degraded due to evidence

    # Output stats
    total_candidates: int | None = None
    opportunity_count: int = 0
    notes: list[str] = Field(default_factory=list)

    # Timing (for observability)
    wall_time_ms: int | None = None
    evidence_fetch_ms: int | None = None
    llm_synthesis_ms: int | None = None
    llm_scoring_ms: int | None = None

    # Legacy fields (kept for compatibility)
    dominant_pillar: str | None = None
    dominant_persona: str | None = None
    channel_mix: dict[str, int] = Field(default_factory=dict)


class EvidenceShortfallDTO(BaseModel):
    """Details about why evidence was insufficient."""

    required_items: int
    found_items: int
    required_platforms: list[str]
    found_platforms: list[str]
    missing_platforms: list[str]
    transcript_coverage: float  # 0.0-1.0
    min_transcript_coverage: float  # Required threshold


class EvidenceSummaryDTO(BaseModel):
    """Summary of evidence used for opportunity generation."""

    total_items: int
    platforms: dict[str, int]  # {"instagram": 12, "tiktok": 8}
    items_with_text: int
    items_with_transcript: int
    transcript_coverage: float  # 0.0-1.0
    oldest_item_age_hours: float
    newest_item_age_hours: float
```

### 5.2 OpportunityDTO vNext

```python
# kairo/hero/dto.py - OpportunityDTO vNext

class OpportunityDTO(BaseModel):
    """Persisted opportunity as seen by UI."""

    # Identity
    id: UUID
    brand_id: UUID

    # Content (REQUIRED, never null)
    title: str
    angle: str
    why_now: str  # REQUIRED in v2 - must be non-empty, evidence-grounded

    # Classification
    type: OpportunityType
    primary_channel: Channel
    suggested_channels: list[Channel] = Field(default_factory=list)

    # Scoring
    score: float = Field(ge=0, le=100)
    score_explanation: str | None = None

    # Evidence linkage (REQUIRED in v2 - must have at least 1)
    evidence_ids: list[UUID] = Field(min_length=1)  # REQUIRED, non-empty
    evidence_preview: list[EvidencePreviewDTO] = Field(default_factory=list)

    # Optional brand context linkage
    persona_id: UUID | None = None
    pillar_id: UUID | None = None

    # Source tracking (for debugging)
    source: str = "hero_f1_v2"
    source_url: str | None = None  # MAY BE NULL

    # User state
    is_pinned: bool = False
    is_snoozed: bool = False
    snoozed_until: datetime | None = None

    # Lifecycle
    created_via: CreatedVia = CreatedVia.AI_SUGGESTED
    created_at: datetime
    updated_at: datetime

    # Display hints
    freshness_label: Literal["fresh", "aging", "stale"] | None = None


class EvidencePreviewDTO(BaseModel):
    """
    Minimal evidence info for opportunity card display.

    IMPORTANT: All fields except `id` and `platform` are OPTIONAL.
    kairo-frontend MUST handle missing values gracefully.
    """

    id: UUID
    platform: str  # "instagram", "tiktok" - REQUIRED
    content_type: str | None = None  # MAY BE NULL
    author_handle: str | None = None  # MAY BE NULL
    text_snippet: str | None = None  # MAY BE NULL - first 100 chars
    view_count: int | None = None  # MAY BE NULL
    url: str | None = None  # MAY BE NULL

    # INTENTIONALLY OMITTED: thumbnail_url
    # Thumbnails are NOT reliable - they expire, 404, or may never exist.
    # kairo-frontend must render evidence cards without thumbnails.
```

### 5.3 EvidenceDTO vNext (First-Class Contract)

```python
# kairo/hero/dto.py - EvidenceDTO vNext

class EvidenceDTO(BaseModel):
    """
    Normalized evidence item from external sources.

    This is the canonical shape for all evidence regardless of source platform.
    Adapters transform raw actor output into this shape.

    OPTIONAL FIELD POLICY:
    Fields marked "MAY BE NULL" are genuinely optional. kairo-frontend must
    handle missing values gracefully. Do NOT build UI logic that assumes
    these fields are present.
    """

    # Identity (REQUIRED)
    id: UUID
    brand_id: UUID

    # Source identification (REQUIRED)
    platform: Literal["instagram", "tiktok", "linkedin", "youtube", "web"]
    content_type: Literal["post", "reel", "short_video", "video", "text_post", "web_page"]
    canonical_url: str  # Dedupe key and linkback

    # Platform ID (MAY BE NULL for web)
    external_id: str | None = None

    # Timing
    published_at: datetime | None = None  # MAY BE NULL
    ingested_at: datetime  # REQUIRED

    # Content (at least one must be non-empty for valid evidence)
    author_ref: str  # Handle, URL, or channel ID - REQUIRED
    title: str | None = None  # MAY BE NULL - only for YouTube/web
    text_primary: str  # Caption, body, or page text - REQUIRED (may be empty)
    text_secondary: str | None = None  # MAY BE NULL - transcript or description
    hashtags: list[str] = Field(default_factory=list)

    # Engagement metrics (ALL OPTIONAL - platform-dependent)
    metrics: EvidenceMetricsDTO | None = None

    # Media metadata (ALL OPTIONAL - best effort)
    media: EvidenceMediaDTO | None = None

    # Quality flags
    has_transcript: bool = False
    is_low_value: bool = False  # Empty text, collection page, etc.

    # Provenance (for debugging, not UI)
    raw_refs: list[RawRefDTO] = Field(default_factory=list)


class EvidenceMetricsDTO(BaseModel):
    """
    Engagement metrics - ALL FIELDS OPTIONAL.

    Different platforms provide different metrics. kairo-frontend must
    handle any combination of present/missing values.
    """

    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    reposts: int | None = None


class EvidenceMediaDTO(BaseModel):
    """
    Media metadata - ALL FIELDS OPTIONAL, best effort.

    WARNING: thumbnail_url may 404 or be missing entirely.
    UI must handle gracefully with placeholder/fallback.
    """

    duration_seconds: int | None = None
    thumbnail_url: str | None = None  # MAY 404 - UI must handle
    width: int | None = None
    height: int | None = None


class RawRefDTO(BaseModel):
    """Reference back to raw Apify data for debugging."""

    apify_run_id: UUID
    raw_item_id: UUID
```

### 5.4 ConceptDTO v1 (New Object)

```python
# kairo/hero/dto.py - ConceptDTO v1

class ConceptDTO(BaseModel):
    """
    Concept: structured user intent for a content piece.

    Created when user clicks "Build Concept" on an opportunity.
    Links opportunity insight to user's creative direction.
    """

    # Identity
    id: UUID
    brand_id: UUID
    opportunity_id: UUID  # Source opportunity

    # Required fields (tier 1)
    take: str = Field(min_length=10, max_length=500)  # User's angle/hook
    format: ConceptFormat
    target_audience: str = Field(min_length=5, max_length=200)

    # Optional fields (tier 2)
    proof_points: list[str] = Field(default_factory=list, max_length=5)
    cta_preference: str | None = None
    constraints: list[str] = Field(default_factory=list, max_length=3)

    # Lifecycle
    status: ConceptStatus = ConceptStatus.DRAFT
    created_at: datetime
    updated_at: datetime

    # Forward reference (set when concept → package)
    package_id: UUID | None = None


class ConceptFormat(str, Enum):
    """Content format categories."""
    SHORT_VIDEO = "short_video"
    LONG_VIDEO = "long_video"
    CAROUSEL = "carousel"
    SINGLE_IMAGE = "single_image"
    TEXT_POST = "text_post"
    ARTICLE = "article"


class ConceptStatus(str, Enum):
    """Concept lifecycle states."""
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"
```

### 5.5 Request/Response DTOs for Concept

```python
# kairo/hero/dto.py - Concept request/response shapes

class CreateConceptRequestDTO(BaseModel):
    """Request body for POST /opportunities/{id}/concepts."""

    take: str = Field(min_length=10, max_length=500)
    format: ConceptFormat
    target_audience: str = Field(min_length=5, max_length=200)
    proof_points: list[str] = Field(default_factory=list, max_length=5)
    cta_preference: str | None = None
    constraints: list[str] = Field(default_factory=list, max_length=3)


class UpdateConceptRequestDTO(BaseModel):
    """Request body for PATCH /concepts/{id}."""

    take: str | None = Field(default=None, min_length=10, max_length=500)
    format: ConceptFormat | None = None
    target_audience: str | None = Field(default=None, min_length=5, max_length=200)
    proof_points: list[str] | None = Field(default=None, max_length=5)
    cta_preference: str | None = None
    constraints: list[str] | None = Field(default=None, max_length=3)
    status: ConceptStatus | None = None


class ConceptResponseDTO(BaseModel):
    """Response for concept endpoints."""

    status: str = "ok"
    concept: ConceptDTO
```

### 5.6 Frontend Contract Note (kairo-frontend)

**This section is binding on kairo-frontend implementation.**

```typescript
// kairo-frontend/src/api/README.md

/**
 * OPTIONAL FIELD HANDLING POLICY
 *
 * Fields marked as optional in OpenAPI (nullable: true) are genuinely optional.
 * They may be null, undefined, or missing entirely.
 *
 * NEVER DO THIS:
 * - evidence.thumbnail_url.startsWith("http")  // May crash
 * - evidence.metrics.views.toLocaleString()    // May crash
 * - evidence.author_handle.split("@")          // May crash
 *
 * ALWAYS DO THIS:
 * - evidence.thumbnail_url ?? null
 * - evidence.metrics?.views ?? null
 * - evidence.author_handle ?? "Unknown"
 *
 * EVIDENCE PREVIEW CARDS:
 * Must render gracefully with ALL optional fields missing.
 * Use text-only layout when thumbnail_url is null.
 * Show "—" for missing metrics.
 */

// Example: Safe evidence preview card
function EvidencePreviewCard({ evidence }: { evidence: EvidencePreviewDTO }) {
  return (
    <div className="evidence-card">
      {/* NO thumbnail dependency - text only */}
      <span className="platform">{evidence.platform}</span>
      <span className="author">{evidence.author_handle ?? "Unknown"}</span>
      <p className="snippet">{evidence.text_snippet ?? "No preview available"}</p>
      <span className="views">
        {evidence.view_count != null
          ? `${evidence.view_count.toLocaleString()} views`
          : "—"}
      </span>
    </div>
  );
}
```

---

## 6. Evidence Quality Gates

This section defines the hard requirements for evidence before synthesis can run.

### 6.1 Minimum Evidence Requirements

| Requirement | Threshold | Rationale |
|-------------|-----------|-----------|
| Total items | ≥ 8 | Below this, LLM hallucinates to fill gaps |
| Items with text | ≥ 6 | Empty captions provide no signal |
| Platform diversity | ≥ 1 platform from {instagram, tiktok} | LinkedIn-only is not v1 target |
| Transcript coverage | ≥ 0.3 (30%) | Transcripts are critical for voice/tone signals |
| Freshness | At least 1 item < 7 days old | Stale evidence produces stale opportunities |

### 6.2 Evidence Usability Gates (HARDENED)

Beyond minimum requirements, evidence must be **actually usable** for synthesis. These gates catch edge cases that pass basic checks but would produce garbage output.

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| **Minimum text length** | `text_primary` ≥ 30 characters for ≥ 4 items | Single-word captions provide no context |
| **Distinct authors** | ≥ 3 unique `author_ref` values | All evidence from one creator is not diverse |
| **Distinct URLs** | ≥ 6 unique `canonical_url` values | Duplicate scrapes inflate item count |
| **Near-duplicate detection** | < 20% near-duplicates | Same content with minor variations |
| **Non-empty content ratio** | ≥ 60% items have `text_primary` OR `text_secondary` | Too many media-only items |

#### Near-Duplicate Detection

Two evidence items are **near-duplicates** if:
- Same `author_ref` AND Jaccard similarity of `text_primary` ≥ 0.8
- OR same `canonical_url` (exact duplicate)

```python
# kairo/hero/services/evidence_quality.py

def compute_text_similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity of word sets."""
    if not text_a or not text_b:
        return 0.0
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union > 0 else 0.0


def detect_near_duplicates(evidence: list[EvidenceDTO]) -> list[tuple[UUID, UUID]]:
    """
    Detect near-duplicate evidence pairs.

    Returns list of (id_a, id_b) pairs that are near-duplicates.
    """
    duplicates = []

    # Exact URL duplicates
    url_to_ids: dict[str, list[UUID]] = {}
    for e in evidence:
        url_to_ids.setdefault(e.canonical_url, []).append(e.id)
    for ids in url_to_ids.values():
        if len(ids) > 1:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    duplicates.append((ids[i], ids[j]))

    # Text similarity duplicates (same author)
    author_groups: dict[str, list[EvidenceDTO]] = {}
    for e in evidence:
        author_groups.setdefault(e.author_ref, []).append(e)

    for items in author_groups.values():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                sim = compute_text_similarity(
                    items[i].text_primary, items[j].text_primary
                )
                if sim >= 0.8:
                    duplicates.append((items[i].id, items[j].id))

    return duplicates
```

#### Complete Usability Check

```python
# kairo/hero/services/evidence_quality.py

@dataclass
class UsabilityCheckResult:
    """Result of evidence usability check."""

    passed: bool
    failures: list[str]
    stats: dict[str, Any]


def check_evidence_usability(
    evidence: list[EvidenceDTO],
    min_text_length: int = 30,
    min_items_with_long_text: int = 4,
    min_distinct_authors: int = 3,
    min_distinct_urls: int = 6,
    max_duplicate_ratio: float = 0.2,
    min_content_ratio: float = 0.6,
) -> UsabilityCheckResult:
    """
    Check if evidence is actually usable for synthesis.

    This runs AFTER basic quality checks pass.
    LLM synthesis MUST NOT run unless usability gates pass.
    """
    failures = []
    stats = {}

    # Text length check
    items_with_long_text = sum(
        1 for e in evidence
        if e.text_primary and len(e.text_primary.strip()) >= min_text_length
    )
    stats["items_with_long_text"] = items_with_long_text
    if items_with_long_text < min_items_with_long_text:
        failures.append(
            f"insufficient_text_length: only {items_with_long_text} items have "
            f"≥{min_text_length} chars (need {min_items_with_long_text})"
        )

    # Distinct authors check
    distinct_authors = len({e.author_ref for e in evidence})
    stats["distinct_authors"] = distinct_authors
    if distinct_authors < min_distinct_authors:
        failures.append(
            f"insufficient_author_diversity: only {distinct_authors} distinct authors "
            f"(need {min_distinct_authors})"
        )

    # Distinct URLs check
    distinct_urls = len({e.canonical_url for e in evidence})
    stats["distinct_urls"] = distinct_urls
    if distinct_urls < min_distinct_urls:
        failures.append(
            f"insufficient_url_diversity: only {distinct_urls} distinct URLs "
            f"(need {min_distinct_urls})"
        )

    # Near-duplicate check
    duplicates = detect_near_duplicates(evidence)
    duplicate_ratio = len(duplicates) / len(evidence) if evidence else 0.0
    stats["duplicate_pairs"] = len(duplicates)
    stats["duplicate_ratio"] = duplicate_ratio
    if duplicate_ratio > max_duplicate_ratio:
        failures.append(
            f"too_many_duplicates: {duplicate_ratio:.1%} duplicate ratio "
            f"(max {max_duplicate_ratio:.1%})"
        )

    # Non-empty content ratio
    items_with_content = sum(
        1 for e in evidence
        if (e.text_primary and e.text_primary.strip()) or
           (e.text_secondary and e.text_secondary.strip())
    )
    content_ratio = items_with_content / len(evidence) if evidence else 0.0
    stats["content_ratio"] = content_ratio
    if content_ratio < min_content_ratio:
        failures.append(
            f"insufficient_content: only {content_ratio:.1%} items have text content "
            f"(need {min_content_ratio:.1%})"
        )

    return UsabilityCheckResult(
        passed=len(failures) == 0,
        failures=failures,
        stats=stats,
    )
```

### 6.3 Combined Quality + Usability Flow

```python
# kairo/hero/engines/opportunities_engine.py

def validate_evidence_for_synthesis(evidence: list[EvidenceDTO]) -> tuple[bool, str | None, dict]:
    """
    Full evidence validation before synthesis.

    Returns (can_proceed, failure_reason, diagnostics)
    """

    # Step 1: Basic quality gates
    quality_result = check_evidence_quality(evidence)
    if not quality_result.passed:
        return False, "quality_gate_failed", {
            "shortfall": quality_result.shortfall,
            "summary": quality_result.summary,
        }

    # Step 2: Usability gates (runs ONLY if quality passes)
    usability_result = check_evidence_usability(evidence)
    if not usability_result.passed:
        return False, "usability_gate_failed", {
            "failures": usability_result.failures,
            "stats": usability_result.stats,
        }

    # All gates passed
    return True, None, {
        "summary": quality_result.summary,
        "usability_stats": usability_result.stats,
    }
```

### 6.4 Degraded Behavior When Gates Fail

When evidence quality or usability gates fail, the engine MUST:

1. **Return honest empty state** - `opportunities: []`
2. **Set degraded flag** - `meta.degraded = true`
3. **Explain the reason** - `meta.reason = "insufficient_evidence"`
4. **Provide remediation** - `meta.remediation = "Connect Instagram or TikTok sources in Settings, then run BrandBrain compile."`
5. **Include shortfall details** - `meta.evidence_shortfall` with specific numbers

**MUST NOT:**
- Generate stub/fake opportunities
- Call Apify to fetch more evidence
- Proceed with synthesis on thin evidence (LLM will hallucinate)

---

## 7. Hard Performance Budgets

### 7.1 Request Path Budgets (GET /today/)

| Budget | Hard Cap | Fail-Fast Behavior |
|--------|----------|-------------------|
| **Total wall time** | 15 seconds | Abort, return cached or degraded |
| **Evidence fetch** | 2 seconds | Abort, return cached or degraded |
| **Evidence items loaded** | 50 items max | Truncate, log warning |
| **LLM synthesis call** | 10 seconds | Abort, return cached or degraded |
| **LLM scoring call** | 5 seconds | Abort with partial results |
| **Total LLM calls** | 2 max | Hard limit, no retries on request path |
| **Max tokens (synthesis)** | 4000 output | Truncate response |
| **Max tokens (scoring)** | 1000 output | Truncate response |

### 7.2 Timeout Implementation

```python
# kairo/hero/engines/opportunities_engine.py

from kairo.hero.budgets import (
    BUDGET_TOTAL_WALL_TIME_S,
    BUDGET_EVIDENCE_FETCH_S,
    BUDGET_LLM_SYNTHESIS_S,
    BUDGET_LLM_SCORING_S,
    BUDGET_MAX_EVIDENCE_ITEMS,
)

class BudgetExceededError(Exception):
    """Raised when a performance budget is exceeded."""
    def __init__(self, budget_name: str, limit: float, actual: float):
        self.budget_name = budget_name
        self.limit = limit
        self.actual = actual
        super().__init__(f"Budget {budget_name} exceeded: {actual:.2f}s > {limit}s")


def generate_today_board(brand_id: UUID, run_id: UUID) -> TodayBoardDTO:
    """
    Generate today board with hard performance budgets.

    If any budget is exceeded, returns cached or degraded response.
    """
    overall_start = time.monotonic()
    diagnostics = OpportunityGenerationDiagnostics(run_id=run_id, brand_id=brand_id)

    try:
        # Budget: evidence fetch
        evidence_start = time.monotonic()
        evidence = evidence_service.get_evidence_for_brand(
            brand_id,
            limit=BUDGET_MAX_EVIDENCE_ITEMS,
            timeout_s=BUDGET_EVIDENCE_FETCH_S,
        )
        diagnostics.evidence_fetch_ms = int((time.monotonic() - evidence_start) * 1000)

        if time.monotonic() - overall_start > BUDGET_TOTAL_WALL_TIME_S:
            raise BudgetExceededError("total_wall_time", BUDGET_TOTAL_WALL_TIME_S, time.monotonic() - overall_start)

        # Check evidence quality gates
        quality = check_evidence_quality(evidence)
        if not quality.passed:
            return _build_degraded_response(brand_id, quality, diagnostics)

        # Budget: LLM synthesis
        synthesis_start = time.monotonic()
        drafts = graph_synthesize_opportunities(
            evidence=evidence,
            brand_snapshot=snapshot,
            timeout_s=BUDGET_LLM_SYNTHESIS_S,
        )
        diagnostics.llm_synthesis_ms = int((time.monotonic() - synthesis_start) * 1000)

        # ... rest of pipeline with similar budget checks

    except BudgetExceededError as e:
        logger.warning(f"Budget exceeded: {e}", extra={"diagnostics": diagnostics.to_json()})
        return _get_cached_or_degraded(brand_id, reason=f"budget_exceeded:{e.budget_name}")
```

### 7.3 Caching Semantics

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Cache backend** | Redis or Django cache | Configurable |
| **Cache key format** | `today_board:v2:{brand_id}` | Versioned to allow cache busting |
| **TTL** | 6 hours (21600 seconds) | Configurable via `OPPORTUNITIES_CACHE_TTL_S` |
| **Cache hit indicator** | `meta.cache_hit = true` | Always set in response |
| **Cache miss indicator** | `meta.cache_hit = false` | Always set in response |
| **Invalidation** | On POST /regenerate/ | Explicit invalidation |

```python
# kairo/hero/services/today_service.py

CACHE_KEY_PREFIX = "today_board:v2"
CACHE_TTL_SECONDS = int(os.environ.get("OPPORTUNITIES_CACHE_TTL_S", 21600))

def get_today_board(brand_id: UUID) -> TodayBoardDTO:
    """Get today board with caching."""

    cache_key = f"{CACHE_KEY_PREFIX}:{brand_id}"

    # Try cache first
    cached = cache.get(cache_key)
    if cached:
        board = TodayBoardDTO.model_validate_json(cached)
        board.meta.cache_hit = True
        board.meta.cache_key = cache_key
        return board

    # Generate fresh
    board = opportunities_engine.generate_today_board(brand_id)
    board.meta.cache_hit = False
    board.meta.cache_key = cache_key
    board.meta.cache_ttl_seconds = CACHE_TTL_SECONDS

    # Store in cache
    cache.set(cache_key, board.model_dump_json(), timeout=CACHE_TTL_SECONDS)

    return board
```

---

## 8. Graph IO Contract (Synthesis Pipeline)

### 8.1 Pipeline Structure

The opportunities pipeline is a **2-step sequential pipeline** (not a complex graph):

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      SYNTHESIS PIPELINE                                  │
│                                                                          │
│   ┌─────────────────┐         ┌─────────────────┐                       │
│   │   STEP 1:       │         │   STEP 2:       │                       │
│   │   Synthesis     │────────▶│   Scoring       │                       │
│   │   (heavy LLM)   │         │   (fast LLM)    │                       │
│   └─────────────────┘         └─────────────────┘                       │
│          │                           │                                   │
│          ▼                           ▼                                   │
│   RawOpportunityIdea[]        OpportunityDraftDTO[]                     │
│   (unscored, unvalidated)     (scored, validated)                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Step 1: Synthesis Node

**Input Contract:**

```python
@dataclass
class SynthesisInput:
    """Input to synthesis step."""

    evidence_bundle: list[EvidenceDTO]  # 8-50 items
    brand_snapshot: BrandSnapshotDTO
    target_count: int = 12  # Target opportunities to generate

    # Determinism knobs
    temperature: float = 0.7
    seed: int | None = None  # Set for reproducibility in tests
    max_output_tokens: int = 4000
    model: str = "gpt-4o"  # Heavy model for quality
```

**Output Contract:**

```python
@dataclass
class RawOpportunityIdea:
    """Raw output from synthesis LLM call."""

    title: str
    angle: str
    why_now: str
    type: str  # "trend", "evergreen", "competitive", "community_signal"
    primary_channel: str
    suggested_channels: list[str]
    evidence_ids: list[str]  # REQUIRED - must reference input evidence
    reasoning: str | None = None
```

**Validation Errors (Step 1):**

| Error | Condition | Handling |
|-------|-----------|----------|
| `missing_evidence_ids` | `evidence_ids` is empty | Reject opportunity |
| `invalid_evidence_id` | ID not in input bundle | Reject opportunity |
| `empty_title` | `title` is empty/whitespace | Reject opportunity |
| `empty_angle` | `angle` is empty/whitespace | Reject opportunity |
| `empty_why_now` | `why_now` is empty/whitespace | Reject opportunity |
| `forbidden_phrase` | Contains banned marketing speak | Reject opportunity |
| `vacuous_why_now` | Contains "always relevant", etc. | Reject opportunity |
| `invalid_type` | Type not in allowed set | Default to "trend", log warning |
| `invalid_channel` | Channel not in allowed set | Default to "instagram", log warning |

### 8.3 Step 2: Scoring Node

**Input Contract:**

```python
@dataclass
class ScoringInput:
    """Input to scoring step."""

    opportunities: list[RawOpportunityIdea]
    brand_snapshot: BrandSnapshotDTO
    evidence_bundle: list[EvidenceDTO]  # For freshness scoring

    # Determinism knobs
    temperature: float = 0.0  # Deterministic for scoring
    seed: int | None = None
    max_output_tokens: int = 1000
    model: str = "gpt-4o-mini"  # Fast model for scoring
```

**Output Contract:**

```python
@dataclass
class ScoringResult:
    """Scoring output for one opportunity."""

    index: int  # Index into input list
    score: int  # 0-100
    band: str  # "invalid", "weak", "strong"
    explanation: str  # Short explanation
```

**Validation Errors (Step 2):**

| Error | Condition | Handling |
|-------|-----------|----------|
| `score_out_of_range` | Score not in [0, 100] | Clamp to range, log warning |
| `missing_index` | Index not provided | Skip item |
| `invalid_band` | Band not in allowed set | Infer from score |

### 8.4 Final Output: OpportunityDraftDTO

After both steps, produce final drafts:

```python
class OpportunityDraftDTO(BaseModel):
    """Final draft ready for persistence."""

    proposed_title: str
    proposed_angle: str
    why_now: str  # REQUIRED, non-empty
    type: OpportunityType
    primary_channel: Channel
    suggested_channels: list[Channel]
    evidence_ids: list[UUID]  # REQUIRED, non-empty
    score: float  # 0-100
    score_explanation: str | None

    # Validation status
    is_valid: bool
    rejection_reasons: list[str]
```

### 8.5 Determinism Configuration

```python
# kairo/hero/graphs/config.py

@dataclass
class GraphConfig:
    """Configuration for synthesis pipeline determinism."""

    # Synthesis step
    synthesis_model: str = "gpt-4o"
    synthesis_temperature: float = 0.7
    synthesis_max_tokens: int = 4000
    synthesis_seed: int | None = None  # Set in tests

    # Scoring step
    scoring_model: str = "gpt-4o-mini"
    scoring_temperature: float = 0.0  # Deterministic
    scoring_max_tokens: int = 1000
    scoring_seed: int | None = None  # Set in tests

    @classmethod
    def for_testing(cls) -> "GraphConfig":
        """Config for deterministic test runs."""
        return cls(
            synthesis_seed=42,
            scoring_seed=42,
        )
```

---

## 9. Prompt Strategy (Anti-Slop Rules)

### 9.1 Synthesis Prompt

```python
SYNTHESIS_SYSTEM_PROMPT_V2 = """You are a content strategist analyzing real evidence from {platform_list}.

BRAND: {brand_name}
POSITIONING: {positioning}
TONE: {tone_tags}
TABOOS: {taboos}

You will receive {evidence_count} evidence items. Your job is to identify content opportunities.

OUTPUT RULES:
1. Title must be specific and intriguing
   BAD: "Leverage trending topics for engagement"
   GOOD: "The $9 coffee breakdown going viral with 12M views"

2. Angle must explain the brand's specific take
   BAD: "Create content about this trend"
   GOOD: "Gen Z baristas are exposing markup math—we can flip the script by showing our transparent pricing"

3. why_now must cite SPECIFIC evidence with numbers/dates
   BAD: "always relevant", "timeless insight"
   GOOD: "12M views in 3 days, 847 creator videos this week, peak engagement on Tuesday"

4. You MUST include evidence_ids (from the evidence you received) for every opportunity
   If you cannot cite evidence, do not generate the opportunity

5. Write like a sharp strategist, not a LinkedIn influencer
   BAD: "In today's fast-paced digital landscape..."
   GOOD: "This format is blowing up because..."

FORBIDDEN PHRASES (will cause rejection):
- "leverage" (in marketing context)
- "drive engagement"
- "thought leadership"
- "value proposition"
- "in today's fast-paced"
- "now more than ever"
- "always relevant"
- "timeless"
- "evergreen truth"

Return JSON with "opportunities" array."""
```

### 9.2 Anti-Slop Validation

```python
# kairo/hero/graphs/validation.py

FORBIDDEN_PATTERNS = [
    (r"leverage\s+\w+\s+to\s+drive", "leverage_drive"),
    (r"thought\s+leadership", "thought_leadership"),
    (r"value\s+proposition", "value_proposition"),
    (r"in\s+today's\s+fast-paced", "fast_paced_world"),
    (r"now\s+more\s+than\s+ever", "now_more_than_ever"),
    (r"always\s+relevant", "always_relevant"),
    (r"timeless\s+(insight|truth|wisdom)", "timeless"),
    (r"drive\s+engagement", "drive_engagement"),
    (r"digital\s+landscape", "digital_landscape"),
]

VACUOUS_WHY_NOW_PATTERNS = [
    r"^always\s",
    r"^timeless\s",
    r"^evergreen\s",
    r"relevant\s+for\s+any\s+brand",
    r"works\s+for\s+everyone",
]

@dataclass
class ValidationResult:
    """Result of opportunity validation."""

    is_valid: bool
    rejection_reasons: list[str]
    warnings: list[str]


def validate_opportunity(opp: RawOpportunityIdea, evidence_ids: set[str]) -> ValidationResult:
    """
    Validate a single opportunity against all quality rules.

    Returns ValidationResult with is_valid=False if any hard rule fails.
    """
    reasons = []
    warnings = []

    # Check evidence_ids (HARD REQUIREMENT)
    if not opp.evidence_ids:
        reasons.append("missing_evidence_ids: opportunity must cite at least one evidence item")
    else:
        invalid_ids = set(opp.evidence_ids) - evidence_ids
        if invalid_ids:
            reasons.append(f"invalid_evidence_ids: {invalid_ids} not in input bundle")

    # Check forbidden phrases
    full_text = f"{opp.title} {opp.angle} {opp.why_now}"
    for pattern, name in FORBIDDEN_PATTERNS:
        if re.search(pattern, full_text, re.IGNORECASE):
            reasons.append(f"forbidden_phrase:{name}")

    # Check vacuous why_now
    if opp.why_now:
        for pattern in VACUOUS_WHY_NOW_PATTERNS:
            if re.search(pattern, opp.why_now, re.IGNORECASE):
                reasons.append(f"vacuous_why_now: matches pattern {pattern}")
    else:
        reasons.append("empty_why_now: why_now is required")

    # Check title/angle
    if not opp.title or len(opp.title.strip()) < 10:
        reasons.append("title_too_short: must be at least 10 characters")

    if not opp.angle or len(opp.angle.strip()) < 20:
        reasons.append("angle_too_short: must be at least 20 characters")

    return ValidationResult(
        is_valid=len(reasons) == 0,
        rejection_reasons=reasons,
        warnings=warnings,
    )
```

---

## 10. Observability and Diagnostics

### 10.1 Diagnostics Data Structure

```python
# kairo/hero/diagnostics.py

@dataclass
class OpportunityGenerationDiagnostics:
    """
    Complete diagnostics for one opportunity generation run.

    Logged on every request (success or failure).
    Stored in DB when STORE_GENERATION_DIAGNOSTICS=true.
    """

    run_id: UUID
    brand_id: UUID
    started_at: datetime
    finished_at: datetime | None = None

    # Outcome
    status: str = "pending"  # pending, success, degraded, error
    error_message: str | None = None

    # Evidence stats
    evidence_items_requested: int = 0
    evidence_items_loaded: int = 0
    evidence_items_after_quality_gate: int = 0
    evidence_quality_passed: bool = False
    evidence_platforms: dict[str, int] = field(default_factory=dict)
    evidence_transcript_coverage: float = 0.0

    # LLM stats
    llm_calls: list[LLMCallDiagnostics] = field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0

    # Pipeline stats
    candidates_from_synthesis: int = 0
    candidates_after_validation: int = 0
    candidates_after_dedupe: int = 0
    opportunities_persisted: int = 0

    # Validation stats
    validation_rejections: dict[str, int] = field(default_factory=dict)  # reason -> count
    slop_violations: list[str] = field(default_factory=list)
    missing_evidence_citations: int = 0

    # Timing breakdown (milliseconds)
    wall_time_ms: int = 0
    evidence_fetch_ms: int = 0
    quality_gate_ms: int = 0
    llm_synthesis_ms: int = 0
    llm_scoring_ms: int = 0
    validation_ms: int = 0
    dedupe_ms: int = 0
    persistence_ms: int = 0

    # Cache
    cache_hit: bool = False
    cache_key: str | None = None

    def to_json(self) -> dict:
        """Serialize for logging/storage."""
        return asdict(self)


@dataclass
class LLMCallDiagnostics:
    """Diagnostics for a single LLM call."""

    step: str  # "synthesis" or "scoring"
    model: str
    temperature: float
    tokens_in: int
    tokens_out: int
    latency_ms: int
    truncated: bool = False
    error: str | None = None
```

### 10.2 Logging Requirements

Every opportunity generation run MUST log:

```python
# kairo/hero/engines/opportunities_engine.py

def generate_today_board(brand_id: UUID, run_id: UUID) -> TodayBoardDTO:
    diagnostics = OpportunityGenerationDiagnostics(
        run_id=run_id,
        brand_id=brand_id,
        started_at=datetime.utcnow(),
    )

    try:
        # ... generation logic populates diagnostics ...

        diagnostics.status = "success"
        diagnostics.finished_at = datetime.utcnow()
        diagnostics.wall_time_ms = int((diagnostics.finished_at - diagnostics.started_at).total_seconds() * 1000)

        # REQUIRED: Log diagnostics on every request
        logger.info(
            "opportunity_generation_complete",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "status": "success",
                "wall_time_ms": diagnostics.wall_time_ms,
                "opportunities_count": diagnostics.opportunities_persisted,
                "cache_hit": diagnostics.cache_hit,
                "evidence_items": diagnostics.evidence_items_loaded,
                "llm_tokens_total": diagnostics.total_tokens_in + diagnostics.total_tokens_out,
                "diagnostics": diagnostics.to_json(),
            }
        )

        return board

    except Exception as e:
        diagnostics.status = "error"
        diagnostics.error_message = str(e)
        diagnostics.finished_at = datetime.utcnow()

        logger.error(
            "opportunity_generation_failed",
            extra={
                "run_id": str(run_id),
                "brand_id": str(brand_id),
                "status": "error",
                "error": str(e),
                "diagnostics": diagnostics.to_json(),
            },
            exc_info=True,
        )
        raise
```

### 10.3 Cost Tracking (Envelopes, Not Estimates)

We do NOT claim specific dollar amounts. Instead, we:

1. **Log token counts** - Actual tokens used per LLM call
2. **Enforce caps** - Max tokens per call prevents runaway costs
3. **Track trends** - Dashboard shows tokens/day, tokens/brand

```python
# Caps (enforced)
MAX_SYNTHESIS_TOKENS_OUT = 4000
MAX_SCORING_TOKENS_OUT = 1000
MAX_EVIDENCE_ITEMS = 50

# These are caps, not estimates
# Actual cost = tokens * model_rate (varies by provider)
```

---

## 11. Source Activation Strategy

### 11.1 Critical Constraint: Read-Only on Request Path

**GET /today/ reads existing evidence ONLY.** It does NOT:
- Call Apify actors
- Trigger BrandBrain compile
- Fetch from external APIs

Evidence is populated by BrandBrain compile (separate flow):
1. User connects sources in Settings
2. User triggers BrandBrain compile (or it runs on schedule)
3. BrandBrain compile calls Apify, normalizes results, stores in `NormalizedEvidenceItem`
4. GET /today/ reads from `NormalizedEvidenceItem`

### 11.2 Evidence Service (Read-Only)

```python
# kairo/hero/services/evidence_service.py

def get_evidence_for_brand(
    brand_id: UUID,
    limit: int = 50,
    max_age_days: int = 30,
    platforms: list[str] | None = None,
    timeout_s: float = 2.0,
) -> list[EvidenceDTO]:
    """
    Fetch normalized evidence for a brand.

    READS FROM DATABASE ONLY. No external API calls.

    Args:
        brand_id: Brand to fetch evidence for
        limit: Maximum items to return (hard cap: 50)
        max_age_days: Exclude evidence older than this
        platforms: Filter to specific platforms (None = all)
        timeout_s: Database query timeout

    Returns:
        List of EvidenceDTO, sorted by published_at DESC

    Raises:
        EvidenceFetchTimeout: If query exceeds timeout
    """

    # IMPORTANT: This is a DB read only
    # No imports from kairo.integrations.apify allowed

    cutoff = datetime.utcnow() - timedelta(days=max_age_days)

    queryset = NormalizedEvidenceItem.objects.filter(
        brand_id=brand_id,
        is_low_value=False,
    ).exclude(
        published_at__lt=cutoff,
    ).order_by("-published_at")

    if platforms:
        queryset = queryset.filter(platform__in=platforms)

    items = list(queryset[:min(limit, 50)])

    return [_to_evidence_dto(item) for item in items]
```

### 11.3 When Evidence is Missing

If `get_evidence_for_brand()` returns insufficient evidence:

1. **DO NOT call Apify** - This is the request path
2. **Return degraded state** with remediation instructions
3. **User must run BrandBrain compile** to populate evidence

```json
{
  "opportunities": [],
  "meta": {
    "degraded": true,
    "reason": "insufficient_evidence",
    "remediation": "Your content sources haven't been analyzed yet. Go to Settings → Sources → Run BrandBrain Compile to generate opportunities.",
    "evidence_shortfall": {
      "required_items": 8,
      "found_items": 0,
      "missing_platforms": ["instagram", "tiktok"]
    }
  }
}
```

---

## 12. API Surface

### 12.1 Today Board Endpoints

| Method | Path | Response | Notes |
|--------|------|----------|-------|
| GET | `/api/brands/{brand_id}/today/` | `TodayBoardDTO` | **Read-only.** Returns cached board or status state. NEVER triggers LLM. |
| POST | `/api/brands/{brand_id}/today/regenerate/` | `RegenerateResponseDTO` | **Triggers generation.** The ONLY endpoint that calls LLMs. |

**GET /api/brands/{brand_id}/today/** (Read-Only, see §0.2)

```python
# state: "ready" - Board available
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "snapshot": { ... },
  "opportunities": [ ... ],
  "meta": {
    "state": "ready",  # CRITICAL: Always check this field
    "generated_at": "2026-01-17T10:30:00Z",
    "source": "hero_f1_v2",
    "cache_hit": true,
    "cache_key": "today_board:v2:550e8400-e29b-41d4-a716-446655440000",
    "cache_ttl_seconds": 21600,
    "degraded": false,
    "opportunity_count": 8,
    "wall_time_ms": 150,
    ...
  },
  "evidence_summary": {
    "total_items": 32,
    "platforms": {"instagram": 14, "tiktok": 12, "linkedin": 6},
    "transcript_coverage": 0.65,
    ...
  }
}

# state: "generating" - Background job running, poll again
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "snapshot": { ... },
  "opportunities": [],  # Or stale cached if available
  "meta": {
    "state": "generating",
    "job_id": "abc-123-def",
    "generated_at": null,
    "degraded": false
  },
  "evidence_summary": null
}

# state: "insufficient_evidence" - Quality gates failed
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "snapshot": { ... },
  "opportunities": [],
  "meta": {
    "state": "insufficient_evidence",
    "generated_at": "2026-01-17T10:30:00Z",
    "source": "hero_f1_v2",
    "cache_hit": false,
    "degraded": true,
    "reason": "insufficient_evidence",
    "remediation": "Connect Instagram or TikTok sources in Settings, then run BrandBrain compile.",
    "evidence_shortfall": {
      "required_items": 8,
      "found_items": 2,
      "required_platforms": ["instagram", "tiktok"],
      "found_platforms": ["linkedin"],
      "missing_platforms": ["instagram", "tiktok"],
      "transcript_coverage": 0.0,
      "min_transcript_coverage": 0.3
    },
    "opportunity_count": 0
  },
  "evidence_summary": null
}

# state: "not_generated_yet" - First run, auto-enqueued
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "snapshot": { ... },
  "opportunities": [],
  "meta": {
    "state": "not_generated_yet",
    "remediation": "We're preparing your first opportunities. Check back in 30-60 seconds."
  },
  "evidence_summary": null
}
```

**POST /api/brands/{brand_id}/today/regenerate/** (Triggers Generation)

```python
# Request: POST /api/brands/{brand_id}/today/regenerate/
# Body: (optional) {"force": true}  # Force regeneration even if recent

# Response: 202 Accepted
{
  "status": "accepted",
  "job_id": "abc-123-def",
  "poll_url": "/api/brands/550e8400-e29b-41d4-a716-446655440000/today/",
  "message": "Generation queued. Poll GET /today/ for status."
}
```

### 12.2 Concept Endpoints

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/api/opportunities/{id}/concepts/` | `CreateConceptRequestDTO` | `ConceptResponseDTO` |
| GET | `/api/concepts/{id}/` | - | `ConceptDTO` |
| PATCH | `/api/concepts/{id}/` | `UpdateConceptRequestDTO` | `ConceptResponseDTO` |
| GET | `/api/brands/{id}/concepts/` | - | `list[ConceptDTO]` |
| DELETE | `/api/concepts/{id}/` | - | 204 No Content |

---

## 13. Golden Path Integration Test (HARDENED)

### 13.1 Purpose

The golden path test validates the entire pipeline end-to-end with realistic fixtures. It prevents:

- Regression to stub/fake data
- Evidence quality gate bypass
- Anti-slop validation bypass
- Cache behavior bugs
- Contract drift

**CRITICAL:** This test MUST include adversarial fixtures that exercise edge cases. "Clean" fixtures that always pass do not catch regressions.

### 13.2 Fixture Requirements (MANDATORY)

**Location:** `tests/fixtures/golden_path/`

**Files:**
```
tests/fixtures/golden_path/
├── README.md                           # How fixtures were captured
├── brand_acme_coffee.json              # Brand snapshot
├── evidence/
│   ├── instagram_reels_acme.json       # 10 real IG reels (anonymized)
│   ├── tiktok_videos_acme.json         # 8 real TikTok videos (anonymized)
│   └── linkedin_posts_acme.json        # 4 real LinkedIn posts (anonymized)
├── evidence_adversarial/               # REQUIRED: Edge case fixtures
│   ├── missing_thumbnails.json         # Items with thumbnail_url = null
│   ├── missing_metrics.json            # Items with metrics = null
│   ├── missing_transcripts.json        # Items with text_secondary = null
│   ├── duplicate_urls.json             # Exact URL duplicates
│   ├── near_duplicate_text.json        # Same author, similar text
│   ├── short_captions.json             # text_primary < 30 chars
│   └── single_author.json              # All items from one creator
├── expected_outputs/
│   ├── opportunities_warm_cache.json   # Expected output (cache hit)
│   └── opportunities_cold_cache.json   # Expected output (fresh generation)
└── llm_responses/
    ├── synthesis_response.json         # Mocked LLM response for synthesis
    ├── synthesis_sloppy.json           # REQUIRED: Response with forbidden phrases
    └── scoring_response.json           # Mocked LLM response for scoring
```

**Fixture Requirements (BINDING):**

Fixtures MUST include:
1. **Missing thumbnails** - At least 3 items with `thumbnail_url: null`
2. **Missing engagement metrics** - At least 2 items with `metrics: null`
3. **Missing transcripts** - At least 2 items with `text_secondary: null`
4. **Duplicate or near-duplicate URLs** - At least 2 pairs of duplicates
5. **Short/empty captions** - At least 2 items with `text_primary` < 30 chars
6. **Single author subset** - At least one fixture set where all items share `author_ref`

**Fixture Generation:**
- Captured from real Apify runs (one-time)
- PII removed/anonymized (usernames, faces)
- Metrics preserved (views, likes, comments)
- Transcripts preserved (critical for quality)
- **Adversarial fixtures MUST be derived from real data, not hand-crafted**

### 13.3 Test Implementation

```python
# tests/integration/test_golden_path.py

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "golden_path"


class TestGoldenPathIntegration:
    """
    Golden path integration test for opportunities pipeline.

    This test validates the entire end-to-end flow with realistic fixtures.
    It MUST pass before any PR is merged.
    """

    @pytest.fixture
    def brand_with_evidence(self, db):
        """Set up brand with normalized evidence from fixtures."""
        brand = create_brand_from_fixture(FIXTURES_DIR / "brand_acme_coffee.json")
        load_evidence_fixtures(brand.id, FIXTURES_DIR / "evidence")
        return brand

    @pytest.fixture
    def mock_llm_responses(self):
        """Mock LLM to return deterministic responses."""
        return MockLLMResponses(
            synthesis=load_json(FIXTURES_DIR / "llm_responses" / "synthesis_response.json"),
            scoring=load_json(FIXTURES_DIR / "llm_responses" / "scoring_response.json"),
        )

    def test_generates_opportunities_from_real_evidence(
        self, brand_with_evidence, mock_llm_responses
    ):
        """
        GOLDEN PATH: Full pipeline with realistic evidence.

        Validates:
        - Evidence is loaded from DB (not fabricated)
        - Quality gates pass with sufficient evidence
        - Synthesis produces opportunities with evidence_ids
        - Anti-slop validation runs
        - Opportunities are persisted
        """
        with mock_llm_responses.activate():
            board = today_service.get_today_board(brand_with_evidence.id)

        # Must not be degraded
        assert board.meta.degraded is False, f"Unexpectedly degraded: {board.meta.reason}"

        # Must have opportunities
        assert len(board.opportunities) >= 6, "Should generate at least 6 opportunities"

        # Every opportunity must have evidence_ids
        for opp in board.opportunities:
            assert len(opp.evidence_ids) > 0, f"Opportunity {opp.id} missing evidence_ids"

        # why_now must be non-empty and specific
        for opp in board.opportunities:
            assert opp.why_now, f"Opportunity {opp.id} missing why_now"
            assert len(opp.why_now) >= 20, f"Opportunity {opp.id} has too-short why_now"
            # Check not vacuous
            assert "always relevant" not in opp.why_now.lower()
            assert "timeless" not in opp.why_now.lower()

        # No forbidden phrases
        for opp in board.opportunities:
            full_text = f"{opp.title} {opp.angle} {opp.why_now}"
            assert "leverage" not in full_text.lower() or "lever" in full_text.lower()  # Allow "lever" but not "leverage X to drive"
            assert "thought leadership" not in full_text.lower()
            assert "drive engagement" not in full_text.lower()

    def test_cache_behavior(self, brand_with_evidence, mock_llm_responses):
        """Validates cache hit/miss behavior."""
        with mock_llm_responses.activate():
            # First call: cache miss
            board1 = today_service.get_today_board(brand_with_evidence.id)
            assert board1.meta.cache_hit is False

            # Second call: cache hit
            board2 = today_service.get_today_board(brand_with_evidence.id)
            assert board2.meta.cache_hit is True

            # Same opportunities
            assert [o.id for o in board1.opportunities] == [o.id for o in board2.opportunities]

    def test_degraded_state_when_evidence_insufficient(self, db):
        """Validates honest degraded state when evidence is missing."""
        # Brand with no evidence
        brand = create_brand_from_fixture(FIXTURES_DIR / "brand_acme_coffee.json")
        # DO NOT load evidence

        board = today_service.get_today_board(brand.id)

        # Must be degraded
        assert board.meta.degraded is True
        assert board.meta.reason == "insufficient_evidence"
        assert board.meta.remediation is not None
        assert "Connect" in board.meta.remediation or "compile" in board.meta.remediation.lower()

        # Must have zero opportunities (not stubs)
        assert len(board.opportunities) == 0

        # Must have shortfall details
        assert board.meta.evidence_shortfall is not None
        assert board.meta.evidence_shortfall.found_items < board.meta.evidence_shortfall.required_items

    def test_no_apify_calls_on_request_path(self, brand_with_evidence, mock_llm_responses):
        """Validates that GET /today does NOT call Apify."""
        with mock_llm_responses.activate():
            with patch("kairo.integrations.apify.client.ApifyClient") as mock_apify:
                board = today_service.get_today_board(brand_with_evidence.id)

                # ApifyClient should never be instantiated
                mock_apify.assert_not_called()

    def test_evidence_preview_handles_missing_optional_fields(self, brand_with_evidence, mock_llm_responses):
        """Validates that evidence preview works with missing thumbnails/metrics."""
        with mock_llm_responses.activate():
            board = today_service.get_today_board(brand_with_evidence.id)

        for opp in board.opportunities:
            for preview in opp.evidence_preview:
                # These are required
                assert preview.id is not None
                assert preview.platform is not None

                # These are optional - may be None
                # Test that serialization works regardless
                preview_dict = preview.model_dump()
                assert "id" in preview_dict
                assert "platform" in preview_dict
                # thumbnail_url is intentionally omitted from schema
                assert "thumbnail_url" not in preview_dict


class TestGoldenPathAntiCheat:
    """
    Anti-cheat tests that ensure validation logic is not bypassed.

    These tests use adversarial fixtures and MUST NOT be over-mocked.
    """

    @pytest.fixture
    def adversarial_evidence(self, db):
        """Load adversarial evidence fixtures."""
        brand = create_brand_from_fixture(FIXTURES_DIR / "brand_acme_coffee.json")
        # Load evidence with known edge cases
        load_evidence_fixtures(brand.id, FIXTURES_DIR / "evidence_adversarial")
        return brand

    @pytest.fixture
    def sloppy_llm_responses(self):
        """
        LLM responses containing forbidden phrases.

        The validation layer MUST reject these.
        """
        return MockLLMResponses(
            synthesis=load_json(FIXTURES_DIR / "llm_responses" / "synthesis_sloppy.json"),
            scoring=load_json(FIXTURES_DIR / "llm_responses" / "scoring_response.json"),
        )

    def test_evidence_ids_reference_real_evidence(self, brand_with_evidence, mock_llm_responses):
        """
        ANTI-CHEAT: Every opportunity must reference real evidence_ids.

        This test MUST NOT be bypassed by over-mocking.
        """
        # Get all evidence IDs from the DB
        all_evidence_ids = set(
            str(e.id) for e in NormalizedEvidenceItem.objects.filter(brand_id=brand_with_evidence.id)
        )

        with mock_llm_responses.activate():
            board = today_service.get_today_board(brand_with_evidence.id)

        for opp in board.opportunities:
            # CRITICAL: Every evidence_id must exist in the input bundle
            for eid in opp.evidence_ids:
                assert str(eid) in all_evidence_ids, (
                    f"Opportunity {opp.id} references evidence_id {eid} "
                    f"that does not exist in the input bundle. "
                    f"This indicates the LLM hallucinated an evidence reference."
                )

    def test_why_now_includes_concrete_anchor(self, brand_with_evidence, mock_llm_responses):
        """
        ANTI-CHEAT: why_now must include at least one concrete anchor.

        A concrete anchor is: a number, a date, a velocity term, or a specific event.
        """
        ANCHOR_PATTERNS = [
            r'\d+',                          # Any number (views, days, etc.)
            r'\d{4}[-/]\d{2}[-/]\d{2}',      # Date pattern
            r'(this|last)\s+(week|month)',   # Relative time
            r'\d+%',                         # Percentage
            r'(trending|viral|blowing up)',  # Velocity terms
            r'(million|thousand|k|M)\s+(views|likes|shares)',  # Metric with scale
        ]

        with mock_llm_responses.activate():
            board = today_service.get_today_board(brand_with_evidence.id)

        for opp in board.opportunities:
            why_now = opp.why_now.lower()
            has_anchor = any(re.search(p, why_now, re.IGNORECASE) for p in ANCHOR_PATTERNS)
            assert has_anchor, (
                f"Opportunity {opp.id} has why_now without concrete anchor: '{opp.why_now}'. "
                f"why_now must include a number, date, velocity, or specific event."
            )

    def test_banned_phrases_rejected_from_llm_output(self, brand_with_evidence, sloppy_llm_responses):
        """
        ANTI-CHEAT: Validation MUST reject LLM output with banned phrases.

        This test uses a mock LLM response containing forbidden phrases.
        The validation layer MUST filter them out.
        """
        BANNED_PHRASES = [
            "leverage",
            "thought leadership",
            "drive engagement",
            "value proposition",
            "in today's fast-paced",
            "now more than ever",
        ]

        with sloppy_llm_responses.activate():
            board = today_service.get_today_board(brand_with_evidence.id)

        for opp in board.opportunities:
            full_text = f"{opp.title} {opp.angle} {opp.why_now}".lower()
            for phrase in BANNED_PHRASES:
                assert phrase not in full_text, (
                    f"Opportunity {opp.id} contains banned phrase '{phrase}'. "
                    f"Validation should have rejected this opportunity."
                )

    def test_usability_gates_reject_adversarial_fixtures(self, adversarial_evidence):
        """
        ANTI-CHEAT: Usability gates must reject low-quality evidence bundles.

        This test uses adversarial fixtures (duplicates, single author, etc.)
        that should FAIL usability checks.
        """
        evidence = evidence_service.get_evidence_for_brand(adversarial_evidence.id)

        # This fixture set has known issues - usability gates should catch them
        result = check_evidence_usability(evidence)

        # At least one usability check should fail
        assert not result.passed, (
            f"Usability check passed when it should have failed. "
            f"Adversarial fixtures should trigger usability gate failures. "
            f"Stats: {result.stats}"
        )

    def test_duplicate_detection_catches_near_duplicates(self, db):
        """
        ANTI-CHEAT: Duplicate detection must catch near-duplicates.

        Uses fixture with same author + similar text.
        """
        brand = create_brand_from_fixture(FIXTURES_DIR / "brand_acme_coffee.json")
        load_evidence_fixtures(brand.id, FIXTURES_DIR / "evidence_adversarial" / "near_duplicate_text.json")

        evidence = evidence_service.get_evidence_for_brand(brand.id)
        duplicates = detect_near_duplicates(evidence)

        assert len(duplicates) > 0, (
            "Near-duplicate detection failed to catch duplicates in adversarial fixture. "
            "This fixture contains items with same author and >80% text similarity."
        )

    def test_no_over_mocking_of_validation(self, brand_with_evidence):
        """
        ANTI-CHEAT: Validation logic MUST NOT be mocked in golden path tests.

        This test verifies that validation code actually runs.
        """
        # Inject a spy to verify validation is called
        with patch("kairo.hero.graphs.validation.validate_opportunity", wraps=validate_opportunity) as spy:
            with MockLLMResponses(...).activate():
                board = today_service.get_today_board(brand_with_evidence.id)

            # Validation must have been called at least once per synthesized opportunity
            assert spy.call_count > 0, (
                "validate_opportunity was never called. "
                "This indicates the validation logic is being bypassed."
            )
```

### 13.4 Prohibited Test Patterns

The following patterns are **explicitly prohibited** in golden path tests:

```python
# PROHIBITED: Over-mocking LLM to bypass validation
@patch("kairo.hero.graphs.validation.validate_opportunity")  # NEVER mock this
def test_bad_example(...):
    ...

# PROHIBITED: Using "clean" fixtures that never exercise nullability
evidence_fixture = {
    "thumbnail_url": "https://example.com/thumb.jpg",  # ALWAYS present - BAD
    "metrics": {"views": 1000, "likes": 100},          # ALWAYS present - BAD
    ...
}

# PROHIBITED: Skipping usability checks in test setup
def setup():
    with patch("kairo.hero.services.evidence_quality.check_evidence_usability"):
        ...  # NEVER bypass usability checks

# PROHIBITED: Hardcoding evidence_ids in mock LLM responses
mock_synthesis_response = {
    "opportunities": [{
        "evidence_ids": ["some-uuid-you-made-up"],  # MUST reference real fixture IDs
        ...
    }]
}
```

### 13.5 CI Gate

```yaml
# .github/workflows/golden-path.yml
name: Golden Path Test

on: [push, pull_request]

jobs:
  golden-path:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run golden path test
        run: pytest tests/integration/test_golden_path.py -v --tb=long

      - name: Fail if golden path fails
        if: failure()
        run: |
          echo "Golden path test failed. This is a merge blocker."
          exit 1
```

---

## 14. Execution Plan (Phases + PR Map)

### Risk-Ordered PR Sequence

The PR order is designed to prevent BrandBrain v1 mistakes:
1. Test harness first (prove we can detect regressions)
2. Evidence quality gates (prevent thin-evidence synthesis)
3. Then features

### PR0: Golden Path Test Harness + Fixtures

**Scope:**
- Create `tests/fixtures/golden_path/` with realistic anonymized data
- Implement `TestGoldenPathIntegration` test class
- Add CI workflow for golden path test
- Document fixture generation process

**Files:**
- `tests/fixtures/golden_path/` (new directory)
- `tests/integration/test_golden_path.py` (new)
- `.github/workflows/golden-path.yml` (new)
- `tests/fixtures/golden_path/README.md` (new)

**Acceptance Criteria:**
- Golden path test runs and FAILS (because v2 features don't exist yet)
- Fixtures are realistic (captured from real Apify runs)
- CI blocks merge if golden path fails
- Test validates all critical invariants from §0.1

**Why First:** We need the test harness before implementing features to catch regressions.

### PR1: Evidence Quality Gates + Service

**Scope:**
- Implement `evidence_service.get_evidence_for_brand()` (read-only)
- Implement `check_evidence_quality()` with thresholds
- Add `EvidenceShortfallDTO` to contracts
- Wire degraded response when gates fail

**Files:**
- `kairo/hero/services/evidence_service.py` (new)
- `kairo/hero/services/evidence_quality.py` (new)
- `kairo/hero/dto.py` (add EvidenceShortfallDTO)
- `tests/hero/services/test_evidence_quality.py` (new)

**Acceptance Criteria:**
- `get_evidence_for_brand()` reads from DB only (no Apify imports)
- Quality gates reject thin evidence (< 8 items, < 30% transcript)
- Degraded response includes remediation instructions
- CI test verifies no Apify imports in `kairo/hero/`

**Why Second:** Quality gates must exist before synthesis to prevent hallucination.

### PR2: Contract Pipeline + OpenAPI

**Scope:**
- Add OpenAPI generation (`export_openapi` command)
- Add CI workflow for contract validation
- Update DTOs with v2 fields (evidence_ids, why_now, etc.)
- Generate TypeScript types for `kairo-frontend`

**Files:**
- `kairo/core/management/commands/export_openapi.py` (new)
- `kairo/hero/dto.py` (update with v2 fields)
- `.github/workflows/contract-check.yml` (new)
- `openapi.json` (generated, committed)

**Acceptance Criteria:**
- `python manage.py export_openapi` generates valid OpenAPI 3.1
- CI fails if openapi.json drifts
- `kairo-frontend` can generate types from spec
- Optional fields marked `nullable: true` in schema

### PR3: Performance Budgets + Caching

**Scope:**
- Implement hard timeout enforcement
- Add caching layer with TTL
- Add timing fields to TodayBoardMetaDTO
- Add `BudgetExceededError` handling

**Files:**
- `kairo/hero/budgets.py` (new - constants)
- `kairo/hero/services/today_service.py` (add caching)
- `kairo/hero/engines/opportunities_engine.py` (add budget checks)
- `tests/hero/test_budgets.py` (new)

**Acceptance Criteria:**
- GET /today/ returns within 15s or degrades
- Cache hit returns within 200ms
- `meta.cache_hit`, `meta.cache_key`, `meta.wall_time_ms` populated
- Budget exceeded triggers degraded response (not error)

### PR4: Graph IO Contract + Validation

**Scope:**
- Refactor synthesis pipeline with explicit IO contracts
- Implement anti-slop validation
- Add `evidence_ids` requirement enforcement
- Add determinism configuration

**Files:**
- `kairo/hero/graphs/config.py` (new)
- `kairo/hero/graphs/validation.py` (new)
- `kairo/hero/graphs/contracts.py` (new)
- `kairo/hero/graphs/opportunities_graph.py` (refactor)

**Acceptance Criteria:**
- Synthesis requires evidence_ids in output
- Anti-slop patterns trigger rejection
- Validation results logged with rejection reasons
- Deterministic mode available for testing

### PR5: Diagnostics + Observability

**Scope:**
- Implement `OpportunityGenerationDiagnostics`
- Add structured logging for all runs
- Add optional DB storage for diagnostics
- Create diagnostics dashboard (Grafana/similar)

**Files:**
- `kairo/hero/diagnostics.py` (new)
- `kairo/hero/engines/opportunities_engine.py` (add diagnostics)
- `kairo/hero/models.py` (add OpportunityGenerationRun model)

**Acceptance Criteria:**
- Every generation run logs diagnostics JSON
- Token counts, timings, evidence stats all captured
- Dashboard shows tokens/day, cache hit rate, error rate
- No dollar estimates (only token counts)

### PR6: Concept Model + Endpoints

**Scope:**
- Add `Concept` Django model
- Implement CRUD endpoints
- Add idempotency support
- Wire to opportunity detail

**Files:**
- `kairo/core/models.py` (add Concept)
- `kairo/hero/api_views.py` (add concept endpoints)
- `kairo/hero/services/concept_service.py` (new)

**Acceptance Criteria:**
- POST /opportunities/{id}/concepts/ creates concept
- Concept links to opportunity and brand
- Idempotency-Key header prevents duplicates

### PR7: Frontend Types + Integration

**Scope:**
- Generate TypeScript types in `kairo-frontend`
- Update components to use generated types
- Implement optional field handling
- Remove manual type definitions

**Files (in kairo-frontend):**
- `src/api/generated/types.ts` (generated)
- `src/components/EvidencePreviewCard.tsx` (update)
- `package.json` (add generate:types script)

**Acceptance Criteria:**
- `npm run generate:types` produces types
- Components handle missing optional fields
- No manual API type definitions
- Evidence cards render without thumbnails

### Timeline Summary

| PR | Scope | Dependencies | Risk Mitigation |
|----|-------|--------------|-----------------|
| PR0 | Golden path test harness | None | Proves we can detect regressions |
| PR1 | Evidence quality gates | PR0 | Prevents thin-evidence synthesis |
| PR2 | Contract pipeline | None | Prevents frontend drift |
| PR3 | Performance budgets | PR1 | Prevents slow/runaway requests |
| PR4 | Graph IO contract | PR1, PR2 | Ensures quality output |
| PR5 | Diagnostics | PR3, PR4 | Enables debugging |
| PR6 | Concept model | PR2 | New feature |
| PR7 | Frontend types | PR2, PR4 | Closes frontend loop |

---

## 15. Migration Plan

### Phase 1: Feature Flag

```python
# kairo/settings.py
OPPORTUNITIES_V2_ENABLED = os.environ.get("OPPORTUNITIES_V2_ENABLED", "false").lower() == "true"
```

### Phase 2: Parallel Run

- v1 serves production traffic
- v2 runs in shadow mode, logs results
- Compare: quality, latency, error rates

### Phase 3: Gradual Rollout

```bash
OPPORTUNITIES_V2_ENABLED=true
OPPORTUNITIES_V2_ROLLOUT_PERCENT=10  # Start at 10%
# Increase gradually to 100%
```

### Phase 4: Remove v1 Code

After 2 weeks at 100%:
- Remove `_generate_stub_opportunities()` entirely
- Remove v1 code paths
- Update tests

### Rollback Plan

```bash
OPPORTUNITIES_V2_ENABLED=false
# Immediate rollback to v1 behavior
# All persisted data preserved
```

---

## Appendix A: Concept Model Schema

```python
# kairo/core/models.py

class Concept(TimestampedModel):
    """Structured user intent for content creation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="concepts")
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        related_name="concepts"
    )

    take = models.TextField()
    format = models.CharField(max_length=50, choices=ConceptFormat.choices)
    target_audience = models.CharField(max_length=200)
    proof_points = models.JSONField(default=list)
    cta_preference = models.CharField(max_length=100, blank=True)
    constraints = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=ConceptStatus.choices, default=ConceptStatus.DRAFT)
    package = models.ForeignKey("ContentPackage", on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        db_table = "concept"
        indexes = [
            models.Index(fields=["brand", "-created_at"]),
            models.Index(fields=["opportunity"]),
            models.Index(fields=["status"]),
        ]
```

---

## Appendix B: Budget Constants

```python
# kairo/hero/budgets.py

"""
Hard performance budgets for opportunity generation.

These are CAPS, not targets. Exceeding them triggers fail-fast behavior.
"""

# Total wall time for GET /today/
BUDGET_TOTAL_WALL_TIME_S = 15.0

# Per-step timeouts
BUDGET_EVIDENCE_FETCH_S = 2.0
BUDGET_LLM_SYNTHESIS_S = 10.0
BUDGET_LLM_SCORING_S = 5.0

# Item limits
BUDGET_MAX_EVIDENCE_ITEMS = 50

# Token limits
BUDGET_MAX_SYNTHESIS_TOKENS_OUT = 4000
BUDGET_MAX_SCORING_TOKENS_OUT = 1000

# LLM call limits
BUDGET_MAX_LLM_CALLS = 2

# Cache settings
CACHE_TTL_SECONDS = 21600  # 6 hours
CACHE_KEY_VERSION = "v2"
```

---

## Appendix C: Evidence Quality Thresholds

```python
# kairo/hero/services/evidence_quality.py

"""
Evidence quality thresholds for opportunity synthesis.

These are MINIMUM requirements. Below these, synthesis will not run.
"""

# Minimum total evidence items
MIN_EVIDENCE_ITEMS = 8

# Minimum items with non-empty text
MIN_ITEMS_WITH_TEXT = 6

# Minimum transcript coverage (fraction of items with transcripts)
MIN_TRANSCRIPT_COVERAGE = 0.3

# Maximum age of evidence to consider (days)
MAX_EVIDENCE_AGE_DAYS = 30

# Required platforms (at least one must be present)
REQUIRED_PLATFORMS = {"instagram", "tiktok"}

# Minimum freshness (at least one item must be newer than this)
MIN_FRESHNESS_DAYS = 7
```

---

*End of Specification*
