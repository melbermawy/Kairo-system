# Kairo – Overall System

Kairo is a multi-engine system for brand content pre-production.

This doc explains how the whole machine works end-to-end:  
what comes in, what gets transformed, which engines touch which objects, and how the system learns over time.  
it is **not** a UI spec, infra spec, or PRD.

---

## 1. Kairo as a system at 10,000 ft

at the highest level, Kairo is a **per-brand pre-production factory**.

for each brand, Kairo:

- **ingests**:
  - brand definition (who we are, who we speak to, what we talk about),
  - external signals (articles, posts, threads, news, competitor content),
  - historical content and performance.
- **transforms** these via engines:
  - **brand brain** – stabilises and structures the brand identity.
  - **opportunities** – maps the outside world to concrete content opportunities.
  - **patterns** – mines and manages patterns, hooks, and structures.
  - **content engineering** – turns opportunities into multi-channel content packages.
  - **learning** – updates preferences and priors from feedback and performance.
- **emits**:
  - a stream of **OpportunityCards** (candidate things to talk about),
  - a stream of **ContentPackages** with **ContentVariants** per channel,
  - updated **BrandPreferences** and **GlobalPriors** that make the next cycle smarter.

engines operate on **canonical objects** (Brand, Persona, Pillar, BrandBrainSnapshot, OpportunityCard, ContentPackage, ContentVariant, FeedbackEvent, AnalyticsEvent, etc.), not free-form text blobs.  

once a brand is configured and channels are connected, the factory is conceptually **always on**:

- ingesting new external documents,
- proposing new opportunities,
- generating packages when asked,
- and periodically folding feedback/performance back into its parameters.

---

## 2. Core loops (factory view)

there are three main loops to understand:

- the **pre-production loop** (factory),
- the **learning loop** (control),
- the **multi-brand loop** (scope).

### 2.1 pre-production loop (factory)

**inputs**

for each brand, the factory starts from:

- brand definition:
  - `Brand`
  - `Persona`
  - `Pillar`
  - `BrandPreferences`
- brand state:
  - `BrandBrainSnapshot`
  - `BrandRuntimeContext`
  - `BrandMemoryFragment`
- external world:
  - `GlobalSourceDoc` (scraped or user-pasted articles, posts, threads, news, etc.)
- patterns and history:
  - `PatternSourcePost` (model accounts, internal hits),
  - existing `ContentPackage` / `ContentVariant` (especially marked “golden”).

**transformations**

- **brand brain engine**
  - keeps `BrandBrainSnapshot` and `BrandRuntimeContext` up to date from:
    - onboarding answers,
    - example posts,
    - inspiration links,
    - “golden” internal content,
    - constraints / do-not-dos.
- **opportunities engine**
  - takes `GlobalSourceDoc` + `BrandBrainSnapshot` + `BrandRuntimeContext` (+ priors) and:
    - scores and filters external signals,
    - produces structured `OpportunityCard`s,
    - groups them into `OpportunitiesBatch` per brand.
- **patterns engine**
  - takes `PatternSourcePost` + “golden” `ContentVariant`s and:
    - extracts reusable `PatternTemplate`s (hooks, structures, narrative shapes),
    - tracks `PatternUsage` and effectiveness,
    - contributes to pattern-related parts of `GlobalPriors`.
- **content engineering engine**
  - takes selected `OpportunityCard`s + `BrandBrainSnapshot` + `BrandRuntimeContext` + `PatternTemplate` + `BrandPreferences` + `ChannelConfig` and:
    - forms a `ContentPackage` with:
      - a `CoreArgument` (central POV),
      - a `ChannelPlan` (which channels, which roles),
      - multiple `ContentVariant`s per channel.

**outputs**

- per brand:
  - `OpportunitiesBatch` containing ranked `OpportunityCard`s,
  - `ContentPackage`s with attached `ContentVariant`s ready for human review, editing, and scheduling.

### 2.2 learning loop (control)

**inputs**

