# 01 – architecture spine

> how the system repo hangs together: processes, layers, and contracts

---

## 1. scope

this doc defines the **runtime architecture** and **module boundaries** for the **system repo** (django + supabase + deepagents) that powers kairo.

it answers:

- what processes exist?
- how do they talk?
- where do engines live?
- how does deepagents orchestrate flows?
- how does the ui repo integrate?

it does **not** specify:

- exact django app names
- exact endpoint list
- prompt text / deepagents graph details  
  (those live in `02-llm-orchestration.md` and per-engine prds)

---

## 2. runtime topology

### 2.1 repos

- **ui repo (next.js)**
  - next app, consuming a typed api.
  - has no direct db or llm access.
- **system repo (django + supabase + deepagents)**
  - this doc is for this repo.

### 2.2 processes (system repo)

single deploy unit to start with, but **logically** three processes:

1. **api web app**
   - django + drf (or similar) http api.
   - handles authenticated requests from ui.
   - exposes **only** canonical dto contracts.
2. **orchestrator / workers**
   - async workers (celery / rq / dramatiq / django-q – we’ll pick one) that:
     - run deepagents graphs
     - fan out long-running flows (e.g. “build content package variants”).
   - consume jobs from a queue.
3. **background learners**
   - batch / streaming tasks for the learning engine:
     - recompute pattern weights
     - refresh opportunity scores
     - run ablations / evaluation.

initially all three can be separate processes in the same container. later we can split if needed.

---

## 3. layering

### 3.1 overview

we enforce strict layering inside the system repo:

1. **persistence layer**  
   postgresql (supabase) + (later) vector store.
2. **domain layer (engines)**  
   pure-ish python modules implementing core logic over canonical objects.
3. **orchestration layer (deepagents)**  
   graphs/tools that call engines + llm.
4. **api layer**  
   django views/serializers exposing flows + simple queries.
5. **integration layer**  
   external services (slack, notion, etc.) – **not** in scope for v1, but reserved.

no layer is allowed to “reach around” another layer:

- ui → api only
- deepagents graphs → **domain + persistence** via explicit tools
- engines → db via repositories, not raw sql from random places.

---

## 4. canonical objects & ids

### 4.1 canonical objects (restate)

system-level canonical objects (from 00):

- `Brand`
- `Persona`
- `ContentPillar`
- `Opportunity`
- `ContentPackage`
- `Variant` (per-channel content unit)
- `PatternTemplate`
- `ExecutionEvent` (metrics, engagement, publishing events)
- `LearningEvent` (what we feed back into learning)

each of these must exist as:

1. **db model** (django + supabase)
2. **python dataclass / pydantic model** (domain)
3. **api dto** (serializer schema)

### 4.2 id scheme

- all top-level objects use **opaque string ids** (uuid v4 or ulid) with **type-safe prefixes**:
  - `brand_...`, `opp_...`, `pkg_...`, `pat_...`, etc.
- **multi-tenant rule:** every record that carries semantics has:
  - `brand_id`
  - `tenant_id` if we introduce multi-org later  
    (for now, marketer with many brands is still under single tenant).

engines and deepagents tools **never infer** brand/tenant from context; they receive them explicitly.

---

## 5. persistence layer

### 5.1 database

- **postgres (supabase)** is the source of truth.
- schema must be:
  - **normalized enough** for consistency
  - not over-engineered (we’re not building a crm).

tables (high-level):

- `brands`
- `personas`
- `content_pillars`
- `opportunities`
- `content_packages`
- `variants`
- `pattern_templates`
- `execution_events`
- `learning_events`

plus cross-link tables where needed (e.g. package ⇄ opportunity).

### 5.2 access pattern

we use **repositories** to hide raw sql:

- `BrandRepository`
- `OpportunityRepository`
- `PackageRepository`
- `PatternRepository`
- `LearningRepository`
- …

rules:

- api and deepagents **never** call orm directly.
- repositories return **domain models**, not orm models.
- repositories handle multi-tenant constraints and soft deletes.

### 5.3 vector store (later)

