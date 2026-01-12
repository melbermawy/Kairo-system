# 02 – engines overview

this doc is the **routing map** for kairo’s system:

- which **engines** exist,
- which **canonical objects (CO-xx)** they create / mutate / read,
- when they run,
- and how they connect in one end-to-end flow.

it is **conceptual**. concrete prompts, schemas, and phase plans live in per-engine docs and the prd.

---

## 1. engine list (frozen)

we standardize on five engines:

- **E-01 — brand brain engine**  
  turns onboarding input + example content into a versioned brand strategy (`BrandBrainSnapshot`) and runtime knobs (`BrandRuntimeContext`, `BrandMemoryFragment`).

- **E-02 — opportunities engine**  
  turns external/internal signals into scored, brand-specific `OpportunityCard`s grouped into `OpportunityBatch`es.

- **E-03 — patterns engine**  
  turns high-performing posts into reusable `PatternTemplate`s and logs `PatternUsage` to ground pattern quality.

- **E-04 — content engineering engine (CE)**  
  turns an `OpportunityCard` (or manual topic) into a full `ContentPackage` → `CoreArgument` → `ChannelPlan` → `ContentVariant`s.

- **E-05 — learning engine**  
  turns `FeedbackEvent`s + performance data into updated `BrandPreferences` and `GlobalPriors` that bias all other engines.

these names / ids are **canonical** and must be used consistently across code, docs, and prompts.

---

## 2. engine ↔ canonical objects map

this section is about **ownership and responsibilities** for CO-xx objects.  
rule of thumb: each “preference” / “strategy” store has **one writer engine**.

### E-01 — brand brain engine

**one-line job**  
builds and maintains a structured, versioned understanding of a brand’s identity, audiences, and pillars, and materializes it into runtime knobs.

**creates**

- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-05 BrandBrainSnapshot`
- `CO-06 BrandRuntimeContext`
- `CO-07 BrandMemoryFragment` (initial examples, curated snippets)

**mutates**

- `CO-02 Persona` (re-clustering, edits via recalibration flows)
- `CO-03 Pillar` (refinement, priority tweaks)
- `CO-06 BrandRuntimeContext` (initial derivation from snapshot + preferences)

> note: **does not** mutate `CO-01 Brand`. brand is pure identity / ownership.

**reads**

- `CO-01 Brand`
- `CO-07 BrandMemoryFragment` (when building new snapshots)
- `CO-18 FeedbackEvent` (optional, to surface “clarify brand” prompts)
- `CO-19 BrandPreferences` (to inform runtime context materialization)

---

### E-02 — opportunities engine

**one-line job**  
turns external and internal signals into brand-specific “reasons to speak now”, scored and mapped to personas/pillars.

**creates**

- `CO-08 GlobalSourceDoc` (normalized external content)
- `CO-09 OpportunityCard`
- `CO-10 OpportunityBatch`

**mutates**

- `CO-08 GlobalSourceDoc` (add relevance tags, topic tags)
- `CO-09 OpportunityCard` (update `score`, `lifecycle_state`)
- `CO-10 OpportunityBatch` (add/remove cards as scores change)

**reads**

- `CO-01 Brand`
- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-05 BrandBrainSnapshot`
- `CO-06 BrandRuntimeContext`
- `CO-07 BrandMemoryFragment` (for on-brand angle suggestions)
- `CO-19 BrandPreferences` (opportunity scoring weights)
- `CO-20 GlobalPriors` (global priors on what tends to perform)
- `CO-21 ChannelConfig` (which channels exist / are connected)

---

### E-03 — patterns engine

**one-line job**  
mines posts into structural templates and tracks how those templates perform over time.

**creates**

- `CO-11 PatternSourcePost` (from internal hits or imported external posts)
- `CO-12 PatternTemplate` (aggregated structural patterns)
- `CO-13 PatternUsage` (when first logging pattern use per variant, or as backfill)

**mutates**

- `CO-11 PatternSourcePost` (add tags, derived metadata)
- `CO-12 PatternTemplate` (update `usage_stats`, status `active/experimental/deprecated`)
- `CO-13 PatternUsage` (attach structural metadata if missing)

> note: **outcome metrics** on `PatternUsage` are primarily updated by the learning engine (E-05).

**reads**