learning is driven by two classes of signals:

- from the UI (human decisions):
  - on `OpportunityCard`:
    - selected vs ignored,
    - edited angle/persona/pillar.
  - on `ContentVariant`:
    - edited vs untouched,
    - approved vs discarded,
    - explicitly marked as “golden example” or “never again”.
- from channels:
  - `AnalyticsEvent` per `ContentVariant`:
    - impressions, clicks, saves, replies, etc. (whatever we decide to support in v1 and beyond).

**transformations**

- **learning engine** consumes these and:
  - turns them into structured `FeedbackEvent`s keyed by:
    - brand, persona, pillar, pattern, tone, channel, etc.
  - updates:
    - `BrandPreferences` (brand-specific knobs: tone, aggressiveness, pattern tastes),
    - `GlobalPriors` (global weights for hooks/patterns/styles, anonymised).

**outputs**

those updated preferences and priors feed back into:

- opportunities engine:
  - changes scoring, diversity, and aggressiveness of `OpportunityCard`s,
- patterns engine:
  - adjusts sampling / availability of `PatternTemplate` per persona/pillar/brand,
- content engineering engine:
  - biases which patterns, tones, and structures it chooses for new `ContentVariant`s.

### 2.3 multi-brand loop (scope)

all of the above runs **per brand**:

- each brand has its own:
  - `BrandBrainSnapshot`
  - `BrandRuntimeContext`
  - `BrandMemoryFragment`
  - `BrandPreferences`
  - `OpportunitiesBatch`
  - `ContentPackage`s / `ContentVariant`s
- engines always run in a context scoped by `brand_id` (and optionally `workspace_id`).

shared, global structures (e.g. `PatternTemplate`, `GlobalPriors`) live on a separate layer:

- they collect abstract information about what patterns/hooks tend to work,
- but **never** store or re-use raw brand copy across brands.

---

## 3. flow A – brand onboarding → first content shipped

this is “first day with Kairo” from the system’s POV, object by object.

### step 1 – brand setup (human)

the user creates and configures:

- `Brand` (top-level entity),
- one or more `Persona`s (who we’re speaking to),
- `Pillar`s (strategy themes / content pillars),
- initial `BrandPreferences` (safe vs bold, tone sliders, do-not-touch topics),
- `ChannelConfig` per connected channel (e.g. LinkedIn page, X account).

### step 2 – brand brain initialisation (brand brain engine)

inputs:

- onboarding questionnaire answers,
- uploaded example posts,
- links to inspiration / model accounts,
- explicit constraints and positioning.

outputs:

- initial `BrandBrainSnapshot`
  - structured representation of positioning, tone, offers, ICPs, examples.
- initial `BrandRuntimeContext`
  - runtime-ready subset: key descriptors and flags the engines need per run.
- initial `BrandMemoryFragment`s
  - small, embedded text fragments (snippets from examples, answers, etc.) for retrieval.

### step 3 – seed sources (human + system)

- human pastes in a few key external items:
  - news, competitor case studies, threads, own blog posts, etc.
- system fetches and cleans these into `GlobalSourceDoc` entries:
  - stripped HTML,
  - metadata (source, date, author, URL),
  - raw text chunks.
- optionally, user can mark some posts as `PatternSourcePost`:
  - from model accounts or their own historic hits.

### step 4 – first opportunity batch (opportunities engine)

inputs:

- `GlobalSourceDoc` (seed set),
- `BrandBrainSnapshot`,
- `BrandRuntimeContext`,
- initial `GlobalPriors` (mostly default at this stage).

outputs:

- several `OpportunityCard`s:
  - each with:
    - a short summary of the trigger,
    - a proposed angle,
    - suggested persona and pillar,
    - “because” links back to source docs.
- one `OpportunitiesBatch` referencing those cards, scoped to the brand.

### step 5 – first content packages (content engineering engine)

