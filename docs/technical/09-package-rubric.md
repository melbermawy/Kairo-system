# 09-package-rubric

> quality rubric for content packages produced in F2 (`graph_hero_package_from_opportunity`) and persisted by `content_engine`.

---

## 1. purpose

this doc defines what a **good content package** is for PRD-1, and gives concrete rules for:

- what makes a package **invalid**, **valid-but-weak**, or **board-ready**
- how fields in `ContentPackageDTO` are expected to be populated
- how the **graph** vs the **engine** share responsibility for quality

this is what the package graph should optimize for and what the engine should enforce before persistence.

---

## 2. scope

### 2.1 in scope (prd-1)

- packages created via: `create_package_from_opportunity(brand_id, opportunity_id)`
- channels: `linkedin`, `x`, `newsletter` (baseline; others can exist but aren’t required)
- packages whose **source** is:
  - `CreatedVia.ai_suggested`
  - `CreatedVia.manual` seeded in fixtures for eval

### 2.2 out of scope (prd-1)

- full campaign orchestration across weeks/months
- multi-opportunity packages (one package can reference multiple opps, but we design as if **one primary opportunity** per package)
- automated A/B tests or multi-variant optimization
- channel-specific scheduling / posting logic

---

## 3. dto + fields

### 3.1 dto reference

`ContentPackageDTO` (from `kairo.hero.dto`) is the canonical shape.

for rubric purposes, we care especially about:

- `id: UUID`
- `brand_id: UUID`
- `opportunity_id: UUID`
- `title: str`
- `thesis: str`
- `summary: str`
- `primary_channel: Channel`
- `channels: list[Channel]`
- `cta: str | None`
- `pattern_ids: list[UUID] | None`
- `notes_for_humans: str | None`
- `status: PackageStatus` (should start as `draft` in PRD-1)
- `meta: dict[str, Any]` (used for debug/trace only)

### 3.2 required vs optional (prd-1)

for PRD-1, when a package is created by the graph:

- **required (must be non-empty, non-vacuous)**
  - `title`
  - `thesis`
  - `summary`
  - `primary_channel`
  - `channels` (must include `primary_channel`)
- **recommended (strongly preferred)**
  - `cta` (clear next action)
  - `pattern_ids` (valid pattern refs or empty – never invalid ids)
- **optional**
  - `notes_for_humans`
  - extra meta fields in `meta` (for tooling / explanations)

---

## 4. validity categories

we use the same three-way classification as opportunities:

1. **invalid**  
   the package violates hard rules. it must not be shown on the hero board or persisted as “ready for work”.

2. **valid-but-weak**  
   passes hard rules, but scores low on rubric dimensions. allowed on the board, but should not dominate.

3. **board-ready**  
   passes hard rules and meets minimum bar for all core dimensions. this is what we want top-of-board to be.

the graph produces package drafts with enough signals for the engine to:

- tag invalid packages
- down-rank weak ones
- surface a board of mostly board-ready packages

---

## 5. hard validity rules (must-have)

a **content package is INVALID** if any of these are true:

### 5.1 missing or useless thesis

- `thesis` is missing, empty, or “vacuous” (example patterns):
  - “write a post about this”
  - “general marketing post”
  - “talk about the product”
- or `thesis` is just copy-paste of the opportunity title with no extra structure (e.g. no mention of audience / benefit).

### 5.2 no primary channel or invalid channel

- `primary_channel` is missing or not a valid `Channel`
- or `primary_channel` **not** in `channels`

### 5.3 channel set incoherent

- `channels` is empty
- or includes channels that clearly contradict the intent, e.g.:
  - a “long-form explainer” with only `x` selected and no other channels
- or includes channels that the brand has explicitly disabled (later via brand config; for PRD-1 assume all standard channels allowed).

### 5.4 duplicate / conflicting CTAs

- package-level `cta` is missing **and** all variants are expected to carry the CTA from the package (in PRD-1 we assume CTA is at package level)
- or CTA is clearly contradictory (“sign up for newsletter” and “book a demo” mashed together with no priority).

### 5.5 taboo violation (package-level)

- package thesis or summary suggests content that violates `BrandSnapshot.taboos`:
  - banned topics
  - banned tones (e.g. “no fear-mongering”)
  - obvious offensive content
- if taboo is violated, the package is **invalid** regardless of other quality.

### 5.6 no clear opportunity linkage

- `opportunity_id` points to nothing meaningful (graph forgets to bind it)
- or thesis clearly does not correspond to the opportunity (e.g. opportunity is “pricing transparency” and thesis is about “hiring updates”).

