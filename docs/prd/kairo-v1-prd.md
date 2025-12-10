# Kairo v1 – PRD 1: Hero Loop (Today → Package → Learning)

> **Status:** DRAFT  
> **Scope:** Single, end-to-end “hero loop” from unstructured brand input → opportunities → content packages → variants → learning events.

---

## 1. Overview

### 1.1 Problem

most working marketers today live in a constant “feed and fire drill” loop: they scroll social, skim internal docs, react to exec pings, and ship posts opportunistically. they rarely have (a) a single, structured board that turns all that noise into ranked, explainable opportunities, (b) a repeatable way to turn those opportunities into coherent multi‑channel content packages, and (c) any learning loop that makes the system smarter the more they decide.

instead, they juggle:

- fragmented inputs (screenshots, links, slack threads, notion docs, ad hoc “ideas”)
- opaque prioritization (“we should talk about this… why now?”)
- one‑off posts that don’t roll up into a strategy
- zero memory of what they’ve ignored, pinned, or repurposed

this hero loop exists to solve exactly that: take unstructured brand + market context, turn it into an explainable Today board of ranked opportunities, make it trivial to spin a high‑quality content package from any opportunity, and then capture the user’s decisions as learning signals so that tomorrow’s board is better than today’s.

### 1.2 Scope of PRD 1

PRD 1 covers a single, end‑to‑end "hero loop" for a **single human marketer** working on **one brand at a time**, focused on **organic social content** for **LinkedIn and X**. it is **system‑side** scope (django + supabase + deepagents + contracts to the existing Next.js hero UI), not a full product surface in itself.

**UI constraint:** the existing Next.js hero UI is **read-only context** for this PRD. PRD 1 defines the backend contracts (DTOs, endpoints, behavior) that the UI will consume; it does **not** spec new UI screens, flows, or components. where UI behavior is mentioned (e.g. "user clicks X"), it describes the expected backend effect, not the frontend implementation.

concretely, PRD 1 includes:

- ingesting a structured brand brief into a `BrandSnapshot` and related canonical objects (personas, pillars, taboos)
- generating and maintaining a **Today board** of ranked `Opportunity` objects for that brand
- turning a selected `Opportunity` into a `ContentPackage` with one or more `Variant`s across LinkedIn and X
- capturing explicit user decisions on opportunities and variants (`do`, `later`, `no`, `edited`, `published`) as `ExecutionEvent` + `LearningEvent` records
- running a minimal but real **learning loop** that uses those events to adjust future opportunities and package suggestions for that same brand

out of scope for PRD 1: multi‑brand dashboards, calendar views, publishing integrations, or any channels beyond LinkedIn/X. those will sit on top of the same engines and contracts but are not required to validate the hero loop.

### 1.3 Explicit Non-Goals

PRD 1 is intentionally narrow. it will **not** attempt to:

- support paid media (ads on Meta, Google, LinkedIn, etc.)
- support email, SMS, or long‑form blog generation
- manage assets beyond plain text (no image/video generation, no asset library)
- implement a full calendar / scheduling system or direct posting to social APIs
- handle multi‑tenant orgs, complex roles/permissions, or SSO
- provide a generic “agent platform” or arbitrary workflow builder
- solve ingestion from every possible external source (we stub external signals where needed)
- optimize for scale, throughput, or latency beyond “good enough for a single marketer using a few brands”

if a feature requires any of the above to feel "complete", it belongs in a future PRD (e.g. PRD 2–4) built on top of the contracts defined here. PRD 1's job is to prove that the core engines + deepagents orchestration can reliably run the Today → Package → Learning loop for one marketer on one brand.

**implementation rule:** if during implementation you encounter a choice that "sounds like" one of the non-goals above, stop and ask. the scope of PRD 1 is intentionally narrow; over-building here creates debt we'll carry into every future PRD.

### 1.4 References

- System technical docs:
  - `docs/technical/00-principles-and-anti-goals.md`
  - `docs/technical/01-system-architecture.md`
  - `docs/technical/02-canonical-objects.md`
  - `docs/technical/03-engines-overview.md`
  - `docs/technical/04-orchestrator-and-flows.md`
  - `docs/technical/05-llm-and-deepagents-conventions.md`
  - `docs/technical/06-content-engine-deep-agent-spec.md`
- UI repo:
  - Kairo frontend hero slice (Today / Content / Patterns / Strategy / Chat)

### 1.5 Security & Privacy Constraints (PRD 1)

PRD 1 is not a full security hardening spec, but we must set basic guardrails so we do not bake in unsafe patterns.

- data sent to LLMs:
  - limited to brand-facing content and strategy fields (snapshots, pillars, personas, opportunities, packages, variants, external signal text).
  - must **not** include user credentials, access tokens, or any secrets.
- logging:
  - structured logs (section 8) must not include full post bodies or raw external content by default; ids and hashes are preferred.
  - llm prompts/responses may only be logged in redacted form and only in non-prod envs.
- access control:
  - PRD 1 assumes a simple single-tenant environment, but code should not hard-code assumptions that block later introduction of orgs/roles.
- external integrations:
  - any future scrapers or api clients must be built with clear scopes and rate limits; PRD 1 uses only local fixtures for external signals.

future PRDs will deepen this into a proper threat model (multi-tenant isolation, org-level authz, vendor data retention), but PRD 1 must at least respect these boundaries.

---

## 2. Personas & Journeys

### 2.1 Primary Personas

For PRD 1 we explicitly optimize for **one primary persona** and acknowledge a secondary one.

#### 2.1.1 Primary – Senior B2B Content Lead (“Maya”)

- **Role & context**
  - Senior B2B content / brand lead at a 20–200 person SaaS company.
  - Owns **organic content strategy** for 1–3 brands (mainly LinkedIn, sometimes X).
  - Works with 1–3 junior marketers, freelancers, and the founder/C-suite.

- **Responsibilities**
  - Turn vague business goals (“we need more SQLs”, “we’re invisible to RevOps leaders”) into content themes.
  - Keep a **steady, high-quality posting cadence** on LinkedIn and X.
  - Coordinate with sales / CS for case studies, customer stories, and proof points.
  - Report on “what’s working” to leadership in a way they actually trust.

- **Channels in-scope for PRD 1**
  - Company LinkedIn page.
  - Founder / exec personal LinkedIn.
  - Company X account (secondary for most, primary for some).

- **Pain points today**
  - Lives across **too many inputs**:
    - LinkedIn feed, X feed, Slack screenshots, Looms, Gong calls, internal docs.
  - No **single “Today” view** of what’s worth turning into content *this week*.
  - When she *does* create content:
    - It’s either ad-hoc “post something today” or a static Notion calendar that quickly goes stale.
    - Turning a good idea into **multi-channel variants** is tedious and error-prone.
  - There is **no learning loop**:
    - They “feel” what works (“this case study went nuts”) but can’t systemically feed that back.
    - Every quarter feels like reinventing the wheel.

- **What success looks like inside Kairo (for PRD 1)**
  - She logs into Kairo and:
    - Sees **a Today board** that makes immediate sense: “here are 6–10 concrete ideas, here’s *why* they matter right now, here’s who they’re for”.
    - Can **turn an opportunity into a multi-channel package** in 1–2 clicks and get sane, on-brand variants.
    - Can **triage** ideas (do / later / no) and feel the system learns from those decisions.
  - After a week:
    - Today feels less chaotic; the board reflects **her brand, her pillars, and her decisions**.
    - She can articulate a story to stakeholders:
      - “Here are the angles we doubled down on.”
      - “Here’s what we’re intentionally ignoring.”

#### 2.1.2 Secondary – Solo Marketing Generalist (“Leo”)

- **Role & context**
  - First marketing hire at a seed / Series A startup.
  - Does **everything**: events, paid, product launches, organic, CRM.
- **Relevance to PRD 1**
  - Uses Kairo more sporadically (a few deep sessions per week).
  - For PRD 1 we do **not** optimize flows for his full workload.
  - We *do* ensure:
    - The hero loop works for a single brand.
    - He can come back after 3–4 days and still understand “what Kairo thinks is next”.

> **Constraint:** PRD 1 is explicitly *not* for agencies managing 10+ brands, nor for pure performance marketers. That’s future PRDs.

---

### 2.2 Core Journeys in PRD 1

Each journey is written from the persona’s POV first, then mapped to system flows (F1/F2/F3 from `04-orchestrator-and-flows.md`).

#### 2.2.1 Journey A – First Time Setup & First Today Board

**Narrative (Maya):**

1. Maya signs into Kairo and chooses **“Create a new brand”**.
2. She pastes:
   - A short brand description.
   - Links to website, LinkedIn, and (optionally) X.
   - A few “voice examples” (e.g. URLs or pasted posts).
3. Kairo shows her a **Brand Snapshot preview**:
   - Positioning summary.
   - 3–5 suggested pillars.
   - 2–3 personas.
   - “Never do” guardrails.
4. She **accepts or lightly edits** this snapshot (text fields only in PRD 1).
5. She clicks **“Generate Today Board”**.
6. Within ~30–60s, she sees:
   - A Today view with ~6–10 opportunities.
   - Each opportunity shows:
     - Angle, who it’s for, why-now, score, channel suggestion.
   - A small hero strip at the top summarizing:
     - “This week: focus on [pillar], [channel], [persona].”
7. She understands **what the board is telling her** within 5–10 seconds:
   - “Okay, it wants us to lean into [pillar] for [persona] on LinkedIn this week.”

**System Flow Mapping:**

- **F0 (pre-hero)** – Brand ingestion (out of scope for deep agents here; simple LLM calls / deterministic transforms).

> **implementation note:** for PRD 1, brand ingestion is a **manual or semi-manual** process. the user provides structured input via a form or pastes raw text; backend normalizes it into a `BrandSnapshot`. we do **not** build automated website scraping, social profile ingestion, or document parsing in this PRD.

- **F1 – Today Board generation**:
  - Orchestrator calls `graph_hero_generate_opportunities` with:
    - BrandSnapshot + recent external signals (stubbed in PRD 1).
  - Graph outputs:
    - A typed list of Opportunities stored in DB.
  - Today API:
    - Reads opportunities + computes the hero strip.

> **Success criteria (user POV):** Maya reads the board and can clearly answer: “What does Kairo think we should talk about this week, and why?”

#### 2.2.2 Journey B – Build Package from an Opportunity

**Narrative (Maya):**

1. On the Today board, she spots an opportunity:
   - “Confessional post about our migration failures for RevOps leaders.”
   - Score 86, tagged with her core persona and pillar.
2. She clicks **“Open as Package”**.
3. She lands in the **Package workspace**:
   - Left: the opportunity explanation (“why this, why now, who it’s for”).
   - Center: channels tabs (LinkedIn, X).
   - Right: brand voice + suggested patterns.
4. She clicks **“Generate package”**.
5. Kairo:
   - Proposes a **package thesis** (“the argument we’re making”).
   - Proposes **1–3 variants per channel** using a chosen pattern.
6. She skims:
   - She edits a word or two in one LinkedIn variant.
   - She discards one X variant as off-tone.
7. She accepts the package as **“Ready”** (status change only in PRD 1).

**System Flow Mapping:**

- **F2 – Package creation**:
  - Orchestrator calls:
    - `graph_hero_package_from_opportunity` to generate package thesis + channel plan.
    - `graph_hero_variants_from_package` to generate initial variants per channel.
  - Django services:
    - Persist ContentPackage + Variant objects.
  - UI:
    - Allows lightweight edits (text fields).
    - Writes an **ExecutionEvent** when Maya accepts the package as ready.

> **Success criteria (user POV):** Maya feels: “This took me from idea → multi-channel, on-brand drafts in one focus session, without starting from a blank page.”

#### 2.2.3 Journey C – Daily Decision & Learning Loop

**Narrative (Maya):**

1. A few days later, Maya comes back to Kairo.
2. Today now shows:
   - Some opportunities she previously ignored.
   - New opportunities informed by fresh signals.
   - Visual hints about which areas are **over-saturated** vs **neglected**.
3. She triages:
   - Pins 1–2 high-score opportunities.
   - Snoozes a few (“not this week”).
   - Marks 1–2 as **“Not relevant”**.
4. She also marks one previously generated package as:
   - “Published” (simple status change).
5. Behind the scenes, Kairo records **LearningEvents** based on:
   - What she pinned / snoozed / rejected.
   - What she published.
6. The next time she refreshes Today:
   - The board subtly shifts:
     - Fewer ideas in ignored areas.
     - More in areas she consistently pins and publishes.
   - The hero strip reflects updated focus.

**System Flow Mapping:**

- **F3 – Learning update**:
  - Django writes:
    - ExecutionEvents for decisions on opportunities and packages.
    - LearningEvents derived from those executions.
  - Orchestrator calls:
    - `graph_hero_learning_from_decisions` periodically or on demand.
  - `graph_hero_generate_opportunities` uses updated brand/pillar weights for future boards.

> **Success criteria (user POV):** Maya feels like the system is **paying attention** to her decisions. Ignoring something has a visible consequence over time, and the board feels more “hers” after a week of use.

## 3. Data Model & Object Flow (This PRD Only)

This section constrains **which parts** of the global canonical model are in scope for PRD 1 and how they flow.

### 3.1 Objects in Scope

for PRD 1 we intentionally use a **minimal subset** of the global canonical model. anything not listed here is **out of scope** for this hero loop.

#### 3.1.1 Brand & BrandSnapshot

