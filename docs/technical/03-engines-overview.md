# 03 – engines overview

> what each engine owns, and the surface area they expose

---

## 1. purpose

this doc defines:

- the **engine layer** inside the system repo
- the **responsibility boundaries** of each engine
- the **public methods** (signatures + behavior) they expose
- how engines sit between:
  - django/api
  - supabase/postgres
  - deepagents flows

if deepagents graphs, views, or ui disagree with this, this doc wins.

---

## 2. mental model

### 2.1 engines are services, not agents

- an **engine** is a **pure-ish python service** that:
  - talks to the db (read/write canonical objects)
  - encapsulates domain logic + invariants
  - returns **plain dto objects**, not prompts or langchain graphs.

- **agents** (deepagents) are:
  - *clients* of engines
  - orchestration of multiple engine calls + llm calls.

### 2.2 key invariants

- django views / api **never** hit the db directly for domain logic.
  - they call engines.
- agents **never** bypass engines to mutate state.
- engines **do not** know about:
  - http
  - react / ui
  - deepagents internal graphs

---

## 3. engine list

we define five core engines for v1:

1. **brand_brain_engine**
   - owns brand, personas, pillars, guardrails, and brand-level views.
2. **opportunities_engine**
   - owns opportunities, today board sorting, pin/snooze semantics.
3. **patterns_engine**
   - owns pattern templates, pattern ranking, channel suitability.
4. **content_engine**
   - owns packages, variants, workflow status & channel-ready content.
5. **learning_engine**
   - owns execution events, learning events, and feedback loops that update scores / weights.

orchestrator flows (in `04-orchestrator-and-flows.md`) call into these engines.

---

## 4. brand_brain_engine

### 4.1 responsibility

- single source of truth for **brand strategy** layer:
  - positioning, tone, taboos
  - personas
  - pillars
  - channel handles
- provides **read models** used by:
  - ui (strategy page, context bars)
  - content/opportunities/patterns/learning engines
  - agents (“what does this brand care about?”)

### 4.2 python module

- `kairo/engines/brand_brain/__init__.py`
- `kairo/engines/brand_brain/service.py`
- `kairo/engines/brand_brain/models.py` (dtos)

### 4.3 primary dtos

- `BrandSummary`
  - brand core fields + channels
- `BrandStrategyView`
  - positioning, tone_tags, taboos, personas, pillars in one view
- `PersonaSummary`
- `PillarSummary`

### 4.4 public methods (sync)

```python
class BrandBrainEngine:
    def get_brand_summary(self, tenant_id: str, brand_id: str) -> BrandSummary: ...

    def get_brand_strategy_view(
        self,
        tenant_id: str,
        brand_id: str,
    ) -> BrandStrategyView: ...

    def list_brand_personas(
        self,
        tenant_id: str,
        brand_id: str,
    ) -> list[PersonaSummary]: ...

    def list_brand_pillars(
        self,
        tenant_id: str,
        brand_id: str,
    ) -> list[PillarSummary]: ...

    # write operations – called by onboarding/ops tools, not agents directly in v1
    def upsert_brand(
        self,
        tenant_id: str,
        brand: BrandSummary,
    ) -> BrandSummary: ...

    def upsert_persona(
        self,
        tenant_id: str,
        brand_id: str,
        persona: PersonaSummary,
    ) -> PersonaSummary: ...

    def upsert_pillar(
        self,
        tenant_id: str,
        brand_id: str,
        pillar: PillarSummary,
    ) -> PillerSummary: ...

```

### 4.5 invariants owned

- `(tenant_id, slug)` uniqueness for brands.
- personas & pillars must reference existing brand.
- taboos/tone tags are authoritative guardrails for content/patterns engines.

---

## 5. opportunities_engine

### 5.1 responsibility

- manages Opportunity lifecycle:
  - ingest / creation (manual or automated)
  - scoring / re-scoring (via learning engine inputs)
  - board-level state: pin, snooze, staleness.
- builds Today board view:
  - sorted set of opportunities
  - filter/group metadata
  - metrics for today page header & cockpit.

### 5.2 python module

- `kairo/engines/opportunities/service.py`
- `kairo/engines/opportunities/models.py`

### 5.3 primary dtos

- `OpportunityDTO` – direct mapping of canonical Opportunity with resolved handles:
  - `persona_handle`, `pillar_handle`, `channel_handles`.
- `TodayBoardView`
  - `opportunities`: list[OpportunityDTO]
  - `high_score_count`: int
  - breakdown by pillar/persona/channel (for focus strip)
- `OpportunityIngestResult`
  - ids, dedupe flags, initial score.

### 5.4 public methods

