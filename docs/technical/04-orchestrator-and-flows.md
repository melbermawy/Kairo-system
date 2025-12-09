# 04 – orchestrator and flows

> how deepagents, engines, and flows fit together

---

## 1. purpose

this doc defines:

- **what “orchestrator” means** in kairo
- **how deepagents is used** (and restricted)
- the **core flows** we support in v1:
  - F1 – today board + focus summary (hero slice entry)
  - F2 – package creation + multi-channel draft (content engine core)
  - F3 – post-publish learning update (feedback loop)

it sits **on top of**:

- `01-architecture-spine.md`
- `02-canonical-objects.md`
- `03-engines-overview.md`

if deepagents config or “prompt experiments” disagree with this doc, this doc wins.

---

## 2. orchestrator mental model

### 2.1 orchestrator vs engines vs agents

we distinguish three layers:

1. **engines (service layer)**
   - pure python services, no llm:
     - `BrandBrainEngine`, `OpportunitiesEngine`, `PatternsEngine`,
       `ContentEngine`, `LearningEngine`
   - own business logic + invariants
   - read/write canonical objects, return simple DTOs

2. **orchestrator flows**
   - **deterministic workflows** that:
     - stitch multiple engine calls together
     - enforce sequencing + pre/post conditions
     - decide **where llm is allowed to participate**
   - implemented as **deepagents “deep workflows”**, but:
     - graph structure is pre-defined
     - no open-ended free-roam agent

3. **llm calls inside flows**
   - specific “turns” in a flow where the agent:
     - reads **strictly bounded context** (DTOs & small schemas)
     - returns **structured outputs** (pydantic models)
   - no “decide your own tools and goals” autonomy.

### 2.2 what deepagents is allowed to do

deepagents is used to:

- define **graphs**:
  - nodes = engine calls, llm sub-tasks, basic transforms
  - edges = explicit next-steps and error branches
- define **roles** at llm nodes:
  - pattern selector
  - copy editor
  - summarizer
- enforce **input/output schemas** around llm calls.

deepagents is **not** used to:

- talk directly to supabase/postgres
- mutate state without going through engines
- spawn open-ended sub-agents that call arbitrary tools.

---

## 3. code layout for flows

target structure (system repo):