not needed for v1 hero slice, but architecture must leave space for:

- `pattern_embeddings`
- `brand_corpus_embeddings`  
  (site copy, prior posts, etc.)

behind an interface:

- `BrandSearchIndex`
- `PatternSearchIndex`

so we can swap “raw supabase rls + pgvector” for something else later.

---

## 6. domain layer (engines)

each engine is a python module with:

- **pure-ish services** that operate on canonical objects
- **no llm calls** inside engine functions
- **no django imports**

### 6.1 module layout (system repo)

```text
kairo/
  core/
    ids.py                # id helpers
    dto.py                # shared dtos
    errors.py
    time.py
  persistence/
    repositories/
      brands.py
      opportunities.py
      packages.py
      patterns.py
      learning.py
    transactions.py
  engines/
    brand_brain/
      service.py
      models.py
    opportunities/
      service.py
      scoring.py
      filters.py
    patterns/
      service.py
      ranking.py
    content_engineering/
      planner.py
      evaluator.py
    learning/
      updater.py
      features.py
  orchestration/
    graphs/
    tools/
  api/
    http/
    schemas/

```

### 6.2 engine responsibilities

**brand brain engine**

- manages positioning, tone, guardrails, persona–pillar matrix.
- pure functions like:
  - `summarize_brand_for_channel(brand, channel) -> BrandChannelProfile`
  - `apply_guardrails(brand, draft_variant) -> GuardrailedVariant`

**opportunities engine**

- merges raw signals into Opportunity objects.
- scoring, deduping, ranking for "today" board.
- examples:
  - `score_opportunity(opp, brand, patterns, history) -> float`
  - `rank_opportunities(list[Opportunity], brand) -> list[Opportunity]`

**patterns engine**

- manages PatternTemplates and their performance stats.
- examples:
  - `suggest_patterns(brand, channel, pillar, persona) -> list[PatternTemplate]`

**content engineering engine**

- non-llm responsibilities:
  - content graph constraints (how many variants per package, per channel)
  - variant states and transitions (draft → review → scheduled → published)
  - evaluation hooks (place where llm scoring plugs in).
- examples:
  - `propose_variant_slots(pkg, brand) -> list[VariantSlot]`

**learning engine**

- offline/online updates to:
  - pattern effectiveness
  - opportunity score priors
  - brand-specific biases.
- examples:
  - `update_pattern_weights(events)`
  - `update_opportunity_priors(events)`

llm calls sit above these engines in orchestration; engines consume concrete structured inputs.

---

## 7. orchestration layer (deepagents)

### 7.1 philosophy

deepagents provides:

- **graphs** (directed workflows) for flows like:
  - "generate today board"
  - "turn this opportunity into a multi-channel package"
  - "evaluate variants after performance data".
- **tools** that wrap engines + repositories:
  - `GetBrandContextTool`
  - `ListTodayOpportunitiesTool`
  - `CreatePackageFromOpportunityTool`
  - `ScoreVariantTool`
  - etc.

constraints:

- tools are thin adapters:
  - validate inputs
  - call engine/repository
  - return dto.
- graphs are explicitly named and versioned:
  - e.g. `TodayBoardV1`, `PackageWorkspaceV1`.

### 7.2 deepagents modules

```text
kairo/orchestration/
  graphs/
    today_board.py
    package_workspace.py
    pattern_suggestion.py
  tools/
    brand_tools.py
    opportunity_tools.py
    package_tools.py
    pattern_tools.py
    learning_tools.py
  llm/
    client.py         # unified llm client
    configs.py        # model + temperature configs
```

- `client.py` encapsulates vendor/model choice and temperature policy.
- graphs import tools + client and define workflows.

### 7.3 flow types

we distinguish:

1. **sync flows** (short, ui-blocking)
   - e.g. "summarize this opportunity" or "suggest 3 patterns".
   - called directly from api web app.
2. **async flows** (long-running)
   - e.g. "generate and evaluate 12 variants across 3 channels".
   - enqueued by api, processed by workers.
   - ui polls status or subscribes later via websockets.

---