- human chooses 1–3 `OpportunityCard`s from the batch.
- CE engine consumes:
  - selected `OpportunityCard`s,
  - `BrandBrainSnapshot`,
  - available `PatternTemplate`s,
  - `BrandPreferences`,
  - `ChannelConfig`.
- outputs:
  - `ContentPackage` for each chosen opportunity:
    - `CoreArgument` (the central point),
    - `ChannelPlan` (e.g. LinkedIn narrative post + X thread).
  - multiple `ContentVariant`s per channel:
    - different hooks,
    - different pattern applications (e.g. teardown vs story),
    - all tied back to the same package.

### step 6 – review and publish (human + system)

- in the UI, the human:
  - edits and polishes `ContentVariant`s,
  - approves a subset for publishing at certain times → `PublishingJob`s,
  - marks a few variants as:
    - “golden example”,
    - or “never again”.
- system:
  - stores those decisions as `FeedbackEvent`s,
  - creates `PublishingJob`s for approved variants.

after posting (via channel integrations), the system creates basic `AnalyticsEvent`s per posted `ContentVariant`.

### step 7 – first learning pass (learning engine)

- learning engine consumes:
  - early `FeedbackEvent`s,
  - whatever `AnalyticsEvent`s are available.
- it makes small initial updates to:
  - `BrandPreferences` (e.g. “this tone worked well for Persona A on LinkedIn”),
  - `GlobalPriors` (e.g. “this hook template seems promising in B2B contexts”).

this completes the first full loop:  
brand defined → brand brain initialised → opportunities → packages → shipped content → early learning.

---

## 4. flow B – weekly run for a brand

this is “normal week” operation once the brand is onboarded.

### step 1 – continuous ingestion (opportunities + brand brain)

- external ingestion:
  - scrapers/APIs + manual additions generate new `GlobalSourceDoc` entries over time.
- brand brain refresh:
  - periodically, brand brain engine:
    - incorporates newly marked “golden” `ContentVariant`s,
    - possibly new `PatternSourcePost`s,
    - refreshes `BrandBrainSnapshot` / `BrandRuntimeContext` as needed.

### step 2 – periodic opportunity generation (opportunities engine)

on a schedule (e.g. daily) per brand:

- opportunities engine:
  - selects a slice of `GlobalSourceDoc` relevant by recency and source type,
  - uses `BrandBrainSnapshot`, `BrandRuntimeContext`, `BrandPreferences`, `GlobalPriors` to:
    - filter irrelevant docs,
    - map relevant docs to candidate angles,
    - diversify across personas and pillars.
- outputs:
  - fresh `OpportunityCard`s,
  - appended to or replacing the latest `OpportunitiesBatch` for the brand.

### step 3 – opportunity selection (human)

per brand:

- human opens the current `OpportunitiesBatch`:
  - skims the cards,
  - marks some as “select for this week”,
  - marks others as “ignore / not relevant”,
  - may tweak persona/pillar/angle on a few.
- these choices are logged as `FeedbackEvent`s:
  - positive signal for selected cards,
  - negative or neutral for ignored ones.

### step 4 – package generation (content engineering engine)

for selected `OpportunityCard`s:

- CE engine:
  - ensures/creates `ContentPackage`s,
  - updates `CoreArgument` and `ChannelPlan` if needed,
  - generates / updates `ContentVariant`s per channel, using:
    - `PatternTemplate` + `PatternUsage`,
    - `BrandBrainSnapshot` / `BrandRuntimeContext`,
    - `BrandPreferences`,
    - `ChannelConfig`.
- result:
  - a queue of `ContentPackage`s with variants ready for human review.

### step 5 – review & scheduling (human + system)

- human:
  - edits and refines variants they care about,
  - approves a subset to become scheduled posts (`PublishingJob`s),
  - marks standout variants as “golden” and bad ones as “never again”.
- system:
  - creates `PublishingJob`s with timing and channel info,
  - logs these decisions as `FeedbackEvent`s on:
    - patterns,
    - tones,
    - personas/pillars,
    - channels.