```python
class OpportunitiesEngine:
    # read

    def get_today_board(
        self,
        tenant_id: str,
        brand_id: str,
    ) -> TodayBoardView:
        """
        - fetch active opportunities
        - filter out snoozed/expired
        - sort with engine's ranking policy
        - compute summary metrics for UI (counts per pillar/persona/channel)
        """

    def get_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
    ) -> OpportunityDTO: ...

    def list_opportunities_for_brand(
        self,
        tenant_id: str,
        brand_id: str,
        limit: int = 100,
    ) -> list[OpportunityDTO]: ...

    # write – board interactions

    def pin_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
    ) -> OpportunityDTO: ...

    def unpin_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
    ) -> OpportunityDTO: ...

    def snooze_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
        until: datetime,
    ) -> OpportunityDTO: ...

    def unsnooze_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
    ) -> OpportunityDTO: ...

    # write – creation / updates

    def ingest_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        payload: dict,
        created_by_user_id: str | None,
    ) -> OpportunityIngestResult:
        """
        payload may come from:
          - manual form
          - ingestion pipeline (social listening)
          - agent-proposed ideas
        engine is responsible for:
          - dedupe
          - initial scoring
          - canonicalizing into Opportunity
        """

    def update_opportunity_score(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
        new_score: float,
        explanation: str | None = None,
    ) -> OpportunityDTO: ...
```

### 5.5 invariants owned

- all score updates come through this engine (even if learning_engine proposes them).
- pin/snooze rules (max pins, snooze windows) live here.

---

## 6. patterns_engine

### 6.1 responsibility

- manages PatternTemplate library:
  - global + brand-specific overrides.
- decides which patterns to recommend:
  - per channel
  - per pillar/persona
  - based on performance & brand fit.
- exposes pattern summaries for:
  - ui (patterns page)
  - content engine (to pick for generation)
  - agents (when building prompts).

### 6.2 python module

- `kairo/engines/patterns/service.py`
- `kairo/engines/patterns/models.py`

### 6.3 primary dtos

- `PatternDTO`
- `PatternRecommendation`
  - `pattern`
  - `rationale`
  - `score`
- `PatternLibraryView`
  - all patterns grouped by category/status.

### 6.4 public methods

```python
class PatternsEngine:
    def list_patterns(
        self,
        tenant_id: str,
        brand_id: str | None = None,
    ) -> PatternLibraryView: ...

    def get_pattern(
        self,
        tenant_id: str,
        pattern_id: str,
    ) -> PatternDTO: ...

    def recommend_patterns_for_context(
        self,
        tenant_id: str,
        brand_id: str,
        *,
        channel: Channel,
        pillar_id: str | None,
        persona_id: str | None,
        max_results: int = 3,
    ) -> list[PatternRecommendation]:
        """
        ranking heuristic:
          - active patterns only
          - channel-compatible
          - brand-specific overrides > global
          - performance-weighted, guardrail-safe
        """

    # admin / authoring (v2+)
    def upsert_pattern(
        self,
        tenant_id: str,
        pattern: PatternDTO,
    ) -> PatternDTO: ...
```

### 6.5 invariants owned

- deprecated patterns are not returned in recommendations by default.
- brand-specific patterns override global with same name/category when appropriate.

---

## 7. content_engine

### 7.1 responsibility

this is the heavy engine.

- owns ContentPackage and Variant lifecycles:
  - create from opportunity
  - manage multi-channel variants
  - handle workflow statuses (draft → in_review → scheduled → published)
- coordinates with other engines:
  - brand_brain_engine for context
  - patterns_engine for selecting patterns
  - learning_engine for evaluation feedback
- is the main "bridge" between llm agents and persistent content.

### 7.2 python module

- `kairo/engines/content/service.py`
- `kairo/engines/content/models.py`

### 7.3 primary dtos

- `PackageDTO`
- `VariantDTO`
- `PackageWorkspaceView`
  - `package`
  - origin opportunity (resolved)
  - variants by channel
  - brand strategy slice (tone, taboos)
  - recommended patterns (from patterns_engine)

### 7.4 public methods (core)

```python
class ContentEngine:
    # read

    def list_packages_for_brand(
        self,
        tenant_id: str,
        brand_id: str,
        *,
        status: PackageStatus | None = None,
        limit: int = 50,
    ) -> list[PackageDTO]: ...

    def get_package(
        self,
        tenant_id: str,
        brand_id: str,
        package_id: str,
    ) -> PackageDTO: ...

    def get_package_workspace_view(
        self,
        tenant_id: str,
        brand_id: str,
        package_id: str,
    ) -> PackageWorkspaceView:
        """
        used by UI and agents:
          - loads package
          - joins origin opportunity (if any)
          - groups variants by channel
          - fetches brand context + recommended patterns
        """

    # write – packages

    def create_package_from_opportunity(
        self,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
        *,
        channels: list[Channel],
        created_by_user_id: str | None,
    ) -> PackageDTO: ...

    def update_package_status(
        self,
        tenant_id: str,
        brand_id: str,
        package_id: str,
        new_status: PackageStatus,
    ) -> PackageDTO: ...

    # write – variants

    def create_variant(
        self,
        tenant_id: str,
        brand_id: str,
        package_id: str,
        channel: Channel,
        *,
        pattern_template_id: str | None = None,
        initial_draft_text: str | None = None,
        generated_by_model: str | None = None,
    ) -> VariantDTO: ...

    def update_variant_text(
        self,
        tenant_id: str,
        brand_id: str,
        variant_id: str,
        *,
        draft_text: str | None = None,
        edited_text: str | None = None,
        approved_text: str | None = None,
        new_status: VariantStatus | None = None,
    ) -> VariantDTO: ...

    def schedule_variant(
        self,
        tenant_id: str,
        brand_id: str,
        variant_id: str,
        publish_at: datetime,
    ) -> VariantDTO: ...

    # llm/agent helpers (content engine will call llm via deepagents – spec in 06)
    def propose_variants_for_package(
        self,
        tenant_id: str,
        brand_id: str,
        package_id: str,
        *,
        channels: list[Channel],
        max_variants_per_channel: int = 2,
    ) -> list[VariantDTO]: ...
```

