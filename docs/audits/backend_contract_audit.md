# Backend Contract Audit

**Generated:** 2025-12-15T18:15:00Z
**Scope:** Backend repo only (no frontend assumptions)

---

## 1. Canonical DTOs (Current Truth)

**Source file:** `kairo/hero/dto.py`

### 1.1 TodayBoardDTO

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `brand_id` | `UUID` | No | - | No | FK to Brand |
| `snapshot` | `BrandSnapshotDTO` | No | - | Yes | In-memory snapshot |
| `opportunities` | `list[OpportunityDTO]` | No | `[]` | No | Persisted opps |
| `meta` | `TodayBoardMetaDTO` | No | - | Yes | Generation metadata |

### 1.2 TodayBoardMetaDTO

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `generated_at` | `datetime` | No | - | Yes | Generation timestamp |
| `source` | `str` | No | `"hero_f1"` | Yes | Flow identifier |
| `degraded` | `bool` | No | `False` | Yes | True if fallback mode |
| `total_candidates` | `int \| None` | Yes | `None` | Yes | Raw count before filtering |
| `reason` | `str \| None` | Yes | `None` | Yes | Degraded reason code |
| `notes` | `list[str]` | No | `[]` | Yes | Generation notes |
| `opportunity_count` | `int` | No | `0` | Yes | Final count |
| `dominant_pillar` | `str \| None` | Yes | `None` | Yes | Most common pillar |
| `dominant_persona` | `str \| None` | Yes | `None` | Yes | Most common persona |
| `channel_mix` | `dict[str, int]` | No | `{}` | Yes | Channel distribution |

### 1.3 OpportunityDTO (Persisted)

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `id` | `UUID` | No | - | No | Primary key |
| `brand_id` | `UUID` | No | - | No | FK to Brand |
| `title` | `str` | No | - | No | Opportunity title |
| `angle` | `str` | No | - | No | Content angle/thesis |
| `type` | `OpportunityType` | No | - | No | trend/evergreen/competitive/campaign |
| `primary_channel` | `Channel` | No | - | No | linkedin/x |
| `score` | `float` | No | - | No | 0-100, ge/le constrained |
| `score_explanation` | `str \| None` | Yes | `None` | No | Scoring rationale |
| `source` | `str` | No | `""` | No | Signal source |
| `source_url` | `str \| None` | Yes | `None` | No | Source URL |
| `persona_id` | `UUID \| None` | Yes | `None` | No | FK to Persona |
| `pillar_id` | `UUID \| None` | Yes | `None` | No | FK to ContentPillar |
| `suggested_channels` | `list[Channel]` | No | `[]` | No | Additional channels |
| `is_pinned` | `bool` | No | `False` | No | User pinned |
| `is_snoozed` | `bool` | No | `False` | No | User snoozed |
| `snoozed_until` | `datetime \| None` | Yes | `None` | No | Snooze expiry |
| `created_via` | `CreatedVia` | No | `AI_SUGGESTED` | No | Creation source |
| `created_at` | `datetime` | No | - | No | Auto-set |
| `updated_at` | `datetime` | No | - | No | Auto-updated |

### 1.4 OpportunityDraftDTO (Graph Output, Not Persisted)

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `proposed_title` | `str` | No | - | **Yes** | Title from graph |
| `proposed_angle` | `str` | No | - | **Yes** | Angle from graph |
| `type` | `OpportunityType` | No | - | No | Maps to Opportunity.type |
| `primary_channel` | `Channel` | No | - | No | Maps to Opportunity.primary_channel |
| `suggested_channels` | `list[Channel]` | No | `[]` | No | Maps directly |
| `score` | `float` | No | - | No | 0-100, maps directly |
| `score_explanation` | `str \| None` | Yes | `None` | No | Maps directly |
| `source` | `str` | No | `""` | No | Maps directly |
| `source_url` | `str \| None` | Yes | `None` | No | Maps directly |
| `persona_hint` | `str \| None` | Yes | `None` | **Yes** | Resolved to persona_id by engine |
| `pillar_hint` | `str \| None` | Yes | `None` | **Yes** | Resolved to pillar_id by engine |
| `raw_reasoning` | `str \| None` | Yes | `None` | **Yes** | LLM reasoning (not persisted) |
| `is_valid` | `bool` | No | `True` | **Yes** | Per rubric §4.7 |
| `rejection_reasons` | `list[str]` | No | `[]` | **Yes** | Why it failed |
| `why_now` | `str \| None` | Yes | `None` | **Yes** | Timing justification |

