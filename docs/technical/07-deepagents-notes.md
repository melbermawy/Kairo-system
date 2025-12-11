# deepagents reference for kairo (context-7)

> this doc exists so codegen always uses **real** deepagents patterns, not hallucinated ones, and keeps them aligned with kairo's architecture + prd-1.

---

## 0. what this is

- this is a **narrow reference** for how kairo uses **LangChain Deep Agents** ("deepagents").
- it does **not** re-spec the product. it just:
  - pins **docs links + version expectations**
  - explains **how deepagents fits** into our django + engines architecture
  - defines **allowed patterns** and **anti-patterns** for agent code

if anything here conflicts with:

- `docs/technical/00-principles-and-anti-goals.md`
- `docs/technical/01-system-architecture.md`
- `docs/technical/04-orchestrator-and-flows.md`
- `docs/technical/05-llm-and-deepagents-conventions.md`
- `docs/technical/06-content-engine-deep-agent-spec.md`

…then **those** win. this doc is a usage aide, not the source of truth.

---

## 1. authoritative docs (what to read)

when you need specifics about deepagents behavior or api, use these:

- deepagents overview
  https://docs.langchain.com/oss/python/deepagents/overview
- quickstart (canonical import + baseline pattern)
  https://docs.langchain.com/oss/python/deepagents/quickstart
- core sections:
  - **agent harness**
    https://docs.langchain.com/oss/python/deepagents/agent-harness
  - **backends**
    https://docs.langchain.com/oss/python/deepagents/backends
  - **subagents**
    https://docs.langchain.com/oss/python/deepagents/subagents
  - **middleware**
    https://docs.langchain.com/oss/python/deepagents/middleware
  - **long-term memory**
    https://docs.langchain.com/oss/python/deepagents/long-term-memory

**rules for codegen:**

- if you're unsure about a deepagents feature, **look it up in those docs**.
- do **not** invent new entrypoints, decorators, or backends that aren't documented there.
- if the library's api changed and our code no longer matches docs, prefer the **docs** and leave a `TODO(version drift)` comment next to the mismatch.

---

## 2. baseline usage pattern we expect

### 2.1 minimal deep agent per official quickstart

the canonical pattern from the quickstart (simplified):

```python
from deepagents import create_deep_agent

def some_tool(...):
    ...

system_prompt = """..."""

agent = create_deep_agent(
    tools=[some_tool],
    system_prompt=system_prompt,
)

result = agent.invoke({"messages": [{"role": "user", "content": "..."}]})
```

that is the mental starting point.

### 2.2 how kairo wraps this

in kairo we never scatter `create_deep_agent` calls everywhere. we:

- define one file per graph under something like:
  - `kairo/agents/hero_opportunities.py`
  - `kairo/agents/hero_package.py`
  - `kairo/agents/hero_variants.py`
  - `kairo/agents/learning_update.py` (later)
- each file exports exactly one public function:

```python
def run_graph(input: GraphInputDTO, ctx: RunContext) -> GraphOutputDTO: ...
```

- that function is the only place where:
  - we construct the deep agent (or reuse a cached one)
  - we call `.invoke(...)` or equivalent

all of this is consistent with:

- `04-orchestrator-and-flows.md` (graphs are orchestration, not business logic)
- `05-llm-and-deepagents-conventions.md` (single llm_client, dto in/out)

---

## 3. where deepagents fits in kairo

restate the architecture in deepagents terms:

- **django services layer**
  - owns persistence, transactions, queries
  - is the only layer allowed to talk to the ORM
- **engines**
  - `opportunities_engine`, `content_engine`, `learning_engine`
  - own business rules and invariants
  - call deepagents graphs as pure functions that transform DTOs
- **deepagents graphs**
  - live under `kairo/agents/*`
  - use tools that call services, not the ORM directly
  - take DTOs, return DTOs
  - never write to the database themselves

**concrete contract (non-negotiable):**

```python
# in opportunities_engine.py
from kairo.agents.hero_opportunities import run_hero_opportunities_graph

def generate_today_board(brand_id: UUID, run_ctx: RunContext) -> TodayBoardDTO:
    snapshot = brands_service.get_brand_snapshot(brand_id)
    learning = learning_service.get_learning_summary(brand_id)
    signals = external_signals_service.get_bundle_for_brand(brand_id)

    graph_input = OpportunitiesGraphInput(
        brand_snapshot=snapshot,
        learning_summary=learning,
        external_signals=signals,
    )

    graph_output = run_hero_opportunities_graph(graph_input, run_ctx)

    # all db writes happen here, in the engine:
    # - persist opportunities
    # - build TodayBoardDTO
    ...
```

the graph:

```python
# kairo/agents/hero_opportunities.py
from deepagents import create_deep_agent
from kairo.llm.client import llm_client  # wrapper per 05-llm-and-deepagents-conventions

def run_hero_opportunities_graph(
    graph_input: OpportunitiesGraphInput,
    run_ctx: RunContext,
) -> OpportunitiesGraphOutput:
    agent = _get_or_create_agent(...)
    result = agent.invoke({
        "messages": [
            {"role": "system", "content": _build_system_prompt(graph_input, run_ctx)},
            {"role": "user", "content": "..."},
        ]
    })
    return _parse_output(result)
```

engines own db writes + invariants. deepagents only orchestrates calls + text reasoning.

---

## 4. allowed tools vs. forbidden tools

### 4.1 allowed tools (kairo)

in PRD-1, tools are thin wrappers over our services. examples:

- `get_brand_context_tool`
  calls `brands_service.get_brand_snapshot` + pillars/personas query, returns a DTO
