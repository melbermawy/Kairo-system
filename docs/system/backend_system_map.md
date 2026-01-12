# Kairo Backend System Map

**Generated**: 2026-01-05 | **Branch**: ingestion-phase1

---

## 0) Executive Summary

### What Works End-to-End Today

**With LLM enabled:**
- F1 (Today Board): Opportunities generation via `graph_hero_generate_opportunities` → persist to DB → return `TodayBoardDTO`
- F2 (Packages): Package creation via `graph_hero_package_from_opportunity` → persist `ContentPackage`
- F2 (Variants): Variant generation via `graph_hero_variants_from_package` → persist `Variant` rows
- Eval harness: `run_hero_eval` command runs full F1+F2 pipeline with metrics + quality classification

**With LLM disabled (LLM_DISABLED=true):**
- All graphs return deterministic stub responses via `_STUB_*` constants in [llm_client.py](kairo/hero/llm_client.py)
- Full pipeline still exercises DB writes, DTO validation, observability

### What Is Intentionally Stubbed
- **External signals**: Fixture-based (`EXTERNAL_SIGNALS_MODE=fixtures`) or ingestion-based (`EXTERNAL_SIGNALS_MODE=ingestion`)
- **Auth**: Brand lookup uses raw UUID; no real user auth yet
- **Decision recording**: Records `LearningEvent` but doesn't affect scoring yet