### 1.5 ContentPackageDTO (Persisted)

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `id` | `UUID` | No | - | No | Primary key |
| `brand_id` | `UUID` | No | - | No | FK to Brand |
| `title` | `str` | No | - | No | Package title |
| `status` | `PackageStatus` | No | `DRAFT` | No | draft/ready/published/archived |
| `origin_opportunity_id` | `UUID \| None` | Yes | `None` | No | FK to Opportunity |
| `persona_id` | `UUID \| None` | Yes | `None` | No | FK to Persona |
| `pillar_id` | `UUID \| None` | Yes | `None` | No | FK to ContentPillar |
| `channels` | `list[Channel]` | No | `[]` | No | Target channels |
| `planned_publish_start` | `datetime \| None` | Yes | `None` | No | Scheduled start |
| `planned_publish_end` | `datetime \| None` | Yes | `None` | No | Scheduled end |
| `owner_user_id` | `UUID \| None` | Yes | `None` | No | Assigned user |
| `notes` | `str \| None` | Yes | `None` | No | Internal notes |
| `created_via` | `CreatedVia` | No | `MANUAL` | No | Creation source |
| `created_at` | `datetime` | No | - | No | Auto-set |
| `updated_at` | `datetime` | No | - | No | Auto-updated |

### 1.6 ContentPackageDraftDTO (Graph Output, Not Persisted)

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `title` | `str` | No | - | No | Maps to ContentPackage.title |
| `thesis` | `str` | No | - | **Yes** | Core content thesis (not in DB model) |
| `summary` | `str` | No | - | **Yes** | Brief explanation (not in DB model) |
| `primary_channel` | `Channel` | No | - | **Yes** | Main channel (not in DB model) |
| `channels` | `list[Channel]` | No | `[]` | No | Maps directly |
| `cta` | `str \| None` | Yes | `None` | **Yes** | Call-to-action (not in DB model) |
| `pattern_hints` | `list[str]` | No | `[]` | **Yes** | Suggested patterns |
| `persona_hint` | `str \| None` | Yes | `None` | **Yes** | Resolved to persona_id |
| `pillar_hint` | `str \| None` | Yes | `None` | **Yes** | Resolved to pillar_id |
| `notes_for_humans` | `str \| None` | Yes | `None` | **Yes** | Maps to ContentPackage.notes |
| `raw_reasoning` | `str \| None` | Yes | `None` | **Yes** | LLM reasoning |
| `is_valid` | `bool` | No | `True` | **Yes** | Per rubric §10 |
| `rejection_reasons` | `list[str]` | No | `[]` | **Yes** | Why it failed |
| `package_score` | `float \| None` | Yes | `None` | **Yes** | 0-15 scale per rubric §7 |
| `package_score_breakdown` | `dict[str, float] \| None` | Yes | `None` | **Yes** | thesis/coherence/relevance/cta/brand_alignment |
| `quality_band` | `Literal["invalid","weak","board_ready"] \| None` | Yes | `None` | **Yes** | Quality classification |

### 1.7 VariantDTO (Persisted)

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `id` | `UUID` | No | - | No | Primary key |
| `package_id` | `UUID` | No | - | No | FK to ContentPackage |
| `brand_id` | `UUID` | No | - | No | FK to Brand |
| `channel` | `Channel` | No | - | No | linkedin/x/newsletter |
| `status` | `VariantStatus` | No | `DRAFT` | No | draft/ready/approved/published |
| `pattern_template_id` | `UUID \| None` | Yes | `None` | No | FK to PatternTemplate |
| `body` | `str` | No | `""` | No | Active content text |
| `call_to_action` | `str \| None` | Yes | `None` | No | CTA |
| `generated_by_model` | `str \| None` | Yes | `None` | No | LLM model used |
| `proposed_at` | `datetime \| None` | Yes | `None` | No | When AI proposed |
| `scheduled_publish_at` | `datetime \| None` | Yes | `None` | No | Scheduled publish |
| `published_at` | `datetime \| None` | Yes | `None` | No | Actual publish time |
| `eval_score` | `float \| None` | Yes | `None` | No | Evaluation score |
| `eval_notes` | `str \| None` | Yes | `None` | No | Evaluation notes |
| `created_at` | `datetime` | No | - | No | Auto-set |
| `updated_at` | `datetime` | No | - | No | Auto-updated |

### 1.8 VariantDraftDTO (Graph Output, Not Persisted)