- `get_learning_summary_tool`
  calls `learning_service.get_learning_summary`, returns DTO
- `get_external_signals_tool`
  calls `external_signals_service.get_bundle_for_brand`, returns DTO
- `get_available_patterns_tool`
  calls patterns service, returns list of `PatternTemplateDTO`
- `get_brand_voice_tool`
  calls brand brain/strategy service

**pattern:** tool → service → ORM, never tool → ORM.

### 4.2 forbidden tools (for now)

within deepagents graphs:

- **no direct http:**
  no `requests`, no raw `httpx`. external web is abstracted behind `external_signals_service` and fixtures.
- **no filesystem tools** that write to arbitrary paths, logs, etc. (we don't need them for hero loop v1).
- **no ad-hoc openai/anthropic calls**; all LLM traffic must go through our `llm_client` abstraction.
- **no db access from tools**; only services call the ORM.

if deeply needed later, those go into a separate PRD with explicit risk analysis.

---

## 5. backend selection & model policy

deepagents can be configured with different backends/providers. for kairo:

- we treat models as **policy**, not random choices.
- `llm_client` owns:
  - which provider/model to use for which graph / subtask
  - temperature, max tokens, timeouts
  - retry policy

deepagents code must not hardcode provider sdk calls. instead, use either:

- the standard `create_deep_agent` path and pass provider config via env
  and still respect our `llm_client` constraints (per `05-llm-and-deepagents-conventions`), or
- a thin backend wrapper that uses `llm_client` under the hood (future work; if we do this, it will be spelled out in that doc).

until explicitly extended:

- assume OpenAI models (e.g. gpt-5.1 family) and keep temperature at or near 0 for anything that must be deterministic.

---

## 6. graph design patterns we allow

### 6.1 "shallow" deep agents for hero loop

for PRD-1 the graphs are intentionally shallow:

- 1 main agent per graph (opportunities, package, variants).
- 3–6 tools each, mostly read-only.
- optional simple planning (todos-style) allowed, but:
  - no arbitrary recursion
  - no unbounded subagent trees

simple target pattern:

```python
agent = create_deep_agent(
    tools=[get_brand_context, get_learning_summary, get_external_signals],
    system_prompt=...,
    # optional: limited planning / subagents as per docs
)

result = agent.invoke({...})
```

### 6.2 subagents: not in PRD-1

- deepagents supports subagents / delegation. we know that.
- we do **not** use subagents in PRD-1 unless the PRD explicitly calls it out and defines:
  - when to spawn
  - how to bound depth
  - how to aggregate results
- if you want subagents, that's a new PRD that defines graphs, tools, and invariants.

---

## 7. middleware, memory, logging

deepagents has middleware + long-term memory features.

for PRD-1:

- **middleware:**
  - allowed only for:
    - adding `run_id` / `brand_id` to prompts
    - logging request/response metadata to our logging layer
  - not allowed for:
    - random side-effects
    - hidden db writes
- **long-term memory:**
  - disabled for hero loop v1.
  - if we ever enable it, it must be wired to the learning engine and its schemas, not an ad-hoc vector store.

all logging still follows:

- `06-content-engine-deep-agent-spec.md` for F2 specifics
- `04-orchestrator-and-flows.md` and PR-map-and-standards for `run_id` behavior

---

## 8. failure behavior + degradation

deepagents graphs must have defined failure behavior; see `04-orchestrator-and-flows.md`. recap:

- **opportunities graph failure:**
  - engine returns:
    - last known Today board if present, marked as degraded
    - or an explicit "no opportunities available" state
- **package / variants graph failure:**
  - engine returns a DTO with clear failure flags
  - no partial db writes of broken variants
- **any tool error:**
  - treated as "tool unavailable → empty result" rather than crash, unless explicitly specified otherwise

the deep agent implementation must:

- catch tool exceptions and map them to graceful outputs (empty bundle, soft warning),
- never leak a stack trace or raw error into user-visible copy,
- always preserve `run_id` in logs for post-mortem.

---

## 9. checklist for codegen before writing deepagents code

whenever you're about to add or modify a graph:

1. **re-read the spec**
   - `04-orchestrator-and-flows.md` for flow behavior
   - `06-content-engine-deep-agent-spec.md` for F2 content flows
   - relevant PR section in `kairo-v1-prd.md`
2. **confirm the location**
   - file under `kairo/agents/...`
   - a single exported function `run_*_graph(...)`
3. **list tools + their services**
   - for each tool, write down the service + DTO it touches
   - ensure tool → service → ORM, never tool → ORM
4. **define inputs/outputs**
   - input DTO(s): e.g. `OpportunitiesGraphInput`
   - output DTO: e.g. `OpportunitiesGraphOutput`
5. **decide failure behavior**
   - what should the engine see if:
     - LLM fails
     - tool fails
     - output parsing fails
6. **wire through llm_client**
   - no direct provider SDK calls
   - ensure we can later plug in fake llm client for tests
7. **tests**
   - at least:
     - happy-path with fake LLM
     - failure path (tool error / malformed output)
     - assert invariants from PRD

if a proposed change breaks any of the above, it probably belongs in a new PRD or at least a PRD update.

---

## 10. future extensions (explicitly not in PRD-1)

these are allowed in principle but explicitly out of scope for PRD-1:

- agents that:
  - autonomously schedule runs
  - modify brand strategy
  - run arbitrary web research in prod
- long-term memory tied to external vector dbs
- generic "agent for everything" chat beyond the bounded Kairo flows

those should each get:

- their own PRD
- changes to the technical docs (esp. 04, 05, 06)
- explicit risk section (cost, safety, quality)

until then, stick to the narrow, spec-driven use of deepagents described above.