## 8. api layer

### 8.1 transport

- http/json to start.
- endpoints grouped by "hero flows" and "reference reads".

### 8.2 categories

**hero-flow apis** (use orchestration + llm)

- `POST /api/brands/{brand_id}/today/refresh`
- `POST /api/brands/{brand_id}/packages/from-opportunity`
- `POST /api/packages/{package_id}/generate-variants`
- etc.

**reference apis** (thin wrappers over engines/repos, no llm)

- `GET /api/brands/{brand_id}/today`
- `GET /api/brands/{brand_id}/patterns`
- `GET /api/packages/{package_id}`

**learning hooks** (invoked from ingestion / webhooks later)

- `POST /api/events/execution`
  (record performance metrics, not llm)

### 8.3 api ⇄ orchestration contract

- hero endpoints never touch engines directly.
- they call orchestrators like:
  - `TodayBoardOrchestrator.run(brand_id, user_id, …)`
  - `PackageWorkspaceOrchestrator.run(...)`.

orchestrators then use deepagents graphs under the hood.

---

## 9. multi-tenant & brand isolation (runtime)

1. **tenant & brand are always explicit**
   - every api call must carry an authenticated `user_id`.
   - every flow entry takes `brand_id` explicitly.
2. **engine calls are scoped**
   - repositories always filtered by `brand_id` (and `tenant_id` later).
   - deepagents tools receive `brand_id` and never "discover" brands automatically.
3. **learning is brand-aware**
   - learning engine updates per-brand weights first.
   - any cross-brand learning must go through:
     - anonymized aggregates
     - explicit opt-in.

---

## 10. observability & testing hooks

### 10.1 tracing

- every hero-flow request gets a `correlation_id`.
- deepagents graphs propagate `correlation_id` through tools + llm calls.
- we log:
  - engine calls (function, args summary, duration)
  - llm calls (model, tokens where available, duration)
  - db writes (object type, count).

### 10.2 testability

architecture must allow:

- **engine unit tests** that:
  - seed repositories with fixtures
  - call engine functions directly
  - require no llm.
- **flow tests** that:
  - run deepagents graphs against fake llm (deterministic stub)
  - assert on dto shapes and invariants.

---

## 11. key end-to-end flows (spine)

these are the spine flows that must always stay simple and traceable.

### 11.1 open "today" board

1. ui calls `GET /api/brands/{brand_id}/today`.
2. api uses `TodayBoardOrchestrator`:
   - fetch brand, pillars, packages, opportunities
   - call opportunities engine to re-score/rank
   - optionally: call llm to generate "focus strip" narrative.
3. api returns a single dto:
   - `TodayBoardDTO`:
     - `focus_strip`
     - `opportunities[]`
     - `metrics_panel`.
4. ui renders from dto.

### 11.2 create package from opportunity

1. ui calls `POST /api/brands/{brand_id}/packages/from-opportunity`.
2. api enqueues async job `CreatePackageFromOpportunityJob`.
3. worker runs `PackageWorkspaceGraph`:
   - fetch brand, opportunity, patterns
   - call content engine to define slots
   - call llm to draft variants (per-slot).
4. job writes `content_package` + `variants`.
5. ui polls `GET /api/packages/{package_id}` until ready.

### 11.3 learning update loop (simplified)

1. we ingest execution events (publish + performance).
2. background job:
   - aggregates into `LearningEvents`
   - calls learning engine:
     - update pattern weights
     - update opportunity priors.
3. future "today" and "pattern suggestions" flows use updated scores.

the architecture spine ensures each of these flows:

- uses canonical objects
- hits engines before llm
- has a clear orchestrator graph.

---

## 12. mapping to future docs

this doc is the spine. follow-ups:

- `02-llm-orchestration.md`
  - deepagents graph patterns
  - llm client policy
  - tool catalog.
- per-engine prds:
  - `brand-brain-engine-prd.md`
  - `opportunities-engine-prd.md`
  - `patterns-engine-prd.md`
  - `content-engineering-engine-prd.md`
  - `learning-engine-prd.md`.

