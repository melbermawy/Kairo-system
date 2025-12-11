# 05 – llm and deepagents conventions

> how we use llms and deepagents in kairo – and what is forbidden

---

## 1. purpose & scope

this doc defines:

- which **llm roles** exist in kairo
- how we use **deepagents** (and where we don’t)
- conventions for:
  - prompts
  - tools
  - schemas
  - logging / safety

it sits on top of:

- `01-architecture-spine.md` (layers)
- `02-canonical-objects.md` (dtos)
- `03-engines-overview.md` (service contracts)
- `04-orchestrator-and-flows.md` (flows f1, f2, f3)

if any deepagents graph, prompt, or agent behavior conflicts with this doc, **this doc is the source of truth**.

---

## 2. llm stack stance

### 2.1 models & providers

- we assume 2 classes of models:
  - **smart** – higher quality, slower, expensive (e.g. for thesis, variants, learning analysis)
  - **fast** – cheaper, used for small rewrites or summaries
- model selection is **config-driven**, not hardcoded in agent graphs:
  - e.g. `LLM_PROFILE_CONTENT_THESIS`, `LLM_PROFILE_VARIANT_DRAFT`, `LLM_PROFILE_SUMMARY`
- switching providers (openai, anthropic, etc.) happens in **one place**:
  - `llm/client.py` (or equivalent) exports:
    - `llm_smart()`
    - `llm_fast()`
    - with consistent interface.

### 2.2 no “god model”

- no single model is allowed to:
  - pick its own tools blindly
  - define its own goals
  - write directly to db
- models operate **inside** orchestrated flows with:
  - small, explicit inputs
  - small, explicit outputs.

---

## 3. allowed llm roles

we only allow llm usage in well-defined **roles**:

1. **thesis synthesizer**
   - takes opportunity + brand strategy + patterns
   - outputs `PackageThesis` dto (see f2).

2. **variant planner / drafter**
   - per channel, chooses pattern and drafts text
   - outputs `VariantPlan` dto with `VariantDraft` entries.

3. **summarizer / explainer**
   - creates short human-facing summaries:
     - today focus line
     - “what worked this week” summaries
   - outputs small text fields in typed models (e.g. `TodayFocusSummaryDTO`).

4. **learning explainer (later)**
   - optional: interpret performance metrics into insights
   - still outputs structured models, not essays.

no other roles (e.g. “tool selection agent”, “autonomous planner”) are allowed unless explicitly added here and documented.

---

## 4. deepagents usage conventions

### 4.1 what deepagents is for

we use deepagents to:

- define *graphs* corresponding to flows:

  - `today_graph.py` → f1.x
  - `package_graph.py` → f2.x
  - `learning_graph.py` → f3.x

- compose nodes of three kinds:
  1. **engine calls** – pure python, business logic
  2. **llm nodes** – transform bounded context → typed outputs
  3. **small transforms** – mapping / filtering / scoring, no i/o

- control **error branching** (what happens if a node fails).

### 4.2 what deepagents is not allowed to do

- cannot talk directly to:
  - supabase
  - postgres
  - external apis (linkedin/x/etc.)
- cannot modify canonical objects directly:
  - only engines can write.
- cannot invent new flows at runtime:
  - graphs are declared once in code.
- cannot auto-discover tools:
  - “available tools” per node are fixed in code.

### 4.3 node patterns

we standardize a few node templates:

1. **engine node**
   - type: `EngineNode`
   - input: ids + simple parameters
   - output: dto(s) from `02-canonical-objects.md`
   - no llm use.

2. **llm node (structured)**
   - type: `LLMNode`
   - input:
     - small dto subset
     - a model_alias (`smart` or `fast`)
     - a pydantic schema for output
   - output:
     - `BaseModel` subclass (e.g. `PackageThesis`, `VariantPlan`).
   - cannot call tools or mutate engines.

3. **llm tool node (optional, later)**
   - we may allow tool-using llm nodes later, but:
     - tools must be thin wrappers around engines
     - tool set is explicit and tiny per node
     - all tool calls must be loggable and reproducible.

if we introduce tool-using llm nodes, this doc must be updated first.

---

## 5. prompt conventions

### 5.1 general rules

- all prompts are **programmatic**, not hand-typed in flows.
- every llm node has:
  - `system` template
  - `instructions` or `user` template
  - optional `examples` section (few-shot)
- prompts are **versioned** or named:
  - e.g. `content_thesis_v1`, `linkedin_variant_v1`
- prompts must:
  - mention the **schema** explicitly
  - emphasise what is **forbidden** (e.g. violating taboos)

### 5.2 content + strategy prompts

for content / pattern / brand-related tasks:

- system content must include:
  - role: “you are a content strategist for {brand_name}…”
  - constraints:
    - never violate brand taboos
    - keep within specified tone tags
    - avoid platform policy violations
- user/instructions:
  - include **labels**, not raw blobs:
    - `opportunity.title`
    - `opportunity.angle`
    - `persona.name`, `persona.goals`
    - `brand_strategy.positioning`
  - keep total tokens small:
    - no dumping of entire strategy docs.