```text
kairo/
  orchestrator/
    __init__.py
    context.py          # SystemContext: engine bundle, config
    flows/
      today_board.py    # F1 – today board + focus
      package_build.py  # F2 – package creation + drafts
      learning_update.py# F3 – learning loop
    deepagents/
      today_graph.py
      package_graph.py
      learning_graph.py

- `context.py`
  - owns construction of engines from configs (db connections etc.)
  - passes a `SystemContext` into each flow / deepagents graph.
- `flows/*.py`
  - python-side entrypoints with clear signatures.
  - used by:
    - django api
    - cronjobs / celery / lambdas
    - tests
- `deepagents/*.py`
  - actual graph definitions using deepagents primitives.
  - strictly adhere to contracts in this doc.

---

## 4. cross-cutting rules for all flows

1. **engines own invariants**
   - flows never bypass engines to touch db or business rules.
2. **structured i/o only**
   - every llm step returns a pydantic model, not free text.
   - any text intended for ui is wrapped in a dto (e.g. `VariantDTO` field).
3. **idempotency**
   - for any flow that can be retried, repeated runs must not corrupt state.
   - learning updates are explicitly idempotent over a time window.
4. **auditability**
   - every flow logs:
     - input parameters
     - critical engine mutations
     - llm node outputs (summaries or hashes if needed)
   - learning flows attach `LearningEvent` records.
5. **no "unbounded prompts"**
   - context size is tightly controlled:
     - only relevant DTOs
     - never raw database dumps
     - never unfiltered user config blobs.

---

## 5. flow F1 – today board + focus summary (hero slice)

### 5.1 intent

given a `tenant_id` and `brand_id`, produce:

- a Today board:
  - sorted list of opportunities
  - pin/snooze state
- a focus summary:
  - "focus on {pillar} / {channel} / {persona} today"
  - counts of high-score items in that focus slice
- no writes in v1 (pure read model).

this powers:

- today page main list + focus strip
- "kairo, what should i work on today?" quick answer.

### 5.2 entrypoint

```python
# kairo/orchestrator/flows/today_board.py

class TodayBoardOrchestrator:
    def build_today_view(
        self,
        ctx: SystemContext,
        tenant_id: str,
        brand_id: str,
    ) -> TodayBoardView:
        """
        orchestrates engines + an optional llm summarizer
        to produce TodayBoardView-for-UI.
        """
```

### 5.3 main steps (no llm version)

1. **fetch base board**

```python
board = ctx.opportunities.get_today_board(tenant_id, brand_id)
```

2. **enrich with brand context**

```python
strategy = ctx.brand_brain.get_brand_strategy_view(tenant_id, brand_id)
```

3. **compute focus slice**

deterministic algorithm (no llm) that:

- counts opportunities by:
  - pillar
  - persona
  - channel
- picks focus pillar and focus persona using policy:
  - high-score density vs neglected pillar heuristic
- returns `TodayFocusContext` dto:

```python
TodayFocusContext(
    primary_pillar_id=...,
    primary_persona_id=...,
    primary_channel=...,
    high_score_opportunities=[...ids...],
    metrics=FocusMetrics(...),
)
```

4. **assemble view**

`TodayBoardViewForUI`:

- board opportunities (list)
- `focus_context`
- `brand_summary` or subset from strategy.

no llm needed for the ui; optional llm summarizer is a separate call.

### 5.4 llm summarizer node (optional F1.1)

if we want a one-sentence summary like "Today you're focusing on…", we create:

```python
class TodaySummaryOrchestrator:
    def summarize_today_focus(
        self,
        ctx: SystemContext,
        tenant_id: str,
        brand_id: str,
    ) -> TodayFocusSummaryDTO: ...
```

- inside, we call F1 core (no llm) then hand small context to deepagents:

```python
class TodayFocusSummary(BaseModel):
    summary: str  # 1–2 sentences
```

- graph has one llm node, consumes:
  - brand name
  - focus pillar/persona/channel labels
  - high-score count
- returns `TodayFocusSummary` model.

no engine writes allowed in this flow.

---

## 6. flow F2 – package creation & multi-channel draft

### 6.1 intent

given an `opportunity_id`, create a ContentPackage plus draft variants across channels, with:

- brand strategy respected
- patterns selected
- drafts ready for human editing.

this is where we actually use deepagents more heavily.

### 6.2 entrypoint

```python
# kairo/orchestrator/flows/package_build.py

class PackageBuildOrchestrator:
    def create_package_from_opportunity(
        self,
        ctx: SystemContext,
        tenant_id: str,
        brand_id: str,
        opportunity_id: str,
        channels: list[Channel],
        created_by_user_id: str | None,
    ) -> PackageWorkspaceView:
        """
        orchestrates content_engine + patterns_engine + brand_brain_engine
        + llm to produce an initial package + channel drafts.
        """
```

### 6.3 steps (high-level graph)

1. **load context (engines only)**

- `opportunities_engine`:
  - `get_opportunity(...)`
- `brand_brain_engine`:
  - `get_brand_strategy_view(...)`
- `patterns_engine`:
  - `recommend_patterns_for_context(..., channel=None or per-channel)`

assemble a `PackageBuildContext` dto:

```python
class PackageBuildContext(BaseModel):
    opportunity: OpportunityDTO
    brand_strategy: BrandStrategyView
    recommended_patterns: list[PatternRecommendation]
    channels: list[Channel]
```

2. **llm node – synthesize core thesis**

deepagents node:

- input: `PackageBuildContext`
- output: structured model:

```python
class PackageThesis(BaseModel):
    core_argument: str          # 1–2 sentences
    supporting_points: list[str]# 3–5 bullets
    risks_to_avoid: list[str]   # taboos rephrased for this context
```

constraints:

- must obey `brand_strategy.taboos` and `tone_tags`
- must mirror `opportunity.angle` but can rewrite for clarity.

3. **engine – create package**

```python
package = ctx.content.create_package_from_opportunity(
    tenant_id=tenant_id,
    brand_id=brand_id,
    opportunity_id=opportunity_id,
    channels=channels,
    created_by_user_id=created_by_user_id,
)

package = ctx.content.update_package_thesis(
    ...,
    core_argument=thesis.core_argument,
    key_points=thesis.supporting_points,
)
```

(if `update_package_thesis` isn't in ContentEngine yet, it will be added; spec-wise it's part of content engine responsibility.)

4. **llm node – per-channel variant plans**

deepagents fan-out stage:

- for each channel:
  - input: `PackageThesis`, brand tone, taboos, channel constraints
  - select a pattern (or take recommendation from patterns_engine)
  - output:

```python
class VariantPlan(BaseModel):
    channel: Channel
    pattern_id: str
    variants: list["VariantDraft"]
```

where:

```python
class VariantDraft(BaseModel):
    raw_text: str
    rationale: str            # short explanation for learning later
    safety_flags: list[str]   # any potential issues
```

5. **engine – persist variants**

orchestrator loops over `VariantPlan` outputs:

```python
for plan in plans:
    for draft in plan.variants:
        variant = ctx.content.create_variant(
            tenant_id, brand_id, package.id,
            channel=plan.channel,
            pattern_template_id=plan.pattern_id,
            initial_draft_text=draft.raw_text,
            generated_by_model=...,  # model name
        )
```

6. **assemble workspace view**

finally:

```python
view = ctx.content.get_package_workspace_view(
    tenant_id, brand_id, package.id
)
```

return `PackageWorkspaceView` to ui / caller.

### 6.4 constraints for F2

- **no publishing in this flow:**
  - status for package: `draft` or `in_review` only.
  - variants: `draft` only.
- **llm outputs must be safe:**
  - we either:
    - add a guard-rail node (simple content filter), or
    - rely on model-level filters + taboos.
- **idempotency:**
  - this flow is not idempotent by default (it creates objects).
  - caller must not retry blindly without a guard.
  - we may add a "regenerate variants for package" variant of this flow later.

---

## 7. flow F3 – post-publish learning update

### 7.1 intent

periodically:

- ingest platform execution data (clicks, impressions, etc.)
- aggregate into LearningEvents
- update:
  - pattern performance
  - opportunity scores
  - variant performance metadata

this is run on a schedule (cron / background worker), no ui caller.

### 7.2 entrypoints

```python
# kairo/orchestrator/flows/learning_update.py

class LearningUpdateOrchestrator:
    def run_for_brand(
        self,
        ctx: SystemContext,
        tenant_id: str,
        brand_id: str,
        window_days: int = 30,
    ) -> None:
        """
        one-shot learning update for a given brand + window.
        """

    def run_global(
        self,
        ctx: SystemContext,
        window_days: int = 30,
    ) -> None:
        """
        iterate over all brands for the tenant(s) configured.
        """
```

### 7.3 steps

1. **ingest execution events**

ingestion itself can be separate (webhook handlers or polling tasks), but at the learning flow level we assume events are in the db.

2. **compute variant performance**

```python
summaries = ctx.learning.compute_variant_performance_summary(
    tenant_id, brand_id, window_days=window_days
)
```

`PerformanceSummary` includes:

- `variant_id`
- `engagement_score`
- `platform_metrics` (impressions, clicks, etc.)
- `pattern_id` (if present)
- `origin_opportunity_id`

3. **update pattern performance**

```python
ctx.learning.update_pattern_performance_from_events(
    tenant_id, brand_id, window_days=window_days
)
```

inside:

- aggregates across variants per pattern
- updates pattern records (via patterns_engine) with:
  - `usage_count`
  - `last_used_at`
  - `avg_engagement_score`

4. **update opportunity scores**

```python
ctx.learning.update_opportunity_scores_from_events(
    tenant_id, brand_id, window_days=window_days
)
```

inside:

- groups performance by `origin_opportunity_id`
- proposes new scores
- calls `OpportunitiesEngine.update_opportunity_score(...)`

5. **emit learning events**

optionally, orchestrator logs:

```python
LearningEvent(
    tenant_id, brand_id,
    type="OPPORTUNITY_SCORE_UPDATE",
    payload={...}
)
```

these are purely observational and don't drive further writes.

### 7.4 llm involvement (optional F3.1)

for v1, F3 is non-llm.

later, we can add a summarizer:

- "what patterns worked last week?"
- "which pillar is over/under-invested?"

this would be a separate llm flow that:

- reads aggregated summaries only
- produces natural-language analytics for the ui or email reports.

---

## 8. error handling & retries

### 8.1 classification

we treat errors as:

- **hard errors** (must fail the flow):
  - missing brand/opportunity/package
  - engine invariant violation
- **soft errors** (skip node, continue flow):
  - individual llm node failure
  - partial engine write failure that can be rolled back or ignored.

### 8.2 where retries are allowed

- **F1 (today board):**
  - idempotent, safe to retry.
- **F2 (package build):**
  - not safe to blindly retry; caller must decide:
    - create another package
    - or add "regenerate drafts" sub-flow with explicit semantics.
- **F3 (learning):**
  - idempotent by window; safe to retry.

deepagents graph configs must:

- map node failures to specific exception types.
- define whether to:
  - bubble up (abort flow)
  - or compensate (log & skip).

---

## 9. how ui and api call these flows

### 9.1 ui

- nextjs frontend never talks to flows directly.
- it calls django api endpoints:
  - `GET /brands/{brand_id}/today` → F1 core
  - `POST /packages/from-opportunity` → F2
  - `POST /learning/run` → admin-only, triggers F3

### 9.2 api layer

in django:

```python
def get_today(request, brand_id: str):
    ctx = build_system_context()
    orchestrator = TodayBoardOrchestrator()
    view = orchestrator.build_today_view(
        ctx,
        tenant_id=request.tenant_id,
        brand_id=brand_id,
    )
    return JsonResponse(view.to_dict())
```

similar for other flows.

---

## 10. what this doc does not define

- **deepagents config code:**
  - node implementations
  - prompts
  - graph wiring details
  - → that lives in `05-llm-and-deepagents-conventions.md` + `06-content-engine-deep-agent-spec.md`.
- **api endpoints details** (urls, auth)
  - → api/docs.
- **onboarding engine / tenant bootstrapping flows**
  - → separate doc later.

this doc is the source of truth for:

- which flows exist,
- what they're allowed to do,
- which engines they may call,
- and where llm is permitted into the loop.