- **Brand**
  - persistent identity for a client brand.
  - key fields in scope:
    - `id` (uuid)
    - `name`
    - `primary_domain`
    - `primary_channels` (enum list: `linkedin`, `x`)
  - source of truth: `brands` table (django + supabase).

- **BrandSnapshot**
  - structured representation of the brand used by engines.
  - key fields in scope:
    - `brand_id`
    - `positioning_summary` (llm-generated text)
    - `tone_descriptors` (list of short tags)
    - `taboos` (list of "never do" strings)
    - `pillars` (embedded `ContentPillar` refs)
    - `personas` (embedded `Persona` refs)
  - source of truth: `brand_snapshots` table, refreshed on ingestion / major edits.
  - generation: combination of deterministic normalization + llm transforms.

#### 3.1.2 Persona

- represents a **target audience slice** for a brand.
- key fields in scope:
  - `id`
  - `brand_id`
  - `name` (e.g. "revops director")
  - `role_title`
  - `summary` (llm-generated)
  - `goals` (short bullet strings)
  - `pains` (short bullet strings)
- source of truth: `personas` table, but in PRD 1 we only **read** from it (created during brand ingestion).

#### 3.1.3 ContentPillar

- represents **themes** the brand should talk about.
- key fields in scope:
  - `id`
  - `brand_id`
  - `name` (e.g. "attribution reality")
  - `description`
  - `weight` (numeric weight used by learning engine)
- source of truth: `content_pillars` table.
- `weight` is adjusted over time by learning.

#### 3.1.4 PatternTemplate

- describes reusable **narrative patterns** used by the content engine.
- key fields in scope:
  - `id`
  - `name` (e.g. "confessional story → lesson")
  - `beats` (ordered list of short labels)
  - `channels` (supported channels)
  - `status` (active / experimental / deprecated)
- source of truth: `pattern_templates` table.
- in PRD 1, patterns are **read-only** fixtures.

#### 3.1.5 Opportunity

- the atomic object on the Today board; a ranked, explainable idea.
- key fields in scope:
  - `id`
  - `brand_id`
  - `title` (short label)
  - `angle` (llm-generated explanation / why-now)
  - `score` (0–100)
  - `persona_id` (optional)
  - `pillar_id` (optional)
  - `primary_channel` (`linkedin` or `x`)
  - `source_type` (enum: `trend`, `evergreen`, `competitive`, `campaign`, `internal_signal`)
  - `source_refs` (list of urls / ids)
  - `status` (enum: `candidate`, `curated`, `archived`)
- source of truth: `opportunities` table.
- generation: llm graph proposes candidates; deterministic layer curates/normalizes.

#### 3.1.6 ContentPackage

- a **bundle** of content work anchored on a single opportunity.
- key fields in scope:
  - `id`
  - `brand_id`
  - `opportunity_id`
  - `status` (enum: `draft`, `ready`, `published`)
  - `thesis` (llm-generated argument summary)
  - `channels` (list of channels this package covers)
  - `created_by_user_id`
  - timestamps (`created_at`, `updated_at`, `published_at` nullable)
- source of truth: `content_packages` table.

#### 3.1.7 Variant

- a **single-channel realization** of a package.
- key fields in scope:
  - `id`
  - `package_id`
  - `channel` (`linkedin`, `x`)
  - `pattern_template_id` (nullable)
  - `body` (llm-generated text, editable by user)
  - `status` (enum: `draft`, `edited`, `approved`, `published`)
  - `ai_generated` (boolean)
  - `last_edited_by_user_id` (nullable)
- source of truth: `variants` table.

#### 3.1.8 ExecutionEvent

- raw log of **what the user did** in the hero loop.
- key fields in scope:
  - `id`
  - `brand_id`
  - `actor_user_id`
  - `subject_type` (enum: `opportunity`, `content_package`, `variant`)
  - `subject_id`
  - `decision_type` (enum: `pin`, `snooze`, `reject`, `open_as_package`, `mark_ready`, `mark_published`, `edit_variant`)
  - `metadata` (jsonb; e.g. previous_status, channel)
  - `created_at`
- source of truth: `execution_events` table.
- fully deterministic, no llm involvement.

#### 3.1.9 LearningEvent

- processed, **aggregated signal** derived from execution events.
- key fields in scope:
  - `id`
  - `brand_id`
  - `scope_type` (enum: `pillar`, `persona`, `pattern`, `channel`)
  - `scope_id` (e.g. `pillar_id`)
  - `signal_type` (enum: `positive_engagement`, `negative_engagement`, `ignored`, `overused`)
  - `weight_delta` (numeric)
  - `source_execution_ids` (array of ids)
  - `created_at`
- source of truth: `learning_events` table.
- written by learning engine jobs, consumed by opportunities / content engines.

#### 3.1.10 LearningSummary (in-memory DTO)

- **not a persisted object**; this is an in-memory DTO computed on-demand by `learning_service`.
- represents an **aggregated view** over recent `LearningEvent`s for a brand.
- key fields:
  - `brand_id`
  - `pillar_weights: dict[pillar_id, float]`
  - `persona_emphasis: dict[persona_id, float]`
  - `pattern_scores: dict[pattern_id, float]`
  - `channel_mix: dict[channel, float]`
  - `as_of: datetime`
- consumed by:
  - `graph_hero_generate_opportunities` (to bias opportunity ranking)
  - `graph_hero_package_from_opportunity` (to bias pattern selection)
- source of truth: computed by `learning_service.summarize_learning_for_brand(brand_id)`.

> out-of-scope canonical objects for PRD 1 include: publishing integrations, calendar slots, multi-tenant orgs, user roles/permissions, and any asset/media objects.

### 3.2 End-to-End Flow

this PRD cares about a **single spine**:

`BrandSnapshot` → `Opportunity` → `ContentPackage` → `Variant` → `ExecutionEvent` → `LearningEvent` → back into future `Opportunity` + `ContentPackage` runs.

we describe the flow in 6 hops.

#### 3.2.1 BrandBrief / BrandSnapshot → Opportunity Candidates

