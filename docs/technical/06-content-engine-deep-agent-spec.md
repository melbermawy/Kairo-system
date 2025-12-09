# 06 – content engine deepagents spec

> how the content engine uses deepagents to turn opportunities into multi-channel packages

---

## 0. scope

this doc defines how the **content engine** is implemented as a set of **deepagents graphs**, sitting on top of:

- `02-canonical-objects.md`
- `03-engines-overview.md`
- `04-orchestrator-and-flows.md`
- `05-llm-and-deepagents-conventions.md`

it covers:

- the **core flow**: F2.1 “create package from opportunity”
- two secondary flows:
  - F2.2 “regenerate variants for a channel”
  - F2.3 “light edit + re-sync”
- how these flows map to:
  - deepagents **graphs**
  - python **nodes**
  - **llm nodes** vs **engine nodes**

anything outside content creation (learning updates, opportunity scoring) belongs to other engines.

---

## 1. responsibilities

### 1.1 what content engine owns

the content engine is responsible for:

- turning a **single opportunity** (+ brand context) into a:
  - **ContentPackageDTO**
  - with **ChannelVariantDTO[]** per channel
- maintaining the **internal consistency** of a package:
  - thesis ↔ variants
  - persona ↔ tone
  - patterns ↔ channel
- providing **regeneration** and **edit-safe** APIs:
  - regenerate subset (one channel, one variant)
  - preserve human edits where asked
- never violating:
  - brand **taboos**
  - tone **constraints**
  - platform **policy** basics

### 1.2 what it does *not* own

it does **not**:

- decide which opportunities are “worth a package” (that’s opportunities engine)
- manage performance feedback loops (learning engine)
- publish to external platforms (future “publishing engine” / integration layer)
- manage user permissions or collaboration

---

## 2. canonical objects used

(from `02-canonical-objects.md`, names here are indicative)

- `BrandDTO`
- `BrandStrategyDTO`  
  includes: `positioning`, `tone_tags[]`, `taboos[]`, `pillars[]`
- `PersonaDTO`
- `PillarDTO`
- `OpportunityDTO`  
  includes: `id`, `title`, `angle`, `score`, `persona_id`, `pillar_id`, `type`, `source`
- `PatternTemplateDTO`  
  includes: `id`, `name`, `beats[]`, `channels[]`, `status`, `category`
- `ContentPackageDTO`  
  includes: `id`, `brand_id`, `opportunity_id`, `thesis`, `status`, `channels[]`
- `PackageThesisDTO`  
  includes: `core_belief`, `tension`, `promise`, `audience`, `pillar`, `risk_notes`
- `ChannelVariantDTO`  
  includes: `id`, `channel`, `pattern_id`, `raw_text`, `headline`, `call_to_action`, `status`, `is_human_edited`

supporting “bundle” dtos for context:

- `ContentContextDTO`
  - `brand: BrandDTO`
  - `strategy: BrandStrategyDTO`
  - `opportunity: OpportunityDTO`
  - `persona: PersonaDTO`
  - `pillar: PillarDTO | null`
  - `patterns: PatternTemplateDTO[]`
  - `history: PastPackageSummaryDTO[]` (optional)

- `VariantPlanDTO`
  - `channel: ChannelId`
  - `pattern_id: PatternId`
  - `angle_adjustments: str`
  - `length_preference: Literal["short","medium","long"]`

---

## 3. graphs overview

we define 3 deepagents graphs for content engine:

1. `F2_1_CREATE_PACKAGE_GRAPH`
   - “new package from opportunity”
2. `F2_2_REGENERATE_CHANNEL_GRAPH`
   - “regenerate variants for one channel”
3. `F2_3_RESYNC_AFTER_EDIT_GRAPH`
   - “user has edited text; keep thesis in sync”

module layout:

- `kairo/content_engine/agent/`
  - `create_package_graph.py`
  - `regenerate_channel_graph.py`
  - `resync_after_edit_graph.py`
  - `nodes/context_nodes.py`
  - `nodes/llm_nodes.py`
  - `nodes/persist_nodes.py`
  - `schemas.py` (pydantic models)

---

## 4. graph F2.1 – create package from opportunity

### 4.1 high-level behavior

goal: given `(brand_id, opportunity_id, channels[])`, produce:

- a **new ContentPackageDTO** stored via `ContentEngine`
- initial **ChannelVariantDTO[]`** per requested channel
- stable ids so the ui can immediately render the package workspace

no side effects outside `ContentEngine` (no learning updates, no publishing).

### 4.2 node list (in order)

graph name: `create_package_graph`

1. `LoadContextNode`
2. `ThesisLLMNode`
3. `PlanChannelsNode`
4. `DraftVariantsLLMNode`
5. `AssemblePackageNode`
6. `PersistPackageNode`

### 4.3 node specs

#### 4.3.1 LoadContextNode (engine node)

**type:** engine node (no llm)

**input:**

```python
class CreatePackageInput(BaseModel):
    brand_id: BrandId
    opportunity_id: OpportunityId
    target_channels: list[ChannelId]
```

**implementation outline:**

- call `BrandBrainEngine.get_brand(brand_id)`
- call `BrandBrainEngine.get_strategy(brand_id)`
- call `OpportunitiesEngine.get_opportunity(opportunity_id)`
- resolve persona + pillar:
  - `BrandBrainEngine.get_persona_for_opportunity(...)`
  - `BrandBrainEngine.get_pillar_for_opportunity(...)` (if separate)
- call `PatternsEngine.get_patterns_for_channels(target_channels)`
- optionally fetch `LearningEngine.get_past_packages_for_brand(brand_id)` (summary only)

**output:**

```python
class CreatePackageContext(BaseModel):
    context: ContentContextDTO
    target_channels: list[ChannelId]
```

**failure modes:**

- if any required object is missing:
  - node raises `ContextMissingError`
  - graph returns failure; orchestrator decides whether to show ui error.

#### 4.3.2 ThesisLLMNode (llm node)

**type:** structured llm node (no tools)

**input:** `CreatePackageContext`

**prompt shape:**

- system:
  - "you are a content strategist for {brand_name}…"
  - list `tone_tags`, `taboos`
- user/instructions:
  - labeled fields:
    - `opportunity.title`, `opportunity.angle`, `opportunity.type`
    - `persona.name`, `persona.goals`, `persona.pains`
    - `pillar.name` (if any)
    - `brand_strategy.positioning`
    - short history summary (if provided)
  - ask explicitly:
    - define `core_belief`, `tension`, `promise`, `audience`, `pillar_link`, `risk_notes`

**output model:**

```python
class PackageThesisDTO(BaseModel):
    core_belief: str
    tension: str
    promise: str
    audience_summary: str
    pillar_id: PillarId | None
    risk_notes: str
```

**node returns:**

```python
class ThesisNodeOutput(BaseModel):
    context: ContentContextDTO
    thesis: PackageThesisDTO
    target_channels: list[ChannelId]
```

**validation:**

- pydantic validation
- soft checks:
  - `core_belief`, `tension`, `promise` non-empty
  - `risk_notes` present but may be short
- one retry on invalid structure; then fail.

#### 4.3.3 PlanChannelsNode (engine node)

**type:** pure python, no llm

**goal:** decide which pattern to use for each channel, and any length preferences.

**input:** `ThesisNodeOutput`

**logic (deterministic):**

- for each channel in `target_channels`:
  - filter `context.patterns` where:
    - `channel in pattern.channels`
    - `pattern.status == "active"`
  - if none:
    - fallback to generic evergreen patterns
  - sort by:
    - `learning_engine_score` if available
    - otherwise by `usage_count` descending
  - choose top 1 pattern per channel
- set `length_preference` by channel:
  - linkedin: `"medium"`
  - x: `"short"`
  - blog: `"long"`, etc.

**output:**

```python
class PlannedChannelBundle(BaseModel):
    context: ContentContextDTO
    thesis: PackageThesisDTO
    plans: list[VariantPlanDTO]