| Field | Type | Optional | Default | DTO-only | Notes |
|-------|------|----------|---------|----------|-------|
| `channel` | `Channel` | No | - | No | Maps directly |
| `body` | `str` | No | - | No | Maps directly |
| `title` | `str \| None` | Yes | `None` | **Yes** | Newsletter title (not in DB model) |
| `call_to_action` | `str \| None` | Yes | `None` | No | Maps directly |
| `pattern_hint` | `str \| None` | Yes | `None` | **Yes** | Resolved to pattern_template_id |
| `raw_reasoning` | `str \| None` | Yes | `None` | **Yes** | LLM reasoning |
| `is_valid` | `bool` | No | `True` | **Yes** | Per rubric §10 |
| `rejection_reasons` | `list[str]` | No | `[]` | **Yes** | Why it failed |
| `variant_score` | `float \| None` | Yes | `None` | **Yes** | 0-12 scale per rubric §6 |
| `variant_score_breakdown` | `dict[str, float] \| None` | Yes | `None` | **Yes** | clarity/anchoring/channel_fit/cta |
| `quality_band` | `Literal["invalid","weak","publish_ready"] \| None` | Yes | `None` | **Yes** | Quality classification |

---

## 2. Graphs Output Contracts

### 2.1 F1: Opportunities Graph

**Source:** `kairo/hero/graphs/opportunities_graph.py`

**Entrypoint:**
```python
def graph_hero_generate_opportunities(
    run_id: UUID,
    brand_snapshot: BrandSnapshotDTO,
    learning_summary: LearningSummaryDTO,
    external_signals: ExternalSignalBundleDTO,
    llm_client: LLMClient | None = None,
) -> list[OpportunityDraftDTO]
```

**Internal LLM Schemas:**

| Schema | Purpose | Key Fields |
|--------|---------|------------|
| `RawOpportunityIdea` | Synthesis output | title, angle, type, primary_channel, why_now, source, persona_hint, pillar_hint |
| `SynthesisOutput` | Wrapper | `opportunities: list[RawOpportunityIdea]` (6-24 items) |
| `MinimalScoringItem` | Scoring output | idx (0-based), score (0-100), band ("invalid"/"weak"/"strong"), reason |
| `MinimalScoringOutput` | Wrapper | `scores: list[MinimalScoringItem]` |
| `ScoredOpportunity` | Joined result | All RawOpportunityIdea fields + score, score_explanation |

**Validation Filters (in engine):**

| Filter | Location | Description |
|--------|----------|-------------|
| `_filter_invalid_opportunities()` | `opportunities_engine.py:369-399` | Drops `is_valid=False` opps per rubric §4.7 |
| `_filter_redundant_opportunities()` | `opportunities_engine.py:421-459` | Drops near-duplicates (Jaccard similarity >= 0.75) |
| `_validate_opportunity()` | `opportunities_graph.py:584-632` | Validates against rubric §4 (title, angle, channel, why_now, score, type) |

**Rubric Hard Requirements (§4):**
- §4.1: Single clear thesis (title >=5 chars, angle >=10 chars)
- §4.2: Valid channel (linkedin/x)
- §4.3: Clear why_now (>=10 chars, non-vacuous)
- §4.6: No taboo violations (score=0 means taboo)
- §4.4: Valid opportunity type

### 2.2 F2: Package Graph

**Source:** `kairo/hero/graphs/package_graph.py`

**Entrypoint:**
```python
def graph_hero_package_from_opportunity(
    run_id: UUID,
    brand_snapshot: BrandSnapshotDTO,
    opportunity: OpportunityDTO,
    llm_client: LLMClient | None = None,
) -> ContentPackageDraftDTO
```

**Internal LLM Schemas:**

| Schema | Purpose | Key Fields |
|--------|---------|------------|
| `RawPackageIdea` | LLM output | title, thesis (20-500 chars), summary (20-1000 chars), primary_channel, channels, cta, pattern_hints |
| `PackageSynthesisOutput` | Wrapper | `package: RawPackageIdea` |

**Validation Filters (in graph):**

| Filter | Location | Description |
|--------|----------|-------------|
| `_validate_package()` | `package_graph.py:184-243` | Validates against rubric §5 |
| `_compute_package_score()` | `package_graph.py:246-325` | Scores package (0-15 scale) |
| `_determine_quality_band()` | `package_graph.py:328-343` | Assigns band: invalid/weak/board_ready |