### step 6 – post-publish metrics (system)

after posts go live:

- channel integrations write `AnalyticsEvent`s per `ContentVariant`:
  - basic metrics appropriate per channel (impressions, clicks, engagement, etc.).
- system may aggregate these up to:
  - the `ContentPackage` level,
  - the `PatternUsage` level (e.g. “pattern X on channel Y for Persona Z had CTR ~k”).

### step 7 – learning pass (learning engine)

on a schedule (e.g. daily/weekly):

- learning engine:
  - consumes accumulated `FeedbackEvent`s and `AnalyticsEvent`s,
  - updates:
    - `BrandPreferences` (brand-specific biases),
    - `GlobalPriors` (pattern/tone priors),
    - optionally summary stats in `PatternUsage`.
- these updates influence:
  - the next run of opportunities scoring,
  - the next pattern selection in CE,
  - the default tones and structures chosen per persona/channel.

this loop repeats; over time, Kairo becomes more “on brand” and less generic without asking the user to explicitly tune prompts every time.

---

## 5. flow C – learning loop in detail

to avoid “we log things but nothing changes”, we make the learning loop explicit.

### 5.1 signals captured

**from UI**

- opportunity-level:
  - selected vs ignored vs dismissed.
  - manual edits to angle / persona / pillar.
- variant-level:
  - edited vs untouched (edit distance / diff heuristics),
  - approved vs discarded,
  - explicitly tagged as:
    - “golden example”,
    - “never again”.

**from channels**

- per `ContentVariant`, `AnalyticsEvent` entries such as:
  - impressions,
  - clicks / CTR,
  - saves / bookmarks,
  - replies / comments (possibly summarised).

### 5.2 feedback abstraction (learning engine)

learning engine:

- normalises raw signals into `FeedbackEvent`s:
  - key dimensions:
    - brand, persona, pillar,
    - pattern template,
    - hook type,
    - channel,
    - tone/style categories.
- updates:
  - `BrandPreferences`:
    - brand-specific weights for patterns, hooks, tones, aggressiveness, etc.
  - `GlobalPriors`:
    - aggregated weights at the pattern/hook level across brands and verticals (anonymised).
  - optionally `PatternUsage` stats:
    - counts, win-rates, etc.

### 5.3 where feedback flows back

- **opportunities engine**
  - uses updated `BrandPreferences` + `GlobalPriors` to:
    - reweight which kinds of opportunities rise to the top,
    - e.g. “this brand’s Persona A responds well to teardown POVs; surface more of those.”
- **patterns engine**
  - uses feedback to:
    - up/down-weight `PatternTemplate`s per persona/pillar/channel,
    - retire templates with consistently bad signals.
- **content engineering engine**
  - uses feedback to:
    - bias pattern and hook sampling,
    - adjust tone and structure parameters per persona/pillar/channel,
    - steer away from previously marked “never again” combinations.

### 5.4 tempo and stability

learning doesn’t have to be real-time:

- updates can run on a scheduled cadence (e.g. nightly/weekly),
- we prefer **stable behaviour with visible step changes** over jittery day-to-day swings.

this keeps the system predictable for users while still improving over time.

---

## 6. engine responsibilities at system level

this section fixes who owns what, using canonical objects.  
if a future change violates this, it’s probably wrong.

### brand brain engine

- **responsibility**  
  maintain a high-fidelity, usable representation of the brand.

- **reads**  
  `Brand`, `Persona`, `Pillar`, `BrandPreferences`, `BrandMemoryFragment`, `PatternSourcePost`, “golden” `ContentVariant`.

- **writes**  
  `BrandBrainSnapshot`, `BrandRuntimeContext`, `BrandMemoryFragment`.

- **never writes**  
  `OpportunityCard`, `ContentPackage`, `ContentVariant`, `GlobalPriors`, `AnalyticsEvent`.

### opportunities engine

- **responsibility**  
  turn the external world + brand brain into ranked `OpportunityCard`s.

