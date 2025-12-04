# Kairo docs

Kairo is an AI-native content copilot for brands and content teams.  
This repo is the **backend systems + orchestration** (Django + LLMs).

The `docs/` folder defines the **domain model**, **engines**, and **v1 product spec**.  
Code is expected to follow these docs.

---

## 1. Structure of this folder

    docs/
      README.md
      vision.md

      system/
        01-overall-system.md
        02-engines-overview.md
        03-canonical-objects.md

      engines/
        brand-brain-engine.md
        opportunities-engine.md
        patterns-engine.md
        content-engineering-engine.md
        learning-engine.md

      prd/
        kairo-v1-prd.md

High-level intent:

- `vision.md`  
  Long-term product narrative and non-goals. No schemas.

- `system/01-overall-system.md`  
  Big-picture mental model. How a brand flows through Kairo end-to-end.

- `system/02-engines-overview.md`  
  Catalog of engines: names, one-line transformations, core inputs/outputs.

- `system/03-canonical-objects.md`  
  **Single source of truth** for all domain objects (CO-01..CO-22).

- `engines/*.md`  
  Deep specs for each engine (Brand Brain, Opportunities, Patterns, Content Engineering, Learning).

- `prd/kairo-v1-prd.md`  
  Product requirements for Kairo v1, including phase plan and key flows.

---

## 2. Law vs context

Not all docs have the same weight. There are two levels:

### Level 1 – Authoritative

These are **law** for the system:

- `system/03-canonical-objects.md`
- `engines/brand-brain-engine.md`
- `engines/opportunities-engine.md`
- `engines/patterns-engine.md`
- `engines/content-engineering-engine.md`
- `engines/learning-engine.md`
- `prd/kairo-v1-prd.md` (for v1 scope)

Rules:

- If Level 1 and Level 2 conflict, **Level 1 wins**.
- Code must match Level 1.  
  Changing system behavior **requires** updating Level 1 docs first.

### Level 2 – Context

These are supporting narrative and framing:

- `vision.md`
- `system/01-overall-system.md`
- `system/02-engines-overview.md`

They should **not** contradict Level 1, but can be looser and more descriptive.

---

## 3. Core concepts and naming conventions

### Canonical objects (CO-xx)

- All domain entities are defined as **Canonical Objects** `CO-01`, `CO-02`, …, `CO-22`.
- Their jobs, invariants, and example shapes live in  
  `system/03-canonical-objects.md`.
- Engines **do not invent new domain objects**. They create, mutate, and read CO-xx.

Examples (names only; details live in the canonical doc):

- Brand, Persona, Pillar  
- BrandBrainSnapshot, BrandRuntimeContext, BrandMemoryFragment  
- GlobalSourceDoc, OpportunityCard, OpportunityBatch  
- PatternSourcePost, PatternTemplate, PatternUsage  
- ContentPackage, CoreArgument, ChannelPlan, ContentVariant  
- FeedbackEvent, BrandPreferences, GlobalPriors, ChannelConfig, PublishingJob

### Engines

There are five engines:

- Brand Brain engine
- Opportunities engine
- Patterns engine
- Content Engineering engine
- Learning engine

Each has its own doc in `engines/` with a consistent template:

- Definition and one-line transformation
- Inputs and outputs (only in terms of CO-xx)
- Invariants (what must always be true)
- Quality dimensions
- Failure modes and how they surface
- Latency and cost constraints
- Learning hooks
- Baseline comparison (vs manual + custom GPT)
- V1 scope vs later evolution

### Object responsibility

For each CO:

- There is a clear **creator** (engine or human process).
- Only a small, explicit set of engines are allowed to **mutate** it.
- Many parts of the system may **read** it.

This responsibility mapping lives in `system/03-canonical-objects.md` and engine docs.  
If in doubt, check those docs; do not guess in code.

---

## 4. Rules for changing the system (doc-first workflow)

Kairo is **doc-first**: docs change before code.

### Changing or adding a Canonical Object

1. Edit `system/03-canonical-objects.md`:
   - Add or update the CO entry (purpose, invariants, example shape).
   - Update which engines create/mutate/read it.
2. Update any affected `engines/*.md`:
   - Adjust inputs, outputs, and invariants as needed.
3. Only then:
   - Update models / serializers / prompts / endpoints in code.

### Changing engine behavior

1. Update the relevant `engines/*.md`:
   - Clarify stage behavior, IO, invariants, failure modes, costs, etc.
2. If new IO cannot be expressed with existing COs:
   - Propose a new CO in `system/03-canonical-objects.md` and add it there.
3. Then update implementation:
   - Orchestration code, prompts, validation, tests.

### Changing product scope (v1)

1. Update `prd/kairo-v1-prd.md`:
   - Phase plans, flows, in/out of scope.
2. Reflect scope changes in:
   - Engine docs (what is v1 vs later).
   - Canonical objects (only if the domain model actually changes).
3. Then adjust code and UI.

**No code change should be made without a corresponding doc change you can point to.**

---

## 5. How to use these docs

### For humans

Recommended reading order for a new contributor:

1. `docs/vision.md` – why Kairo exists, who it serves.
2. `docs/system/01-overall-system.md` – end-to-end mental model.
3. `docs/system/03-canonical-objects.md` – the domain vocabulary.
4. The engine doc(s) relevant to your work in `docs/engines/`.
5. The relevant sections in `docs/prd/kairo-v1-prd.md` (if touching v1 features).

Before adding new concepts in code, check whether they already exist as CO-xx.

### For AI assistants (Claude Code, ChatGPT, etc.)

When asking an assistant to write or modify backend code:

- Always reference:
  - `docs/system/03-canonical-objects.md`
  - The relevant `docs/engines/*.md`
  - `docs/prd/kairo-v1-prd.md` if it’s a feature-level task
- Explicitly instruct:
  - Do **not** invent new domain objects outside CO-xx.
  - Keep IO shapes consistent with canonical object definitions.
  - Preserve engine responsibilities and invariants.

When an assistant suggests new fields or objects:

- Decide if they belong in the canonical model.
  - If yes: update `03-canonical-objects.md` (and engines) first, then accept code.
  - If no: reject or constrain the suggestion and tighten the spec.

---

## 6. Non-goals for this repo

This repo is focused on **domain + orchestration**, not everything about the product.

Out of scope here (for now):

- Infra details (deployment, scaling, multi-tenant setup, secrets management).
- Frontend implementation details (Next.js/React components live in the UI repo).
- Pricing, onboarding flows, marketing copy.
- Choice and configuration of specific agent frameworks (LangGraph vs custom, etc.):
  - Engines are specified at the IO + invariants level.
  - Concrete orchestration choices will be documented in the PRD and/or implementation docs.

---

## 7. Status and versioning

Current status:

- `system/03-canonical-objects.md`: initial canonical object set in progress.
- `engines/*.md`: engine specs being defined and aligned with canonical objects.
- `prd/kairo-v1-prd.md`: to be drafted using the coaching-spec style (phase plan, flows).

Simple convention:

- When a breaking change is made to canonical objects or engine IO, update a short status line here and summarise the change in the relevant file.

    Docs version: v0.1 – initial structure and rules established.