**Rubric Hard Requirements (§5):**
- §5.1: Non-vacuous thesis (>=20 chars, no template phrases like "write about")
- §5.2: Valid primary_channel in channels list
- §5.3: Non-empty channels
- §5.5: No taboo violations
- §5.6: Clear opportunity linkage

### 2.3 F2: Variants Graph

**Source:** `kairo/hero/graphs/variants_graph.py`

**Entrypoint:**
```python
def graph_hero_variants_from_package(
    run_id: UUID,
    package: ContentPackageDraftDTO,
    brand_snapshot: BrandSnapshotDTO,
    llm_client: LLMClient | None = None,
) -> list[VariantDraftDTO]
```

**Internal LLM Schemas:**

| Schema | Purpose | Key Fields |
|--------|---------|------------|
| `RawVariant` | LLM output | channel, title (optional), body (>=10 chars), call_to_action, pattern_hint |
| `VariantsGenerationOutput` | Wrapper | `variants: list[RawVariant]` (>=1 items) |

**Channel Constraints (per rubric §5):**

| Channel | min_chars | max_chars | Notes |
|---------|-----------|-----------|-------|
| linkedin | 100 | 6000 | 2-8 paragraphs |
| x | 20 | 600 | Ideally <280 chars |
| newsletter | 200 | 10000 | Email-style, longer form |

**Template Artifact Patterns (rubric §3.3):**
- `[insert X here]`, `{brand}`, `{name}`, `{cta}`
- `as an ai`, `language model`, `i cannot`, `i'm unable`
- `TODO:`, `placeholder`, `you should write`

**Validation Filters:**

| Filter | Location | Description |
|--------|----------|-------------|
| `_validate_variant()` | `variants_graph.py:198-247` | Validates against rubric §3 |
| `_compute_variant_score()` | `variants_graph.py:250-340` | Scores variant (0-12 scale) |
| `_determine_variant_quality_band()` | `variants_graph.py:343-358` | Assigns band: invalid/weak/publish_ready |

---

## 3. API Surface

### 3.1 Today Board Endpoints

| Endpoint | Method | Handler | Response DTO | Notes |
|----------|--------|---------|--------------|-------|
| `/api/brands/{brand_id}/today/` | GET | `api_views.get_today_board` | `TodayBoardDTO` | Main board endpoint |
| `/api/brands/{brand_id}/today/regenerate/` | POST | `api_views.regenerate_today_board` | `RegenerateResponseDTO` | Force regeneration |

### 3.2 Package Endpoints

| Endpoint | Method | Handler | Response DTO | Notes |
|----------|--------|---------|--------------|-------|
| `/api/brands/{brand_id}/opportunities/{opportunity_id}/packages/` | POST | `api_views.create_package_from_opportunity` | `CreatePackageResponseDTO` | Create package |
| `/api/packages/{package_id}/` | GET | `api_views.get_package` | `ContentPackageDTO` | Get package by ID |

### 3.3 Variant Endpoints

| Endpoint | Method | Handler | Response DTO | Notes |
|----------|--------|---------|--------------|-------|
| `/api/packages/{package_id}/variants/generate/` | POST | `api_views.generate_variants` | `GenerateVariantsResponseDTO` | Generate variants |
| `/api/packages/{package_id}/variants/` | GET | `api_views.get_variants` | `VariantListDTO` | List variants |
| `/api/variants/{variant_id}/` | PATCH | `api_views.update_variant` | `VariantDTO` | Update variant |

### 3.4 Decision Endpoints

| Endpoint | Method | Handler | Response DTO | Notes |
|----------|--------|---------|--------------|-------|
| `/api/opportunities/{opportunity_id}/decision/` | POST | `api_views.record_opportunity_decision` | `DecisionResponseDTO` | Record opp decision |
| `/api/packages/{package_id}/decision/` | POST | `api_views.record_package_decision` | `DecisionResponseDTO` | Record pkg decision |
| `/api/variants/{variant_id}/decision/` | POST | `api_views.record_variant_decision` | `DecisionResponseDTO` | Record var decision |

### 3.5 Internal Admin Endpoints (Token Auth Required)