- **reads**  
  `GlobalSourceDoc`, `BrandBrainSnapshot`, `BrandRuntimeContext`, `BrandPreferences`, `GlobalPriors`.

- **writes**  
  `OpportunityCard`, `OpportunitiesBatch`, internal scoring logs if needed.

- **never writes**  
  `ContentPackage`, `ContentVariant`, `BrandBrainSnapshot`, `PatternTemplate`, `GlobalSourceDoc`.

### patterns engine

- **responsibility**  
  mine and manage reusable patterns, hooks, and structures.

- **reads**  
  `PatternSourcePost`, “golden” `ContentVariant`, `BrandBrainSnapshot`, `AnalyticsEvent` (for pattern performance).

- **writes**  
  `PatternTemplate`, `PatternUsage`, pattern-related parts of `GlobalPriors`.

- **never writes**  
  `OpportunityCard`, `BrandBrainSnapshot`, `ContentPackage`, `ContentVariant`.

### content engineering engine

- **responsibility**  
  turn opportunities into detailed, multi-channel content packages and variants.

- **reads**  
  `OpportunityCard`, `BrandBrainSnapshot`, `BrandRuntimeContext`, `PatternTemplate`, `PatternUsage`, `BrandPreferences`, `ChannelConfig`.

- **writes**  
  `ContentPackage`, `CoreArgument`, `ChannelPlan`, `ContentVariant`.

- **never writes**  
  `GlobalSourceDoc`, `OpportunityCard`, `GlobalPriors`, `BrandBrainSnapshot`.

### learning engine

- **responsibility**  
  turn human feedback + performance into updated preferences and priors.

- **reads**  
  `FeedbackEvent`, `AnalyticsEvent`, `ContentPackage`, `ContentVariant`, `PatternTemplate`, `PatternUsage`.

- **writes**  
  `BrandPreferences`, `GlobalPriors`, updated `PatternUsage` metrics.

- **never writes**  
  `GlobalSourceDoc`, `OpportunityCard`, `BrandBrainSnapshot`, `ContentPackage`.

---

## 7. multi-brand model and isolation

Kairo is explicitly **multi-brand**; this section encodes isolation rules.

- all brand-specific objects are keyed by `brand_id` (and optionally `workspace_id`):
  - `BrandBrainSnapshot`, `BrandRuntimeContext`, `BrandMemoryFragment`,
  - `BrandPreferences`,
  - `OpportunitiesBatch`, `OpportunityCard`,
  - `ContentPackage`, `ContentVariant`,
  - brand-scoped `FeedbackEvent`s and `AnalyticsEvent`s.
- engines always operate with an explicit brand context:
  - you don’t “run opportunities globally”; you “run opportunities for Brand X”.

global/shared objects:

- `PatternTemplate`, `GlobalPriors`, and any other global stats:
  - can aggregate **abstract** pattern effectiveness across brands,
  - must **not** store raw, brand-specific copy or identifiable data.
- when a brand/client churns:
  - their brand-scoped objects can be deleted cleanly,
  - global objects must not contain anything that lets you reconstruct their content.

this preserves both data governance and guarantees against cross-brand leakage.

---

## 8. out of scope for this doc

this doc intentionally **does not** specify:

- infra details:
  - queues / schedulers,
  - whether engines run as lambdas, celery workers, or anything else,
  - how scraping is implemented or scheduled.
- LLM / agent implementation details:
  - which provider(s),
  - whether we use an agent framework or simple orchestrated calls,
  - exact prompt formats or JSON schemas.
- exact database schemas or API payloads:
  - table DDL,
  - REST/GraphQL shapes,
  - auth flows.

those live in:

- `system/02-engines-overview.md` and `system/03-canonical-objects.md` (object shapes and engine IO),
- `docs/prd/kairo-v1-prd.md` (v1 features and phase plan),
- lower-level design docs and the codebase.

this file’s job is to pin down **how the system behaves as a whole**, so every other decision can be checked against it.