- `CO-01 Brand` (for brand-local vs global patterns)
- `CO-07 BrandMemoryFragment` (to seed patterns from saved examples)
- `CO-11 PatternSourcePost`
- `CO-12 PatternTemplate`
- `CO-13 PatternUsage`
- `CO-17 ContentVariant` (to mine new patterns from successful variants)
- `CO-19 BrandPreferences` (which patterns are currently favored)
- `CO-20 GlobalPriors` (cross-brand pattern stats)

---

### E-04 — content engineering engine (CE)

**one-line job**  
turns a chosen opportunity (or manual topic) into a structured content package with channel-specific, pattern-grounded variants.

**creates**

- `CO-14 ContentPackage`
- `CO-15 CoreArgument`
- `CO-16 ChannelPlan`
- `CO-17 ContentVariant`
- `CO-13 PatternUsage` (initial log row for “pattern X used in variant Y”)

**mutates**

- `CO-14 ContentPackage` (status, channel plan bindings)
- `CO-15 CoreArgument` (regens, edits)
- `CO-16 ChannelPlan` (pattern bindings, target_variants)
- `CO-17 ContentVariant` (regens, user-edited copy; status)

**reads**

- `CO-01 Brand`
- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-05 BrandBrainSnapshot`
- `CO-06 BrandRuntimeContext`
- `CO-07 BrandMemoryFragment` (retrieve on-brand snippets / phrasings)
- `CO-08 GlobalSourceDoc` (for more detailed context behind an opportunity)
- `CO-09 OpportunityCard`
- `CO-10 OpportunityBatch` (for context like “this is today’s board”)
- `CO-11 PatternSourcePost` (examples when rendering pattern-based content)
- `CO-12 PatternTemplate` (to structure channel plans and variants)
- `CO-19 BrandPreferences` (pattern weights, tone biases)
- `CO-21 ChannelConfig` (what channels are valid targets)

---

### E-05 — learning engine

**one-line job**  
takes feedback + performance and turns it into updated per-brand and global preferences that bias all future decisions.

**creates**

- `CO-18 FeedbackEvent` (system-generated events like performance snapshots; user-generated ones are created by frontend but conceptually part of this stream)
- `CO-19 BrandPreferences` (initial defaults for a new brand)
- `CO-20 GlobalPriors`

**mutates**

- `CO-06 BrandRuntimeContext` (update runtime knobs based on preferences)
- `CO-07 BrandMemoryFragment` (promote/demote fragments, re-tag)
- `CO-12 PatternTemplate` (update `usage_stats`, status flags)
- `CO-13 PatternUsage` (attach `outcome` data once performance arrives)
- `CO-19 BrandPreferences` (pattern weights, persona/pillar bias, tone bias, opportunity scoring weights)
- `CO-20 GlobalPriors` (aggregated cross-brand stats)
- optionally: `CO-09 OpportunityCard` scores (recalibration based on historical hit rates)

**reads**

- `CO-01 Brand`
- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-05 BrandBrainSnapshot`
- `CO-06 BrandRuntimeContext`
- `CO-07 BrandMemoryFragment`
- `CO-11 PatternSourcePost`
- `CO-12 PatternTemplate`
- `CO-13 PatternUsage`
- `CO-14 ContentPackage`
- `CO-15 CoreArgument`
- `CO-16 ChannelPlan`
- `CO-17 ContentVariant`
- `CO-18 FeedbackEvent`
- `CO-21 ChannelConfig`
- `CO-22 PublishingJob`

---

## 3. engine run modes (when they run)

this is **behavioral**, not infra-specific. we’re describing *triggers*, not cron syntax.

### E-01 — brand brain engine

- **onboarding runs**
  - when a new `Brand (CO-01)` is created and onboarding is completed:
    - build first `BrandBrainSnapshot (CO-05)`,
    - generate initial `Persona (CO-02)` / `Pillar (CO-03)`,
    - generate initial `BrandRuntimeContext (CO-06)`,
    - seed initial `BrandMemoryFragment`s (CO-07) from imported examples.
- **recalibration runs**
  - explicit user action “recalibrate brand / update strategy”.
  - creates a **new** `BrandBrainSnapshot` (immutability), updates `BrandRuntimeContext`.

no continuous background loop here; this is discrete, user-visible work.

---

### E-02 — opportunities engine

- **scheduled ingestion**
  - periodic (e.g. hourly/daily) scraping / api pulls:
    - create/update `GlobalSourceDoc (CO-08)` for relevant content.