| Endpoint | Method | Handler | Response | Notes |
|----------|--------|---------|----------|-------|
| `/hero/internal/runs/` | GET | `internal_views.list_hero_runs` | HTML table | Run browser |
| `/hero/internal/runs/{run_id}/` | GET | `internal_views.get_hero_run` | HTML detail | Run detail |
| `/hero/internal/runs/{run_id}.json` | GET | `internal_views.get_hero_run_json` | JSON | Run JSON export |
| `/hero/internal/evals/` | GET | `internal_views.list_evals` | HTML list | Eval browser |
| `/hero/internal/evals/{filename}` | GET | `internal_views.get_eval_detail` | HTML (rendered MD) | Eval detail |
| `/hero/internal/brands/` | GET | `internal_views.list_brands` | HTML table | Brand browser |
| `/hero/internal/brands/{brand_id}/` | GET | `internal_views.get_brand_detail` | HTML detail | Brand detail |

---

## 4. Failure Semantics Currently Implemented

### 4.1 Failure Mode Matrix

| Component | Failure Type | Behavior | Meta Fields Set |
|-----------|--------------|----------|-----------------|
| F1 Graph | `GraphError` | **Degrade** - Return existing opps or empty board | `meta.degraded=True`, `meta.reason="graph_error"` |
| F1 Graph | LLM timeout | **Degrade** - Same as GraphError | `meta.degraded=True`, `meta.reason="graph_error"` |
| F1 Graph | Parse error | **Degrade** - Same as GraphError | `meta.degraded=True`, `meta.reason="graph_error"` |
| Learning Summary | Any error | **Fallback** - Use default empty summary | No meta impact, logged |
| External Signals | Any error | **Fallback** - Use empty bundle | No meta impact, logged |
| F2 Package Graph | `PackageGraphError` | **Fail loudly** - Raise to caller | n/a (error response) |
| F2 Variants Graph | `VariantsGraphError` | **Fail loudly** - Raise to caller | n/a (error response) |
| F2 Regeneration | Package exists with variants | **Fail loudly** - Raise `VariantsAlreadyExistError` | n/a (error response) |
| LLM_DISABLED mode | n/a | **Stub** - Return deterministic fake data | Stubs pass validation |

### 4.2 Degraded Board Meta Fields

When F1 returns a degraded board (`opportunities_engine.py:243-261`):

```python
{
    "meta": {
        "degraded": True,
        "reason": "graph_error",
        "total_candidates": None,
        "notes": [
            "Graph failed: <error message>",
            "Returning degraded board with fallback opportunities"
        ]
    }
}
```

### 4.3 Observability Logging

| Event | Function | Location |
|-------|----------|----------|
| Run start | `log_run_start()` | `observability_store.py` |
| Run complete | `log_run_complete()` | `observability_store.py` |
| Run fail | `log_run_fail()` | `observability_store.py` |
| Classification | `log_classification()` | `observability_store.py` |

**Classification Labels:**
- `obs_health`: `ok` / `degraded` / `failed` (operational health)
- These are DISTINCT from quality labels in `quality_classifier.py`: `good` / `partial` / `bad`

### 4.4 F1 Classification Rules (`classify_f1_run`)

| Condition | obs_health | Reason Code |
|-----------|------------|-------------|
| status="fail" | `failed` | `engine_failure` |
| taboo_violations > 0 | `failed` | `taboo_violations:N` |
| valid_opportunity_count = 0 | `failed` | `zero_valid_opportunities` |
| valid_opportunity_count >= 3 | `ok` | `healthy_count:N` |
| valid_opportunity_count 1-2 | `degraded` | `low_count:N` |

### 4.5 F2 Classification Rules (`classify_f2_run`)

| Condition | obs_health | Reason Code |
|-----------|------------|-------------|
| status="fail" | `failed` | `engine_failure` |
| taboo_violations > 0 | `failed` | `taboo_violations:N` |
| package_count = 0 | `failed` | `no_package_created` |
| variant_count = 0 | `failed` | `no_variants_created` |
| variant_count >= expected_channels | `ok` | `full_coverage:N_variants` |
| variant_count > 0 but < expected | `degraded` | `partial_coverage:N/M_variants` |

---

## Summary

This audit captures the current backend contract state:

1. **DTOs are well-defined** in `kairo/hero/dto.py` with clear separation between persisted fields and DTO-only fields (validation, scoring, hints)

2. **Graphs return typed DTOs** (`OpportunityDraftDTO`, `ContentPackageDraftDTO`, `VariantDraftDTO`) with internal LLM schemas for parsing

3. **Engine applies validation filters** before persistence (invalid filtering, deduplication)

4. **Failure semantics are clear**:
   - F1 degrades gracefully with meta flags
   - F2 fails loudly (no partial success)
   - LLM_DISABLED returns deterministic stubs
   - Observability logs all run states

5. **API endpoints return wrapper DTOs** with status fields and nested content DTOs