```

#### 4.3.4 DraftVariantsLLMNode (llm node)

**type:** structured llm node (no tools)

**input:** `PlannedChannelBundle`

**call strategy:**

- either:
  - one llm call per channel (simpler logging)
- or:
  - one call for all channels in v2
- in v1: one call per channel for simplicity.

**per-channel prompt:**

- system:
  - "you are a {channel} content writer for {brand_name}…"
  - taboos list
  - tone tags
- user/instructions:
  - thesis fields
  - opportunity title + angle
  - persona summary
  - chosen pattern:
    - `pattern.name`
    - `pattern.beats[]` as "outline beats"
  - explicit instructions per channel:
    - x: 1–2 tweets + optional thread continuation
    - linkedin: 1 long post, ~200–300 words, with clear narrative arc
  - ask to:
    - respect pattern beats in order
    - include one clear call-to-action

**output model:**

```python
class ChannelVariantDraftDTO(BaseModel):
    channel: ChannelId
    pattern_id: PatternId
    main_text: str
    headline: str | None
    call_to_action: str | None
    rationale: str  # why this pattern + approach
```

**node returns:**

```python
class DraftVariantsOutput(BaseModel):
    context: ContentContextDTO
    thesis: PackageThesisDTO
    drafts: list[ChannelVariantDraftDTO]
```

**validation:**

- ensure:
  - all channel in `target_channels`
  - `pattern_id` matches one of planned patterns
  - `main_text` non-trivial length
- if any channel missing → one retry with explicit error.

#### 4.3.5 AssemblePackageNode (engine node)

**type:** pure python

**input:** `DraftVariantsOutput`

**logic:**

- create a new, not yet persisted `ContentPackageDTO`:
  - generate `package_id`
  - set `brand_id`, `opportunity_id`
  - embed thesis
  - set `status: "draft"`
  - set channels from drafts
- for each draft, create `ChannelVariantDTO`:
  - `id`: generated
  - `channel`: as provided
  - `pattern_id`
  - `raw_text = main_text`
  - `headline`
  - `call_to_action`
  - `status = "draft"`
  - `is_human_edited = False`

**output:**

```python
class AssembledPackage(BaseModel):
    package: ContentPackageDTO
    variants: list[ChannelVariantDTO]
```

#### 4.3.6 PersistPackageNode (engine node)

**type:** engine node

**input:** `AssembledPackage`

**calls:**

- `ContentEngine.save_package_with_variants(package, variants)`

**output:**

```python
class CreatePackageResult(BaseModel):
    package_id: PackageId
```

**failure behavior:**

- db error → raise `PersistenceError`
- graph returns failure; orchestrator logs + surfaces ui error.

---

## 5. graph F2.2 – regenerate variants for a channel

### 5.1 use case

user in the package workspace clicks:

- "regenerate linkedin variants"

or

- "add x channel to this package"

we reuse as much context as possible:

- existing package
- thesis
- brand strategy
- patterns

### 5.2 node list

graph name: `regenerate_channel_graph`

1. `LoadPackageContextNode`
2. `PlanSingleChannelNode`
3. `DraftSingleChannelLLMNode`
4. `MergeVariantNode`
5. `PersistVariantNode`

### 5.3 node specs (delta vs F2.1)

#### 5.3.1 LoadPackageContextNode

similar to `LoadContextNode`, but starting from `package_id`:

**input:**

```python
class RegenerateChannelInput(BaseModel):
    package_id: PackageId
    channel: ChannelId
```

**calls:**

- `ContentEngine.get_package(package_id)`
- `ContentEngine.get_variants_for_package(package_id)`
- `BrandBrainEngine.get_brand(...)`
- `BrandBrainEngine.get_strategy(...)`
- `OpportunitiesEngine.get_opportunity(package.opportunity_id)`
- `PatternsEngine.get_patterns_for_channels([channel])`

**output:**

```python
class RegenerateChannelContext(BaseModel):
    context: ContentContextDTO
    package: ContentPackageDTO
    existing_variants: list[ChannelVariantDTO]
    channel: ChannelId
```

#### 5.3.2 PlanSingleChannelNode

same logic as `PlanChannelsNode`, but for one channel.

#### 5.3.3 DraftSingleChannelLLMNode

same as `DraftVariantsLLMNode` but:

- input includes:
  - existing variant text (if any) as optional reference
- instructions:
  - if `is_human_edited` is `True` on existing variant:
    - treat existing text as "strong reference"
    - keep core narrative but improve clarity or structure
  - else:
    - free to rewrite, but preserve thesis.

output model can be reused (`ChannelVariantDraftDTO`).

#### 5.3.4 MergeVariantNode

**goal:** decide whether to create a new variant or overwrite an existing one.

**policy v1:**

- if channel not present:
  - create new variant
- if channel present:
  - overwrite one variant with:
    - `status = "draft"`
    - `is_human_edited = False`
  - keep any older variants but mark them "superseded" (optional, depending on data model).

#### 5.3.5 PersistVariantNode

**calls:**

- `ContentEngine.update_or_add_variant(package_id, merged_variant)`

**result dto:**

```python
class RegenerateChannelResult(BaseModel):
    package_id: PackageId
    channel: ChannelId
    variant_id: VariantId