- **batch opportunity generation**
  - after ingestion per brand:
    - generate new `OpportunityCard`s,
    - recompute `score` and `lifecycle_state` for existing ones,
    - assemble/update `OpportunityBatch (CO-10)` for “today/this week”.
- **interactive refresh**
  - user hits “refresh opportunities” → brand-local run that:
    - re-scores cards,
    - possibly pulls in a small extra set of `GlobalSourceDoc`s.

---

### E-03 — patterns engine

- **scheduled mining**
  - periodically scan:
    - `PatternSourcePost (CO-11)` plus high-performing `ContentVariant (CO-17)`,
    - create/merge `PatternTemplate (CO-12)`,
    - update templates’ `usage_stats`.
- **on-demand patterning**
  - user marks a post/variant as “save pattern”:
    - create `PatternSourcePost`,
    - update or create `PatternTemplate`.

---

### E-04 — content engineering engine

- **on-demand package generation**
  - user opens an `OpportunityCard` or creates a manual topic → run:
    - create `ContentPackage` + `CoreArgument` + `ChannelPlan` + draft `ContentVariant`s.
- **regeneration & refinement**
  - user triggers:
    - “regenerate variants”,
    - “try different pattern”,
    - “add channel script”.
  - CE updates the same objects, respecting traceability and statuses.

CE is **interactive-first**: every run maps to a clear user action in the workspace.

---

### E-05 — learning engine

- **streaming feedback capture**
  - `FeedbackEvent` is written immediately when:
    - user rates a variant,
    - user saves as example / marks “never again”,
    - performance webhook fires.
- **batch learning passes**
  - periodic job (e.g. daily) that:
    - aggregates `FeedbackEvent`s + `PatternUsage` outcomes,
    - updates `BrandPreferences` per brand,
    - updates `GlobalPriors` (anonymized),
    - nudges `BrandRuntimeContext` where appropriate.
- **optional online tweaks**
  - light, cheap updates (e.g. increment counts) can happen synchronously inside user flows (e.g. saving an example immediately bumps weights).

---

## 4. end-to-end flow (object + engine lens)

this is the **canonical happy path** for “from nothing to learning loop”.

1. **brand onboarding (E-01)**
   - user creates `Brand (CO-01)` and completes onboarding.
   - brand brain engine:
     - creates initial `Persona (CO-02)` and `Pillar (CO-03)`,
     - creates `BrandBrainSnapshot (CO-05)` (strategy, tone, offers, taboos),
     - materializes `BrandRuntimeContext (CO-06)` (per-channel knobs),
     - seeds `BrandMemoryFragment`s (CO-07) from example posts.

2. **opportunities generation (E-02)**
   - ingestion pipeline pulls external content → `GlobalSourceDoc (CO-08)`.
   - opportunities engine, per brand:
     - reads `BrandBrainSnapshot`, `BrandRuntimeContext`, `BrandPreferences`, `GlobalPriors`,
     - emits `OpportunityCard`s (CO-09) with `persona_id`, `pillar_id`, `score`, `lifecycle_state`,
     - groups them into `OpportunityBatch (CO-10)` for that day/week.

3. **content production (E-04, E-03)**
   - user opens the board, chooses an `OpportunityCard`.
   - CE engine:
     - creates `ContentPackage (CO-14)` tied to that opportunity,
     - creates `CoreArgument (CO-15)` (thesis + supporting points),
     - creates per-channel `ChannelPlan`s (CO-16) using `PatternTemplate`s (CO-12),
     - generates one or more `ContentVariant`s (CO-17) per channel/pattern,
     - logs initial `PatternUsage (CO-13)` rows.
   - user edits, chooses favorites; patterns engine may later mine successful `ContentVariant`s into new or refined `PatternTemplate`s.

4. **publishing**
   - when a `ContentVariant` is approved and scheduled:
     - frontend creates a `PublishingJob (CO-22)` using `ChannelConfig (CO-21)`.
     - publishing worker posts it on the target channel.
   - once successful, variant’s status becomes `published`.

5. **feedback and learning (E-05, E-03)**
   - user feedback (ratings, “save as example”, “never again”) becomes `FeedbackEvent (CO-18)`.
   - performance metrics for `PublishingJob`/`ContentVariant` become either:
     - `FeedbackEvent` of type `performance_snapshot`,
     - or outcome fields on `PatternUsage (CO-13)`.
   - learning engine:
     - aggregates these signals,
     - updates `BrandPreferences (CO-19)` (pattern weights, persona/pillar bias, tone bias, opportunity scoring),
     - updates `GlobalPriors (CO-20)` (cross-brand stat aggregates),
     - may adjust `BrandRuntimeContext (CO-06)` (e.g. tone/risk defaults).

