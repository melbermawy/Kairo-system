# PRD map

> master index of all kairo PRDs and their structure

---

## 0. global PRD structure (applies to every PRD)

each PRD must follow the same skeleton so claude code can't freestyle:

1. **context & scope**
   - what this PRD covers, what it explicitly *does not* cover.
2. **goals & success criteria**
   - 3–5 concrete "done means" bullets.
3. **non-goals / out of scope**
   - things that *sound* related but are banned from this PRD.
4. **actors & canonical objects**
   - which actors (marketer, brand, orchestrator)
   - which canonical objects (Brand, Persona, Pillar, PatternTemplate, Opportunity, ContentPackage, Variant, ExecutionEvent, LearningEvent, etc.)
5. **flows & states**
   - 2–4 named flows (F1.x, F2.x, etc.)
   - state diagrams or step lists from input → output.
6. **deepagents graph & node specs**
   - for each flow: node list with:
     - inputs
     - outputs
     - contracts / invariants
     - where LLM is allowed vs pure logic
7. **data contracts**
   - JSON-ish schemas for:
     - incoming payloads
     - internal artifacts
     - outgoing results
   - versioning strategy where relevant.
8. **failure modes & fallbacks**
   - table: failure → detection → fallback → user-facing behavior.
9. **telemetry & evaluation**
   - events to log
   - metrics to track (per flow + per node)
   - any offline eval / golden cases.
10. **safety & brand guardrails**
    - how brand taboos / risk filters are enforced in this slice.
11. **open questions & future hooks**
    - what we're *deliberately* punting on, but leaving hooks for.

if a PRD doesn't have these sections, it's not a real PRD.

---

## PRD-1 — hero slice: today → package → variants (content loop v1)

**working title:** `prd-1-hero-content-loop.md`

**scope:** single marketer, single brand, linkedin + X only.

### what this PRD owns

- the **core daily loop**:
  - F1.1: "today board" generation from existing opportunities.
  - F1.2: marketer picks one opportunity.
  - F1.3: create a **ContentPackage** from that opportunity.
  - F1.4: generate initial LinkedIn + X variants.
- content-engine deepagents graphs:
  - align with `06-content-engine-deep-agent-spec.md`.
- UI ↔ backend contracts for:
  - today board
  - packages list
  - package workspace.

### key flows to spec

- **F1.1**: build Today board for a brand
- **F1.2**: create package from opportunity
- **F1.3**: generate multi-channel variants
- **F1.4**: regenerate a single channel
- **F1.5**: resync after manual edits

### critical cross-cut pieces

- **data contracts**: for Opportunity, ContentPackage, Variant must be final here.
- **eval**: define "good" vs "bad" variants (structure, taboo holes, tone).
- **failure modes**: no viable variants, conflicting brand constraints, etc.
- **safety**: strict taboo enforcement and factuality checks baked into nodes.

this PRD should feel very close to the nymble coaching PRD in structure.

---

## PRD-2 — brand bootstrapping & strategy: getting a useful brand brain

**working title:** `prd-2-brand-bootstrapping.md`

**scope:** how a brand goes from zero → "usable" brand brain that can power PRD-1.

### what this PRD owns

- ingesting messy brand inputs:
  - website, existing posts, briefing text, docs.
- generating:
  - `BrandSummary`
  - `Personas`
  - `ContentPillars` (incl. "Launch & Promos" etc.)
  - Tone descriptors
  - Guardrails / taboos
- aligning with Brand and BrandStrategy canonical objects.

### key flows

- **F2.1**: "fast bootstrap" (marketer pastes homepage + 3 posts)
- **F2.2**: "deep bootstrap" (multi-source ingest)
- **F2.3**: brand strategy refinement loop (human edits → update BrandBrain)

### critical cross-cut pieces

- **data contracts**:
  - input sources (URLs, raw text blobs, structured questionnaires).
  - BrandStrategy schema (must match canonical docs).
- **eval**:
  - consistency checks: personas vs pillars vs taboos.
  - textual quality checks: no generic "we're innovative" garbage.
- **safety**:
  - ensure the brand brain *reduces* risk downstream, not amplifies it.

PRD-2 is what keeps PRD-1 from being "generic copy factory".

---

## PRD-3 — learning & feedback engine: closing the loop

**working title:** `prd-3-learning-feedback.md`

**scope:** from shipped content + metrics → updated scores, patterns, focus recommendations.