```

---

## 6. graph F2.3 – resync after human edit

### 6.1 use case

- user has manually edited one or more variants in the ui.
- we need to:
  - mark `is_human_edited = True`
  - optionally adjust the thesis to reflect the new "actual story".

note: v1 can keep thesis unchanged and only mark flags; v2 can do llm-based "back-propagation" of edits into thesis.

### 6.2 node list

**v1 (minimal):**

1. `MarkHumanEditedNode`
2. `PersistEditsNode`

**v2 (optional learning-ish):**

1. `LoadPackageAndVariantsNode`
2. `UpdateThesisFromEditsLLMNode`
3. `PersistThesisNode`

### 6.3 v1 nodes

#### 6.3.1 MarkHumanEditedNode

**input:**

```python
class HumanEditInput(BaseModel):
    package_id: PackageId
    variant_id: VariantId
    new_text: str
```

**logic:**

- fetch variant
- update:
  - `raw_text = new_text`
  - `is_human_edited = True`
  - `status = "edited"`

**output:** updated `ChannelVariantDTO`

#### 6.3.2 PersistEditsNode

calls `ContentEngine.update_variant(variant)`.

no llm involved in v1.

---

## 7. integration with orchestrator

these graphs are not called by the ui directly.

instead:

- the orchestrator layer defines high-level operations:
  - `orchestrator.create_package_from_opportunity(...)`
  - `orchestrator.regenerate_channel(...)`
  - `orchestrator.mark_variant_edited(...)`
- each orchestrator function:
  - constructs the proper graph input dto
  - calls deepagents graph
  - handles:
    - success → return ids to ui / api
    - failure → map to well-typed errors

**example (pseudo-python):**

```python
def create_package_from_opportunity(brand_id, opportunity_id, channels):
    inp = CreatePackageInput(
        brand_id=brand_id,
        opportunity_id=opportunity_id,
        target_channels=channels,
    )
    result = create_package_graph.run(inp)
    return result.package_id
```

---

## 8. observability and logging

for each graph run we log:

- `flow_id` (uuid)
- `graph_name` (e.g. `F2_1_CREATE_PACKAGE`)
- inputs (ids, channel list, no raw text)
- node results:
  - for engine nodes: success/failure, duration
  - for llm nodes:
    - model profile (smart/fast)
    - prompt id (e.g. `content_thesis_v1`)
    - output hash + schema validation result
- final result: `package_id` / error code

this must obey `05-llm-and-deepagents-conventions.md` logging rules.

---

## 9. constraints and invariants

the following must hold after any content-engine graph:

1. **one canonical thesis per package**
   - `ContentPackageDTO.thesis` always present
   - it must be the source of truth for future regenerations.
2. **channel variants consistent with channels list**
   - `package.channels` is the set of `variant.channel` values
3. **brand taboos respected**
   - all llm nodes for content creation must receive `taboos[]`
   - content that clearly violates taboos must be filtered or rejected
4. **no direct db access from llm nodes**
   - deepagents llm nodes never hit db, only use dto snapshots
5. **id stability**
   - package id and variant ids are generated by engine nodes, not llm nodes.

---

## 10. open questions (v2+)

things we may add later, but not in v1:

- **multiple variants per channel with ranking:**
  - allow llm to draft N variants; engine picks top-k by heuristic
- **learning-aware pattern choice:**
  - integrate learning engine metrics into `PlanChannelsNode` scoring
- **long-running async generation:**
  - queue-backed graphs instead of in-request runs
- **tool-using llm nodes for:**
  - dynamic pattern lookup
  - light brand voice adaptation

any of these must be reflected in:

- updated `03-engines-overview.md`
- updated `05-llm-and-deepagents-conventions.md`
- this doc, before implementation.