6. **next cycle: smarter opportunities + content**
   - next run of opportunities / CE / patterns reads:
     - the updated `BrandPreferences` and `GlobalPriors`,
     - which subtly changes:
       - which `OpportunityCard`s are scored higher,
       - which patterns are preferred,
       - how aggressive/safe the default tone is.

this loop is the core “closed system” you’re building.

---

## 5. cross-engine invariants & boundaries

to avoid spaghetti, we explicitly state some **rules of the world**.

### 5.1 single-writer rule for strategy / preference stores

- **only E-01 brand brain** creates `BrandBrainSnapshot (CO-05)`.  
  snapshots are **immutable**; changes create new versions.
- **only E-05 learning** creates and mutates:
  - `BrandPreferences (CO-19)`
  - `GlobalPriors (CO-20)`
- **BrandRuntimeContext (CO-06)**:
  - initially created by E-01 (from snapshot + defaults),
  - later **only E-05** can tweak its values programmatically
    (user can still adjust via UI, but those adjustments are persisted through the same object).

no other engine is allowed to invent its own strategy/preference store.

---

### 5.2 traceability constraints

- every `ContentVariant (CO-17)` MUST be traceable to:
  - a `ChannelPlan (CO-16)` →
  - a `ContentPackage (CO-14)` →
  - either an `OpportunityCard (CO-09)` **or** a manual origin flag,
  - and a `BrandBrainSnapshot (CO-05)` id used during generation.
- every `OpportunityCard (CO-09)` MUST:
  - reference its `GlobalSourceDoc`(s) (CO-08) or explicit internal trigger,
  - have `persona_id` + `pillar_id` (or explicit “global” exception).
- every pattern-related decision must be auditable via:
  - `PatternTemplate (CO-12)`,
  - `PatternSourcePost (CO-11)`,
  - `PatternUsage (CO-13)`.

if you can’t walk a path **Brand → Snapshot → Opportunity → Package → Variant → PublishingJob → Feedback**, something is wrong in the design.

---

### 5.3 brand isolation

- no object with brand-local content (`BrandMemoryFragment`, `ContentVariant`, `PatternSourcePost` with brand_id, etc.) can be reused across brands.
- `GlobalPriors (CO-20)` must never store raw brand ids; it only stores aggregated stats.
- engines that operate across brands (patterns, learning) must:
  - use `brand_id` for isolation where needed,
  - only use `GlobalPriors` for cross-brand learning.

this keeps you safe when clients ask for “delete all my data” and also prevents accidental cross-brand style leakage.

---

### 5.4 feedback and learning discipline

- `FeedbackEvent (CO-18)` is **append-only**. no edits, no deletes (except hard-privacy cases).
- learning engine is responsible for:
  - turning feedback → updates in `BrandPreferences` and `GlobalPriors`,
  - never writing ad-hoc preferences elsewhere.
- engines that care about learning (brand brain, opportunities, patterns, CE) must **only** read preferences from:
  - `BrandRuntimeContext (CO-06)` (runtime knobs),
  - `BrandPreferences (CO-19)` (long-term per-brand),
  - `GlobalPriors (CO-20)` (long-term global).

no “shadow preference caches” per engine.

---

### 5.5 energy cost for the user

engine design must respect:

- **opportunities**:
  - don’t flood: default to a small, ranked set per `OpportunityBatch`.
- **CE**:
  - don’t ask for ratings on every variant; focus on the ones that matter (e.g. winners, saved examples).
- **learning**:
  - must primarily consume **implicit** signals (publishing, editing, performance) plus a few high-quality explicit ones.

these are not enforced in schema, but this doc is the place where we encode the intent.

---

### 5.6 evolution path (v1 vs later)

even at overview level, we assume:

- v1 engines can be **simpler** internally (fewer patterns, fewer opportunity types, simpler scoring),
- but the object graph and boundaries above should **not** change lightly.

future work (more channels, more complex learning, richer pattern mining) should happen by:

- adding fields to existing CO-xx,
- adding new CO-xx when absolutely necessary,
- extending engines to use them,

not by introducing “side stores” or bypassing these invariants.

---