1. a brand is created / updated via the brand ingestion flow (out of scope for this PRD's implementation details, but assumed to exist).

> **implementation note (PRD 1):** brand ingestion in this PRD is a simple, mostly-manual flow. backend receives structured form data or pasted text; a thin LLM call normalizes it into a `BrandSnapshot`. no automated scraping, no multi-source ingest.

2. ingestion produces or updates a `BrandSnapshot` that contains:
   - positioning, tone, taboos
   - personas and pillars (with initial weights)
3. when a Today board run is triggered (F1), the orchestrator calls the opportunities engine with:
   - `BrandSnapshot`
   - recent `LearningEvent`s for that brand
   - external signal stubs (see section 6)
4. the opportunities engine + `graph_hero_generate_opportunities` produce a transient list of **opportunity candidates** (in-memory objects, not yet persisted):
   - `OpportunityDraft` (internal type)
   - includes proposed angle, score, persona/pillar refs, channel, why-now.

**LLM vs deterministic:**

- llm:
  - synthesizes angles, why-now text, preliminary scores, and suggested persona/pillar.
- deterministic:
  - clamps scores to [0,100]
  - ensures persona/pillar ids exist for the brand
  - drops any obviously malformed candidates.

#### 3.2.2 Opportunity Candidates → Curated Today Board Opportunities

1. the opportunities engine ranks and filters the `OpportunityDraft` list using:
   - pillar weights from `ContentPillar`
   - `LearningEvent` aggregates
   - basic diversity constraints (per pillar / per channel caps)
2. the top N (e.g. 6–12) are normalized into full `Opportunity` records and persisted:
   - `status = curated`
   - existing curated opportunities may be updated or archived.
3. the Today API reads the `opportunities` table for the brand and computes:
   - the ordered list of Opportunities
   - a lightweight **Today summary** used by the hero strip:
     - dominant pillar, dominant persona, channel mix, high-score count.

**source of truth:**

- `opportunities` table for persisted opportunities.
- Today summary is **computed on read**, not stored.

**LLM vs deterministic:**

- no further llm calls happen here; this hop is deterministic ranking + persistence.

#### 3.2.3 Today Board Opportunity → ContentPackage

1. user selects an `Opportunity` from the Today board and clicks **open as package**.
2. the content engine receives:
   - `Opportunity`
   - brand’s `BrandSnapshot`
   - available `PatternTemplate`s for the opportunity’s channel(s).
3. orchestrator triggers `graph_hero_package_from_opportunity`, which produces:
   - a proposed `thesis` (argument summary)
   - a proposed channel plan (which channels to support and why).
4. django service persists a new `ContentPackage` row:
   - `status = draft`
   - `channels = [...]`
   - `thesis` as returned by the graph.
5. UI navigates to the package workspace, reading the newly created `ContentPackage`.

**LLM vs deterministic:**

- llm:
  - generates the `thesis` text and justification for channel selection.
- deterministic:
  - ensures only channels in-scope (`linkedin`, `x`) are kept.
  - enforces required fields and status defaults.

#### 3.2.4 ContentPackage → Variants

1. from the package workspace, user triggers **generate variants** (explicit button or implicit on first load).
2. orchestrator calls `graph_hero_variants_from_package` with:
   - `ContentPackage`
   - brand `BrandSnapshot`
   - selected `PatternTemplate`s per channel.
3. the graph returns, per channel:
   - 1–3 proposed variant texts
   - suggested pattern template ids.
4. django service persists `Variant` rows for each proposed variant:
   - `ai_generated = true`
   - `status = draft`.
5. UI displays these variants; user may edit text (transitioning to `status = edited`).

**LLM vs deterministic:**

- llm:
  - generates `body` text and pattern choice.
- deterministic:
  - validates pattern ids exist
  - enforces max variants per channel
  - truncates overly long content if needed (per channel constraints).

#### 3.2.5 User Decisions → ExecutionEvents → LearningEvents

1. when user interacts with opportunities / packages / variants (pin, snooze, reject, mark ready, mark published, edit, etc.), the UI calls django endpoints that:
   - mutate the primary object (e.g. package status → `ready`)
   - append an `ExecutionEvent` capturing the decision.
2. periodically (or on certain triggers), the learning engine consumes recent `ExecutionEvent`s and:
   - groups them by pillar/persona/pattern/channel
   - emits `LearningEvent`s that encode weight deltas and signal types.
3. subsequent F1 and F2 runs read `LearningEvent`s for that brand and:
   - adjust pillar weights
   - adjust pattern preferences
   - bias scoring and ranking for future opportunities and packages.

**LLM vs deterministic:**

- **no** llm calls are required to create `ExecutionEvent`s.
- `LearningEvent` computation can be deterministic (rule-based) in PRD 1, with the option to introduce llm-assisted analysis later.

### 3.3 Contracts per Hop

for each hop we define the **contract**: inputs, outputs, validation owner, and failure behavior. these contracts are what django services and deepagents graphs must respect for PRD 1.

#### 3.3.1 BrandSnapshot → OpportunityCandidates (F1 input contract)

- **Input:**
  - `brand_snapshot: BrandSnapshot`
  - `learning_summary: LearningSummary` (aggregated view over recent `LearningEvent`s; implementation detail of the learning engine)
    - note: `LearningSummary` is an **in-memory DTO**, not a persisted object. see 3.1.10 for its shape.
  - `external_signals: ExternalSignalBundle` (stubbed in PRD 1; see section 6)
- **Output:**
  - `candidates: OpportunityDraft[]`, where each draft has at least:
    - `title: str`
    - `angle: str`
    - `score: float` (may be rough, will be clamped later)
    - `persona_id: Optional[UUID]`
    - `pillar_id: Optional[UUID]`
    - `primary_channel: Literal["linkedin", "x"]`
    - `source_type`
- **Validation owner:**
  - opportunities engine validates that:
    - all `persona_id` / `pillar_id` belong to the brand
    - scores are finite numbers
    - text fields are non-empty and within sane limits.
- **Failure modes & fallbacks:**
  - **graph failure:** if `graph_hero_generate_opportunities` fails entirely, engine:
    - logs structured error
    - returns an empty list; Today API will surface a "no generated opportunities" state.
  - **partial bad drafts:** invalid drafts are dropped; if fewer than a minimum threshold (e.g. 3) remain, engine may:
    - fall back to a small set of evergreen templates anchored on pillars.

#### 3.3.2 OpportunityCandidates → Today Board Opportunities (F1 output contract)

- **Input:**
  - `candidates: OpportunityDraft[]`
  - `brand_pillars: ContentPillar[]`
  - `learning_summary: LearningSummary`
- **Output:**
  - persisted `Opportunity` records with:
    - `status = curated`
    - normalized `score` in [0,100]
    - validated `persona_id` / `pillar_id`
  - `TodayBoardDTO` returned to UI:
    - `opportunities: Opportunity[]` (already sorted)
    - `summary: TodaySummary` (dominant pillar/persona/channel, counts).
- **Validation owner:**
  - opportunities engine owns ranking, clamping, and archiving rules.
  - UI must **not** re-rank beyond local UX adjustments (e.g. pinning on the client must still be persisted as server-side state).
- **Failure modes & fallbacks:**
  - **no curated opportunities:** UI shows an intentional empty state (“no opportunities generated for today”) instead of breaking.
  - **stale board:** if generating a new board fails, we may continue to show the last successful board with a banner.

#### 3.3.3 Today Board Opportunity → ContentPackage (F2 input contract)

- **Input:**
  - `opportunity_id: UUID`
  - resolved `Opportunity`
  - `brand_snapshot: BrandSnapshot`
- **Output:**
  - created `ContentPackage` record:
    - linked to `opportunity_id`
    - with `status = draft`
    - with non-empty `thesis`
    - with `channels` limited to `["linkedin", "x"]` subset.
- **Validation owner:**
  - content engine validates that opportunity belongs to the brand and is not archived.
  - django service enforces one active package per (brand, opportunity) pair (idempotent create).
- **Failure modes & fallbacks:**
  - **graph failure:** if `graph_hero_package_from_opportunity` fails, service:
    - logs error
    - optionally creates an empty `ContentPackage` scaffold with a clear status flag so UI can show “package could not be auto-generated”.

#### 3.3.4 ContentPackage → Variants (F2.2 input contract)

- **Input:**
  - `package_id: UUID`
  - resolved `ContentPackage`
  - `brand_snapshot: BrandSnapshot`
  - allowed `PatternTemplate[]` for each channel.
- **Output:**
  - 1–3 `Variant` records per channel in `package.channels`:
    - each with `ai_generated = true`
    - each with `status = draft`.
- **Validation owner:**
  - content engine ensures:
    - no more than max variants per channel (configurable; default 3).
    - pattern ids returned exist and are `status = active`.
  - django service enforces that variants belong to the package and brand.
- **Failure modes & fallbacks:**
  - **channel-level failure:** if generation fails for one channel, create a placeholder variant with a clear error message.
  - **total failure:** if no variants can be generated, leave the package in `draft` with a failure marker; UI communicates that no drafts were created.

#### 3.3.5 User Decisions → ExecutionEvents → LearningEvents (F3 contracts)

- **Input:**
  - from UI to backend:
    - `decision_request` with:
      - `actor_user_id`
      - `subject_type` / `subject_id`
      - `decision_type`
      - optional metadata (e.g. `new_status`, `channel`).
- **Output:**
  - immediate:
    - updated primary object (e.g. package `status` changed)
    - appended `ExecutionEvent` row.
  - downstream (learning job):
    - one or more `LearningEvent` rows with scoped weight deltas.
- **Validation owner:**
  - django services validate:
    - subject exists and belongs to brand
    - decision is allowed for current status (e.g. cannot publish a package that is not `ready`).
  - learning engine validates that it only emits events with valid scope ids (pillar/persona/pattern/channel).
- **Failure modes & fallbacks:**
  - **execution write failure:**
    - primary mutation and `ExecutionEvent` must be in the same transaction; if either fails, neither is committed.
  - **learning job failure:**
    - failures do **not** block user actions; they are logged and retried.
    - lack of fresh `LearningEvent`s simply means the next board is less personalized, not broken.

#### 3.3.6 TodayBoardDTO (response shape)

`TodayBoardDTO` is the **response object** returned by `today_service.get_today_board(brand_id)` and consumed by the UI. it is an **in-memory DTO**, not persisted.

- **Fields:**
  - `brand_id: UUID`
  - `opportunities: list[Opportunity]` (sorted by score descending, with pins first)
  - `summary: TodaySummary`
    - `dominant_pillar_id: UUID | None`
    - `dominant_persona_id: UUID | None`
    - `channel_mix: dict[channel, int]` (count per channel)
    - `high_score_count: int`
  - `external_signals_used: bool`
  - `generated_at: datetime`
  - `run_type: Literal["good", "partial", "bad"]` (see 7.3)

- **Invariants:**
  - `opportunities` list is never null; may be empty if no curated opportunities exist.
  - `summary` is always present; fields may be null/empty if data is sparse.

these contracts are the backbone for how django, deepagents, and the UI cooperate in PRD 1. future PRDs can extend the model (more fields, more scopes) but should avoid breaking these shapes.

### 3.4 Schema & Migration Strategy (PRD 1)

for PRD 1, the postgres schema (managed via django migrations and surfaced through supabase) must match the canonical objects in `docs/technical/02-canonical-objects.md` and the contracts in 3.1–3.3. this section defines how we create, change, and version that schema.

#### 3.4.1 source of truth

- the **canonical source of truth** for tables and fields is:
  - `02-canonical-objects.md` for conceptual models.
  - the initial django models + migrations for concrete implementation.
- any new table/column in PRD 1 must be justified by a corresponding object/field in 3.1, or explicitly called out as an implementation detail.
- **in-memory DTOs** (e.g. `LearningSummary`, `TodayBoardDTO`) are **not** persisted; they are computed on-demand by service methods and passed to graphs or returned to the UI. they do not have corresponding tables.
- enum-like fields (status, source_type, channel, scope_type, signal_type, decision_type) must be defined once and reused in:
  - django model choices / constraints.
  - deepagents schemas / DTOs.
  - UI typings.

#### 3.4.2 initial migration set (v1)

PRD 1 requires an initial migration set that creates at least:

- core brand tables:
  - `brands`
  - `brand_snapshots`
  - `personas`
  - `content_pillars`
  - `pattern_templates`
- hero-loop tables:
  - `opportunities`
  - `content_packages`
  - `variants`
  - `execution_events`
  - `learning_events`

acceptance criteria for the initial migration:

- a fresh database, after running migrations and seeding fixtures (pattern templates, example brands), can:
  - run the hero loop end-to-end for at least one seed brand.
  - pass all contract tests for the DTOs in 3.3.

#### 3.4.3 migration rules (forward compatibility)

for PRD 1 we enforce conservative migration rules:

- no destructive changes to tables in 3.1 (drop column, rename column, change type) without:
  - an explicit data migration,
  - a compatibility shim for deepagents / UI,
  - and a clear note in the PRD changelog.
- additive changes only (new nullable columns, new tables) are preferred.
- enum evolution:
  - adding new enum values is allowed if all consumers treat unknown values defensively.
  - removing or renaming enum values is **not** allowed in PRD 1.

all schema changes must be:

- expressed as django migrations,
- run in staging before prod,
- and validated by rerunning the offline eval harness (7.1) on at least the reference brands.

#### 3.4.4 seeding & fixtures

- `pattern_templates` and example `BrandSnapshot`s used in evals must be seeded via migrations or management commands, not ad-hoc sql.
- we maintain versioned seed data for:
  - pattern templates (e.g. `v1_confessional_story`, `v1_myth_buster`).
  - reference brands used in 7.1.
- breaking changes to seed structures require bumping a seed version and updating eval fixtures accordingly.

#### 3.4.5 versioning & evolution of schema

- schemas exposed to deepagents and the UI are treated as **versioned contracts**.
- any breaking change (field removal, type change, semantic change) requires:
  - introducing a new DTO version (e.g. `OpportunityDTOv2`) and keeping v1 readable for at least one deploy cycle.
  - updating eval harnesses to explicitly test both old and new shapes until migration is complete.
- future PRDs (2+) may introduce new objects and tables, but PRD 1 tables and enums should be treated as long-lived unless this PRD is updated.

---


## 4. System Responsibilities

this section makes the split explicit: what lives in django (services + persistence), what lives in deepagents (graphs + tools), and what the existing Next.js hero UI is and is not allowed to do. if we keep these boundaries tight in PRD 1, later PRDs can add surfaces and engines without turning the system into an un-debuggable agent soup.

### 4.1 Django Services (Backend)

for PRD 1, django is the **single point of entry** for the hero loop. the UI never talks to deepagents directly and deepagents never write to the database; django services own persistence, validation, and transactions.

**4.1.1 service modules (conceptual)**

we group functionality into a small set of service modules. exact django app names can differ, but the responsibilities should match:

- `brands_service`
  - read brand + snapshot:
    - `get_brand(brand_id)`
    - `get_brand_snapshot(brand_id)`
  - write brand snapshot (for future PRDs; in PRD 1 we assume ingestion produced it).
- `today_service`
  - read today board:
    - `get_today_board(brand_id)` → `TodayBoardDTO`
  - trigger board regeneration:
    - `regenerate_today_board(brand_id, trigger_source)`  
      (calls opportunities engine + deepagents, see section 5).
- `opportunities_service`
  - read opportunities for a brand:
    - `list_opportunities(brand_id, filters?)`
  - resolve single opportunity:
    - `get_opportunity(opportunity_id)`
- `content_packages_service`
  - create / fetch packages:
    - `create_package_from_opportunity(brand_id, opportunity_id)`
    - `get_package(package_id)`
    - `list_packages(brand_id, filters?)`
  - status transitions:
    - `mark_package_ready(package_id)`
    - `mark_package_published(package_id)`
- `variants_service`
  - generate variants:
    - `generate_variants_for_package(package_id)`  
      (calls deepagents graph, persists variants).
  - read / update variants:
    - `list_variants(package_id)`
    - `update_variant_body(variant_id, new_body)` (also sets `status = edited`).
- `decisions_service`
  - write execution events + primary mutations in one transaction:
    - `record_opportunity_decision(...)`
    - `record_package_decision(...)`
    - `record_variant_decision(...)`
  - **implementation rule:** all user-facing actions that change canonical state (pin, snooze, mark ready, publish, edit) **must** go through `decisions_service`. direct mutations to objects without emitting an `ExecutionEvent` are not allowed.
- `learning_service`
  - offline / job-facing API:
    - `summarize_learning_for_brand(brand_id)` → `LearningSummary`
    - `ingest_execution_events(events[])` → emits `LearningEvent`s (can be batch job).

these modules can be plain python service classes or functions; the important part is the separation of responsibilities and clear contracts.

**4.1.2 http api surface (hero loop)**

for PRD 1 we keep the HTTP surface small and explicitly typed. paths are indicative, not final:

- **today board**
  - `GET /api/brands/{brand_id}/today`
    - returns `TodayBoardDTO` (summary + ordered opportunities).
  - `POST /api/brands/{brand_id}/today/regenerate`
    - triggers F1 board generation; returns updated `TodayBoardDTO` or a job handle if async.
- **opportunities → packages**
  - `POST /api/brands/{brand_id}/opportunities/{opportunity_id}/packages`
    - idempotent create of a `ContentPackage` for this opportunity.
  - `GET /api/packages/{package_id}`
    - returns package details + minimal related data (opportunity, brand snapshot refs).
- **packages → variants**
  - `POST /api/packages/{package_id}/variants/generate`
    - triggers `graph_hero_variants_from_package`, persists variants, returns `VariantDTO[]`.
  - `GET /api/packages/{package_id}/variants`
    - list variants for a package.
  - `PATCH /api/variants/{variant_id}`
    - update body text; sets `status = edited` and `last_edited_by_user_id`.
- **decision endpoints**
  - `POST /api/opportunities/{opportunity_id}/decisions`
  - `POST /api/packages/{package_id}/decisions`
  - `POST /api/variants/{variant_id}/decisions`  
    all three:
    - mutate primary object (status / pinned flags / etc.)
    - append `ExecutionEvent`
    - respond with updated object.

**4.1.3 idempotency & transactions**

- any endpoint that **creates** packages or triggers graphs must be **idempotent** on `(brand_id, opportunity_id)` or `(package_id, channel)` where appropriate:
  - repeated `POST /opportunities/{id}/packages` returns the existing package.
  - repeated `POST /packages/{id}/variants/generate`:
    - **PRD 1 behavior:** reject with a clear error (`variants already generated`) if variants already exist for this package. regeneration is out of scope for PRD 1.
- writes to primary objects and `ExecutionEvent`s must be in a **single transaction** so we never observe a mutated object without a corresponding execution log (or vice versa).

**4.1.4 auth & multi-tenant assumptions (v1)**

for PRD 1:

- we assume a simple auth layer (single tenant, one or few users) where:
  - `actor_user_id` is trusted and injected by middleware.
  - every request is scoped to a single `brand_id`.
- we do **not** implement:
  - orgs, roles/permissions, or SSO.
- but we must design APIs so that:
  - adding `org_id` and enforcing per-org isolation later does **not** change shapes or semantics of hero-loop endpoints.

**4.1.5 what django must *not* do**

- never call LLMs directly from controllers; all LLM usage goes through:
  - engine service methods that in turn call deepagents graphs.
- never let UI bypass service modules to talk directly to ORM models.
- never encode business rules in serializers or random utils; those live in the service layer where we can test them.

### 4.2 DeepAgents Graphs

deepagents is the **only** place where multi-step llm workflows live. for PRD 1 we keep the graph surface small and align it directly with the flows defined in section 5.

**4.2.1 ownership & placement**

- graphs live in a dedicated python module, e.g. `kairo.agents.hero`.
- each graph has:
  - a **single owner engine** (opportunities, content, learning).
  - a **single public entry function** that django calls, e.g. `run_graph_hero_generate_opportunities(...)`.
- graphs do **not**:
  - talk directly to the database.
  - perform http calls to the UI or external clients.
- all side effects (reads/writes) happen via:
  - engine-provided tools/adapters that are thin wrappers around django services or http clients.
- **implementation rule:** every tool exposed to a graph must call a django service method, not raw ORM or direct SQL. this ensures all business rules (validation, transactions, logging) are enforced consistently.

**4.2.2 invocation model (sync vs async)**

for PRD 1:

- `graph_hero_generate_opportunities`:
  - may be called **sync** from `regenerate_today_board` if latency is acceptable (< ~30–45s).
  - we design the API so it can later be run as an async job (returning a job id), but we do not implement full job orchestration yet.
- `graph_hero_package_from_opportunity` and `graph_hero_variants_from_package`:
  - are called **sync** from the respective service methods.
  - must return structured outputs within a reasonable timeout.
- `graph_hero_learning_from_decisions`:
  - is expected to run in **batch** (cron / worker) rather than on the hot path.
  - django will invoke it via a job runner (celery / rq / supabase functions) but for PRD 1 we can stub this as a management command.

**4.2.3 contracts & invariants**

each graph must respect:

- clear **input DTOs**, matching section 3.3 contracts.
- clear **output DTOs**, with:
  - no raw llm strings where a structured field is expected.
  - explicit `errors` / `warnings` fields if degraded behavior occurs.
- **invariants** per graph, e.g.:
  - `graph_hero_generate_opportunities`:
    - never returns more than `MAX_OPPORTUNITIES_PER_RUN`.
    - scores are floats; downstream clamps them.
  - `graph_hero_package_from_opportunity`:
    - always returns a non-empty `thesis` if successful.
  - `graph_hero_variants_from_package`:
    - returns at least one variant per requested channel or an explicit per-channel error reason.

any invariant violation is treated as a **graph failure** and surfaced to django as a structured error, not as a silent partial success.

**4.2.4 logging & traceability**

- graphs must log:
  - a `run_id`
  - `brand_id`
  - `graph_name`
  - high-level status (`success`, `partial_success`, `failure`).
- llm prompts and responses:
  - are logged in a redacted form when possible (no customer PII, no secrets).
  - are never exposed directly to the UI.

**4.2.5 what graphs must *not* do**

- no long-running, open-ended loops; max steps per graph must be bounded and configurable.
- no nested graphs that create cyclic dependencies (e.g. content engine calling learning engine graphs which call content again).
- no speculative parallel calls to different models “just to see” what happens; model selection is a responsibility of the llm client layer, not graph authors.

### 4.3 UI Responsibilities

for PRD 1 the Next.js hero UI is a **pure client** of the django + deepagents system. it can manage view state and presentation, but cannot reinterpret the business logic.

**4.3.1 allowed responsibilities**

the UI may:

- manage **presentation-only** concerns:
  - local filters (e.g. “show only pinned opportunities”) based on fields already in the DTO.
  - responsive layout, sections, and visual hierarchy.
- manage **optimistic UI** for obvious, low-risk transitions:
  - toggling pin / snooze state.
  - marking a package as ready / published.
  - editing variant body text in place.
- manage **session-local state**:
  - which package is currently open.
  - which channel tab is selected.
  - whether the Kairo chat drawer is open.

**4.3.2 required contracts with backend**

the UI must:

- treat backend data as **source of truth**:
  - no creating “fake” opportunities or packages on the client.
  - no re-ranking Today opportunities in a way that diverges from server ordering without persisting the change.
- always call the appropriate API when:
  - an object’s canonical status changes.
  - the user performs a decision (pin/snooze/reject/publish/edit).
- handle degraded states explicitly:
  - if Today board generation fails, show an intentional message (“we couldn’t generate new opportunities, here’s your last board”) rather than hiding the problem.
  - if variant generation fails, show placeholders with retry affordances.

**4.3.3 things the UI must *not* do**

- must not:
  - call LLMs directly.
  - talk to deepagents or any agent runtime directly.
  - implement its own scoring/ranking logic beyond trivial display-only sorts that are clearly marked as such.
- must not:
  - persist any long-term business state in local storage; only ephemeral UX state is allowed.
- must not:
  - silently swallow backend errors. every failed hero-loop action should result in a visible, user-understandable error state (or at minimum a toast).

the mental model: if a future engineer reads the UI code, they should see *what* is displayed and *which* endpoints are called, but all core business rules should be discoverable in the backend and agent code, not in React components.

### 4.5 Internal Admin & Debug Surfaces

PRD 1 requires minimal but real internal surfaces to inspect and debug the hero loop without raw SQL.

#### 4.5.1 required admin capabilities (v1)

we must be able to, at minimum:

- list brands and open a brand detail view that shows:
  - latest `BrandSnapshot` (read-only),
  - current pillars and personas,
  - basic hero-loop status (last today run timestamp, last run_type).
- list opportunities for a brand and inspect:
  - score, persona, pillar, source_type, source_refs,
  - creation time and last update time.
- list content packages and variants for a brand and inspect:
  - package thesis, status, channels,
  - variant text, status, pattern template, channel.

these can be delivered via:

- django admin customizations, or
- a simple internal-only React view behind auth.

#### 4.5.2 replay & diagnostics hooks

for debugging hero-loop behavior we also need:

- a way to trigger a "manual" Today board regeneration for a brand with a visible `run_id`.
- a way to see, for a given `run_id`:
  - input summary (BrandSnapshot hash, learning summary snapshot, external signals summary),
  - output summary (candidate_count, curated_count, run_type, error_code if any).

PRD 1 does **not** require a full UI for diffing runs, but it must be possible for an engineer to:

- answer "what did the system think for brand X on date Y?",
- and correlate that with logs and eval reports.

### 4.6 Manual Content Flows

PRD 1 is graph-driven, but we must support manual escape hatches so users can keep their workflow inside Kairo while still feeding the learning loop.

#### 4.6.1 manual opportunities

- the UI must allow creation of a `manual` `Opportunity` for cases like:
  - time-bound events (launches, conferences, announcements),
  - internal initiatives that won't show up in external signals.
- manual opportunities:
  - have `source_type = internal_signal` and a flag `is_manual = true`.
  - are eligible for packages and variants like any other opportunity.

#### 4.6.2 manual packages and variants

- users may create or heavily rewrite packages/variants, bypassing LLM generation if they choose.
- requirements:
  - manually created packages/variants still live in the same tables.
  - all key decisions (mark ready/published, edits) still emit `ExecutionEvent`s and downstream `LearningEvent`s.
- PRD 1 does **not** require first-class UX for composing from scratch, but it must not block users from:
  - zeroing out an LLM draft and pasting their own copy,
  - or creating a minimal package shell and filling it manually.
- **UX scope clarification:** PRD 1 backend must support manual creation and editing via API; whether the UI exposes "create from scratch" buttons is **not** specified here. the UI may choose to only show "generate" flows initially, as long as edit flows allow full overwrite.

#### 4.6.3 impact on learning

- learning rules must treat manual and LLM-assisted content consistently at the **decision** level:
  - publishing a manual package still counts as a strong positive signal for its pillar/persona/channel.
  - repeated rejection of LLM variants vs acceptance of manual variants can later be used to tune prompts/patterns, but PRD 1 only needs to log the data (via ExecutionEvents).

### 4.4 Out-of-Scope Responsibilities

to keep PRD 1 tractable and debuggable, the following responsibilities are explicitly **out of scope** and should not sneak into implementations:

- **multi-tenant & org model**
  - orgs, workspaces, role-based access control, SSO.
  - sharing brands or packages across orgs.
- **publishing & scheduling**
  - posting to LinkedIn/X APIs.
  - scheduling calendars, content calendars, or reminders.
  - webhook integrations with external tools (hubspot, salesforce, etc.).
- **full-text ingestion at scale**
  - automated scraping of large content corpora.
  - long-running crawl jobs or large document indexing.
- **advanced analytics**
  - dashboards of performance over time.
  - cohort analysis, attribution modeling, or BI exports.
- **generic agent platform features**
  - arbitrary user-defined workflows or “build your own agent” UI.
  - plug-in marketplaces or third-party tools.

if a design or implementation choice starts to depend on any of the above, it belongs in a **future PRD** (e.g. PRD 2–4) and should be called out explicitly rather than partially implemented inside PRD 1.

---

## 5. DeepAgents Graphs in Scope

For PRD 1, we expect at least the following graphs (see 04-orchestrator-and-flows + 06-content-engine-deep-agent-spec):

- `graph_hero_generate_opportunities`
- `graph_hero_package_from_opportunity`
- `graph_hero_variants_from_package`
- `graph_hero_learning_from_decisions`

Each subsection below is a **template** to be filled in later.

### 5.1 graph_hero_generate_opportunities

**Purpose**

generate a ranked set of opportunity candidates for a single brand’s Today board from:

- brand strategy state (`BrandSnapshot`)
- recent learning signals (`LearningSummary`)
- external signals (`ExternalSignalBundle`, stubbed for PRD 1)

this graph is responsible for: “given what we know about this brand and market, what are 10–20 plausible things they could talk about this week?”

**Inputs**

- `brand_snapshot: BrandSnapshot`
- `learning_summary: LearningSummary`
  - aggregated view over recent `LearningEvent`s (pillar weights, persona emphasis, etc.)
- `external_signals: ExternalSignalBundle`
  - PRD 1: static fixtures / canned objects; see section 6.

**Outputs**

- `candidates: OpportunityDraft[]` (before deterministic ranking/persistence)
  - 10–20 drafts per run.
  - each draft must include:
    - `title: str`
    - `angle: str` (why-now explanation)
    - `score: float` (0–100, may be rough)
    - `persona_id: Optional[UUID]`
    - `pillar_id: Optional[UUID]`
    - `primary_channel: Literal["linkedin", "x"]`
    - `source_type: OpportunitySourceType`
    - `source_refs: list[str]` (urls or opaque ids)

**High-level behavior**

1. read brand strategy, learning summary, and external signals.
2. identify 3–5 “focus themes” (pillar × persona × channel cells) worth exploring.
3. for each theme, propose 3–5 concrete opportunities.
4. enrich each opportunity with:
   - why-now angle
   - suggested channel
   - coarse score.
5. return candidate list to the opportunities engine for deterministic ranking/filtering.

**Node list (draft)**

- `N1_load_context`
  - tool: `get_brand_context_tool`
  - merges `BrandSnapshot`, `LearningSummary`, and `ExternalSignalBundle` into a single structured context object.
- `N2_select_focus_cells`
  - type: reasoning node (LLM)
  - decides 3–5 pillar × persona × channel “cells” to emphasize.
  - output: structured list:
    - `[{ pillar_id, persona_id?, channel, rationale }]`
- `N3_propose_opportunities_for_cells`
  - type: map node (LLM)
  - for each cell, proposes 3–5 raw opportunity ideas:
    - `title`, `angle`, `rough_score`, `source_type`, `source_refs`.
- `N4_normalize_and_attach_ids`
  - type: deterministic node
  - resolves `pillar_id` / `persona_id` from names when needed.
  - clamps scores to [0,100], drops malformed ideas.
- `N5_prune_and_deduplicate`
  - type: deterministic node
  - removes near-duplicates and overly generic ideas.
  - enforces max per pillar, per persona, per channel.
- `N6_output_candidates`
  - type: sink node
  - returns `OpportunityDraft[]` to the opportunities engine.

**Tools**

- `get_brand_context_tool`
  - reads `BrandSnapshot`, `ContentPillar`, and `Persona` data for the brand.
- `get_learning_summary_tool`
  - returns high-level weights (e.g. “pillar X overweighted, pillar Y underused”).
- `get_external_signals_tool`
  - PRD 1: returns stubbed objects representing trends, competitive posts, etc.
- `opportunity_normalizer`
  - deterministic helper for scoring and shape validation.

**Invariants**

- between 6 and 24 candidates **per run**:
  - if fewer are produced, graph must mark `partial_success` and set a warning.
- all `pillar_id` / `persona_id` values either:
  - reference valid objects for the brand, or
  - are left `null` and clearly marked in the candidate.
- `primary_channel` is always `linkedin` or `x`.
- `score` values are numeric; `NaN`/`inf` not allowed.

**Failure behavior**

- if any tool call fails:
  - graph returns `failure` with `error_code` and an empty candidate list.
- if LLM nodes produce unusable output (no valid candidates):
  - graph returns `partial_success` with:
    - a small set of evergreen, pillar-based backup candidates, or
    - an explicit `no_candidates_reason`.
- graph must **never** raise raw exceptions to django; all failures are encoded in the result object.

### 5.2 graph_hero_package_from_opportunity

**Purpose**

turn a single curated `Opportunity` into a structured `ContentPackage` draft:

- pick / confirm the core argument (“thesis”).
- choose which channels (linkedin, x) to cover for this opportunity.
- explain the choice in structured fields for downstream use.

**Inputs**

- `opportunity: Opportunity`
- `brand_snapshot: BrandSnapshot`
- `learning_summary: LearningSummary` (optional; used to bias toward underused pillars/patterns)

**Outputs**

- `package_proposal` object with:
  - `thesis: str`
  - `channels: list[Literal["linkedin", "x"]]`
  - `channel_rationales: dict[channel, str]`
  - optional `suggested_pattern_ids_by_channel: dict[channel, list[PatternTemplateId]]`

**High-level behavior**

1. read opportunity and brand voice.
2. restate the opportunity as a “package thesis”:
   - the core argument we want to make.
3. decide which channels should carry this package:
   - minimally: the opportunity’s `primary_channel`.
   - optionally: a second channel if justified.
4. map likely patterns per channel (for the content engine to use later).

**Node list (draft)**

- `N1_load_opportunity_context`
  - collates opportunity, brand snapshot, and any relevant learning hints.
- `N2_refine_thesis`
  - type: LLM
  - rewrites `opportunity.angle` into a crisp thesis:
    - 1–3 sentences, on-brand, non-fluffy.
- `N3_select_channels`
  - type: LLM
  - chooses channels with rationale:
    - must always include `opportunity.primary_channel`.
    - may add one more channel if it adds real value.
- `N4_suggest_patterns`
  - type: LLM (optional per channel)
  - suggests 1–2 `PatternTemplate` ids per channel, or none if not confident.
- `N5_output_package_proposal`
  - type: sink node
  - returns normalized `package_proposal`.

**Tools**

- `get_brand_voice_tool`
  - exposes tone descriptors, taboos, and example snippets.
- `get_available_patterns_tool`
  - returns active `PatternTemplate`s per channel.
- `pattern_resolver`
  - deterministic helper mapping LLM-chosen labels to real `PatternTemplate` ids.

**Invariants**

- `thesis` is non-empty and respects brand taboos.
- `channels` is a non-empty subset of `[linkedin, x]`.
- if any `suggested_pattern_ids_by_channel` are present, they must:
  - exist in `pattern_templates`.
  - have `status = active`.

**Failure behavior**

- if thesis generation fails:
  - graph returns `failure` and **no** package_proposal.
- if only pattern selection fails:
  - graph returns `partial_success` with `thesis` and `channels`, leaving pattern suggestions empty.
- django must treat `failure` as:
  - “package generation unavailable” and either:
    - create an empty `ContentPackage` scaffold, or
    - surface a clear error to the UI (see section 3.3.3).

### 5.3 graph_hero_variants_from_package

**Purpose**

given a `ContentPackage` and brand context, generate a small bundle of on-brand text variants per channel:

- 1–3 variants per channel in `package.channels`.
- each variant mapped to a `PatternTemplate` when possible.

**Inputs**

- `package: ContentPackage`
- `opportunity: Opportunity` (for context)
- `brand_snapshot: BrandSnapshot`
- `pattern_templates_by_channel: dict[channel, list[PatternTemplate]]`

**Outputs**

- `variant_bundle`:
  - `variants: list[VariantDraft]` where each draft has:
    - `channel`
    - `body`
    - `pattern_template_id` (optional)
    - `variant_label` (internal label like “bold”, “safe”, “short”)
  - `errors_by_channel: dict[channel, str]` (optional)

**High-level behavior**

1. for each target channel:
   - choose 1–2 relevant patterns.
   - generate 1–3 text variants that:
     - express the package thesis.
     - respect channel constraints and brand voice.
2. ensure diversity within a channel:
   - different hooks, lengths, or angles.
3. return a flat list of `VariantDraft`s and any per-channel errors.

**Node list (draft)**

- `N1_load_package_context`
  - combines package, opportunity, brand voice, and patterns into a single context object.
- `N2_plan_variants_per_channel`
  - type: LLM
  - for each channel, decides:
    - how many variants to attempt (1–3).
    - which patterns (if any) to lean on.
- `N3_generate_variants`
  - type: map node (LLM)
  - for each planned variant:
    - generates `body` text and internal `variant_label`.
- `N4_normalize_and_validate_variants`
  - type: deterministic node
  - enforces:
    - max variants per channel.
    - channel-specific length/format hints (soft limits, not strict enforcement in PRD 1).
  - attaches `pattern_template_id` when LLM chooses a known pattern.
- `N5_output_variant_bundle`
  - type: sink node
  - returns `VariantDraft[]` + optional `errors_by_channel`.

**Tools**

- `get_brand_voice_tool`
- `get_channel_guidelines_tool`
  - returns rough constraints for linkedin vs x (length, tone, structure).
- `pattern_resolver`
  - maps LLM pattern references to real ids.

**Invariants**

- at least **one** variant per channel if the channel is reachable and no hard failure occurred.
- total variants per channel ≤ configured `MAX_VARIANTS_PER_CHANNEL` (default 3).
- no variant body is empty or whitespace-only.
- generated text must not violate explicit taboos (e.g. banned phrases).

**Failure behavior**

- per-channel:
  - if generation fails for a given channel, record `errors_by_channel[channel]` and generate **no** variants for that channel.
- global:
  - if all channels fail, graph returns `failure` with empty `variants`.
- django must handle:
  - partial success by creating variants where available and surfacing errors to the UI as placeholders (“no drafts for X, try again later”).

### 5.4 graph_hero_learning_from_decisions

**Purpose**

consume raw `ExecutionEvent`s and emit aggregated `LearningEvent`s that adjust brand-level weights for pillars, personas, patterns, and channels.

in PRD 1 this is deliberately **simple and mostly deterministic**; the goal is to prove the loop, not to implement a perfect bandit.

**Inputs**

- `brand_id: UUID`
- `execution_events: list[ExecutionEvent]`
  - usually a window over “since last run” or the last N days.

**Outputs**

- `learning_events: list[LearningEvent]`
- optional `learning_summary_delta`:
  - pre-aggregated view suitable for caching.

**High-level behavior**

1. bucket execution events by:
   - pillar, persona, pattern, channel.
2. compute simple signals, e.g.:
   - pins / “open_as_package” → positive.
   - snoozes / rejects → negative.
   - edited variants → nuanced (could be slight negative for pattern, neutral for pillar).
   - published packages → strong positive.
3. translate those into `weight_delta` per scope:
   - small, bounded adjustments (e.g. ±0.1…±0.5).
4. emit `LearningEvent`s that encode:
   - scope_type, scope_id, signal_type, `weight_delta`.

**Node list (draft)**

- `N1_load_recent_executions`
  - fetches executions for brand and time window (or receives them as input).
- `N2_bucket_by_scope`
  - deterministic grouping:
    - builds counters per (pillar, persona, pattern, channel).
- `N3_compute_signals`
  - deterministic rules mapping:
    - counts → signal types + raw scores.
- `N4_bound_and_normalize_deltas`
  - enforces:
    - max absolute delta per run.
    - optional decay for very old events (if window > 1 day).
- `N5_emit_learning_events`
  - writes `LearningEvent` objects (via tool) and produces `learning_summary_delta`.

**Tools**

- `get_brand_topology_tool`
  - returns mapping of opportunities/packages/variants to pillars, personas, patterns, channels.
- `learning_event_writer_tool`
  - persists `LearningEvent` rows transactionally.

**Invariants**

- no `weight_delta` exceeds configured bounds (e.g. |delta| ≤ 0.5 per run per scope).
- every `LearningEvent.scope_id` refers to a real object in its scope table.
- learning graph **never** mutates primary tables directly (only writes `LearningEvent`s).

**Failure behavior**

- if fetching executions fails:
  - graph returns `failure` with no writes.
- if writing learning events fails:
  - graph must either:
    - write none (all-or-nothing), or
    - clearly indicate which subset was written; PRD 1 can choose all-or-nothing for simplicity.
- failures must **not** block user-facing flows:
  - hero loop continues with stale learning until the next successful run.

### 5.5 LLM Model & Cost Policy (PRD 1)

for PRD 1 we fix a simple, explicit model and cost policy so quality and spend are predictable and evals are reproducible.

#### 5.5.1 model assignment per graph

- `graph_hero_generate_opportunities`:
  - uses a high-context reasoning model (primary model M1).
  - expected to be the most expensive graph; we cap total llm calls per run.
- `graph_hero_package_from_opportunity`:
  - uses M1 or a cheaper model M2 if quality is acceptable; this trade-off must be tested in the eval harness.
- `graph_hero_variants_from_package`:
  - may use M2 (cheaper, more style-focused) with stricter validation.
- `graph_hero_learning_from_decisions`:
  - is deterministic in PRD 1 (no llm calls).

exact model ids (e.g. provider/model-name) are configured centrally in the llm client layer and **not** hard-coded in graphs.

#### 5.5.2 call budgets & timeouts

for each graph run we set hard limits:

- max llm calls per run:
  - opportunities: e.g. ≤ 6 calls.
  - package: ≤ 3 calls.
  - variants: ≤ 6 calls total across channels.
- max wall-clock timeout per graph (see 7.2.3):
  - if exceeded, the graph returns `failure` or `partial_success` with clear error codes.

these limits are enforced in the llm client layer and surfaced in metrics (`llm_call_count`, `latency_ms`).

#### 5.5.3 prompt & graph versioning

- each graph has a versioned config (e.g. `hero_generate_opportunities_v1`) that pins:
  - prompt templates,
  - tool list,
  - model selection.
- offline evals (7.1) run against a **specific graph config version**; when we change prompts/models, we:
  - bump the version,
  - rerun evals,
  - and only promote the new version to prod if metrics stay within target bands.

#### 5.5.4 cost observability

- the llm client layer must record, per graph run:
  - estimated token usage,
  - estimated cost (in provider units),
  - model id(s) used.
- PRD 1 does not require a full billing dashboard, but it must be possible to:
  - compute approximate cost per brand per week for hero loop runs,
  - and identify regressions when prompt or graph changes increase token use materially.

---

## 6. External Inputs (Stubs for PRD 1)

for PRD 1, we treat “external signals” as a **conceptual contract** and a **local stub**. the goal is to:

- force us to normalize noisy outside world inputs into a single `ExternalSignalBundle` shape.
- make it trivial to later swap in real integrations (trends apis, scraping, etc.).
- keep the hero loop debuggable by clearly separating “brand/learning state” from “market noise”.

### 6.1 Sources

long term, external inputs will come from multiple systems. in PRD 1, we acknowledge the full set conceptually but only implement a small, stubbed subset.

**conceptual source classes**

- **S1 – macro & search trends**
  - e.g. google trends, keyword volume apis, topic-suggestion apis.
  - tells us: “people are increasingly searching for X in this space.”
- **S2 – web content / news**
  - generic web search over blogs, news, industry reports.
  - tells us: “new talking points and narratives are emerging around X.”
- **S3 – competitive social content**
  - scraped / polled posts from competitor and peer brands on linkedin/x.
  - tells us: “competitors are talking (or not talking) about X with Y engagement.”
- **S4 – social listening / community**
  - scraped comments, q&amp;a threads, forums, slack communities.
  - tells us: “real people are asking questions or venting about X.”
- **S5 – internal signals (out-of-scope for PRD 1)**
  - crm notes, sales call highlights, support tickets, internal docs.
  - tells us: “what customers and prospects tell us directly.”

**PRD 1 actual sources**

for this PRD, we constrain ourselves to:

- **S2 (web content / news)** – represented as a few **hand-curated snippets** per brand that look like blog / news headlines + short summaries.
- **S3 (competitive social)** – represented as a few **hand-curated competitor posts** per brand (linkedin/x style).
- optional: a small number of **S1-like “trend headlines”** encoded as static strings.

all of these are stored as **fixtures** and exposed via a single `get_external_signals_tool` rather than real network calls.

### 6.2 Expected Shapes

all external inputs must be normalized into an `ExternalSignalBundle` consumed by the opportunities engine and `graph_hero_generate_opportunities`.

```python
class ExternalSignalBundle(TypedDict):
    brand_id: UUID
    as_of: datetime
    trends: list[TrendSignal]              # S1-style
    web_mentions: list[WebMentionSignal]   # S2-style
    competitor_posts: list[CompetitivePostSignal]  # S3-style
    social_moments: list[SocialMomentSignal]       # S4-style (stubbed/empty in PRD 1)

class TrendSignal(TypedDict):
    id: str
    topic: str                 # e.g. "revops efficiency"
    normalized_score: float    # 0–1 relative intensity
    direction: Literal["up", "flat", "down"]
    region: str | None
    channel_hint: Literal["linkedin", "x", "mixed"] | None

class WebMentionSignal(TypedDict):
    id: str
    title: str                 # blog/news headline
    source: str                # domain or publisher
    url: str | None
    excerpt: str               # 1–3 sentence summary
    recency_days: int
    pillar_hint_id: UUID | None
    persona_hint_id: UUID | None

class CompetitivePostSignal(TypedDict):
    id: str
    brand_name: str
    platform: Literal["linkedin", "x"]
    url: str | None
    post_excerpt: str          # body snippet (truncated)
    recency_days: int
    approx_engagement: int     # raw proxy count (likes + comments + reposts)
    pillar_hint_id: UUID | None
    persona_hint_id: UUID | None

class SocialMomentSignal(TypedDict):
    id: str
    source: str                # e.g. "reddit", "slack", "forum"
    url: str | None
    question_or_rant: str
    recency_days: int
    pillar_hint_id: UUID | None
    persona_hint_id: UUID | None
```

**design notes**

- all signals are **brand-scoped at read time**:
  - bundler is responsible for filtering to the relevant brand and attaching `pillar_hint_id` / `persona_hint_id` where possible.
- hints are **optional**:
  - graphs must be robust to missing hints and allowed to infer pillar/persona from text when needed.
- `recency_days` and `normalized_score` let us:
  - decay very old signals.
  - bias toward “spiking” topics without hard-coding per-source thresholds.

### 6.3 Stub vs Real in PRD 1

for PRD 1, we explicitly **do not** implement real external apis, crawlers, or schedulers. instead, we ship a deterministic stub layer with the same shape as the eventual real system.

**6.3.1 implementation stance**

- `ExternalSignalBundle` is constructed by a **pure python bundler** (e.g. `external_signals_service.get_bundle_for_brand(brand_id)`).
- in PRD 1, that bundler:
  - reads from in-repo fixtures (json/yaml) or seeded supabase tables.
  - applies simple filtering by `brand_id`.
  - fills `as_of` with `now()` and computes `recency_days` from seeded timestamps.
- `get_external_signals_tool` is a thin wrapper that:
  - takes `brand_id`.
  - calls the bundler.
  - returns an `ExternalSignalBundle` or an empty bundle on failure.

> **implementation rule:** PRD 1 must **not** include any code that makes real HTTP requests to external trend/search/social APIs. all external signal data is fixture-based. any "real integration" code belongs in a future PRD and should not be scaffolded or partially implemented here.

**6.3.2 what is “real” vs stubbed**

- **real-ish (but local)**
  - we use real-looking text snippets:
    - blog headlines + excerpts tailored to the example brands.
    - competitor post snippets tailored to the example brands.
  - we seed realistic `recency_days` and `approx_engagement` values.
- **stubbed / not implemented**
  - no live requests to google trends or search apis.
  - no scraping of real linkedin/x or competitor sites.
  - no dynamic refresh schedule; bundles only change when fixtures change.

**6.3.3 constraints**

- graphs must not assume:
  - that `trends`, `web_mentions`, or `competitor_posts` are non-empty.
  - that urls are valid or clickable.
- the rest of the system must be able to run the hero loop with:
  - a **fully empty** `ExternalSignalBundle` (pure strategy + learning-based).

### 6.4 Orchestrator Behavior When Inputs Are Missing

we treat external signals as **nice-to-have amplifiers**, not hard dependencies. the orchestrator and graphs must degrade gracefully when inputs are sparse or missing.

**6.4.1 types of “missing”**

- **no bundle at all**
  - `get_external_signals_tool` fails (i/o error, fixture missing, etc.).
- **empty bundle**
  - bundler returns an `ExternalSignalBundle` where all lists are empty.
- **sparse bundle**
  - one signal class present (e.g. competitor posts) but others empty.

**6.4.2 required behavior**

- if `get_external_signals_tool` fails:
  - `graph_hero_generate_opportunities` sets:
    - `external_signals_used = false`
    - `external_signals_error = "...reason..."`
  - continues generation using only `BrandSnapshot` + `LearningSummary`.
- if bundle is empty:
  - graph treats this as “no external pressure”:
    - leans more heavily on:
      - underweighted pillars from `LearningSummary`.
      - evergreen opportunities per pillar/persona.
- if bundle is sparse:
  - graph can still:
    - upweight themes that appear in the available signals.
    - but must not overfit to a single noisy point (e.g. one viral competitor post).

**6.4.3 surfacing degraded modes**

PRD 1 does **not** require full UX surfacing of every degraded mode, but we do require:

- opportunities engine:
  - logs when a Today run was computed with missing/empty external signals.
- today_service:
  - can optionally include a boolean flag in `TodayBoardDTO`:
    - `external_signals_used: bool`.
- future PRDs can:
  - adjust the UI to show subtle “strategy-only board” hints when `external_signals_used = false`.

**6.4.4 future extension hooks**

while we stub for now, we design the contract to support later:

- per-source freshness policies:
  - e.g. “trends must be &lt; 3 days old, competitor posts &lt; 14 days.”
- per-source weighting:
  - e.g. `w_trends`, `w_competitors`, `w_social` tuned per brand.
- asynchronous backfill:
  - beyond PRD 1, a background job can refresh `ExternalSignalBundle` on a cadence independent of hero loop runs.

for PRD 1, the only acceptance criteria are:

- hero loop runs correctly with:
  - rich fixtures,
  - empty bundles,
  - and hard failures in `get_external_signals_tool`.
- opportunity generation behavior remains understandable and debuggable in all three cases.

## 7. Quality & Evaluation

this section defines how we judge whether the hero loop is “good enough” to ship in v1, both **offline** (controlled eval runs) and **online** (hard checks at runtime). the goal is not academic perfection; the goal is a loop that is reliable, debuggable, and clearly better than “blank page + generic chatgpt” for our personas.

### 7.1 Offline Evaluation

offline evaluation answers: “if we feed the system a known brand snapshot and (stubbed) external signals, does it produce opportunities, packages, and variants that a reasonable expert would accept or lightly edit?”

#### 7.1.1 eval dataset

for PRD 1 we maintain a small but opinionated eval set:

- **brands**
  - at least **5 reference brands**, each with:
    - a realistic `BrandSnapshot` (positioning, pillars, personas, taboos).
    - 5–10 `ExternalSignalBundle` fixtures covering different “weeks” (as-of dates).
  - brands should cover different patterns:
    - b2b saas (revops / data product).
    - b2b devtools.
    - b2c lifestyle / hospitality.
    - opinionated solo founder brand.
    - conservative corporate b2b.

- **golden annotations**
  - for each brand-week pair we store:
    - **golden opportunities**:
      - 6–10 short descriptions of “things worth talking about this week”.
      - rough scores (high / medium / low).
      - annotated persona / pillar / channel.
    - **golden packages** (for 1–2 key opportunities per brand-week):
      - a thesis statement.
      - channels we’d actually use.
      - 1–2 bullet points on why this is a good package.
    - **golden variants** (for at least one package per brand-week):
      - 1–2 linkedin posts.
      - 1–2 x posts.
      - with notes on what makes them acceptable.

annotations can be produced by us + a small panel of “expert” reviewers; they do not have to be consensus-perfect, only coherent and self-consistent.

#### 7.1.2 offline eval harness

we implement a simple harness (python script / notebook) that:

1. iterates over the eval dataset.
2. for each brand-week:
   - runs F1 (`graph_hero_generate_opportunities` + deterministic ranking) to produce a Today board.
   - picks the top N opportunities (e.g. 3) and runs F2 (package + variants).
3. dumps outputs to a structured json + markdown report per run.

> **PRD 1 scope:** the eval harness is a **manual, developer-run** tool. it is **not** integrated into CI and does **not** run automatically on every PR. we run it periodically (e.g. before releases or after major prompt/graph changes) and review results by hand. automated CI-integrated evals are a future PRD concern.

we then evaluate each level on a mix of **automatic metrics** and **human ratings**.

#### 7.1.3 opportunity-level metrics

for each brand-week:

- **coverage vs golden**
  - how many golden opportunities have a **semantic match** in the generated board?
    - match definition: embedding similarity above threshold or manual label (“covers same idea”).
  - target (PRD 1): ≥ **60%** of golden items have a recognizable counterpart.

- **alignment**
  - fraction of opportunities where:
    - persona / pillar assignment is consistent with brand snapshot.
    - source_type is not obviously wrong.
  - target: ≥ **80%** of generated opportunities are “on-strategy” (as judged by reviewers).

- **clarity**
  - human rating 1–5:
    - “i understand what this opportunity is asking me to do and why.”
  - computed as the mean across all opportunities.
  - target: average ≥ **3.5** with no brand averaging below 3.

- **diversity**
  - simple stats:
    - count of unique pillars.
    - count of unique personas.
    - channel mix.
  - guardrail: no single pillar should exceed **60%** of the board unless the brand snapshot makes it dominant by design.

#### 7.1.4 package-level metrics

for each selected opportunity:

- **thesis quality (human 1–5)**
  - criteria:
    - captures the core argument.
    - is specific, non-fluffy, and on-brand.
  - target: average ≥ **3.5**, with ≥ 70% of packages rated ≥ 4.

- **channel plan sanity (human 1–5)**
  - “does the set of channels and their rationales make sense?”
  - target: average ≥ **3.5**.

- **structural correctness (automatic)**
  - package always:
    - links to the right `Opportunity`.
    - has at least one channel.
    - respects taboos (no banned phrases in thesis).
  - target: **100%** pass.

#### 7.1.5 variant-level metrics

for each generated variant:

- **edit distance vs acceptance**
  - for a subset of variants, reviewers:
    - either accept as-is, or
    - suggest edits, which we measure via token-level edit distance.
  - we track:
    - % “accept as-is”.
    - % “light edit” (normalized edit distance &lt; 0.3).
  - target: for linkedin:
    - ≥ **25%** accept-as-is; ≥ **60%** accept with light edits.
    - for x, tolerance can be slightly lower initially.

- **brand safety**
  - automatic check:
    - no hard taboo violations (keywords from `taboos`).
    - no obviously off-tone phrases (we can do simple string/regex checks first).
  - target: **0** taboo violations in eval set.

- **pattern usage**
  - for variants that claim a `pattern_template_id`:
    - does the text roughly follow the beats?
  - we track qualitatively; no strict numeric target in PRD 1, but anything obviously off should be flagged.

#### 7.1.6 acceptance criteria for PRD 1

PRD 1 is considered **offline-acceptable** if:

- coverage vs golden ≥ 60% across brands.
- opportunity clarity ≥ 3.5 mean rating.
- package thesis quality ≥ 3.5 mean rating.
- ≥ 25% of linkedin variants are “accept as-is”; ≥ 60% “light edit or better”.
- zero taboo violations in the eval runs.
- no structural correctness failures (broken links, missing ids, invalid status enums).

if any of these are not met, PRD 1 is not “done”; we either:

- tighten prompts and graph logic, or
- adjust goals if we discover the target was unrealistic (documented explicitly in this section).

### 7.2 Online Checks

online checks answer: “at runtime, are we enforcing basic invariants so that a bad llm output or graph bug does not leak through to the user or corrupt state?”

we split this into **schema-level validation**, **business guardrails**, and **performance limits**.

#### 7.2.1 schema validation

every hero-loop call that crosses a boundary (django ↔ deepagents, deepagents ↔ llm) must be validated against a schema:

- use typed dataclasses / pydantic models for:
  - `BrandSnapshot`
  - `OpportunityDraft`, `Opportunity`
  - `ContentPackage`
  - `VariantDraft`, `Variant`
  - `ExecutionEvent`, `LearningEvent`
  - `ExternalSignalBundle` and its subtypes.

online rules:

- any llm or graph output is:
  - parsed into the corresponding model.
  - rejected if parsing fails or required fields are missing.
- any rejected payload:
  - is logged with:
    - run id
    - brand id
    - graph name
    - summary of validation errors.
  - causes a **graph-level failure**, not a partial, silent success.

#### 7.2.2 business guardrails

beyond type safety, we enforce simple business rules at runtime:

- **score bounds**
  - opportunity scores are always clamped to [0,100].
- **channel and status enums**
  - only `linkedin` and `x` channels allowed in PRD 1.
  - only documented status enums (`draft`, `ready`, `published`, etc.) are allowed; unknown values are rejected.
- **taboo enforcement**
  - any generated text (thesis or variants) must be scanned for:
    - explicit taboos from `BrandSnapshot.taboos`.
  - on detection:
    - variant/package is rejected or flagged; we never persist taboo-violating text as “ready” or “published”.

- **length sanity**
  - simple length checks:
    - linkedin: soft limit ~2–3 paragraphs.
    - x: hard-ish limit ~320 chars (to allow future trimming); anything longer is auto-trimmed or flagged.
- **idempotency**
  - repeated “create package from opportunity” for same (brand, opportunity):
    - must not create duplicates.
  - repeated “generate variants” for same package:
    - either blocked or creates a new generation with clear semantics (PRD 1 can choose the simpler variant: block and instruct user to duplicate if needed).

#### 7.2.3 performance and stability

we set basic performance expectations for hero-loop calls:

- **latency targets**
  - today board regeneration (`regenerate_today_board`):
    - p50 &lt; 20s, p95 &lt; 45s for eval brands.
  - package creation (opportunity → package + variants):
    - p50 &lt; 15s, p95 &lt; 30s.
- **timeouts**
  - llm calls:
    - strict timeout (e.g. 20–25s).
  - graphs:
    - max wall-clock per graph run; beyond that, treat as failure.
- **circuit breakers**
  - if a brand experiences repeated graph failures (e.g. 3 in a row within 10 minutes):
    - mark the hero loop as “degraded” for that brand.
    - fall back to:
      - last successful Today board, or
      - a deterministic evergreen board.

these numbers are v1 targets; they can be adjusted as we learn more, but PRD 1 must at least measure them.

### 7.3 Definition of “Good” vs “Bad” Runs

we need clear language to classify hero loop runs so logs, dashboards, and future PRDs can reason about behavior.

#### 7.3.1 run types

for each of F1 (today board) and F2 (package + variants) we classify each run as:

- **good**
  - all required graphs completed.
  - outputs passed schema + business validation.
  - offline-equivalent metrics (if computed) are in the expected band.
  - user-facing effect:
    - board/package looks coherent and useful without obvious errors.

- **partial**
  - some graphs succeeded, others failed, **but**:
    - we still have a usable output:
      - e.g. package thesis ok but variants missing for x.
      - today board generated fewer opportunities but still covers at least 3 pillars/personas.
  - user-facing effect:
    - visible gaps (“no variants generated for x, try again”), but the experience is not broken.

- **bad**
  - graph failure or validation errors leave us with:
    - no board, or
    - no usable package/variants.
  - user-facing effect:
    - we must explicitly tell the user that generation failed and provide a retry or fallback.

#### 7.3.2 classification rules

- **F1 – today board**
  - good:
    - ≥ 6 curated opportunities.
    - at least 2 pillars and 2 personas represented (unless brand only has 1 of each).
  - partial:
    - 3–5 curated opportunities and valid summary.
  - bad:
    - &lt; 3 opportunities, or
    - schema/validation failure, or
    - no opportunities persisted.

- **F2 – package + variants**
  - good:
    - package thesis present.
    - ≥ 1 variant per enabled channel.
  - partial:
    - package thesis present.
    - variants missing in some channels but at least one channel has ≥ 1 variant.
  - bad:
    - no package persisted, or
    - package exists but has no variants for any channel.

- **F3 – learning**
  - good:
    - learning events successfully written for recent executions.
  - partial:
    - only some scopes updated but no corrupt writes.
  - bad:
    - no learning events written for a long window *and* repeated job failures.

#### 7.3.3 acceptance and observability

PRD 1 is only “done” when:

- the vast majority (**≥ 90%**) of eval runs across brands are **good**.
- remaining runs are **partial**, not **bad**, and the partial modes are explicitly handled (copy, errors, fallbacks).
- “bad” runs are:
  - rare.
  - clearly visible in logs and (simple) dashboards.
  - have enough metadata (brand, graph, error_code) to debug within a few minutes.

this definition is what we will use to decide whether the hero loop is ready for external users and to guide future PRDs that improve robustness and quality over time.

### 7.4 Testing Strategy (PRD 1)

in addition to offline evals and runtime checks, PRD 1 must ship with a concrete automated testing strategy so regressions are caught before they hit users.

#### 7.4.1 test layers

we require three main layers of tests:

- **service-layer unit tests (T1)**
  - cover django service modules (brands_service, today_service, opportunities_service, content_packages_service, variants_service, decisions_service, learning_service).
  - run entirely without llm calls (use fixtures and simple stubs).
  - assert:
    - correct use of transactions and idempotency.
    - correct enforcement of business rules (status transitions, enum validation, clamping, etc.).

- **graph contract tests (T2)**
  - cover each graph entry function with deterministic, canned llm outputs.
  - assert that:
    - DTOs are parsed/validated correctly.
    - invariants per graph (5.1–5.4) are enforced.
    - error cases produce `partial_success` / `failure` with the expected error codes.

- **end-to-end hero-loop tests (T3)**
  - use a small subset of the eval fixtures (7.1) with llm calls stubbed or heavily constrained.
  - exercise:
    - today board generation for a seed brand.
    - opportunity → package → variants.
    - decisions → learning.
  - assert that:
    - tables are populated as expected.
    - run_type classification (7.3) behaves as intended.

#### 7.4.2 minimum coverage expectations

PRD 1 is considered test-ready when:

- every public service method in 4.1.1 has at least one T1 test.
- every graph in 5.1–5.4 has at least one T2 test for:
  - a nominal success case,
  - a partial-success case,
  - a hard-failure case.
- at least one T3 end-to-end test passes for each reference brand type (b2b saas, devtools, b2c, solo brand, conservative b2b).

#### 7.4.3 CI requirements

- all tests (T1–T3) must run in CI on every PR that touches hero-loop code (services, graphs, DTOs, schema).
- PRs that add or change hero-loop behavior must:
  - add or update tests in the relevant layer(s),
  - keep existing tests passing.

failing tests or missing coverage should block merging; PRD 1 is not considered "done" until this baseline is in place.

## 8. Instrumentation & Logging

this section defines how we observe the hero loop in PRD 1: which events we emit, which properties they carry, and what minimal dashboards / logs we need so that a single engineer can debug issues quickly without guessing.

### 8.1 Events

for PRD 1 we keep the event vocabulary small but intentional. events are **logical product events**, not raw log lines. they should be emitted in a structured way (json) and sent to whatever sink we choose (supabase, segment, clickhouse, etc.) with the dimensions in 8.2.

for each event we specify: when it fires and what it means at a high level.

- **`hero_today_board_requested`**
  - fired when the UI or an internal job calls `GET /api/brands/{brand_id}/today` or `POST /api/brands/{brand_id}/today/regenerate`.
  - purpose: track demand for today boards independent of whether generation succeeds.
- **`hero_today_board_generated`**
  - fired when F1 completes and a Today board is successfully persisted + returned.
  - includes `run_type` (`good` / `partial`), `candidate_count`, and `curated_count`.
- **`hero_today_board_generation_failed`**
  - fired when F1 fails hard (no usable opportunities).
  - includes `error_code` and `failure_stage` (e.g. `graph`, `validation`, `persistence`).

- **`hero_package_created_from_opportunity`**
  - fired when a `ContentPackage` is created (or returned idempotently) from an `Opportunity`.
  - includes `package_status` at creation and whether thesis was auto-generated or scaffold-only.
- **`hero_package_generation_failed`**
  - fired when `graph_hero_package_from_opportunity` fails and no usable package is created.
  - includes `error_code` and `failure_stage`.

- **`hero_variants_generated`**
  - fired when `graph_hero_variants_from_package` completes and variants are persisted.
  - includes `run_type` (`good` / `partial`), `variant_count_by_channel`, and any channels with errors.
- **`hero_variants_generation_failed`**
  - fired when variant generation fails for all channels (no variants created).
  - includes `error_code` and `failure_stage`.

- **`hero_opportunity_decision_recorded`**
  - fired when an opportunity-level decision endpoint succeeds (pin, snooze, reject, open_as_package).
  - includes `decision_type` and current `opportunity_status`.
- **`hero_package_decision_recorded`**
  - fired when a package-level decision succeeds (mark_ready, mark_published, etc.).
  - includes `decision_type` and resulting `package_status`.
- **`hero_variant_decision_recorded`**
  - fired when a variant-level decision succeeds (edit, approve, publish in future PRDs).
  - includes `decision_type` and resulting `variant_status`.

- **`hero_learning_run_started`**
  - fired when `graph_hero_learning_from_decisions` starts for a brand.
  - helps correlate with downstream `learning_event` writes.
- **`hero_learning_run_completed`**
  - fired when a learning run completes successfully.
  - includes counts of `execution_events_consumed` and `learning_events_emitted`.
- **`hero_learning_run_failed`**
  - fired when a learning run fails hard (no learning events written).
  - includes `error_code` and `failure_stage`.

- **`hero_external_signals_bundle_loaded`**
  - fired when an `ExternalSignalBundle` is successfully loaded for a brand as part of F1.
  - includes counts of signals by type (trends, web_mentions, competitor_posts, social_moments).
- **`hero_external_signals_bundle_failed`**
  - fired when external signals cannot be loaded and we fall back to strategy-only generation.
  - includes `error_code` and whether we fell back to an evergreen board.

> note: we deliberately do **not** emit low-level llm token usage events here; those belong in the llm client/infra layer, not the product PRD. what we care about is “what happened at the level of the hero loop?”

### 8.2 Dimensions

each event in 8.1 should carry a consistent set of core dimensions, plus entity-specific and performance dimensions where relevant.

**8.2.1 core dimensions (all events)**

- `timestamp` – iso8601, server-side.
- `env` – `local`, `dev`, `staging`, `prod`.
- `brand_id` – uuid for the brand.
- `actor_user_id` – uuid for the human, if applicable; `null` for purely system-initiated runs.
- `request_id` – correlation id for the http request (if on a request path).
- `run_id` – correlation id for the hero-loop run (e.g. deepagents run id), reused across all events emitted from that run.
- `graph_name` – when applicable (`graph_hero_generate_opportunities`, `graph_hero_package_from_opportunity`, etc.).
- `run_type` – `good` / `partial` / `bad` for completion events (see 7.3); `null` for purely atomic actions like decisions.

**8.2.2 entity dimensions**

where relevant, we attach ids for the main entities involved so we can drill down later:

- `opportunity_id`
- `package_id`
- `variant_id`
- `pattern_template_id`
- `pillar_id`
- `persona_id`
- `channel` – `linkedin` or `x`.
- `decision_type` – for decision events.
- `package_status`, `variant_status`, `opportunity_status` – resulting status after the action.

we do **not** include raw text (opportunity angles, thesis, post bodies) as dimensions; that data already exists in the db and should be inspected via admin tools when needed, not pumped into analytics systems by default.

**8.2.3 performance & quality dimensions**

for generation and learning events we add basic performance + quality fields:

- `latency_ms` – wall-clock time from request start to completion.
- `llm_call_count` – how many llm calls the graph made during this run (aggregated).
- `llm_model` – model identifier used by the primary graph.
- `candidate_count` – number of opportunity candidates produced by `graph_hero_generate_opportunities`.
- `curated_count` – number of curated opportunities persisted for the board.
- `variant_count_by_channel` – map (e.g. `{linkedin: 2, x: 1}`).
- `execution_events_consumed` – for learning runs.
- `learning_events_emitted` – for learning runs.
- `external_signals_used` – boolean; whether non-empty external signals influenced this run.
- `error_code` / `error_class` – for failed runs; short, enumerable strings, not free-form messages.

### 8.3 Observability Requirements

PRD 1 does **not** require a full observability platform, but it does require enough logging and basic dashboards that:

- we can classify runs as `good` / `partial` / `bad` in practice.
- we can answer “what happened for brand X at time Y?” without spelunking random logs.
- we can see when the system is degrading before users yell.

**8.3.1 logging & tracing**

minimum requirements:

- all deepagents graph runs log a single structured line containing:
  - `timestamp`, `env`, `brand_id`, `graph_name`, `run_id`, `run_type`, `latency_ms`, `error_code?`.
- django request logs include:
  - `request_id`, `path`, `method`, `status_code`, `latency_ms`, `brand_id?`, `actor_user_id?`.
- for failed runs, we log:
  - a summarized reason (`error_class`, `error_code`).
  - pointers to validation errors (counts, not full payloads).
- llm prompts/responses:
  - are logged **only** in redacted form and only in lower environments (`dev`, `staging`) to avoid leaking sensitive brand data in prod logs.
- we use a consistent `run_id` to tie together:
  - http request → django service calls → deepagents graph runs → product events.

open telemetry or equivalent can be used to implement traces, but PRD 1 only requires that:

- each hero-loop call has a single trace or at least a correlated set of log lines via `request_id`/`run_id`.

**8.3.2 minimal dashboards**

for PRD 1 we want at least:

- **hero loop health dashboard**
  - per brand and per env:
    - count of `hero_today_board_generated` per day.
    - distribution of `run_type` (`good` / `partial` / `bad`) over time.
    - p50 / p95 `latency_ms` for board generation and package+variant generation.
- **failure dashboard**
  - top `error_code`s for:
    - today board failures.
    - package/variant generation failures.
    - learning run failures.
  - ability to drill into a specific error code to see recent affected `brand_id`s.
- **learning activity dashboard**
  - per brand:
    - `execution_events_consumed` and `learning_events_emitted` per day.
    - basic view of whether learning is actually running or silently dead.

these ca<truncated__content/>

## 9. Phases, Tasks, and Steps

this section translates the hero loop scope into a concrete build plan. phases are strictly ordered; you do not skip ahead. within a phase, tasks can often be parallelized, but acceptance criteria must be hit before the phase is considered done.

phases for PRD 1:

- **phase 0 – foundations & enablement**
- **phase 1 – backend services & contracts**
- **phase 2 – deepagents graphs**
- **phase 3 – hero UI wiring**
- **phase 4 – eval, hardening, and launch gate**

---

### 9.1 Phase 0 – Foundations & Enablement

**goal:** have a working skeleton where django, supabase, deepagents, and the hero UI can talk to each other in a trivial, non-hero way. no business logic yet; this is about removing yak-shaving during later phases.

#### 9.1.1 Task 0.1 – Repos, Envs, and Feature Flags

**steps**

- create / confirm:
  - `kairo-system` repo (django + deepagents + supabase client).
  - `kairo-ui` repo (next.js hero slice).
- wire basic env config for `kairo-system`:
  - application settings module (env-based).
  - supabase connection config (url, anon/service keys from env).
  - basic logging setup with request-id and run-id support.
- introduce feature flags (env-based or simple config):
  - `HERO_LOOP_V1_ENABLED` – guards all hero-loop endpoints.
  - `HERO_LOOP_EXTERNAL_SIGNALS_ENABLED` – guards use of `ExternalSignalBundle`.
  - `HERO_LOOP_LEARNING_ENABLED` – guards learning graph execution.

**acceptance criteria**

- both repos boot locally with a single command each (`make dev`-style).
- `kairo-system` exposes a trivial health endpoint (e.g. `GET /api/health`).
- feature flags can be flipped per env without code changes.

#### 9.1.2 Task 0.2 – Database Schema for PRD 1 Objects

**steps**

- define ORM models and migrations for all in-scope tables (per section 3.1):
  - `brands`, `brand_snapshots`, `personas`, `content_pillars`, `pattern_templates`.
  - `opportunities`, `content_packages`, `variants`.
  - `execution_events`, `learning_events`.
  - fixtures table(s) for external signals if using DB instead of json.
- apply migrations locally and in dev env.
- create basic admin/browser access to these tables for debugging (django admin or equivalent).

**acceptance criteria**

- migrations run cleanly on a fresh database.
- each table has the fields and basic relationships implied by section 3.1.
- a developer can inspect and edit rows for any table via admin or sql.

#### 9.1.3 Task 0.3 – Dev Tooling & Fixtures

**steps**

- set up:
  - formatter + linter (black/ruff or equivalent) for `kairo-system`.
  - basic test runner (`pytest`).
- seed initial fixtures:
  - 2–3 example brands with `BrandSnapshot`, personas, pillars, patterns.
  - dummy external signals fixtures for those brands (json/yaml or db).
- add a `make seed`/`manage.py` command to populate dev with fixtures.

**acceptance criteria**

- `make test` (or equivalent) runs and passes a trivial smoke test suite.
- `make seed` (or equivalent) produces a dev environment where:
  - brands + snapshots exist.
  - at least one brand can be used end-to-end for later phases.

---

### 9.2 Phase 1 – Backend Services & Contracts

**goal:** implement the core django services and http api surface for the hero loop, with deterministic behavior and typed contracts, but with deepagents still stubbed out.

#### 9.2.1 Task 1.1 – Canonical Models & DTOs

**steps**

- finalize django models (if needed) for objects in section 3.1.
- define typed DTOs (pydantic/dataclasses) for:
  - `BrandSnapshot`, `TodayBoardDTO`, `TodaySummary`.
  - `OpportunityDraft`, `Opportunity`.
  - `ContentPackage`, `VariantDraft`, `Variant`.
  - `ExecutionEvent`, `LearningEvent`.
  - `ExternalSignalBundle` and subtypes.
- implement serialization helpers:
  - db → DTO
  - DTO → http response.

**acceptance criteria**

- type-checking passes for all hero-loop DTOs.
- converting between ORM and DTOs is covered by unit tests.

#### 9.2.2 Task 1.2 – Service Layer Implementation

**steps**

- implement service modules per section 4.1.1:
  - `brands_service`, `today_service`, `opportunities_service`.
  - `content_packages_service`, `variants_service`.
  - `decisions_service`, `learning_service` (stub learning logic for now).
- for each service method, define:
  - input DTOs / ids.
  - output DTOs.
  - explicit error types.
- implement idempotency rules:
  - `create_package_from_opportunity` must not create duplicates.

**acceptance criteria**

- unit tests cover happy paths and common error cases for each service.
- it is possible to:
  - manually create an opportunity, then a package, then variants via service calls (with deepagents stubbed).

#### 9.2.3 Task 1.3 – HTTP API Surface

**steps**

- implement endpoints defined in section 4.1.2:
  - today board (get + regenerate).
  - create/get package.
  - generate/list variants.
  - decision endpoints for opportunities, packages, variants.
- wire each endpoint to the corresponding service method.
- add schema validation for request bodies and responses.

**acceptance criteria**

- swagger/openapi or equivalent docs show all hero-loop endpoints.
- calling endpoints with valid payloads returns typed responses, with no deepagents dependency.
- invalid payloads and invalid state transitions produce clear 4xx errors.

#### 9.2.4 Task 1.4 – External Signals Stub Layer

**steps**

- implement `external_signals_service.get_bundle_for_brand(brand_id)`:
  - reads from fixtures.
  - returns an `ExternalSignalBundle` per section 6.2.
- add a thin tool adapter layer (for later deepagents use):
  - `get_external_signals_tool(brand_id)` → bundle or empty bundle.

**acceptance criteria**

- for seed brands, calling the service returns non-empty bundles.
- empty / missing fixtures are handled gracefully (empty lists, no exceptions).

#### 9.2.5 Task 1.5 – Validation, Guardrails, and Errors

**steps**

- centralize validation for hero-loop entities:
  - clamp scores to [0,100].
  - enforce channel enums (`linkedin`, `x`).
  - enforce status enums for opportunities, packages, variants.
- wire business guardrails from section 7.2 into service methods:
  - taboo checks for text (stubbed or real).
  - basic length sanity for variants.
- define an error taxonomy for hero-loop failures (`HERO_OPPORTUNITY_VALIDATION_ERROR`, etc.).

**acceptance criteria**

- malformed data returned from downstream (later: graphs) is rejected at service level.
- no hero-loop endpoint can persist invalid status/enum combinations.

---

### 9.3 Phase 2 – DeepAgents Graphs

**goal:** implement and integrate the four hero graphs so that django can call them behind the existing service methods, with clear contracts and bounded behavior.

#### 9.3.1 Task 2.1 – LLM Client & DeepAgents Wiring

**steps**

- implement a centralized llm client per 05-llm-and-deepagents-conventions:
  - model selection.
  - timeouts.
  - redaction for logs.
- set up a `kairo.agents.hero` module with:
  - graph registration.
  - common tools (brand context, learning summary, external signals).
- define a thin django-facing api:
  - `run_graph_hero_generate_opportunities(...)`.
  - `run_graph_hero_package_from_opportunity(...)`.
  - `run_graph_hero_variants_from_package(...)`.
  - `run_graph_hero_learning_from_decisions(...)`.

**acceptance criteria**

- a smoke test can invoke each graph with stubbed inputs and receive a structured result.
- logs show `run_id`, `graph_name`, and latency.

#### 9.3.2 Task 2.2 – Implement graph_hero_generate_opportunities

**steps**

- implement nodes described in section 5.1 (N1–N6).
- wire tools:
  - `get_brand_context_tool`.
  - `get_learning_summary_tool` (stubbed deterministic view over `ContentPillar` weights).
  - `get_external_signals_tool` from phase 1.
- make the graph return `OpportunityDraft[]` and error metadata.
- integrate into `today_service.regenerate_today_board`:
  - call graph.
  - run deterministic ranking/persistence.

**acceptance criteria**

- for seed brands, calling regenerate today yields 6–12 curated opportunities.
- failure of the graph yields an empty board with a clear error, not a crash.

#### 9.3.3 Task 2.3 – Implement graph_hero_package_from_opportunity

**steps**

- implement nodes from section 5.2 (N1–N5).
- wire tools:
  - brand voice and patterns.
- integrate into `content_packages_service.create_package_from_opportunity`:
  - on success: persist package with `thesis` and channels.
  - on failure: create scaffold or return a clear error (per 3.3.3).

**acceptance criteria**

- for curated opportunities, calling create-package usually yields a package with non-empty thesis and at least one channel.
- package creation failure modes are logged and surfaced cleanly.

#### 9.3.4 Task 2.4 – Implement graph_hero_variants_from_package

**steps**

- implement nodes from section 5.3 (N1–N5).
- wire tools:
  - brand voice.
  - channel guidelines.
  - pattern resolver.
- integrate into `variants_service.generate_variants_for_package`:
  - persist `Variant` rows on success.
  - handle partial success per channel.

**acceptance criteria**

- for seed brands and opportunities, packages generate 1–3 variants per channel.
- taboo and length guardrails are enforced.
- per-channel failures do not block other channels.

#### 9.3.5 Task 2.5 – Implement graph_hero_learning_from_decisions

**steps**

- implement deterministic learning logic per section 5.4:
  - bucket `ExecutionEvent`s.
  - compute `weight_delta`s.
  - emit `LearningEvent`s via writer tool.
- integrate via `learning_service` as a batch job:
  - management command or background worker.
  - parameterized by `brand_id` and time window.

**acceptance criteria**

- running the learning job on a set of synthetic `ExecutionEvent`s results in plausible `LearningEvent`s.
- subsequent opportunity runs reflect changes in pillar weights.

#### 9.3.6 Task 2.6 – Graph Tests & Invariant Checks

**steps**

- write unit/integration tests for each graph:
  - happy-path runs for seed brands.
  - degraded modes (empty `ExternalSignalBundle`, missing learning, etc.).
  - schema validation failures.
- assert invariants from section 5 (bounds, counts, non-empty fields).

**acceptance criteria**

- test suite fails fast if any graph starts returning malformed outputs.
- coverage is sufficient that common regressions are caught in CI.

---

### 9.4 Phase 3 – Hero UI Wiring

**goal:** replace the current demo/stubbed hero UI wiring with real calls into `kairo-system` while preserving the UX that already exists in the Next.js repo.

#### 9.4.1 Task 3.1 – Environment and Routing Strategy

**steps**

- add env config to `kairo-ui` for selecting backend:
  - `NEXT_PUBLIC_BACKEND_MODE` in {`demo`, `system`}.
  - `NEXT_PUBLIC_SYSTEM_API_BASE`.
- implement a thin api client layer in the UI:
  - wraps calls to hero-loop endpoints.
  - handles auth headers and error mapping.

**acceptance criteria**

- running the UI in `demo` mode behaves as today (local fixtures).
- running in `system` mode causes hero pages to fetch from django.

#### 9.4.2 Task 3.2 – Today Board Integration

**steps**

- wire the Today page to:
  - `GET /api/brands/{brand_id}/today`.
  - `POST /api/brands/{brand_id}/today/regenerate`.
- map `TodayBoardDTO` to existing Today UI components.
- handle degraded cases:
  - empty board.
  - `run_type = partial` / `bad`.
  - show explicit messaging instead of silent failure.

**acceptance criteria**

- for seed brands, Today shows real opportunities from `kairo-system`.
- regenerate triggers a visible refresh and handles errors sanely.

#### 9.4.3 Task 3.3 – Package Workspace Integration

**steps**

- wire opportunity “open as package” to:
  - `POST /api/brands/{brand_id}/opportunities/{opportunity_id}/packages`.
  - then `GET /api/packages/{package_id}`.
- wire package workspace to:
  - `POST /api/packages/{package_id}/variants/generate`.
  - `GET /api/packages/{package_id}/variants`.
- ensure edits to variants call:
  - `PATCH /api/variants/{variant_id}`.

**acceptance criteria**

- a user can go from Today → Package → Variants end-to-end on real data.
- optimistic updates are aligned with backend state and eventually converge.

#### 9.4.4 Task 3.4 – Decision Flows & Learning Hooks

**steps**

- wire UI actions for:
  - opportunity pin/snooze/reject.
  - package mark-ready, mark-published.
  - variant edits.
- call the decision endpoints from section 4.1.2.
- confirm that `ExecutionEvent`s are written and visible in admin/db.

**acceptance criteria**

- user decisions in the UI produce corresponding `ExecutionEvent`s in the db.
- no double-writes or missing events for common interactions.

#### 9.4.5 Task 3.5 – UX States for Degraded Modes

**steps**

- design and implement minimal UI states for:
  - no opportunities for today.
  - package/variant generation failures.
  - learning temporarily disabled.
- ensure errors from backend are mapped to these states (not swallowed).

**acceptance criteria**

- engineers can reproduce degraded modes and see clear, user-facing messaging.
- no hero-screen silently fails in common error cases.

---

### 9.5 Phase 4 – Evaluation, Hardening, and Launch Gate

**goal:** prove that the hero loop beats “blank page + generic chatgpt” for our target personas, harden the system against obvious failures, and define a clear go/no-go gate for exposing it to external users.

#### 9.5.1 Task 4.1 – Offline Eval Harness & Dataset

**steps**

- build the eval dataset described in section 7.1:
  - at least 5 brands × multiple weeks of external signals.
  - golden opportunities, packages, and variants.
- implement an eval runner script/notebook that:
  - runs F1 and F2 for each brand-week.
  - logs outputs and basic metrics.
- collect human ratings for clarity, alignment, and quality.

**acceptance criteria**

- offline metrics meet or exceed targets in section 7.1.6.
- eval runs are reproducible (same config → same outputs modulo expected llm variance).

#### 9.5.2 Task 4.2 – Online Checks & Guardrails

**steps**

- ensure schema validation is wired for all graph outputs (section 7.2.1).
- enforce business guardrails (scores, enums, taboos, lengths).
- add runtime classification of runs (good/partial/bad) into logs/events (section 7.3).

**acceptance criteria**

- intentionally broken llm outputs are caught at validation and do not corrupt state.
- logs clearly show run classification and reasons for partial/bad runs.

#### 9.5.3 Task 4.3 – Performance & Stability Pass

**steps**

- instrument latency for:
  - today board regeneration.
  - package + variant generation.
- tune:
  - llm timeouts.
  - max steps per graph.
- implement simple circuit breakers from section 7.2.3:
  - per-brand failure counters.
  - degraded-mode flags.

**acceptance criteria**

- measured p50/p95 latencies meet targets in section 7.2.3 (or updated, documented ones).
- repeated failures do not spam users; instead, we fall back gracefully.

#### 9.5.4 Task 4.4 – Chaos & Edge-Case Scenarios

**steps**

- simulate:
  - empty or missing `ExternalSignalBundle`.
  - learning job disabled.
  - llm provider outages.
- verify hero loop behavior for each scenario:
  - still usable? clearly degraded? never silently wrong?

**acceptance criteria**

- in all scenarios, the system either:
  - produces a usable, clearly-labeled degraded experience, or
  - fails visibly with a path to retry.

#### 9.5.5 Task 4.5 – Launch Checklist & Go/No-Go

**steps**

- compile a short launch checklist summarizing:
  - offline eval results.
  - online health metrics.
  - known limitations and punted decisions.
- run a “day in the life” for the primary persona on seed brands:
  - create a brand.
  - use Today for a week’s worth of runs.
  - build and edit packages.
- gather qualitative feedback from at least 2–3 real marketers.

**acceptance criteria**

- checklist items pass or have explicit waivers.
- marketers report that Kairo’s hero loop is meaningfully better than their current blank-page + chatgpt workflow.
- any critical issues discovered are either fixed or clearly logged as blockers for exposing PRD 1 beyond friendly users.

---

### 9.6 Phase Deliverables Summary

for quick reference, each phase must leave behind tangible, shippable artifacts:

- **phase 0:**
  - repos, envs, migrations, fixtures, and basic tooling.
- **phase 1:**
  - fully typed django services and http api; hero loop works with stubbed graphs.
- **phase 2:**
  - all four hero graphs implemented and integrated; end-to-end hero loop works from a backend standpoint.
- **phase 3:**
  - hero UI wired to `kairo-system`; marketers can run the hero loop via the real frontend.
- **phase 4:**
  - eval dataset + harness, instrumentation, performance constraints, and a documented launch decision.

only when phase 4 passes its acceptance criteria is PRD 1 truly "done" and safe to use as the foundation for later PRDs (multi-brand, more channels, richer ingestion, etc.).