### Top 5 Architectural Decisions
1. **DTOs as contracts**: Pydantic v2 models in [dto.py](kairo/hero/dto.py) define all API boundaries; engines return DTOs only
2. **Engines own DB writes**: Graphs return `*DraftDTO`; engines convert to ORM and persist ([content_engine.py:774](kairo/hero/engines/content_engine.py#L774))
3. **Fail-safe degradation**: Graph failures return degraded boards with existing/stub opps ([opportunities_engine.py:208](kairo/hero/engines/opportunities_engine.py#L208))
4. **Idempotency guards**: Package creation checks for existing package; variant generation rejects if variants exist ([content_engine.py:171](kairo/hero/engines/content_engine.py#L171))
5. **Two-tier classification**: `obs_health` (ok/degraded/failed) for operational monitoring vs `quality` (good/partial/bad/invalid) for eval only

---

## 1) Capability Inventory

### Hero Loop: F1 Opportunities
| Capability | Entry Point | Implementation |
|------------|-------------|----------------|
| Get Today Board | `GET /api/brands/{id}/today` | [api_views.get_today_board](kairo/hero/api_views.py#L87) → [today_service.get_today_board](kairo/hero/services/today_service.py#L17) → [opportunities_engine.generate_today_board](kairo/hero/engines/opportunities_engine.py#L65) |
| Regenerate Board | `POST /api/brands/{id}/today/regenerate` | Same path as above |
| Graph execution | Internal | [graph_hero_generate_opportunities](kairo/hero/graphs/opportunities_graph.py#L724) |

### Hero Loop: F2 Packages
| Capability | Entry Point | Implementation |
|------------|-------------|----------------|
| Create package | `POST /api/brands/{id}/opportunities/{opp_id}/packages` | [api_views.create_package_from_opportunity](kairo/hero/api_views.py#L160) → [content_engine.create_package_from_opportunity](kairo/hero/engines/content_engine.py#L114) |
| Get package | `GET /api/packages/{id}` | [api_views.get_package](kairo/hero/api_views.py#L195) |

### Hero Loop: F2 Variants
| Capability | Entry Point | Implementation |
|------------|-------------|----------------|
| Generate variants | `POST /api/packages/{id}/variants/generate` | [api_views.generate_variants](kairo/hero/api_views.py#L223) → [content_engine.generate_variants_for_package](kairo/hero/engines/content_engine.py#L286) |
| List variants | `GET /api/packages/{id}/variants` | [api_views.get_variants](kairo/hero/api_views.py#L246) |
| Update variant | `PATCH /api/variants/{id}` | [api_views.update_variant](kairo/hero/api_views.py#L269) |
| Regen guard | N/A | `VariantsAlreadyExistError` raised at [content_engine.py:350](kairo/hero/engines/content_engine.py#L350) |

### Eval Harness & Quality Classifier
| Component | Location | Purpose |
|-----------|----------|---------|
| Eval harness | [f1_f2_hero_loop.py](kairo/hero/eval/f1_f2_hero_loop.py) | Runs F1+F2 against fixtures, outputs JSON+MD |
| Quality classifier | [quality_classifier.py](kairo/hero/eval/quality_classifier.py) | Classifies runs as good/partial/bad/invalid |
| Management cmd | `python manage.py run_hero_eval --brand-slug <slug>` | [run_hero_eval.py](kairo/hero/management/commands/run_hero_eval.py) |

**Quality vs Obs_Health distinction:**
- `quality` labels (good/partial/bad/invalid): eval-harness only, computed in [quality_classifier.py:104](kairo/hero/eval/quality_classifier.py#L104)
- `obs_health` labels (ok/degraded/failed): operational health, computed in [observability_store.py:360](kairo/hero/observability_store.py#L360)

### Internal Admin/Debug Surfaces
| Surface | URL Pattern | Auth |
|---------|-------------|------|
| Run list | `/hero/internal/runs/` | `X-Kairo-Internal-Token` header |
| Run detail | `/hero/internal/runs/{run_id}/` | Same |
| Run JSON | `/hero/internal/runs/{run_id}.json` | Same |
| Eval list | `/hero/internal/evals/` | Same |
| Eval detail | `/hero/internal/evals/{filename}` | Same |
| Brand list | `/hero/internal/brands/` | Same |
| Brand detail | `/hero/internal/brands/{id}/` | Same |

**Auth semantics**: Token from `KAIRO_INTERNAL_ADMIN_TOKEN` env var. Missing/wrong token → 404 (no dev mode). Implementation: [internal_views.py:129](kairo/hero/internal_views.py#L129)

### Observability Store / Run Logging
- Filesystem-based JSONL sink at `$KAIRO_OBS_DIR/{run_id}/{kind}.jsonl`
- Event kinds: `run_start`, `run_complete`, `run_fail`, `llm_call`, `classification`, `opportunity`, `package`, `variant`
- Enabled via `KAIRO_OBS_ENABLED=true`
- Implementation: [observability_store.py:94](kairo/hero/observability_store.py#L94)

### Existing Brand Objects/Fixtures
- Fixture brands in `kairo/hero/fixtures/` with `eval_brand_id` for eval
- External signals fixtures in `kairo/hero/fixtures/external_signals/`
- Index file: `_index.json` maps brand_slug → fixture filename

---

## 2) Canonical Contracts Snapshot

### Pydantic DTOs (kairo/hero/dto.py)

**Brand Context:**
- `BrandSnapshotDTO` - point-in-time brand context for LLM prompts
- `PersonaDTO`, `PillarDTO`, `PatternTemplateDTO` - nested components

**Opportunities (F1):**
- `OpportunityDTO` - persisted opportunity shape
- `OpportunityDraftDTO` - graph output (includes `is_valid`, `rejection_reasons`)
- `TodayBoardDTO`, `TodayBoardMetaDTO` - board response

**Packages & Variants (F2):**
- `ContentPackageDTO`, `ContentPackageDraftDTO`
- `VariantDTO`, `VariantDraftDTO`, `VariantUpdateDTO`, `VariantListDTO`

**External Signals:**
- `ExternalSignalBundleDTO` - bundle of signals for F1
- `TrendSignalDTO`, `WebMentionSignalDTO`, `CompetitorPostSignalDTO`, `SocialMomentSignalDTO`

**Decisions & Events:**
- `DecisionRequestDTO`, `DecisionResponseDTO`
- `ExecutionEventDTO`, `LearningEventDTO`, `LearningSummaryDTO`

**Response Wrappers:**
- `RegenerateResponseDTO`, `CreatePackageResponseDTO`, `GenerateVariantsResponseDTO`

### API Endpoints → DTO Mapping

| Endpoint | Request DTO | Response DTO |
|----------|-------------|--------------|
| `GET /api/brands/{id}/today` | - | `TodayBoardDTO` |
| `POST /api/brands/{id}/today/regenerate` | - | `RegenerateResponseDTO` |
| `POST /api/brands/{id}/opportunities/{opp_id}/packages` | - | `CreatePackageResponseDTO` |
| `GET /api/packages/{id}` | - | `ContentPackageDTO` |
| `POST /api/packages/{id}/variants/generate` | - | `GenerateVariantsResponseDTO` |
| `GET /api/packages/{id}/variants` | - | `VariantListDTO` |
| `PATCH /api/variants/{id}` | `VariantUpdateDTO` | `VariantDTO` |
| `POST /api/*/decision` | `DecisionRequestDTO` | `DecisionResponseDTO` |

### Contract Stability Notes
- **Frozen**: DTO field names in `dto.py` are stable; renaming requires migration
- **Experimental**: `quality_band`, `*_score_breakdown` fields in draft DTOs; internal use only

---

## 3) Data Model Snapshot

### A) Core Brand Models (kairo/core/models.py)

| Model | Key Fields | Unique Constraints | FKs |
|-------|------------|-------------------|-----|
| `Tenant` | `id` (UUID), `name`, `slug` | `slug` unique | - |
| `Brand` | `id`, `tenant`, `name`, `slug`, `positioning`, `tone_tags[]`, `taboos[]` | `(tenant, slug)` | `tenant → Tenant (PROTECT)` |
| `BrandSnapshot` | `id`, `brand`, `snapshot_at`, `positioning_summary`, `pillars[]`, `personas[]` | - | `brand → Brand (PROTECT)` |
| `Persona` | `id`, `brand`, `name`, `role`, `summary`, `priorities[]`, `pains[]` | `(brand, name)` | `brand → Brand (PROTECT)` |
| `ContentPillar` | `id`, `brand`, `name`, `category`, `priority_rank`, `is_active` | `(brand, name)` | `brand → Brand (PROTECT)` |
| `PatternTemplate` | `id`, `brand` (nullable), `name`, `category`, `status`, `beats[]` | - | `brand → Brand (PROTECT)` |

### B) Hero Loop Models (kairo/core/models.py)

| Model | Key Fields | FKs | On Delete |
|-------|------------|-----|-----------|
| `Opportunity` | `id`, `brand`, `title`, `angle`, `type`, `score`, `primary_channel`, `is_pinned`, `is_snoozed` | `brand`, `persona`, `pillar` | PROTECT / SET_NULL |
| `ContentPackage` | `id`, `brand`, `title`, `status`, `channels[]`, `notes`, `metrics_snapshot{}` | `brand`, `origin_opportunity`, `persona`, `pillar` | PROTECT / SET_NULL |
| `Variant` | `id`, `brand`, `package`, `channel`, `status`, `draft_text`, `eval_score` | `brand`, `package`, `pattern_template` | PROTECT / CASCADE / SET_NULL |
| `ExecutionEvent` | `id`, `brand`, `variant`, `channel`, `event_type`, `decision_type` | `brand`, `variant` | PROTECT / CASCADE |
| `LearningEvent` | `id`, `brand`, `signal_type`, `payload{}`, `effective_at` | `brand`, `pattern`, `opportunity`, `variant` | PROTECT / SET_NULL |

**Notable indices:**
- `Opportunity`: `(brand, created_at)`, `(brand, is_pinned, is_snoozed)`, `(brand, type)`
- `Variant`: `(package, channel)`, `(brand, channel, status)`

### C) Observability Models

No Django models. Observability uses filesystem-based JSONL in `$KAIRO_OBS_DIR`.

### D) Ingestion Models (kairo/ingestion/models.py)

**STATUS: MODELS EXIST, PIPELINE PARTIALLY BUILT**

| Model | Key Fields | Purpose |
|-------|------------|---------|
| `Surface` | `platform`, `surface_type`, `surface_key`, `cadence_minutes` | Scrape target definition |
| `CaptureRun` | `surface`, `status`, `item_count`, `started_at`, `ended_at` | Job execution tracking |
| `EvidenceItem` | `platform`, `platform_item_id`, `text_content`, `audio_id`, `hashtags[]`, `view_count`, `raw_json{}` | Raw scraped item (immutable) |
| `Cluster` | `cluster_key_type`, `cluster_key`, `display_name`, `platforms[]` | Grouping key for clustering |
| `NormalizedArtifact` | `evidence_item`, `normalized_text`, `engagement_score` | Standardized artifact |
| `ArtifactClusterLink` | `artifact`, `cluster`, `role` (primary/secondary), `key_type` | Many-to-many clustering |
| `ClusterBucket` | `cluster`, `bucket_start`, `artifact_count`, `velocity`, `acceleration` | Time-windowed aggregation |
| `TrendCandidate` | `cluster`, `status`, `trend_score`, `velocity_score`, `detected_at` | Cluster exceeding thresholds |

**Unique constraints:**
- `Surface`: `(platform, surface_type, surface_key)`
- `EvidenceItem`: `(platform, platform_item_id)`
- `Cluster`: `(cluster_key_type, cluster_key)`
- `ArtifactClusterLink`: one primary per artifact; unique `(artifact, cluster, role)`

---

## 4) Execution Paths

### "Regenerate Today Board" End-to-End

1. `POST /api/brands/{brand_id}/today/regenerate` → [api_views.regenerate_today_board](kairo/hero/api_views.py#L119)
2. → [today_service.regenerate_today_board](kairo/hero/services/today_service.py#L36)
3. → [opportunities_engine.generate_today_board](kairo/hero/engines/opportunities_engine.py#L65): run_id, log_run_start(), Brand.objects.get(), _build_brand_snapshot(), _get_learning_summary_safe(), _get_external_signals_safe()
4. → [graph_hero_generate_opportunities](kairo/hero/graphs/opportunities_graph.py#L724): _synthesize_opportunities() (heavy LLM) → _score_and_normalize_opportunities() (fast LLM) → _convert_to_draft_dtos()
5. Back in engine: _filter_invalid_opportunities(), _filter_redundant_opportunities() (Jaccard ≥0.75), _persist_opportunities(), log_run_complete(), classify_f1_run()
6. Return TodayBoardDTO → RegenerateResponseDTO → JsonResponse

### "Create Package from Opportunity" End-to-End

1. `POST /api/brands/{id}/opportunities/{opp_id}/packages` → [api_views.create_package_from_opportunity](kairo/hero/api_views.py#L160)
2. → [content_engine.create_package_from_opportunity](kairo/hero/engines/content_engine.py#L114)
3. Idempotency check: ContentPackage.objects.filter(brand_id, origin_opportunity_id).first() - if exists, return immediately
4. Build BrandSnapshotDTO → [graph_hero_package_from_opportunity](kairo/hero/graphs/package_graph.py) → ContentPackageDraftDTO
5. Validate (reject if is_valid=False or taboo), _persist_package() → CreatePackageResponseDTO

### "Generate Variants for Package" (+ Regen Guard)

1. `POST /api/packages/{id}/variants/generate` → [content_engine.generate_variants_for_package](kairo/hero/engines/content_engine.py#L286)
2. **Regen guard**: If Variant.objects.filter(package_id).count() > 0 → raise VariantsAlreadyExistError
3. → [graph_hero_variants_from_package](kairo/hero/graphs/variants_graph.py) → list[VariantDraftDTO]
4. _filter_invalid_variants(), _persist_variants() → GenerateVariantsResponseDTO

### "Internal Run Detail Page"

1. `GET /hero/internal/runs/{run_id}/` → [internal_views.get_hero_run](kairo/hero/internal_views.py)
2. require_internal_token (404 if missing/wrong) → get_run_detail() reads JSONL from `$KAIRO_OBS_DIR/{run_id}/`
3. Render HTML, markdown via python-markdown, _sanitize_html() strips XSS (script, onclick/*, javascript:, data: URLs)

### "Eval Run" Path

1. `python manage.py run_hero_eval --brand-slug techflow` → [run_hero_eval.py](kairo/hero/management/commands/run_hero_eval.py#L75)
2. Load brand fixture → run F1: opportunities_engine.generate_today_board()
3. For each opp (up to --max-opportunities): F2 package + F2 variants
4. Quality classification: extract_f1/f2_metrics_from_case() → classify_run() → "good"|"partial"|"bad"|"invalid"
5. Output JSON + Markdown to docs/eval/hero_loop/

---

## 5) Failure Semantics (Truth Table)

| Flow | Fails Loudly | Degrades | Exception | API Response | Logged |
|------|--------------|----------|-----------|--------------|--------|
| F1 Today | No | Yes | `GraphError` caught | `TodayBoardDTO` with `meta.degraded=True` | `log_run_fail()` |
| F1 External Signals | No | Yes | Caught | Empty bundle used | Warning log |
| F1 Learning Summary | No | Yes | Caught | Default summary | Warning log |
| F2 Package | Yes | No | `PackageCreationError` | 500 error | `log_run_fail()` |
| F2 Variants | Yes | No | `VariantGenerationError` | 500 error | `log_run_fail()` |
| F2 Regen Guard | Yes | No | `VariantsAlreadyExistError` | 409 Conflict | Warning log |
| Internal Views | Yes | No | - | 404 (auth) / 500 | - |
| Eval Run | Partial | No | Errors captured in `EvalResult.errors` | N/A (CLI) | Printed to stdout |

**Key exceptions:**
- `GraphError` ([opportunities_graph.py:59](kairo/hero/graphs/opportunities_graph.py#L59)) - LLM/parsing failure
- `PackageCreationError`, `VariantGenerationError` ([content_engine.py:65](kairo/hero/engines/content_engine.py#L65))
- `VariantsAlreadyExistError` ([content_engine.py:82](kairo/hero/engines/content_engine.py#L82))
- `ObjectNotFoundError` ([decisions_service.py](kairo/hero/services/decisions_service.py)) - missing brand/opp/pkg/var

---

## 6) Tests & Gates

### Test Suites

- **DTO/HTTP**: `tests/test_dto_roundtrip.py`, `tests/test_http_contracts.py` - Pydantic serialization, API response shapes
- **Models**: `tests/test_models_schema.py` - Django model constraints
- **Services/Graphs/Engines**: `tests/test_services_*.py`, `tests/test_*_graph.py`, `tests/test_*_engine_integration.py`
- **Eval**: `tests/test_eval_hero_loop.py`, `tests/test_quality_classifier.py`
- **Internal/Obs**: `tests/test_internal_views.py` (auth, XSS), `tests/test_observability_store.py`
- **Ingestion**: `tests/ingestion/test_*.py`

### Key Invariants
- DTO exact keys: JSON matches Pydantic model fields exactly
- Auth 404 behavior: Internal views return 404 (not 401/403) when token missing
- XSS sanitization: `_sanitize_html()` removes script tags, event handlers
- Idempotency: Package returns existing; variant gen rejects if exists

### Running Tests
`DATABASE_URL=sqlite://:memory: LLM_DISABLED=true pytest`

---

## 7) Config Knobs

| Env Var | Default | Effect |
|---------|---------|--------|
| `LLM_DISABLED` | `false` | Graphs return stub responses |
| `EXTERNAL_SIGNALS_MODE` | `fixtures` | `fixtures` or `ingestion` |
| `KAIRO_OBS_ENABLED` | `false` | Enable JSONL logging |
| `KAIRO_OBS_DIR` | `var/obs` | Observability directory |
| `KAIRO_INTERNAL_ADMIN_TOKEN` | unset | Internal admin auth |
| `KAIRO_LLM_MODEL_FAST` | `gpt-4o-mini` | Fast model |
| `KAIRO_LLM_MODEL_HEAVY` | `gpt-4o` | Heavy model |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | DB connection |

---

## 8) Seams for Next Work (BrandBrain → Ingestion)

### Ingestion Status

**PARTIALLY BUILT.** Models exist ([kairo/ingestion/models.py](kairo/ingestion/models.py)), jobs exist but pipeline not fully wired:
- `ingest_capture`, `ingest_normalize`, `ingest_aggregate`, `ingest_score`, `ingest_pipeline` commands present
- `trend_emitter.py` bridges to hero loop via `get_external_signal_bundle()`
- `EXTERNAL_SIGNALS_MODE=ingestion` switches hero loop to use real TrendCandidates

### Where BrandBrain Compiler Would Plug In

**PROPOSED: Brand IR Storage** - New model `BrandIR` (OneToOne with Brand) containing:
- `positioning_embedding` (JSONField) - vector for semantic matching
- `pillar_keywords`, `persona_signals`, `taboo_patterns` - compiled brand intelligence

**Current brand context flow:** [opportunities_engine._build_brand_snapshot()](kairo/hero/engines/opportunities_engine.py#L264) reads Brand → personas → pillars. BrandBrain would extend this to include IR lookup.

### Where Ingestion Would Plug In

**Current external signals flow:** [external_signals_service.get_bundle_for_brand()](kairo/hero/services/external_signals_service.py#L44) checks `EXTERNAL_SIGNALS_MODE`. If `ingestion`: calls [trend_emitter.get_external_signal_bundle()](kairo/ingestion/services/trend_emitter.py#L48)

**PROPOSED: Brand-filtered TrendCandidate bridge** - Extend `trend_emitter.py` to accept brand IR and filter TrendCandidates by pillar_keywords overlap and persona_signals match.

### Minimal Checklist for Adding BrandBrain

1. **DTOs**: Add `BrandIRDTO` to [dto.py](kairo/hero/dto.py)
2. **Models**: Add `BrandIR` to [core/models.py](kairo/core/models.py)
3. **Service**: Create `kairo/hero/services/brand_brain_service.py` with `compile_brand()`, `get_ir()`
4. **Engine extension**: Modify `_build_brand_snapshot()` to include IR fields
5. **Ingestion bridge**: Update `trend_emitter.py` to accept brand IR for filtering
6. **Eval**: Add brand compilation step to eval harness, test IR → opportunity correlation

---

## 9) "Diff from PRD1 Intent" (Short)

### What PRD1 Claimed vs Reality

| PRD1 Claim | Code Reality |
|------------|--------------|
| Quality labels: good/partial/bad | **Implemented** in [quality_classifier.py](kairo/hero/eval/quality_classifier.py) - eval only |
| Operational health: ok/degraded/failed | **Implemented** in [observability_store.py](kairo/hero/observability_store.py) as `obs_health` |
| F1 fallback on graph error | **Implemented**: Returns existing opps or persisted stubs ([opportunities_engine.py:543](kairo/hero/engines/opportunities_engine.py#L543)) |
| F2 idempotency | **Implemented**: Package returns existing; variants reject regen |
| External signals from ingestion | **Partially implemented**: Mode switch exists, trend_emitter bridges |
| Brand-filtered signals | **Not implemented**: All TrendCandidates returned regardless of brand |
| Learning loop affects scoring | **Stubbed**: LearningEvent recorded but not used in scoring yet |

### Stubs vs Real

| Component | Status |
|-----------|--------|
| LLM calls | Real (or stub via `LLM_DISABLED`) |
| DB persistence | Real |
| External signals | Fixtures (default) or ingestion (switchable) |
| Auth | Stubbed (raw UUID, no user context) |
| Learning feedback | Stubbed (records events, no effect) |
| Ingestion pipeline | Models real, jobs exist, not fully wired |

---

## Definition of Done Checklist

- [x] Doc is <= 450 lines
- [x] Every major claim has file path + symbol
- [x] Unbuilt ingestion clearly labeled as partially built with status
- [x] Execution paths are concrete and correct
- [x] Includes seams section with PROPOSED clearly labeled