---

## 6. core rubric dimensions

for packages that are not invalid, we grade along these axes:

### 6.1 thesis clarity (0–3)

- **0** – thesis unreadable or generic (“make content about topic X”).
- **1** – thesis mentions topic but not audience/benefit.
- **2** – thesis clearly states *audience + problem + angle*.
- **3** – thesis is sharp, specific, and easily actionable across channels.

### 6.2 cross-channel coherence (0–3)

- **0** – channels picked randomly; no shared idea.
- **1** – some sense of shared idea, but unclear order/role across channels.
- **2** – channels each play a role in pushing the same story.
- **3** – channels and their roles are explicitly coherent (e.g. “linkedin: long-form; x: teaser thread; newsletter: deep dive”).

### 6.3 relevance to opportunity (0–3)

- **0** – basically ignores the opportunity.
- **1** – loosely related.
- **2** – clearly anchored to opportunity’s “why now / who cares”.
- **3** – sharp reframing or deepening of the opportunity insight.

### 6.4 CTA quality (0–3)

- **0** – no CTA or contradictory CTA.
- **1** – vague (“learn more”) with no context.
- **2** – clear action that matches package intent.
- **3** – compelling CTA tightly coupled to the offer and channel mix.

### 6.5 brand & pattern alignment (0–3)

- **0** – uses patterns that obviously misfit the brand (tone, promise).
- **1** – patterns plausible but mismatched to objective.
- **2** – patterns generally aligned to brand voice and strategy.
- **3** – patterns are chosen with clear intent (e.g. “confessional story → lesson” for trust-building, not hard sell).

---

## 7. scoring bands and board eligibility

we can define a package “quality score” as:

- `package_score = thesis + coherence + relevance + cta + brand_alignment`  
  where each is in `[0,3]`, so total in `[0,15]`.

**bands:**

- **invalid:** any hard rule violated → `valid=False`, package_score treated as `0`
- **valid-but-weak:** `valid=True` and `package_score ∈ [1,7]`
- **board-ready:** `valid=True` and `package_score ≥ 8`

for PRD-1:

- the engine should **never** persist invalid packages as candidates
- `generate_today_board` should favor opportunities whose top package candidate is board-ready (when PR-9 exists)
- the F2 eval harness should compute per-package scores using exactly this rubric

---

## 8. engine vs graph responsibilities

### 8.1 graph responsibilities

`graph_hero_package_from_opportunity` must:

- always produce:
  - non-empty `title`, `thesis`, `summary`
  - a plausible `primary_channel`
  - a reasonable `channels` list
- attach enough signals (explicit or implied) so the engine can:
  - detect taboo violations (via text analysis vs brand taboos)
  - compute the rubric fields (e.g. mark package weak/board-ready)

graph should **not** know about database or persistence.

### 8.2 engine responsibilities

`content_engine.create_package_from_opportunity` must:

- call the graph, get a `ContentPackageDraft` (DTO)  
- run validation and scoring logic from this rubric:
  - set `valid` flag
  - compute `package_score`
  - decide whether to persist or drop
- enforce taboos before persistence:
  - if taboo violation found → drop or mark clearly unusable (PRD-1: drop)
- enforce idempotency and “one package per opp” rule

---

## 9. examples and anti-examples

### 9.1 clear board-ready example (short)

- opportunity: “pricing transparency worries”
- channels: `linkedin`, `x`, `newsletter`
- thesis: “show how our pricing works in plain numbers to rebuild trust”
- summary: “explain the bill in 3 steps; compare to typical alternatives; invite DMs for edge-case questions.”
- CTA: “book a 15-minute pricing walkthrough with our team.”

this is:

- clear thesis
- channel-appropriate
- strongly aligned with the opportunity

### 9.2 invalid example

- title: “social media campaign”
- thesis: “make some posts about the brand”
- channels: `linkedin`, `x`, `instagram`, `tiktok`, `newsletter`, `youtube`
- CTA: none

this violates multiple hard rules (vacuous thesis, incoherent channels, no CTA) → invalid.

---

## 10. implementation notes (prd-1)

- `is_valid`, `package_score`, and `rubric_breakdown` are **DTO-only** fields; they should not become DB columns in PRD-1 (can live under `meta` or companion DTOs).
- invalid packages must not appear on the hero board; they may be logged for debugging.
- evaluation harness should re-use this rubric for F2 scoring, not invent a separate one.