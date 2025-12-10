# 00 – principles and anti-goals

this doc is the spine for the **system repo**. every engine spec, agent spec, and api design should obey this.

---

## 1. product truths

1. **we are a martech system, not an agent toy**
   - primary value: consistent, on-brand content and decisions for marketers running multiple brands.
   - target user: marketers / strategists, not “prompt engineers”.
   - channels: start with linkedin / x, but model must generalize to other surfaces.

2. **canonical objects are the foundation**
   - everything important is a first-class object:
     - `Brand`, `BrandStrategy`, `Opportunity`, `ContentPackage`, `PatternTemplate`, `LearningEvent`, etc.
   - engines transform these objects, they don’t invent ad-hoc shapes.

3. **engines, not “magic agents”, define capabilities**
   - we have a small set of engines:
     - **brand-brain engine**
     - **opportunities engine**
     - **content engine**
     - **patterns engine**
     - **learning engine**
   - engines have explicit responsibilities, inputs, outputs, and invariants.

4. **the orchestrated flows are the product**
   - user-visible behavior = flows wired across engines:
     - “today board”
     - “package workspace”
     - “pattern exploration”
     - “learning / adaptation”
   - llms and deepagents implement *steps* inside flows, not the flow itself.

---

## 2. architectural principles

1. **django + supabase are the system of record**
   - canonical state = postgres tables, accessed via django models / repositories.
   - no agent or llm writes directly to arbitrary storage.
   - any cache / vector store / fs use is derivative, not the source of truth.

2. **clear layering**

- **persistence layer**  
  django models, repositories, supabase schema.

- **engine layer**  
  pure python services operating on canonical objects / dtos.

- **orchestration layer**  
  deepagents / langgraph graphs calling into engines and tools.

- **api layer**  
  django viewsets / rpc endpoints exposing flows to the ui.

3. **engines own logic, not controllers**
   - views/controllers should be thin:
     - auth / validation / routing
     - call a flow or engine
     - return a dto
   - if business logic lives only in views, something is wrong.

4. **types first, prompts second**
   - for any feature:
     1. define dtos / schemas
     2. define engine interfaces
     3. only then design prompts / deepagents.
   - no free-form llm output without a matching schema.

---

## 3. engine boundaries

for each engine:

- **brand-brain engine**
  - owns structured representation of brand strategy, tone, personas, pillars, taboos.
  - answers: “what does this brand *want* to say and avoid?”
  - does **not** generate full content; it informs other engines.

- **opportunities engine**
  - owns discovery and ranking of opportunities (triggers, trends, competitive moves, internal milestones).
  - answers: “what should this brand talk about *now* and in what priority?”
  - does **not** write posts or packages.

- **content engine**
  - owns creation and evolution of `ContentPackage` and channel variants.
  - answers: “how do we turn opportunities + brand brain into actual content?”
  - may use deepagents heavily, but always within defined contracts.

- **patterns engine**
  - owns rhetorical / structural patterns (hooks, beats, templates).
  - answers: “what shapes work best for this brand + channel + goal?”
  - does not own performance metrics; it consumes them from learning engine.

- **learning engine**
  - owns feedback ingestion and adaptation.
  - answers: “what is working, what’s not, and how should we adjust?”
  - updates weights, preferences, and pattern rankings based on results.

everything else must fit into one of these or be explicitly justified.

---

## 4. deepagents and llm stance

1. **deepagents live inside engines, not above them**
   - allowed locations:
     - `content_engine/agents/*`
     - later: `learning_engine/agents/*`
   - not allowed:
     - “global super-agent” that orchestrates all engines.
     - agents that talk directly to db / supabase.

2. **agents are tools, not the architecture**
   - each agent:
     - has a single clear purpose (e.g. “plan linkedin variants for a package”).
     - uses strict input/output schemas.
     - calls engine methods / tools to fetch data.
   - orchestration layer owns flow composition, not the agents themselves.

3. **llm prompts must be grounded**
   - every llm call should:
     - reference canonical objects (brand, opp, package, pattern) via ids or dtos.
     - be scoped to a single well-defined task.
     - have an explicit expected output schema.

4. **no “agent invents new schema in production”**
   - if an agent suggests a new field / object:
     - it must go through a human-driven design step.
     - only then can the db / dtos change.
   - agents cannot mutate schema online.

---

## 5. data, ownership, and mutability