- always restate:
  - target **channel**
  - target **persona**
  - objective (drive awareness, shape thinking, etc.)

### 5.3 structured output enforcement

every llm node must:

- declare `output_model` (pydantic)
- validate raw response against schema:
  - invalid → one retry with clearer error message
  - still invalid → node fails, flow decides what to do
- *never* return “raw html” or markdown for internal consumption:
  - the only exception is if a field is explicitly `html_text` or `markdown_text`.

---

## 6. tools & engine access from llm

### 6.1 default: no tools

by default, llm nodes:

- **cannot** call tools.
- receive a **snapshot** of engine results via dto input.
- are pure transforms.

this keeps:

- state changes explicit in orchestrator
- llm behavior easier to reason about.

### 6.2 future: narrow tool windows

if we introduce tools, they must obey:

- each llm node has at most **one** tool group:
  - e.g. only `PatternsEngine`-related methods for a pattern-selection node.
- each tool:
  - exactly mirrors an engine method
  - returns dtos already known to the schema layer
- usage:
  - tool calls are used to *refine* reading, not to mutate state.
- state writes remain engine-only:
  - even if an llm chooses which pattern id to use, the actual write to db happens in a non-llm node.

until this is implemented properly, **we do not enable deepagents tool-usage**.

---

## 7. safety, guardrails, and red lines

### 7.1 content safety

required controls:

- respect `brand_strategy.taboos`:
  - llm prompts must always include the current taboos list.
- avoid:
  - hate / harassment
  - medical or legal advice framed as fact
  - discriminatory content
- we rely on a combination of:
  - model-level safety
  - prompt constraints
  - optional post-generation filters (non-llm) for obvious red flags.

### 7.2 hallucination boundaries

we explicitly forbid the llm from:

- fabricating:
  - fake performance metrics
  - nonexistent products or company facts
- making claims about:
  - actual linkedin/x behavior or numbers
  - real-world entities beyond what the context provides.

allowed:

- plausible-sounding generic content (“CMOs often struggle with…”)
- variant rationales that stay in the generic domain.

rule of thumb: **if the ui might be interpreted as a factual claim about a real external system, the data must come from engines, not the llm.**

### 7.3 personal data

- llm context must **not contain**:
  - raw emails
  - real customer pii beyond what’s absolutely necessary
- ids and slugs, not names, where possible.

---

## 8. logging, observability, evaluation

### 8.1 logging

for every llm node call we capture:

- correlation id (flow run id)
- node name (e.g. `f2_thesis_node_v1`)
- model profile (`smart` / `fast`)
- input metadata (hashes or truncated snippets, *not* entire context)
- output model (structured, possibly truncated)
- validation result (pass/fail)
- latency and token usage (if available).

logs must *never* include:

- full user data
- raw platform event payloads.

### 8.2 replay & offline eval

- we maintain the ability to:
  - re-run a flow with **recorded engine outputs** and different llm prompts/models
  - compare outputs.
- flows should be structured so:
  - engine data fetching can be stubbed/mocked
  - llm nodes can be replaced by test doubles.

### 8.3 golden tests

for key nodes (at minimum):

- thesis generation
- variant drafting
- today focus summary

we maintain:

- a set of **golden inputs** (dto snapshots)
- expected **structural outputs** (not exact text, but constraints)
  - e.g. number of bullets, presence of taboo avoidance.

---

## 9. anti-patterns (do not do this)

1. **open-ended agents**
   - “you are an agent with tools X, Y, Z, achieve goal K”
   - forbidden unless explicitly approved and documented.

2. **raw db access from llm**
   - no sql in prompts, no free-form data dumps.

3. **giant context blobs**
   - dumping entire brand history / “everything about this tenant” into the model.

4. **free text outputs for core flows**
   - “write whatever you want for the ui and we’ll just display it”.
   - all core flows must use structured dtos.

5. **llm as arbitrator of invariants**
   - “decide whether this is safe to publish and update db”
   - invariants live in engines, not prompts.

---

## 10. open questions / v2

things we’re explicitly *not* solving in v1, but may later:

- tool-using llm nodes:
  - pattern auto-discovery from large pattern spaces
  - dynamic persona synthesis from event streams
- multi-step self-critique loops:
  - where a second llm pass critiques / revises the first pass
- multi-model blending:
  - using a small model to pre-score candidates, larger model to refine top-k.

any of these, if adopted, must:

- be added to this doc
- come with:
  - clear safety constraints
  - test harness
  - observability hooks.

---

## 11. summary

in short:

- **engines** own data and invariants.
- **orchestrator flows** sequence engines + llm nodes.
- **deepagents** is our graph runtime, not our product brain.
- **llms** are tightly scoped workers:
  - synthesize theses
  - draft variants
  - summarize focus
  - explain performance (later)
  - always structured, always bounded.

any new llm usage should be checked against this doc **before** being implemented.