### 7.5 invariants owned

- enforce workflow rules:
  - cannot schedule without text + required approval (if configured).
  - cannot mark published without `published_at`.
- ensure exactly one active text field per variant (based on status).
- enforce channel-level constraints (length, mentions, hashtags) before scheduling.

---

## 8. learning_engine

### 8.1 responsibility

- ingests ExecutionEvents from platforms.
- produces LearningEvents (aggregated signals).
- pushes updates back into:
  - opportunities_engine (opportunity scores)
  - patterns_engine (pattern performance stats)
  - content_engine (variant eval scores).

it does not talk to llms directly; it's a pure analytics/feedback engine.

### 8.2 python module

- `kairo/engines/learning/service.py`
- `kairo/engines/learning/models.py`

### 8.3 primary dtos

- `ExecutionEventDTO`
- `LearningEventDTO`
- `PerformanceSummary`
  - per-variant / per-pattern metrics

### 8.4 public methods

```python
class LearningEngine:
    # ingestion

    def record_execution_event(
        self,
        tenant_id: str,
        brand_id: str,
        event: ExecutionEventDTO,
    ) -> None: ...

    # batch update entrypoints (called by scheduled deepagents flows)

    def compute_variant_performance_summary(
        self,
        tenant_id: str,
        brand_id: str,
        *,
        window_days: int = 30,
    ) -> list[PerformanceSummary]: ...

    def update_pattern_performance_from_events(
        self,
        tenant_id: str,
        brand_id: str,
        *,
        window_days: int = 90,
    ) -> None:
        """
        - aggregates ExecutionEvents
        - writes LearningEvents
        - updates PatternTemplate fields (usage_count, last_used_at, avg_engagement_score)
        """

    def update_opportunity_scores_from_events(
        self,
        tenant_id: str,
        brand_id: str,
        *,
        window_days: int = 30,
    ) -> None:
        """
        - aggregates performance of variants linked to a given origin_opportunity_id
        - calls OpportunitiesEngine.update_opportunity_score(...)
        """
```

### 8.5 invariants owned

- dedupe of execution events per `variant/event_type/platform_event_id`.
- learning runs must be idempotent over a given window.

---

## 9. cross-engine rules

### 9.1 who calls whom

- **brand_brain_engine**
  - baseline; others read it, it calls nobody.
- **patterns_engine**
  - reads brand_brain_engine for guardrails if needed (via orchestrator, not direct cross-import in v1 – we can keep dependencies one-directional via a CoreContext helper later).
  - reads learning_engine outputs (pattern performance).
- **opportunities_engine**
  - may read patterns/learning indirectly for scoring, but we'll likely feed scores into it rather than having it reach out.
- **content_engine**
  - reads brand_brain_engine + patterns_engine.
  - gets updated by learning_engine via eval scores.
- **learning_engine**
  - reads canonicals (variants, patterns, opportunities).
  - writes updates via other engines' public methods.

for now, you can imagine a top-level `SystemContext` that wires concrete engine instances together; direct import cycles are avoided.

### 9.2 isolation vs composition

- ui and agents never juggle raw db models directly.
- engines provide the stable contracts; if db schema changes, engines adapt.

---

## 10. module layout (system repo)

target tree (simplified):

```text
kairo/
  engines/
    brand_brain/
      __init__.py
      service.py
      models.py
    opportunities/
      __init__.py
      service.py
      models.py
    patterns/
      __init__.py
      service.py
      models.py
    content/
      __init__.py
      service.py
      models.py
    learning/
      __init__.py
      service.py
      models.py

  core/
    enums.py
    dto.py       # shared value types (handles, score bands, etc.)

  persistence/
    models/      # django/supabase mapping
    repos/       # thin db access wrappers
```

django views / api layer will:

- construct `SystemContext` with all engines.
- call engine methods instead of touching repos directly.

deepagents flows will:

- receive an engine bundle or context object and only talk to it, never repos.

---

## 11. what's intentionally missing (for now)

this doc does not specify:

- deepagents graphs or node types
  - → that's `04-orchestrator-and-flows.md` and `06-content-engine-deep-agent-spec.md`.
- exact pydantic/django model definitions
  - → those are derived from `02-canonical-objects.md`.
- error model / exception taxonomy
  - → will be captured in a small `errors.md` later if needed.

its only job: make sure everyone (you, claude code, future collaborators) agree what "brand_brain_engine" and friends actually do and don't do.