### what this PRD owns

- how **ExecutionEvents** and **metrics** are ingested:
  - per channel, per variant.
- how **LearningEvents** are created:
  - e.g., "pattern X underperforms on persona Y on X"
  - "pillar Z + this hook style performs 30% above baseline on LinkedIn"
- how this feeds back into:
  - opportunity scoring
  - pattern ranking
  - hero-slice recommendations ("focus on this pillar this week").

### key flows

- **F3.1**: ingest execution + metric payloads into canonical `ExecutionEvent`
- **F3.2**: batch learning update (nightly job) → `LearningEvents`
- **F3.3**: serve updated weights to:
  - Today board (opp scoring)
  - Pattern recommendations
  - Brand suggestions ("you're over-reliant on X pattern").

### critical cross-cut pieces

- **data contracts**:
  - `ExecutionEvent` schema (gracefully handling incomplete metrics).
  - `LearningEvent` schema (what gets stored, how it's versioned).
- **failure modes**:
  - missing or noisy metrics
  - degenerate learning (overfitting a tiny sample).
- **eval**:
  - offline simulations against seeded data.
  - dashboards for "before vs after" on quality / engagement.
- **safety**:
  - prevent learning from drifting into spammy / manipulative tactics.

this PRD is what makes kairo "compound" instead of static.

---

## PRD-4 — opportunity acquisition & ranking: filling the funnel

**working title:** `prd-4-opportunity-acquisition.md`

**scope:** creating structured **Opportunities** on a rolling basis from external + internal signals.

### what this PRD owns

**opportunity sources:**

- **google trends** (topical spikes by region / category).
- **web search / blogs / news** (agent to scan and cluster relevant topics).
- **competitor scraping**:
  - competitors' posts per channel.
  - extract formats, topics, angles.
- **social trend ingestion**:
  - hashtags, trending formats, memes relevant to the brand's category.

**internal signals:**

- decayed backlog (untouched opps)
- learning engine suggestions.

### key flows

- **F4.1**: daily "opportunity fetch" job per brand
- **F4.2**: deduplication + clustering of candidate ideas
- **F4.3**: opportunity scoring & alignment to:
  - brand pillars
  - personas
  - current "focus areas" from learning engine
- **F4.4**: writing these into canonical `Opportunity` objects

### critical cross-cut pieces

- **data contracts**:
  - source-specific raw payload vs normalized Opportunity.
- **failure modes**:
  - google trends empty for a niche brand.
  - crawlers blocked / rate-limited.
  - conflicting signals between sources.
- **eval**:
  - human-judged sample: "would a marketer actually consider this opportunity?"
  - coverage vs noise metrics.
- **safety**:
  - filter out risky / low-taste topics.
  - handle sensitive events (politics, tragedies) with strict rules.

PRD-4 is where your "opportunities engine" becomes real instead of lorem.

---

## PRD-5 — multi-brand, agency mode & governance

**working title:** `prd-5-multi-brand-and-governance.md`

**scope:** multiple brands, one marketer, clean isolation and context propagation.

### what this PRD owns

- **multi-brand structure**:
  - marketers attached to multiple Brands.
  - brand switching in UI & orchestration.
- **tenant isolation**:
  - data separation by Brand (and optionally org).
- **governance**:
  - roles (owner, editor, viewer).
  - audit trail for key actions (publishing, editing taboos, etc.).
- **orchestrator behavior**:
  - ensuring flows always run "within" the right brand.

### key flows

- **F5.1**: "switch brand" flow (within orchestrator + UI + LLM context).
- **F5.2**: permission checks on sensitive actions:
  - editing brand strategy
  - publishing content
  - editing taboos.
- **F5.3**: audit & traceability:
  - who approved what, when, with which LLM calls involved.
- **F5.4**: org onboarding (agency adds/organizes multiple brands).

### critical cross-cut pieces

- **data contracts**:
  - user ↔ brand ↔ org associations.
  - audit event schema (tie LLM decision trails to human actions).
- **failure modes**:
  - cross-brand leakage (LLM using wrong brand's brain).
  - permission bugs (a junior can override taboos).
- **eval**:
  - tests that explicitly assert isolation properties.
  - targeted red-team prompts to test cross-brand leakage.
- **safety**:
  - governance around editing taboos / guardrails.
  - enforce that "dangerous" flows always require human confirmation.

this PRD is what makes your system believable to serious agencies.
