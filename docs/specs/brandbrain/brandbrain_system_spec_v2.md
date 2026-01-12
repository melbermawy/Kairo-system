# BrandBrain System Spec v2.4

**Status:** Implementation-Grade (6/7 actors validated; LinkedIn profile posts unvalidated)
**Scope:** Backend only (Django + Postgres)
**Last Updated:** January 2026
**Validation:** Appendix B & C validated against local ApifyRun DB records and `var/apify_samples/` (except `apimaestro~linkedin-profile-posts`)

---

## Table of Contents

1. [Goals, Non-Goals, and Current Reality](#0-goals-non-goals-and-current-reality)
   - [Naming Guidance](#01-naming-guidance-internal-vs-external)
2. [Key Architectural Decisions](#1-key-architectural-decisions)
   - [Performance & Latency Contracts](#11-performance--latency-contracts)
   - [Indexing Requirements](#12-indexing-requirements-for-budgets)
   - [Implementation Roadmap (PR Plan)](#13-implementation-roadmap-pr-plan)
3. [Data Model](#2-data-model-django-models)
   - [EvidenceStatus Schema](#evidencestatus-schema)
4. [Internal Dev Budget & Caching Policy](#3-internal-only-dev-budget--caching-policy)
5. [Actor Registry](#4-actor-registry)
6. [Normalization Mapping](#5-normalization-mapping-per-actor)
7. [Onboarding Questions Mapping](#6-onboarding-questions--brandbrain-field-path-mapping)
   - [PlatformRulesInput Schema](#platformrulesinput-schema)
8. [Pipeline](#7-pipeline-automatic-onboarding--compile)
   - [Compile Gating Requirements](#70-compile-gating-requirements)
9. [BrandBrainSnapshot Schema](#8-brandbrainsnapshot-schema-v0)
   - [Field Confidence & Fallback Contract](#83-field-confidence--fallback-contract)
10. [Overrides & Pinning](#9-overrides--pinning-merge-semantics)
11. [APIs](#10-apis-backend)
12. [Acceptance Tests](#11-acceptance-tests)
13. [Appendix A: Question-to-Field Mapping](#appendix-a--question-to-field-mapping)
14. [Appendix B: Normalization Mappings](#appendix-b--normalization-mappings-per-actor)
15. [Appendix C: Actor Input Templates](#appendix-c--actor-input-templates)

---

## 0) Goals, Non-Goals, and Current Reality

### Goals (v1)

- Create a multi-brand, multi-platform BrandBrain system that compiles:
  - Tiered onboarding answers
  - Scraped evidence (Apify actors)
  - Optional web homepage crawl
- Into a canonical **BrandBrainSnapshot**
- Support inference-first with overrides + pinning so outputs don't drift
- Keep everything debuggable (raw → normalized → bundle → compile → snapshot)
- Keep actor integration swappable via an actor-agnostic normalized layer
- Keep onboarding "automatic" from the user's POV

### Non-Goals (v1)

- Blog discovery crawl that reliably extracts post bodies (we don't have it; treat web as homepage + user-provided key pages via `settings_json.extra_start_urls`)
- Transcripts for YouTube/TikTok (current actors don't provide them)
- Agentic planning frameworks

### What Is Already Built (Step 1 Infra)

- `kairo/integrations/apify/client.py` with 3 primitives: `start_actor_run`, `poll_run`, `fetch_dataset_items`
- Raw-first storage: `ApifyRun` + `RawApifyItem` (JSONB)
- `brandbrain_apify_explore` management command with resume-mode + hard caps + samples written to `var/apify_samples/...`

### What Is NOT Built Yet (This Spec Adds It)

- Actor registry + input templates + internal caps
- Automatic "onboarding compile" pipeline that triggers ingestion when needed
- Normalization adapters per actor
- Evidence bundling + deterministic feature extraction
- BrandBrain compiler + schema + QA + merge overrides/pins
- API endpoints for onboarding + compile + snapshot + overrides

---

## 0.1) Naming Guidance (Internal vs External)

**Internal naming (code, APIs, database):** Continue using `BrandBrain` and `BrandBrainSnapshot` in all backend code, models, and API routes. No route changes required.

**External naming (UI labels):** The term "BrandBrain" should NOT be exposed to end users. Recommended alternatives for UI/marketing:

| Alternative | Pros | Use When |
|-------------|------|----------|
| **Brand Profile** | Neutral, familiar | General-purpose; safe default |
| **Brand Foundations** | Emphasizes core identity | Positioning the feature as foundational setup |
| **Playbook** | Action-oriented, recognizable | Emphasizing practical guidance for content creation |

> **Implementation Note:** FE should use a display name constant that maps internal `brandbrain` references to the chosen external label. This allows easy renaming without backend changes.

---

## 1) Key Architectural Decisions

1. **NormalizedEvidenceItem is the stable seam.**
   Downstream (bundling/compile) consumes normalized items only; raw is for audit/debug.

2. **Onboarding is "automatic" for users.**
   Users provide sources + answers; the system may auto-run ingestion behind the scenes as needed.

3. **Budget is internal-only (dev optimization), not a product UX concept (for now).**
   We enforce caps and caching via config/env so we don't burn free-tier credits during development. Users never see "budget" or "pull N examples."

4. **Inference-first with overrides + pins.**
   Compiler proposes; user can override and pin. Recompiles must preserve pinned fields deterministically.

---

### 1.1 Performance & Latency Contracts

This section defines hard performance boundaries that backend implementations must meet.

#### P95 Latency Budgets

| Endpoint | P95 Target | Notes |
|----------|------------|-------|
| `GET /api/brands/:id/brandbrain/latest` | **50ms** | Single indexed lookup + JSON return |
| `GET /api/brands/:id/brandbrain/history` | **100ms** | Paginated; default page_size=10, max=50 |
| `POST /api/brands/:id/brandbrain/compile` | **200ms** (kickoff) | Returns immediately with `compile_run_id`; work runs async |
| `GET /api/brands/:id/brandbrain/compile/:compile_run_id/status` | **30ms** | Status poll; no computation |

> **Note:** The compile endpoint returns a `202 Accepted` with `compile_run_id` immediately. Actual compilation (ingestion, LLM calls, etc.) happens asynchronously. Clients poll the status endpoint or receive webhook/SSE notification on completion.

#### Read-Path vs Work-Path Boundary

**Hard Rule:** No read-path endpoint may trigger ingestion, normalization, or LLM work.

| Path Type | Endpoints | Allowed Operations |
|-----------|-----------|-------------------|
| **Read-path** | `GET /latest`, `GET /history`, `GET /status`, `GET /overrides` | DB reads only; no side effects |
| **Work-path** | `POST /compile`, `PATCH /overrides` | May schedule async work; `/compile` triggers pipeline |

**Violations of this rule constitute a bug.** If a GET endpoint is slow because it's computing something, refactor to precompute or move to work-path.

#### Payload Cap Guidance

To meet latency targets, read endpoints return **compact payloads by default**:

| Endpoint | Default Response | Excluded by Default |
|----------|------------------|---------------------|
| `GET /latest` | `snapshot_json` + `meta` | `raw_refs` arrays, `qa_report_json`, full `evidence_status_json` |
| `GET /history` | List of `{id, created_at, diff_summary}` | Full `snapshot_json`, `diff_from_previous_json` |

**Debug/verbose mode:** Add `?include=full` or `?include=qa,evidence` query params to fetch additional data. These endpoints may exceed P95 targets and should be flagged in monitoring.

```typescript
// Compact response (default)
interface LatestSnapshotResponse {
  snapshot_id: UUID;
  brand_id: UUID;
  snapshot_json: BrandBrainSnapshot;  // full snapshot structure
  created_at: datetime;
  compile_run_id: UUID;
}

// With ?include=full
interface LatestSnapshotResponseFull extends LatestSnapshotResponse {
  evidence_status: EvidenceStatus;
  qa_report: QAReport;
  bundle_summary: BundleSummary;
}
```

#### Compile Short-Circuit (No-Op Detection)

Before scheduling async compile work, check if a no-op compile would occur. If so, return the existing snapshot immediately (sync, within 50ms).

**No-op conditions (all must be true):**

1. Latest snapshot exists for brand
2. All enabled source connections have successful ApifyRuns within TTL
3. `hash(onboarding_answers_json)` matches snapshot's `onboarding_snapshot_json` hash
4. `hash(overrides_json + pinned_paths)` matches snapshot's override state
5. `prompt_version` and `model` match current config

```python
def should_short_circuit_compile(brand_id: UUID) -> tuple[bool, Optional[BrandBrainSnapshot]]:
    """
    Returns (True, existing_snapshot) if no-op, else (False, None).
    Must complete in <20ms to stay within compile kickoff budget.
    """
    latest = get_latest_snapshot(brand_id)  # indexed lookup
    if not latest:
        return False, None

    # Check freshness
    if any_source_stale(brand_id):
        return False, None

    # Check input hashes
    current_hash = compute_compile_input_hash(brand_id)
    if latest.input_hash != current_hash:
        return False, None

    return True, latest
```

**Short-circuit response:** Return `200 OK` with `{"status": "UNCHANGED", "snapshot": ...}` instead of `202 Accepted`.

---

### 1.2 Indexing Requirements for Budgets

To meet the latency contracts above, the following indexes are **required**:

#### Required Indexes

| Table | Index | Purpose | Query Pattern |
|-------|-------|---------|---------------|
| `BrandBrainSnapshot` | `brand_id, created_at DESC` | Latest snapshot lookup | `GET /latest` |
| `BrandBrainSnapshot` | `brand_id, created_at DESC` (partial: `LIMIT 50`) | History pagination | `GET /history` |
| `BrandBrainCompileRun` | `id` (PK) | Status lookup | `GET /status` |
| `BrandBrainCompileRun` | `brand_id, created_at DESC` | Latest compile run | Short-circuit check |
| `ApifyRun` | `source_connection_id, status, created_at DESC` | Latest successful run per source | TTL freshness check |
| `ApifyRun` | `brand_id, status` | All runs for brand | Compile evidence gathering |
| `NormalizedEvidenceItem` | `brand_id, platform, content_type, created_at DESC` | Bundle selection by recency | Bundler heuristics |
| `NormalizedEvidenceItem` | `brand_id, platform, content_type, external_id` (unique) | Dedupe on normalize | Idempotent normalization |
| `NormalizedEvidenceItem` | `brand_id, platform, content_type, canonical_url` (unique, partial: web only) | Web page dedupe | Web normalization |
| `SourceConnection` | `brand_id, is_enabled` | Enabled sources for brand | Compile gating |

#### Uniqueness Constraints (Already Specified)

These are already in the data model but restated for completeness:

- `NormalizedEvidenceItem`: `UNIQUE(brand_id, platform, content_type, external_id)` where `external_id IS NOT NULL`
- `NormalizedEvidenceItem`: `UNIQUE(brand_id, platform, content_type, canonical_url)` where `platform = 'web'`
- `BrandOnboarding`: `UNIQUE(brand_id)` (1:1)
- `BrandBrainOverrides`: `UNIQUE(brand_id)` (1:1)

#### Index Implementation Notes

```sql
-- Latest snapshot per brand (covering index for compact response)
CREATE INDEX idx_snapshot_brand_latest
ON brandbrain_snapshot (brand_id, created_at DESC)
INCLUDE (id, compile_run_id);

-- Latest successful ApifyRun per source (for TTL check)
CREATE INDEX idx_apifyrun_source_success
ON apify_run (source_connection_id, created_at DESC)
WHERE status = 'SUCCEEDED';

-- Normalized items for bundling (recency + engagement sorting)
CREATE INDEX idx_normalized_brand_recency
ON normalized_evidence_item (brand_id, platform, published_at DESC NULLS LAST);
```

> **Spec Requirement:** Before shipping, run `EXPLAIN ANALYZE` on all read-path queries and verify index usage. Any full table scan on read-path is a bug.

---

### 1.3 Implementation Roadmap (PR Plan)

This roadmap breaks the BrandBrain backend into reviewable PRs. Each PR must respect the spec's hard rules: read-path/work-path boundary, P95 latency budgets, required indexes, two-layer cap enforcement, TTL caching, and feature flag containment.

#### PR Summary Table

| PR | Name | Key Deliverables | Dependencies |
|----|------|------------------|--------------|
| PR-0 | Test Harness + Fixtures | pytest setup, factories, contract test skeletons | None |
| PR-1 | Data Model + Migrations + Indexes | Models, migrations, required indexes | PR-0 |
| PR-2 | Actor Registry + Caps/TTL | ActorRegistry, input builders, two-layer caps, TTL checks | PR-1 |
| PR-3 | Normalization Adapters | Per-actor normalization, dedupe, golden tests | PR-2 |
| PR-4 | Evidence Bundling | Bundle selection, FeatureReport, collection-page exclusion | PR-3 |
| PR-5 | Compile Orchestration Skeleton | Async kickoff, status endpoint, short-circuit, gating | PR-4 |
| PR-6 | BrandBrain Compiler + QA | LLM compile, confidence caps, overrides/pins merge | PR-5 |
| PR-7 | API Surface + Contract Tests | All endpoints, payload options, performance guards | PR-6 |

---

#### PR-0 — Test Harness + Fixtures (Surgical)

**Scope:** Testing infrastructure only.

**Deliverables:**
- pytest setup + CI target (fast, <30s for unit suite)
- DB fixtures + factories/builders for all models:
  - `Brand`, `BrandOnboarding`, `SourceConnection`
  - `ApifyRun`, `RawApifyItem`, `NormalizedEvidenceItem`
  - `BrandBrainOverrides`, `BrandBrainCompileRun`, `BrandBrainSnapshot`
- Contract test skeletons for read-path endpoints (empty handlers ok)
- Helper loader for `var/apify_samples/` to support golden normalization tests

**Non-goals:**
- No refactors to existing code
- No business logic
- No new endpoints

**Acceptance:**
- [ ] Tests run locally in <30s for unit suite
- [ ] Fixtures are importable and usable in test files
- [ ] CI pipeline passes

---

#### PR-1 — Data Model + Migrations + Indexes

**Scope:** Database schema only.

**Deliverables:**
- Implement all models from Section 2 with exact fields and constraints
- Uniqueness constraints as specified (NEI dedupe, 1:1 relationships)
- Required indexes from Section 1.2
- Extend `ApifyRun` with optional fields: `brand_id`, `source_connection_id`, `raw_item_count`, `normalized_item_count`

**Non-goals:**
- No actor registry
- No ingestion triggers
- No normalization logic
- No compile logic

**Acceptance:**
- [ ] Migrations apply cleanly (`python manage.py migrate`)
- [ ] `EXPLAIN ANALYZE` confirms index usage for:
  - Latest snapshot lookup: `SELECT ... FROM brandbrain_snapshot WHERE brand_id=? ORDER BY created_at DESC LIMIT 1`
  - ApifyRun TTL lookup: `SELECT ... FROM apify_run WHERE source_connection_id=? AND status='SUCCEEDED' ORDER BY created_at DESC LIMIT 1`
- [ ] No read-path code yet—schema only

---

#### PR-2 — Actor Registry + Input Builders + Cap/TTL Enforcement

**Scope:** Actor configuration and freshness logic (no normalization yet).

**Deliverables:**
- `ActorRegistry` with exact specs from Section 4 and templates from Appendix C
- Input builder functions for each validated actor (6 of 7)
- Two-layer cap enforcement:
  - Actor-input caps (e.g., `resultsLimit`, `maxResults`)
  - Dataset-fetch cap in `fetch_dataset_items(limit=N)`
- TTL freshness check per `SourceConnection`:
  - Reuse last `SUCCEEDED` `ApifyRun` within TTL
  - Return `(should_refresh: bool, cached_run: Optional[ApifyRun])`
- Feature flag gate for `linkedin.profile_posts` (excluded by default)

**Non-goals:**
- No normalization adapters
- No bundling
- No LLM compile

**Acceptance:**
- [ ] Unit tests for each input builder (verify output matches Appendix C templates)
- [ ] Unit tests for cap clamping (verify caps are enforced regardless of input)
- [ ] Unit tests for TTL decision matrix:
  - No cached run → refresh
  - Cached run within TTL → reuse
  - Cached run older than TTL → refresh
  - `force_refresh=true` → refresh
- [ ] Feature flag test: `linkedin.profile_posts` is skipped when flag is off

---

#### PR-3 — Normalization Adapters + Idempotent Dedupe

**Scope:** Raw → Normalized transformation.

**Deliverables:**
- Normalization adapter per validated actor (Appendix B mappings)
- Create `NormalizedEvidenceItem` with `raw_refs` pointers
- Dedupe enforcement via unique constraints + safe upserts (`ON CONFLICT DO UPDATE` or equivalent)
- `flags_json` population: `has_transcript`, `is_low_value`, `is_collection_page`

**Non-goals:**
- No bundling or feature extraction
- No BrandBrain schema
- No LLM compile

**Acceptance:**
- [ ] Golden tests against `var/apify_samples/` for each validated actor:
  - `apify~instagram-scraper`
  - `apify~instagram-reel-scraper`
  - `apimaestro~linkedin-company-posts`
  - `clockworks~tiktok-scraper`
  - `streamers~youtube-scraper`
  - `apify~website-content-crawler`
- [ ] Re-running same dataset does not create duplicate `NormalizedEvidenceItem` rows
- [ ] `raw_refs` correctly points back to `ApifyRun` + `RawApifyItem`

---

#### PR-4 — Evidence Bundling + Deterministic FeatureReport

**Scope:** Bundle creation and feature extraction (no LLM).

**Deliverables:**
- `EvidenceBundle` creation with deterministic selection heuristics (Section 7.2):
  - `min(cap, recent_M + top_by_engagement_N)` per platform
  - Respect global max (40 items)
- Web collection-page exclusion logic (Appendix B7 `is_collection_page` flag)
- Key pages eligibility (from `extra_start_urls`) even if homepage is low-value
- `FeatureReport` with deterministic stats: emoji density, CTA frequency, avg lengths, hook markers

**Non-goals:**
- No compile orchestration
- No API endpoints

**Acceptance:**
- [ ] Unit tests prove bundle size respects caps
- [ ] Unit tests prove `is_collection_page=true` items are excluded (unless web-only evidence)
- [ ] `FeatureReport` output is deterministic given same bundle input

---

#### PR-5 — Compile Orchestration Skeleton (Async Kickoff + Status)

**Scope:** Compile lifecycle management (stub LLM output).

**Deliverables:**
- `POST /compile` creates `BrandBrainCompileRun` with:
  - Status: `PENDING` → `RUNNING` → `SUCCEEDED`/`FAILED`
  - `evidence_status_json` structure populated
- Compile gating enforcement (Section 7.0):
  - Tier0 required fields present
  - ≥1 enabled `SourceConnection`
- Short-circuit compile (no-op detection):
  - Check TTL + onboarding hash + overrides hash + prompt_version + model
  - Return `200 OK` with `UNCHANGED` status if no-op
- Async mechanism:
  - **Decision point:** Use existing background job system if present (e.g., Celery, Django-Q, etc.)
  - If none exists, implement minimal async runner (document choice in PR)
  - Do NOT introduce heavy framework without justification

**Non-goals:**
- No LLM draft generation (stub `draft_json` with placeholder)
- No QA checks
- No overrides/pins merge

**Acceptance:**
- [ ] `POST /compile` returns within 200ms (kickoff only)
- [ ] `GET /status` is pure DB read, p95 < 30ms
- [ ] No GET endpoint triggers ingestion or LLM work (hard rule)
- [ ] Short-circuit returns existing snapshot when inputs unchanged
- [ ] Gating rejects compile if Tier0 fields missing or no sources

---

#### PR-6 — BrandBrain Compiler + QA + Overrides/Pins Merge

**Scope:** LLM compilation and post-processing.

**Deliverables:**
- `BrandBrainSnapshot` schema implementation (Section 8):
  - `FieldNode` primitive with `value`, `confidence`, `sources`, `locked`, `override_value`
  - All top-level sections: `positioning`, `voice`, `pillars`, `constraints`, `platform_profiles`, `examples`, `meta`
- LLM compile step:
  - Input: onboarding answers + evidence bundle + feature report
  - Output: schema-valid `draft_json`
  - Provenance required (sources array populated)
- QA checks (`qa_report_json`)
- Evidence-aware confidence caps (Section 7.0 + 8.3)
- `meta.missing_inputs` population based on evidence gaps
- Overrides/pins merge semantics (Section 9):
  - Pin persistence approach (store pinned values explicitly)
  - Merge rules: pinned+override → override wins; pinned+no override → preserve; etc.

**Non-goals:**
- No FE changes
- No new API endpoints beyond compile flow

**Acceptance:**
- [ ] Pin stability test: pinned field survives recompile with new evidence
- [ ] Confidence cap tests: web-only → voice capped at 0.3, etc.
- [ ] "Never infer taboos" rule: `constraints.taboos` only populated from answers
- [ ] Schema validation: `draft_json` passes JSON schema check

---

#### PR-7 — API Surface + Contract Tests + Performance Guards

**Scope:** Complete API implementation with quality gates.

**Deliverables:**
- Implement all endpoints from Section 10:
  - `POST /api/brands/:id/brandbrain/compile`
  - `GET /api/brands/:id/brandbrain/compile/:compile_run_id/status`
  - `GET /api/brands/:id/brandbrain/latest` (compact by default)
  - `GET /api/brands/:id/brandbrain/history` (paginated)
  - `PATCH /api/brands/:id/brandbrain/overrides`
- `?include=full` and `?include=qa,evidence` query params for verbose mode
- Contract tests for:
  - Response payload shapes match TypeScript interfaces
  - Status transitions: `PENDING` → `RUNNING` → `SUCCEEDED`/`FAILED`
  - Error responses for gating failures
- Performance guardrails:
  - Read endpoints are DB-only (no side effects)
  - Payload caps enforced (no `raw_refs` in compact mode)

**Acceptance:**
- [ ] Contract tests pass for all endpoints
- [ ] Spot-check latency with profiling (document results in PR)
- [ ] No `time.sleep()` or intentional delays in backend code paths
- [ ] `?include=full` noted as potentially exceeding P95 in monitoring

---

#### Review Discipline

Every PR in this roadmap must follow these rules:

1. **Small and reviewable** — Each PR should be mergeable in a single review session. If it's too big, split it.

2. **Tests required** — No PR merges without test coverage for new code paths.

3. **Read-path/work-path boundary** — Any PR that adds a GET endpoint must prove it does DB reads only. Any side effect is a bug.

4. **P95 risk callout** — If a change risks exceeding latency budgets, call it out explicitly in the PR description with mitigation plan.

5. **No scope creep** — Stick to deliverables listed. New features require spec update first.

---

## 2) Data Model (Django Models)

> Names can be adjusted to match existing conventions, but the fields and constraints must exist.

### 2.1 Brand + Onboarding

#### Brand

```python
class Brand:
    id: UUID
    tenant_id: UUID
    name: str
    website_url: str (nullable)
    created_at: datetime
```

#### BrandOnboarding

```python
class BrandOnboarding:
    brand_id: UUID  # 1:1 relationship
    tier: int  # 0, 1, or 2
    answers_json: dict  # JSONB - keyed by stable question_id
    updated_at: datetime
    updated_by: UUID
```

### 2.2 Sources + Runs (SourceConnection + ApifyRun)

> **Important:** Do NOT introduce a separate `SourceRun` model. The existing `ApifyRun` model already handles run tracking. We extend it with optional fields to link runs to source connections.

#### SourceConnection

```python
class SourceConnection:
    brand_id: UUID
    platform: str  # enum: instagram|linkedin|tiktok|youtube|web
    capability: str  # enum (see below)
    identifier: str  # handle/url/channel id depending on platform/capability
    is_enabled: bool
    settings_json: dict  # JSONB - optional per-source knobs (e.g., for web: {"extra_start_urls": ["https://.../about", "https://.../pricing"]})
    created_at: datetime
    updated_at: datetime
```

**Web `settings_json` contract:**
- `extra_start_urls` (string[], optional): User-provided "key pages" (about, pricing, case studies, etc.)
- Server clamps to at most **2 extra URLs** in v1 (so total web start URLs ≤ 3: homepage + 2 key pages)
- Populated from `tier1.key_pages` onboarding answer when web SourceConnection exists

**Capability enum by platform:**

| Platform  | Capabilities                    |
|-----------|---------------------------------|
| instagram | `posts`, `reels`                |
| linkedin  | `company_posts`, `profile_posts` ⚠️ |
| tiktok    | `profile_videos`                |
| youtube   | `channel_videos`                |
| web       | `crawl_pages`                   |

> ⚠️ `linkedin.profile_posts` is **unvalidated** and **behind feature flag**. Excluded from default bundling until validated.

#### ApifyRun (existing; extended)

The existing `ApifyRun` model will be extended with these optional fields:

```python
# Extensions to existing ApifyRun model
class ApifyRun:
    # ... existing fields (actor_id, run_id, dataset_id, status, input_json, etc.) ...

    # NEW optional fields for BrandBrain integration:
    source_connection_id: UUID (nullable)  # links run to a SourceConnection
    brand_id: UUID (nullable)              # optional denorm for faster queries
    raw_item_count: int (default 0)        # count of RawApifyItem rows created
    normalized_item_count: int (default 0) # count of NormalizedEvidenceItem rows created
```

**Usage notes:**

- `brandbrain_apify_explore` command can continue creating `ApifyRun` rows with `source_connection_id=NULL` (ad-hoc exploration)
- The automatic BrandBrain pipeline **must always** set `source_connection_id` when triggering runs
- Caching/TTL checks query for the latest successful `ApifyRun` per `SourceConnection` (where `source_connection_id` is set and `status=SUCCEEDED`)

### 2.3 Normalized Evidence (Stable Seam)

#### NormalizedEvidenceItem

```python
class NormalizedEvidenceItem:
    brand_id: UUID
    platform: str  # enum: instagram|linkedin|tiktok|youtube|web
    content_type: str  # enum: post|reel|text_post|short_video|video|web_page
    external_id: str (nullable)  # nullable for web
    canonical_url: str
    published_at: datetime (nullable)
    author_ref: str  # handle/company/channel id
    title: str (nullable)
    text_primary: str  # caption/body/title
    text_secondary: str (nullable)  # description
    hashtags: list[str]  # JSON array, default empty
    metrics_json: dict  # JSONB
    media_json: dict  # JSONB
    raw_refs: list[dict]  # JSONB list of {apify_run_uuid, raw_item_id} pointers
    flags_json: dict  # JSONB - ex: {"is_collection_page": true, "has_transcript": false}
    created_at: datetime
    updated_at: datetime
```

**Uniqueness constraints:**

- When `external_id` present: `UNIQUE(brand_id, platform, content_type, external_id)`
- For web pages: `UNIQUE(brand_id, platform, content_type, canonical_url)`

### 2.4 Bundles + Deterministic Features

#### EvidenceBundle

```python
class EvidenceBundle:
    brand_id: UUID
    criteria_json: dict  # limits/heuristics used
    item_ids: list[UUID]  # array of NormalizedEvidenceItem.id OR M2M join table
    summary_json: dict  # counts per platform, transcript coverage, recency
    created_at: datetime
```

#### FeatureReport

```python
class FeatureReport:
    brand_id: UUID
    bundle_id: UUID
    stats_json: dict  # emoji density, CTA frequency, avg lengths, hook markers
    created_at: datetime
```

### 2.5 BrandBrain Compile + Overrides + Snapshots

#### BrandBrainCompileRun

```python
class BrandBrainCompileRun:
    brand_id: UUID
    bundle_id: UUID
    onboarding_snapshot_json: dict  # copy of answers used
    prompt_version: str
    model: str
    status: str  # enum: SUCCEEDED|FAILED
    draft_json: dict  # LLM output, schema-valid
    qa_report_json: dict
    evidence_status_json: dict  # NEW: see EvidenceStatus schema below
    created_at: datetime
    error: str (nullable)
```

#### EvidenceStatus Schema

The `evidence_status_json` field reports what happened with each source during compile. This enables UI to show users which sources were used vs refreshed vs skipped.

```typescript
interface EvidenceStatus {
  reused: EvidenceSourceEntry[];    // used cached ApifyRun (within TTL)
  refreshed: EvidenceSourceEntry[]; // triggered new ApifyRun
  skipped: EvidenceSourceEntry[];   // intentionally excluded (e.g., unvalidated actor)
  failed: EvidenceSourceEntry[];    // ingestion attempted but failed
}

interface EvidenceSourceEntry {
  source_connection_id: UUID;
  platform: string;
  capability: string;
  reason: string;                   // human-readable explanation
  apify_run_id?: UUID;              // if applicable
  item_count?: number;              // normalized items from this source
  run_age_hours?: number;           // for reused: how old the cached run is
}
```

**Example `evidence_status_json`:**

```json
{
  "reused": [
    {
      "source_connection_id": "abc-123",
      "platform": "instagram",
      "capability": "posts",
      "reason": "Cached run within TTL (18h old)",
      "apify_run_id": "run-456",
      "item_count": 8,
      "run_age_hours": 18
    }
  ],
  "refreshed": [
    {
      "source_connection_id": "def-789",
      "platform": "linkedin",
      "capability": "company_posts",
      "reason": "No cached run found",
      "apify_run_id": "run-012",
      "item_count": 6
    }
  ],
  "skipped": [
    {
      "source_connection_id": "ghi-345",
      "platform": "linkedin",
      "capability": "profile_posts",
      "reason": "Actor unvalidated; excluded from bundling"
    }
  ],
  "failed": []
}
```

#### BrandBrainOverrides

```python
class BrandBrainOverrides:
    brand_id: UUID  # 1:1 relationship
    overrides_json: dict  # field_path → override_value
    pinned_paths: list[str]  # array of field_paths
    updated_at: datetime
    updated_by: UUID
```

#### BrandBrainSnapshot

```python
class BrandBrainSnapshot:
    brand_id: UUID
    compile_run_id: UUID
    snapshot_json: dict  # final merged
    diff_from_previous_json: dict
    created_at: datetime
```

---

## 3) Internal-Only Dev Budget & Caching Policy

> **NOT user-facing** - This is backend enforcement only.

### 3.1 Dev Caps (Defaults)

Caps are enforced server-side regardless of what input JSON says.

| Source Type          | Default Cap |
|----------------------|-------------|
| Instagram posts      | 8           |
| Instagram reels      | 6           |
| LinkedIn company     | 6           |
| LinkedIn profile     | 6           |
| TikTok profile videos| 6           |
| YouTube channel videos| 6          |
| Web crawl            | 3 (homepage + up to 2 key pages from `settings_json.extra_start_urls`) |

**Global max items per BrandBrain compile (normalized input to bundler):** 40 items

### 3.1.1 Two-layer cap enforcement (important gotcha)

Caps must be enforced at **two layers** to protect dev/free-tier credits and prevent accidental large normalizations:

1. **Actor-input caps** — Pass the cap value in the actor's input JSON where the actor supports it (e.g., `resultsLimit`, `maxResults`, `limit`). This reduces work done by the actor.

2. **Dataset-fetch cap** — **ALWAYS** pass a `limit` parameter to `fetch_dataset_items()` regardless of what the actor-input cap was. This is the hard backstop.

**Why both layers?**
- Some actors ignore input caps or have inconsistent behavior
- Some actors may still incur cost even if we fetch fewer items (the scrape already happened)
- Dataset-fetch cap guarantees we never normalize more items than intended
- Protects against unexpected actor behavior or misconfiguration

**Implementation rule:** When calling `fetch_dataset_items(dataset_id, limit=N)`, always pass `limit` equal to the configured cap for that source type. Never fetch unbounded.

### 3.2 Caching Rules

To avoid repeated spend while iterating:

- Per source connection, reuse last successful `ApifyRun` (linked via `source_connection_id`) if within TTL
- `APIFY_RUN_TTL_HOURS=24` (dev default)
- A compile may trigger ingestion only when:
  - No successful `ApifyRun` linked to that `SourceConnection` exists, OR
  - The latest successful `ApifyRun` is older than TTL, OR
  - `force_refresh=true` (internal/dev flag)

### 3.3 Configuration Knobs (Environment Variables)

```bash
BRANDBRAIN_DEV_MODE=true
BRANDBRAIN_APIFY_RUN_TTL_HOURS=24
BRANDBRAIN_CAP_IG_POSTS=8
BRANDBRAIN_CAP_IG_REELS=6
BRANDBRAIN_CAP_LI=6
BRANDBRAIN_CAP_TT=6
BRANDBRAIN_CAP_YT=6
BRANDBRAIN_CAP_WEB=3  # total pages across all startUrls (homepage + up to 2 key pages)
BRANDBRAIN_MAX_NORMALIZED_ITEMS=40
```

> None of this is exposed in APIs or UI. It's backend enforcement only.

---

## 4) Actor Registry

### 4.1 Why We Need This

Right now we can run actors manually (commands). To make onboarding automatic and deterministic, we need a registry that:

- Chooses the `actor_id`
- Builds input JSON from `SourceConnection.identifier`
- Clamps limits server-side

### 4.2 Registry Data Structure

**ActorSpec fields:**

```python
@dataclass
class ActorSpec:
    platform: str
    capability: str
    actor_id: str  # Apify actor
    build_input: Callable[[SourceConnection, int], dict]
    cap_fields: list[str]  # which input keys are limit-like
    notes: str  # known limitations
```

### 4.3 V1 Registry Entries

#### Instagram: Posts

- **Platform:** instagram
- **Capability:** posts
- **Actor ID:** `apify~instagram-scraper`
- **Input Template:** See [Appendix C1](#c1-apifyinstagram-scraper-posts)
- **Cap:** `resultsLimit` in actor input + always enforce dataset-fetch cap

#### Instagram: Reels

- **Platform:** instagram
- **Capability:** reels
- **Actor ID:** `apify~instagram-reel-scraper`
- **Input Template:** See [Appendix C2](#c2-apifyinstagram-reel-scraper-reels)
- **Cap:** `resultsLimit` in actor input (only applies to profile scraping) + always enforce dataset-fetch cap
- **Note:** Dominant voice evidence when transcript present. See Appendix C2 for `resultsLimit` gotcha.

#### LinkedIn: Company Posts

- **Platform:** linkedin
- **Capability:** company_posts
- **Actor ID:** `apimaestro~linkedin-company-posts`
- **Input Template:** See [Appendix C3](#c3-apimaestrolinkedin-company-posts) (validated)
- **Cap:** `limit` in actor input + always enforce dataset-fetch cap

#### LinkedIn: Profile Posts

- **Platform:** linkedin
- **Capability:** profile_posts
- **Actor ID:** `apimaestro~linkedin-profile-posts`
- **Input Template:** See [Appendix C4](#c4-apimaestrolinkedin-profile-posts) ⚠️ **UNVALIDATED**
- **Cap:** `limit` in actor input + always enforce dataset-fetch cap
- **⚠️ Containment:** This actor is **unvalidated** and **behind feature flag**. Must NOT be included in default bundling until validated. Excluded from production pipelines.

#### TikTok: Profile Videos

- **Platform:** tiktok
- **Capability:** profile_videos
- **Actor ID:** `clockworks~tiktok-scraper`
- **Input Template:** See [Appendix C5](#c5-clockworkstiktok-scraper)
- **Cap:** `resultsPerPage` in actor input + always enforce dataset-fetch cap

#### YouTube: Channel Videos

- **Platform:** youtube
- **Capability:** channel_videos
- **Actor ID:** `streamers~youtube-scraper`
- **Input Template:** See [Appendix C6](#c6-streamersyoutube-scraper)
- **Cap:** `maxResults` in actor input + always enforce dataset-fetch cap

#### Web: Crawl Pages (Explicit)

- **Platform:** web
- **Capability:** crawl_pages
- **Actor ID:** `apify~website-content-crawler`
- **Input Template:** See [Appendix C7](#c7-apifywebsite-content-crawler)
- **Cap:** `maxCrawlPages` in actor input + always enforce dataset-fetch cap
- **Note:** Cap is total pages; key pages come from `SourceConnection.settings_json.extra_start_urls` (populated via `tier1.key_pages`)

---

## 5) Normalization Mapping Per Actor

### Goal

Deterministic adapters. No guessing. Defensive against missing keys. Store `raw_refs` always.

### Adapter Interface

```python
def normalize(
    actor_id: str,
    raw_item_json: dict,
    brand_id: UUID,
    source_connection: SourceConnection
) -> NormalizedEvidenceItem:
    """
    Must:
    - Compute canonical_url
    - Compute external_id when possible
    - Set text_primary and text_secondary from known fields
    - Map metrics into metrics_json
    - Set flags (has_transcript, is_collection_page, etc.)
    """
    pass
```

See [Appendix B](#appendix-b--normalization-mappings-per-actor) for per-actor mappings.

---

## 6) Onboarding Questions → BrandBrain Field-Path Mapping

Question IDs are stable keys in `BrandOnboarding.answers_json`. Mapping is deterministic so the compiler can't invent structure.

### Tier 0 Mapping (Required)

| question_id | type | required | maps_to snapshot field path | notes |
|-------------|------|----------|----------------------------|-------|
| `tier0.what_we_do` | string | Yes | `positioning.what_we_do.value` | 1 sentence |
| `tier0.who_for` | string | Yes | `positioning.who_for.value` | 1 sentence |
| `tier0.edge` | string[] | No | `positioning.differentiators.value` | 1-2 picks; strongly recommended |
| `tier0.tone_words` | string[] | No | `voice.tone_tags.value` | 3-5; strongly recommended |
| `tier0.taboos` | string[] | No | `constraints.taboos.value` | 3 bullets; strongly recommended |
| `tier0.primary_goal` | string | Yes | `meta.content_goal.value` | enum |
| `tier0.cta_posture` | string | Yes | `voice.cta_policy.value` | enum |

> **Note:** Fields marked "strongly recommended" are not compile blockers but significantly improve output quality. If omitted, the compiler will infer values with lower confidence and flag them in `meta.missing_inputs`.

### Tier 1 Mapping (Adds)

| question_id | type | required | maps_to | notes |
|-------------|------|----------|---------|-------|
| `tier1.priority_platforms` | string[] | Yes | `meta.priority_platforms.value` | multi-select |
| `tier1.pillars_seed` | string[] | No | `pillars[].name.value` | compiler can refine |
| `tier1.good_examples` | list | No | `examples.user_examples.value` | store links/text |
| `tier1.key_pages` | string[] | No | `meta.web_key_pages.value` + `SourceConnection.settings_json.extra_start_urls` | about/pricing/case studies URLs |

> **Web key pages propagation:** When onboarding answers are saved and a web `SourceConnection` exists for the brand, update `settings_json.extra_start_urls` from `tier1.key_pages` (clamped to 2 URLs). This ensures the crawler receives the user's key pages.

### Tier 2 Mapping (Power)

| question_id | type | required | maps_to | notes |
|-------------|------|----------|---------|-------|
| `tier2.platform_rules.instagram` | PlatformRulesInput | No | `platform_profiles.instagram.rules` | see schema below |
| `tier2.platform_rules.linkedin` | PlatformRulesInput | No | `platform_profiles.linkedin.rules` | see schema below |
| `tier2.platform_rules.tiktok` | PlatformRulesInput | No | `platform_profiles.tiktok.rules` | see schema below |
| `tier2.platform_rules.youtube` | PlatformRulesInput | No | `platform_profiles.youtube.rules` | see schema below |
| `tier2.proof_claims` | list | No | `positioning.proof_types.value` + `meta.proof_library` | store claim+support |
| `tier2.risk_boundaries` | string[] | No | `constraints.risk_boundaries.value` | separate from taboos |

#### PlatformRulesInput Schema

This is the validated schema for `tier2.platform_rules.<platform>`. Both FE and BE must validate against this structure.

```typescript
interface PlatformRulesInput {
  cadence_per_week?: number;              // 1-14; null = no preference
  preferred_formats?: FormatEnum[];       // platform-specific; see below
  hashtag_policy?: HashtagPolicy;
  link_policy?: LinkPolicy;
  cta_policy_override?: CtaPolicyEnum;    // overrides tier0.cta_posture for this platform
  forbidden_patterns?: string[];          // max 10 items; regex patterns or keywords
}

// Format enums (platform-specific)
type InstagramFormat = "carousel" | "single_image" | "reel" | "story" | "text_post";
type LinkedInFormat = "text_only" | "image" | "carousel" | "video" | "document" | "poll" | "article";
type TikTokFormat = "video" | "photo_carousel" | "duet" | "stitch";
type YouTubeFormat = "long_form" | "shorts" | "livestream";

interface HashtagPolicy {
  usage: "none" | "minimal" | "moderate" | "heavy";  // none=0, minimal=1-3, moderate=4-8, heavy=9+
  max_count?: number;                                 // hard cap; overrides usage if set
}

type LinkPolicy = "never" | "bio_only" | "comments_only" | "in_post" | "any";

type CtaPolicyEnum = "none" | "soft" | "direct" | "aggressive";
```

#### Storage Location

Platform rules are stored in `platform_profiles.<platform>.rules` within the snapshot:

```yaml
platform_profiles:
  instagram:
    # ... other PlatformProfile fields ...
    rules:  # PlatformRulesInput (user-provided, not inferred)
      cadence_per_week: 5
      preferred_formats: ["carousel", "reel"]
      hashtag_policy:
        usage: "moderate"
        max_count: 8
      link_policy: "bio_only"
      cta_policy_override: null  # inherit from tier0
      forbidden_patterns: ["engagement bait", "follow for follow"]
```

> **Backwards Compatibility:** If existing data has unstructured `platform_rules` objects, migration should map known keys to this schema and discard unrecognized keys. Log warnings for discarded keys.

> **Spec Requirement:** Compiler must treat `constraints.taboos` as hard and not infer new taboos by default.

---

## 7) Pipeline (Automatic Onboarding → Compile)

### 7.0 Compile Gating Requirements

Compile is **allowed** when both conditions are met:

1. **Tier 0 required fields present:** `tier0.what_we_do`, `tier0.who_for`, `tier0.primary_goal`, `tier0.cta_posture`
2. **At least one enabled SourceConnection exists** (any platform)

If either condition fails, return a validation error (do not attempt compile).

#### Evidence-Aware Behavior Rules

When compile proceeds but evidence is weak, the compiler must adjust confidence and report gaps:

| Evidence Scenario | Allowed? | Confidence Impact | `meta.missing_inputs` Entry |
|-------------------|----------|-------------------|----------------------------|
| Only web source connected | Yes | Voice fields capped at `0.3`; positioning fields capped at `0.5` | `"No social voice signal; connect Instagram reels/posts or LinkedIn to improve voice inference."` |
| IG reels connected but transcript coverage = 0 | Yes | Voice fields capped at `0.4` | `"Instagram reels connected but no transcripts available; voice inference based on captions only."` |
| IG posts only (no reels) | Yes | Voice fields capped at `0.5` | `"No video transcripts; voice inference based on post captions."` |
| No normalized items after ingestion | Yes | All inferred fields capped at `0.3` | `"Evidence ingestion returned no usable items; compile based on onboarding answers only."` |
| LinkedIn profile posts (unvalidated actor) | Yes | Exclude from bundle; no confidence impact | `"LinkedIn profile posts source skipped (unvalidated)."` |

> **Important:** These are backend enforcement rules. User never sees "budget" and never needs to click "pull N". The UI may surface `meta.missing_inputs` as actionable suggestions.

### 7.1 "Compile BrandBrain" Orchestration (Single Entrypoint)

```python
def compile_brandbrain(brand_id: UUID, force_refresh: bool = False) -> BrandBrainSnapshot:
    """
    Steps:
    0. Validate gating requirements (Tier0 required fields + ≥1 enabled source)
    1. Load onboarding answers + source connections
    2. Ensure evidence freshness (internal TTL):
       - For each enabled source, if no recent successful ApifyRun linked to that SourceConnection exists,
         trigger ingestion using ActorRegistry
    3. Normalize new raw items into NormalizedEvidenceItem (idempotent)
    4. Create an EvidenceBundle using deterministic selection heuristics
    5. Create a FeatureReport from the bundle (deterministic)
    6. Apply evidence-aware confidence caps based on source coverage
    7. LLM compile → draft_json (schema-valid, provenance required)
    8. QA checks
    9. Merge overrides/pins → final BrandBrainSnapshot
    10. Compute diff vs previous snapshot
    11. Populate evidence_status in compile run response
    """
    pass
```

> **Important:** User never sees "budget" and never needs to click "pull N". Compile may run ingestion internally if stale/missing.

### 7.2 Selection Heuristics (Bundle)

Per platform:

- Take `min(cap, recent_M + top_by_engagement_N)` within global max
- Exclude `flags.is_collection_page=true` for web unless web is the only evidence
- **Web key pages:** Items from key pages (sourced from `extra_start_urls`) are eligible for bundling even if the homepage is marked `is_low_value=true`. Collection pages remain excluded by default regardless of source.

---

## 8) BrandBrainSnapshot Schema (v0)

### 8.1 Field Node Primitive (Editable + Provenance)

Every editable leaf is:

```json
{
  "value": "...",
  "confidence": 0.0,
  "sources": [
    {"type": "answer", "id": "tier0.what_we_do"},
    {"type": "evidence", "id": "nei_123"}
  ],
  "locked": false,
  "override_value": null
}
```

### 8.2 Top-Level Shape (Stable)

```yaml
positioning:
  what_we_do: FieldNode
  who_for: FieldNode
  differentiators: FieldNode
  proof_types: FieldNode

voice:
  tone_tags: FieldNode
  do: FieldNode
  dont: FieldNode
  cta_policy: FieldNode
  emoji_policy: FieldNode

pillars: list[PillarNode]

constraints:
  taboos: FieldNode
  risk_boundaries: FieldNode

platform_profiles:
  instagram: PlatformProfile
  youtube: PlatformProfile
  linkedin: PlatformProfile
  tiktok: PlatformProfile

examples:
  canonical_evidence: list[EvidenceRef]
  user_examples: FieldNode

meta:
  compiled_at: datetime
  evidence_summary: dict
  missing_inputs: list[str]
  confidence_summary: dict
  content_goal: FieldNode
  priority_platforms: FieldNode
```

> **Spec Requirement:** `platform_profiles` must exist for each connected platform, even if low-confidence.

### 8.3 Field Confidence & Fallback Contract

Confidence values are deterministic based on evidence availability. This section defines the rules.

#### Confidence Bands

| Band | Range | Meaning |
|------|-------|---------|
| High | 0.7–1.0 | Evidence-backed with transcript or strong signal |
| Medium | 0.4–0.69 | Evidence-backed but limited (captions only, few items) |
| Low | 0.2–0.39 | Answers-only or weak evidence |
| Very Low | 0.0–0.19 | Pure inference with no supporting input |

#### Confidence Drivers by Source Type

| Source Type | Max Confidence Contribution |
|-------------|-----------------------------|
| Onboarding answer (direct mapping) | 0.9 (user-provided = high trust) |
| IG reels with transcript | 0.85 (spoken voice = strong signal) |
| IG reels without transcript | 0.5 (caption only) |
| IG posts | 0.5 (caption only) |
| LinkedIn company posts | 0.6 (text-heavy = moderate voice signal) |
| TikTok videos | 0.4 (no transcript available) |
| YouTube videos | 0.4 (no transcript in current actor) |
| Web pages | 0.5 for positioning; 0.3 for voice |

#### Per-Section Fallback Rules

**Positioning (`positioning.*`)**

| Evidence State | Behavior | Confidence Cap |
|----------------|----------|----------------|
| Answers provided | Use answer directly | 0.9 |
| Answers missing + web evidence | Infer from web page text | 0.5 |
| Answers missing + social only | Infer from post content | 0.4 |
| Answers missing + no evidence | Leave empty or use placeholder; flag in `missing_inputs` | 0.1 |

**Voice (`voice.*`)**

| Evidence State | Behavior | Confidence Cap |
|----------------|----------|----------------|
| Answers provided (tone_words, cta_posture) | Use answer directly | 0.9 |
| IG reels with transcripts | Infer tone/style from spoken words | 0.85 |
| IG reels/posts captions only | Infer from captions | 0.5 |
| LinkedIn posts | Infer from post text | 0.6 |
| Web only | Very limited inference; mostly defer to answers | 0.3 |
| No social evidence + no answers | Use neutral defaults; flag in `missing_inputs` | 0.2 |

**Pillars (`pillars[]`)**

| Evidence State | Behavior | Confidence Cap |
|----------------|----------|----------------|
| `tier1.pillars_seed` provided | Use seeds, refine with evidence | 0.8 |
| Seeds missing + evidence exists | Infer from content clustering | 0.5 |
| No seeds + no evidence | Propose generic pillars; flag in `missing_inputs` | 0.2 |

**Constraints (`constraints.*`)**

| Evidence State | Behavior | Confidence Cap |
|----------------|----------|----------------|
| `tier0.taboos` provided | Use directly; do NOT infer additional taboos | 0.9 |
| Taboos missing | Leave empty; do NOT infer | N/A (empty is valid) |
| `tier2.risk_boundaries` provided | Use directly | 0.9 |

> **Spec Requirement:** Compiler must NEVER infer new taboos. Taboos are user-defined only. If not provided, `constraints.taboos.value` should be an empty array with `confidence: null` (not applicable).

#### Deterministic Confidence Calculation

For any field, final confidence is:

```python
def calculate_confidence(field_path: str, sources: list[SourceRef]) -> float:
    if not sources:
        return 0.1  # pure inference fallback

    max_conf = 0.0
    for source in sources:
        if source.type == "answer":
            max_conf = max(max_conf, 0.9)
        elif source.type == "evidence":
            item = get_normalized_item(source.id)
            max_conf = max(max_conf, get_evidence_confidence(item, field_path))

    # Apply section-level caps from evidence-aware rules (Section 7.0)
    return min(max_conf, get_section_cap(field_path))
```

---

## 9) Overrides & Pinning (Merge Semantics)

### 9.1 Storage

- **Overrides** stored as: `{"voice.tone_tags": ["warm", "direct"], ...}`
- **Pins** stored as list of field paths: `["voice.tone_tags", "positioning.what_we_do"]`

### 9.2 Merge Rules (Deterministic)

For each field path:

1. **If pinned AND override exists** → `final.value = override`
2. **If pinned AND no override** → `final.value` remains whatever was previously pinned (see note)
3. **If not pinned AND override exists** → `final.value = override` (compiler can still propose changes, but not applied)
4. **Else** → `final.value = inferred`

### 9.3 Pin Persistence Note

When a path is pinned, we should persist the pinned value explicitly (either by forcing an override, or by storing `pinned_values_json`) so it doesn't "float" with inferred drafts.

---

## 10) APIs (Backend)

### Onboarding + Sources

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/brands` | Create brand |
| PUT | `/api/brands/:id/onboarding` | Update answers_json, tier |
| POST | `/api/brands/:id/sources` | Add source (platform, capability, identifier, enabled) |
| PATCH | `/api/sources/:id` | Enable/disable/settings |

### BrandBrain

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/brands/:id/brandbrain/compile` | Kickoff compile (optional `force_refresh=false`); returns `202` with `compile_run_id` |
| GET | `/api/brands/:id/brandbrain/compile/:compile_run_id/status` | Poll compile status; see Section 1.1 for latency contract |
| GET | `/api/brands/:id/brandbrain/latest` | Get latest snapshot (compact by default; `?include=full` for verbose) |
| GET | `/api/brands/:id/brandbrain/history` | Get snapshot history (paginated; `?page_size=10&cursor=...`) |
| PATCH | `/api/brands/:id/brandbrain/overrides` | Set/unset + pin/unpin |

#### Compile Kickoff Response (202 Accepted)

```typescript
interface CompileKickoffResponse {
  compile_run_id: UUID;
  status: "PENDING" | "UNCHANGED";     // UNCHANGED = short-circuited (no-op)
  poll_url: string;                    // e.g., "/api/brands/:id/brandbrain/compile/:run_id/status"
  snapshot?: BrandBrainSnapshot;       // present only if UNCHANGED (short-circuit)
}
```

#### Compile Status Response

```typescript
interface CompileStatusResponse {
  compile_run_id: UUID;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progress?: {                         // present if RUNNING
    stage: "ingestion" | "normalization" | "bundling" | "compiling" | "qa";
    sources_completed: number;
    sources_total: number;
  };
  snapshot?: BrandBrainSnapshot;       // present if SUCCEEDED
  evidence_status?: EvidenceStatus;    // present if SUCCEEDED or FAILED
  error?: string;                      // present if FAILED
}
```

> **Note:** `evidence_status` is included in final status responses (SUCCEEDED/FAILED), enabling UI to show which sources were used, refreshed, or had issues.

---

## 11) Acceptance Tests (Must Pass)

1. **Golden path:** brand + tier0 answers + 1 source → compile produces snapshot
2. **Idempotent normalization:** rerun same dataset → no dupes
3. **TTL caching:** compile twice within TTL does not start new Apify runs
4. **Caps enforced:** even if source settings request more, system clamps to env caps
5. **Pin stability:** pinned field survives recompiles with new evidence
6. **Web collection page handling:** blog index flagged as collection page and excluded from bundle

---

## Appendix A — Question-to-Field Mapping

> Full tables included in [Section 6](#6-onboarding-questions--brandbrain-field-path-mapping). Expand here if we add more questions.

---

## Appendix B — Normalization Mappings (Per Actor)

### B0) Shared Rules (All Adapters)

Each adapter must output a `NormalizedEvidenceItem` with:

- `platform`, `content_type`
- `external_id` (if possible) + dedupe strategy
- `canonical_url`
- `published_at` (nullable)
- `author_ref`
- `title` (nullable)
- `text_primary`, `text_secondary` (nullable)
- `hashtags[]` (empty ok)
- `metrics_json` (views/likes/comments/etc; actor-dependent)
- `media_json` (duration, media type, etc; actor-dependent)
- `flags_json` including at minimum:
  - `has_transcript` (bool; default false)
  - `is_low_value` (bool; default false)
  - `is_collection_page` (bool; default false; web only)
- `raw_refs` pointers

**Dedupe rule:** If the actor provides a stable id (post id / video id / linkedin urn), use it as `external_id`. If not, use `canonical_url`.

---

### B1) apify~instagram-scraper

**Validated against:** `var/apify_samples/apify_instagram-scraper/fc694124-0928-4c32-8c8b-871483c1a51f/item_0.json`

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"instagram"` |
| `content_type` | (constant) | `"post"` |
| `external_id` | `id` | Instagram media ID (e.g., `"3601328990659355969"`) |
| `canonical_url` | `url` | Full post URL |
| `published_at` | `timestamp` | ISO datetime string |
| `author_ref` | `ownerUsername` | Instagram handle |
| `title` | (null) | Posts don't have titles |
| `text_primary` | `caption` | Post caption text |
| `text_secondary` | (null) | — |
| `hashtags` | `hashtags[]` | Array of hashtag strings |
| `metrics_json.likes` | `likesCount` | Integer |
| `metrics_json.comments` | `commentsCount` | Integer |
| `metrics_json.views` | `videoViewCount` | Integer (video posts only, nullable) |
| `media_json.type` | `type` | `"Image"`, `"Video"`, `"Sidecar"` |
| `media_json.shortcode` | `shortCode` | e.g., `"DEqtFGER8tB"` |
| `media_json.owner_id` | `ownerId` | Instagram user ID |
| `media_json.music_id` | `musicInfo.audio_id` | Audio track ID (nullable) |
| `flags_json.has_transcript` | (constant) | `false` |
| `flags_json.is_low_value` | (derived) | `true` if `caption` is empty/null |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** `UNIQUE(brand_id, platform, content_type, external_id)` using `id` field.

---

### B2) apify~instagram-reel-scraper

**Validated against:** `var/apify_samples/apify_instagram-reel-scraper/bf1391f4-aaab-4576-8782-789d56ad0634/item_0.json`

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"instagram"` |
| `content_type` | (constant) | `"reel"` |
| `external_id` | `id` | Instagram media ID |
| `canonical_url` | `url` | Full reel URL |
| `published_at` | `timestamp` | ISO datetime string |
| `author_ref` | `ownerUsername` | Instagram handle |
| `title` | (null) | Reels don't have titles |
| `text_primary` | `caption` | Reel caption text |
| `text_secondary` | `transcript` | **Actual transcript text** (key field!) |
| `hashtags` | `hashtags[]` | Array of hashtag strings |
| `metrics_json.likes` | `likesCount` | Integer |
| `metrics_json.comments` | `commentsCount` | Integer |
| `metrics_json.views` | `videoViewCount` | Integer |
| `media_json.type` | `type` | Typically `"Video"` |
| `media_json.shortcode` | `shortCode` | e.g., `"DTA4-URETWb"` |
| `media_json.owner_id` | `ownerId` | Instagram user ID |
| `media_json.duration` | `videoDuration` | Seconds (if present) |
| `flags_json.has_transcript` | (derived) | `true` if `transcript` is non-empty string |
| `flags_json.is_low_value` | (derived) | `true` if both `caption` and `transcript` empty |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** `UNIQUE(brand_id, platform, content_type, external_id)` using `id` field.

> **Important:** This is the dominant voice evidence source when `transcript` is present. The `transcript` field contains actual spoken words from the reel.

---

### B3) clockworks~tiktok-scraper

**Validated against:** `var/apify_samples/clockworks_tiktok-scraper/ead52b8b-d2e2-4172-84d4-4355a848ec45/item_0.json`

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"tiktok"` |
| `content_type` | (constant) | `"short_video"` |
| `external_id` | `id` | TikTok video ID (e.g., `"7592641437091532062"`) |
| `canonical_url` | `webVideoUrl` | Full video URL |
| `published_at` | `createTimeISO` | ISO datetime string |
| `author_ref` | `authorMeta.name` | TikTok handle (e.g., `"nogood.io"`) |
| `title` | (null) | TikToks don't have titles |
| `text_primary` | `text` | Video caption/description |
| `text_secondary` | (null) | — |
| `hashtags` | `hashtags[].name` | Extract `name` from each hashtag object |
| `metrics_json.plays` | `playCount` | Integer |
| `metrics_json.likes` | `diggCount` | Integer |
| `metrics_json.comments` | `commentCount` | Integer |
| `metrics_json.shares` | `shareCount` | Integer |
| `metrics_json.saves` | `collectCount` | Integer |
| `media_json.duration` | `videoMeta.duration` | Seconds |
| `media_json.width` | `videoMeta.width` | Pixels |
| `media_json.height` | `videoMeta.height` | Pixels |
| `media_json.cover_url` | `videoMeta.coverUrl` | Thumbnail URL |
| `media_json.author_fans` | `authorMeta.fans` | Follower count |
| `flags_json.has_transcript` | (constant) | `false` (subtitle links are download URLs, not text) |
| `flags_json.is_sponsored` | `isSponsored` | Boolean |
| `flags_json.is_ad` | `isAd` | Boolean |
| `flags_json.is_low_value` | (derived) | `true` if `text` is empty |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** `UNIQUE(brand_id, platform, content_type, external_id)` using `id` field.

> **Note:** `videoMeta.subtitleLinks` contains URLs to subtitle files, not actual transcript text. Set `has_transcript=false`.

---

### B4) streamers~youtube-scraper

**Validated against:** `var/apify_samples/streamers_youtube-scraper/22b6a3f6-4a38-43e8-a8c6-2eceb3eae85f/item_0.json`

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"youtube"` |
| `content_type` | (constant) | `"video"` |
| `external_id` | `id` | YouTube video ID (e.g., `"8eEOaCCxGwo"`) |
| `canonical_url` | `url` | Full video URL |
| `published_at` | `date` | ISO datetime string |
| `author_ref` | `channelId` | YouTube channel ID |
| `title` | `title` | Video title |
| `text_primary` | `title` | Video title (same as title) |
| `text_secondary` | `text` | Video description |
| `hashtags` | `hashtags[]` | Array of hashtag strings (often empty) |
| `metrics_json.views` | `viewCount` | Integer |
| `metrics_json.likes` | `likes` | Integer |
| `metrics_json.comments` | `commentsCount` | Integer |
| `media_json.duration` | `duration` | String format `"HH:MM:SS"` |
| `media_json.thumbnail_url` | `thumbnailUrl` | Thumbnail URL |
| `media_json.channel_name` | `channelName` | Display name |
| `media_json.channel_url` | `channelUrl` | Channel URL |
| `media_json.channel_subscribers` | `numberOfSubscribers` | Integer |
| `flags_json.has_transcript` | (constant) | `false` (this actor doesn't provide transcripts) |
| `flags_json.is_members_only` | `isMembersOnly` | Boolean |
| `flags_json.is_monetized` | `isMonetized` | Boolean (nullable) |
| `flags_json.comments_off` | `commentsTurnedOff` | Boolean |
| `flags_json.is_low_value` | (derived) | `true` if `title` and `text` both empty |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** `UNIQUE(brand_id, platform, content_type, external_id)` using `id` field.

---

### B5) apimaestro~linkedin-company-posts

**Validated against:** `var/apify_samples/apimaestro_linkedin-company-posts/a3373658-29e9-4c7b-81e6-07d27ff4fe24/item_0.json`

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"linkedin"` |
| `content_type` | (constant) | `"text_post"` |
| `external_id` | `activity_urn` | LinkedIn URN (e.g., `"urn:li:activity:..."`) |
| `canonical_url` | `post_url` | Full post URL |
| `published_at` | `posted_at.date` | ISO datetime string |
| `author_ref` | `author.company_url` | Company LinkedIn URL |
| `title` | (null) | LinkedIn posts don't have titles |
| `text_primary` | `text` | Post body text |
| `text_secondary` | (null) | — |
| `hashtags` | (extracted) | Parse `#hashtag` patterns from `text` |
| `metrics_json.reactions` | `stats.total_reactions` | Integer |
| `metrics_json.likes` | `stats.likes` | Integer (if breakdown available) |
| `metrics_json.comments` | `stats.total_comments` | Integer |
| `metrics_json.reposts` | `stats.reposts` | Integer |
| `media_json.has_media` | (derived) | `true` if `media` array non-empty |
| `media_json.media_type` | `media[0].type` | First media item type |
| `media_json.author_name` | `author.name` | Company name |
| `flags_json.has_transcript` | (constant) | `false` |
| `flags_json.is_low_value` | (derived) | `true` if `text` is empty |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** `UNIQUE(brand_id, platform, content_type, external_id)` using `activity_urn` field. Fallback to `full_urn` if `activity_urn` missing.

---

### B6) apimaestro~linkedin-profile-posts

**⚠️ UNVALIDATED — BEHIND FEATURE FLAG**

No local ApifyRun records or sample files exist for this actor. This capability is:
- **Unvalidated:** Normalization mapping below is assumed, not proven
- **Behind feature flag:** Must NOT be enabled in production until validated
- **Excluded from default bundling:** Even if normalized items exist, exclude from bundles

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"linkedin"` |
| `content_type` | (constant) | `"text_post"` |
| `external_id` | `activity_urn` | (assumed same as company posts) |
| `canonical_url` | `post_url` | (assumed) |
| `published_at` | `posted_at.date` | (assumed) |
| `author_ref` | `author.profile_url` | Personal profile URL (assumed) |
| `title` | (null) | — |
| `text_primary` | `text` | (assumed) |
| `text_secondary` | (null) | — |
| `hashtags` | (extracted) | Parse from `text` |
| `metrics_json.reactions` | `stats.total_reactions` | (assumed) |
| `flags_json.has_transcript` | (constant) | `false` |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** (assumed same as company posts)

> **Action Required:** Run `apimaestro~linkedin-profile-posts` actor once, validate this mapping against actual output, then remove the feature flag.

---

### B7) apify~website-content-crawler

**Validated against:** `var/apify_samples/apify_website-content-crawler/a2126ae4-1ef0-4f40-b11e-9f521f30652c/item_0.json`

| NormalizedEvidenceItem Field | Raw JSON Path | Notes |
|------------------------------|---------------|-------|
| `platform` | (constant) | `"web"` |
| `content_type` | (constant) | `"web_page"` |
| `external_id` | (null) | Web pages use URL for dedupe |
| `canonical_url` | `metadata.canonicalUrl` | Fallback to `url` if missing |
| `published_at` | `metadata.jsonLd[].datePublished` | Extract from JSON-LD (nullable) |
| `author_ref` | `url` | Domain/base URL |
| `title` | `metadata.title` | Page title |
| `text_primary` | `text` | Extracted plain text |
| `text_secondary` | `metadata.description` | Meta description |
| `hashtags` | (empty) | `[]` — web pages don't have hashtags |
| `metrics_json` | (empty) | `{}` — no metrics for web pages |
| `media_json.og_image` | `metadata.openGraph[og:image]` | Open Graph image URL |
| `media_json.org_name` | `metadata.jsonLd[].name` | Organization name from JSON-LD |
| `media_json.org_logo` | `metadata.jsonLd[].logo.url` | Logo URL from JSON-LD |
| `flags_json.has_transcript` | (constant) | `false` |
| `flags_json.is_collection_page` | (derived) | `true` if `metadata.jsonLd` contains `@type: "CollectionPage"` or `@type: "BreadcrumbList"` with multiple items |
| `flags_json.is_low_value` | (derived) | `true` if `is_collection_page=true` OR `len(text) < 200` |
| `raw_refs` | (computed) | `[{apify_run_uuid, raw_item_id}]` |

**Dedupe Strategy:** `UNIQUE(brand_id, platform, content_type, canonical_url)` — no `external_id` used.

**Collection Page Detection Logic:**
```python
def is_collection_page(jsonld: list[dict]) -> bool:
    for item in jsonld:
        if item.get("@type") == "CollectionPage":
            return True
        graph = item.get("@graph", [])
        for node in graph:
            if node.get("@type") == "CollectionPage":
                return True
            # BreadcrumbList with single "Home" item = homepage, not collection
            # BreadcrumbList with multiple items = possibly collection (blog index)
    return False
```

> **Note:** Treat web pages as positioning evidence only. Exclude `is_collection_page=true` pages from voice/pillar bundling unless web is the only evidence source.

---

## Appendix C — Actor Input Templates

All templates below are validated against actual `ApifyRun` records in the local database. Placeholders use `<angle_brackets>` format.

---

### C1) apify~instagram-scraper (Posts)

**Validated from ApifyRun record**

```json
{
  "directUrls": ["<instagram_profile_url>"],
  "resultsType": "posts",
  "resultsLimit": <cap>,
  "addParentData": false
}
```

**Parameter Semantics:**
| Key | Type | Description |
|-----|------|-------------|
| `directUrls` | string[] | Array containing Instagram profile URL (e.g., `"https://www.instagram.com/nogood.io/"`) |
| `resultsType` | string | Must be `"posts"` for this capability |
| `resultsLimit` | int | Server-clamped to `BRANDBRAIN_CAP_IG_POSTS` (default 8) |
| `addParentData` | bool | Keep `false` to avoid bloating output |

**Builder Function:**
```python
def build_instagram_posts_input(source: SourceConnection, cap: int) -> dict:
    return {
        "directUrls": [source.identifier],  # e.g., "https://www.instagram.com/handle/"
        "resultsType": "posts",
        "resultsLimit": cap,
        "addParentData": False
    }
```

---

### C2) apify~instagram-reel-scraper (Reels)

**Validated from ApifyRun record**

```json
{
  "username": ["<instagram_username_or_profile_url_or_reel_url>"],
  "resultsLimit": <cap>,
  "includeTranscript": true,
  "includeSharesCount": false,
  "includeDownloadedVideo": false,
  "skipPinnedPosts": true
}
```

**Parameter Semantics:**
| Key | Type | Description |
|-----|------|-------------|
| `username` | string[] | Array with username, profile URL, or explicit reel URLs |
| `resultsLimit` | int | Maximum reels per profile/username. **Does NOT apply when scraping by explicit reel URLs.** |
| `includeTranscript` | bool | **Must be `true`** — this is the key field for voice evidence |
| `includeSharesCount` | bool | Keep `false` to reduce API cost |
| `includeDownloadedVideo` | bool | Keep `false` — we don't need video files |
| `skipPinnedPosts` | bool | Skip pinned reels to reduce duplicates |

**Builder Function:**
```python
def build_instagram_reels_input(source: SourceConnection, cap: int) -> dict:
    return {
        # The actor accepts: username, profile URL, ID, OR explicit reel URLs
        "username": [source.identifier],
        "resultsLimit": cap,
        "includeTranscript": True,  # CRITICAL: enables transcript field
        "includeSharesCount": False,
        "includeDownloadedVideo": False,
        "skipPinnedPosts": True,
    }
```

> **Important gotcha:** `resultsLimit` only applies when scraping by username/profile. If we ever switch to feeding explicit reel URLs, `resultsLimit` won't cap the scrape; we must rely on dataset-fetch caps and/or keep the URL list length bounded.

---

### C3) apimaestro~linkedin-company-posts

**Validated from ApifyRun record**

```json
{
  "sort": "recent",
  "limit": <cap>,
  "company_name": "<linkedin_company_slug>"
}
```

**Parameter Semantics:**
| Key | Type | Description |
|-----|------|-------------|
| `sort` | string | Must be `"recent"` for chronological order |
| `limit` | int | Server-clamped to `BRANDBRAIN_CAP_LI` (default 6) |
| `company_name` | string | Company slug from LinkedIn URL (e.g., `"nogood"` from `linkedin.com/company/nogood`) |

**Builder Function:**
```python
def build_linkedin_company_posts_input(source: SourceConnection, cap: int) -> dict:
    # Extract company slug from URL or use identifier directly
    slug = extract_company_slug(source.identifier)  # "nogood" from "https://linkedin.com/company/nogood"
    return {
        "sort": "recent",
        "limit": cap,
        "company_name": slug
    }
```

---

### C4) apimaestro~linkedin-profile-posts

**⚠️ UNVALIDATED — BEHIND FEATURE FLAG**

No local ApifyRun records or sample files exist for this actor. This capability is:
- **Unvalidated:** Input template and normalization mapping are assumed, not proven
- **Behind feature flag:** Must NOT be enabled in production until validated
- **Excluded from default bundling:** Even if a SourceConnection exists, skip this source in compile pipeline

**Assumed template (based on actor documentation):**

```json
{
  "sort": "recent",
  "limit": <cap>,
  "profile_url": "<linkedin_profile_url>"
}
```

**Parameter Semantics (assumed):**
| Key | Type | Description |
|-----|------|-------------|
| `sort` | string | `"recent"` (assumed same as company posts) |
| `limit` | int | Server-clamped to `BRANDBRAIN_CAP_LI` (default 6) |
| `profile_url` | string | Full LinkedIn profile URL (e.g., `"https://www.linkedin.com/in/username/"`) |

**Builder Function (assumed):**
```python
def build_linkedin_profile_posts_input(source: SourceConnection, cap: int) -> dict:
    # ⚠️ UNVALIDATED - do not use in production until validated
    return {
        "sort": "recent",
        "limit": cap,
        "profile_url": source.identifier  # full LinkedIn profile URL
    }
```

> **Action Required:** Run this actor once, validate the input template and output schema against actual results, then remove the feature flag.

---

### C5) clockworks~tiktok-scraper

**Validated from ApifyRun record**

```json
{
  "profiles": ["<tiktok_handle>"],
  "profileSorting": "latest",
  "resultsPerPage": <cap>,
  "excludePinnedPosts": true,
  "profileScrapeSections": ["videos"]
}
```

**Parameter Semantics:**
| Key | Type | Description |
|-----|------|-------------|
| `profiles` | string[] | Array of TikTok handles WITHOUT `@` (e.g., `["nogood.io"]`) |
| `profileSorting` | string | `"latest"` for chronological order |
| `resultsPerPage` | int | Server-clamped to `BRANDBRAIN_CAP_TT` (default 6) |
| `excludePinnedPosts` | bool | `true` to avoid duplicate pinned content |
| `profileScrapeSections` | string[] | `["videos"]` — only scrape video posts |

**Builder Function:**
```python
def build_tiktok_profile_input(source: SourceConnection, cap: int) -> dict:
    # Strip @ if present in identifier
    handle = source.identifier.lstrip("@")
    return {
        "profiles": [handle],
        "profileSorting": "latest",
        "resultsPerPage": cap,
        "excludePinnedPosts": True,
        "profileScrapeSections": ["videos"]
    }
```

---

### C6) streamers~youtube-scraper

**Validated from ApifyRun record**

```json
{
  "startUrls": [{"url": "<youtube_channel_url>"}],
  "maxResults": <cap>,
  "maxResultsShorts": 0,
  "maxResultsStreams": 0
}
```

**Parameter Semantics:**
| Key | Type | Description |
|-----|------|-------------|
| `startUrls` | object[] | Array of URL objects with channel URL (e.g., `"https://www.youtube.com/channel/UCZ4qs1SgV7wTkM2VjHByuRQ"`) |
| `maxResults` | int | Server-clamped to `BRANDBRAIN_CAP_YT` (default 6) |
| `maxResultsShorts` | int | `0` — exclude YouTube Shorts |
| `maxResultsStreams` | int | `0` — exclude livestreams |

**Builder Function:**
```python
def build_youtube_channel_input(source: SourceConnection, cap: int) -> dict:
    return {
        "startUrls": [{"url": source.identifier}],  # channel URL
        "maxResults": cap,
        "maxResultsShorts": 0,
        "maxResultsStreams": 0
    }
```

---

### C7) apify~website-content-crawler

**Validated from ApifyRun record**

```json
{
  "startUrls": [
    {"url": "<website_url>"},
    {"url": "<optional_key_page_url_1>"},
    {"url": "<optional_key_page_url_2>"}
  ],
  "maxCrawlDepth": 1,
  "maxCrawlPages": <cap>
}
```

**Parameter Semantics:**
| Key | Type | Description |
|-----|------|-------------|
| `startUrls` | object[] | Homepage URL + optional key pages from `SourceConnection.settings_json.extra_start_urls` (max 3 total) |
| `maxCrawlDepth` | int | `1` — only crawl one level deep from each start URL |
| `maxCrawlPages` | int | Server-clamped to `BRANDBRAIN_CAP_WEB` (default 3); set to `min(cap, len(startUrls))` to avoid crawling beyond explicit pages |

**Builder Function:**
```python
def build_web_crawl_input(source: SourceConnection, cap: int) -> dict:
    # Read key pages from settings_json (clamped to 2)
    extra = (source.settings_json or {}).get("extra_start_urls", [])
    extra = [u for u in extra if isinstance(u, str) and u][:2]  # clamp to 2

    # Build startUrls: homepage + key pages
    start_urls = [{"url": source.identifier}] + [{"url": u} for u in extra]

    return {
        "startUrls": start_urls,
        "maxCrawlDepth": 1,
        # Cap to number of explicit start URLs so we don't crawl discovered links
        "maxCrawlPages": min(cap, len(start_urls)),
    }
    # NOTE: dataset-fetch cap is still enforced separately in fetch_dataset_items()
```

> **Contract:** Key pages are stored in `SourceConnection.settings_json.extra_start_urls` (populated from `tier1.key_pages` onboarding answer). Server clamps to 2 extra URLs. Total web cap is 3 pages (homepage + up to 2 key pages). The `maxCrawlPages` is set to `min(cap, len(startUrls))` to ensure we only fetch the explicit pages, not discovered links.

---

## Validation Summary

| Actor | Input Template | Sample File | Status |
|-------|----------------|-------------|--------|
| `apify~instagram-scraper` | ✅ Validated | `var/apify_samples/apify_instagram-scraper/fc694124.../item_0.json` | **Complete** |
| `apify~instagram-reel-scraper` | ✅ Validated | `var/apify_samples/apify_instagram-reel-scraper/bf1391f4.../item_0.json` | **Complete** |
| `apimaestro~linkedin-company-posts` | ✅ Validated | `var/apify_samples/apimaestro_linkedin-company-posts/a3373658.../item_0.json` | **Complete** |
| `apimaestro~linkedin-profile-posts` | ⚠️ UNVALIDATED | (none) | **Behind feature flag** |
| `clockworks~tiktok-scraper` | ✅ Validated | `var/apify_samples/clockworks_tiktok-scraper/ead52b8b.../item_0.json` | **Complete** |
| `streamers~youtube-scraper` | ✅ Validated | `var/apify_samples/streamers_youtube-scraper/22b6a3f6.../item_0.json` | **Complete** |
| `apify~website-content-crawler` | ✅ Validated | `var/apify_samples/apify_website-content-crawler/a2126ae4.../item_0.json` | **Complete** |

---

## Changelog

### v2.4 (January 2026)
- **Added:** Section 1.3 — Implementation Roadmap (PR Plan) with 8 PRs (PR-0 through PR-7)
- **Added:** PR summary table with dependencies
- **Added:** Detailed scope, deliverables, non-goals, and acceptance criteria for each PR
- **Added:** Review Discipline subsection with rules for PR quality gates
- **Added:** Async mechanism decision point in PR-5 (use existing job system or document minimal choice)

### v2.3 (January 2026)
- **Added:** Section 1.1 — Performance & Latency Contracts with P95 latency budgets for all BrandBrain endpoints
- **Added:** Read-path vs work-path boundary definition; hard rule that GET endpoints may not trigger ingestion or LLM work
- **Added:** Payload cap guidance for compact vs verbose responses; `?include=` query param pattern
- **Added:** Compile short-circuit (no-op detection) logic based on TTL + input hash + config version
- **Added:** Section 1.2 — Indexing Requirements for Budgets listing all required indexes with query patterns
- **Added:** SQL index implementation examples for Postgres
- **Added:** `GET /compile/:compile_run_id/status` endpoint to API table for async compile polling

### v2.2 (January 2026)
- **Changed:** Tier 0 required fields reduced — `tier0.edge`, `tier0.tone_words`, `tier0.taboos` now optional (strongly recommended but not compile blockers)
- **Added:** Section 0.1 — Naming guidance for internal vs external terms (recommend "Brand Profile" / "Brand Foundations" / "Playbook" for UI)
- **Added:** Section 7.0 — Compile gating requirements with evidence-aware behavior rules; confidence caps when evidence is weak
- **Added:** Section 8.3 — Field Confidence & Fallback Contract defining confidence bands, source-type contributions, and per-section fallback rules
- **Added:** PlatformRulesInput schema in Section 6 (Tier 2) — fixed, validatable schema for platform rules replacing vague object definitions
- **Added:** EvidenceStatus schema in Section 2.5 — tracks reused/refreshed/skipped/failed sources per compile run
- **Added:** CompileResponse shape in Section 10 APIs — includes `evidence_status` in all compile responses
- **Fixed:** BrandBrainCompileRun model now includes `evidence_status_json` field

### v2.1.1 (January 2026)
- **Fixed:** Removed duplicate `SourceRun` model — use extended `ApifyRun` instead
- **Fixed:** Status/validation lines now explicitly note 6/7 actors validated
- **Added:** Two-layer cap enforcement subsection (actor-input + dataset-fetch)
- **Fixed:** Actor registry entries now point to specific appendices (no wiggle room)
- **Fixed:** Instagram reels input template now includes `resultsLimit` and `skipPinnedPosts`
- **Added:** LinkedIn profile posts containment notes (unvalidated, behind feature flag, excluded from bundling)
- **Removed:** All `SourceRun` references replaced with `ApifyRun` usage
- **Fixed:** Web key pages now representable via `SourceConnection.settings_json.extra_start_urls` + updated C7 template/builder + `tier1.key_pages` onboarding question mapping + `BRANDBRAIN_CAP_WEB=3`

### v2.1 (January 2026)
- **Appendix B:** Filled with concrete raw→normalized field mappings validated against sample files
- **Appendix C:** Filled with exact input templates extracted from ApifyRun database records
- **LinkedIn Profile Posts:** Marked as UNVALIDATED (no local runs exist)
- Added validation summary table
- Added builder function examples for each actor