1. **hard separation: primary vs derived data**
   - **primary**:
     - brand configs, opportunities, packages, patterns, learning events.
   - **derived**:
     - embeddings, caches, intermediate agent plans, traces.
   - only primary data can be relied on by other systems.

2. **no silent destructive writes**
   - engines must not silently overwrite:
     - user edits
     - strategy documents
   - updates must be explicit and traceable (who/what changed what and why).

3. **append-only for learning**
   - `LearningEvent` and similar logs:
     - append-only.
     - never mutated in place.
   - learning engine derives aggregates from events; it doesn’t rewrite history.

---

## 6. anti-goals

what we explicitly **do not** want this system to become.

1. **no “framework soup” for its own sake**
   - we will use deepagents / langgraph, but:
     - only in clearly defined engine areas.
     - only when it adds clarity and reliability.
   - no stacking of frameworks just because they exist (langchain + langgraph + custom “agent runner” + …).

2. **no generic “agent os”**
   - we are not building:
     - a general agent platform.
     - a custom llm ide.
   - the system is purpose-built for brand content workflows.

3. **no everything-through-one-agent routing**
   - no single entrypoint agent that “figures out what to do” for all calls.
   - instead:
     - api endpoints map to flows.
     - flows map to engine calls and, where needed, to deepagents.

4. **no pure wrapper around an llm api**
   - the system must have:
     - real structure.
     - state.
     - learning.
   - if the behavior could be mostly reproduced by “chat with some long prompt”, we failed.

5. **no ad-hoc, per-feature prompts without contracts**
   - “just add a new prompt here” is not allowed.
   - requirements:
     - define or reuse a dto.
     - document behavior in the relevant spec.
     - add tests or fixtures where possible.

---

## 7. non-negotiables for new code

any serious change (new module, new flow, new agent) must:

1. point to the relevant **canonical object** definitions.
2. declare which **engine** owns the logic.
3. respect the layering (no jumping from view → db without engine).
4. follow the **llm + deepagents conventions** doc (once written).
5. avoid adding new global state or config without updating the architecture docs.

if a proposed change violates one of these, it needs an explicit written rationale in `docs/` before being merged.

---

## 8. how to use this doc

when drafting:

- new engine methods  
  → check sections 2 and 3.

- new deepagent / graph  
  → check sections 3 and 4.

- new schema / model changes  
  → check sections 2 and 5.

if something you want to do doesn’t fit in these constraints, update this doc **first**, then adjust the design.

---

## 9. multi-tenant & brand isolation

1. **brand is a first-class boundary**
   - every object that can carry semantics (opportunities, packages, patterns, learning events) is scoped to a `brand_id`.
   - cross-brand sharing (e.g. “global patterns”) must be explicit and documented.

2. **learning is brand-aware**
   - the learning engine never trains or updates purely on mixed-brand data.
   - any cross-brand learning must:
     - be anonymized / aggregated, and
     - be opt-in at the brand level.

3. **agents never see more than they need**
   - deepagents tools only expose data for the current brand (and, if needed, the current user).
   - no “global search” tool that returns arbitrary other-brand state.

---

## 10. observability, traces, and auditability

1. **every flow is traceable**
   - any call from UI → api → engines → llm must have a `correlation_id`.
   - traces include: input dto, engine calls, llm calls (model, params), and resulting writes.

2. **llm calls are first-class events**
   - every llm call is logged as a `ModelCallEvent` with:
     - engine / flow
     - model name + provider
     - input schema version
     - output schema version
     - latency and token usage (where available).

3. **learning changes are auditable**
   - any update to learned weights / rankings stores:
     - which events contributed
     - which algorithm/version was used.
   - it must be possible to answer: “why did this opportunity/pattern get this score?”

---

## 11. testing & simulation

1. **engines must be testable without llms**
   - core engine logic (ranking, state transitions, scoring) must have unit tests with deterministic fixtures.
   - no llm calls inside engine unit tests.

2. **flows get scenario tests**
   - critical flows (today board, package workspace, pattern selection) have scenario tests that:
     - run against seeded demo data
     - assert on dto shapes and invariants (e.g. pinned first, snoozed last).

3. **llm behavior has fixtures**
   - for each llm-backed step, we keep:
     - at least one fixture input → output pair
     - a validation that the schema is respected and critical fields are present.
   - if a model swap breaks fixtures, we either:
     - adjust prompts, or
     - consciously bump a “prompt/behavior version”.