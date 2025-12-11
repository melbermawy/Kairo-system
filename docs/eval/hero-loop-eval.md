# f1 hero-loop eval harness

> offline evaluation spec for the hero loop (today board → packages → variants)

this doc defines **what** we evaluate and **how we score it**.
`evalHarness.md` defines **where the code lives and how it runs**.

---

## 0. scope and goals

**goal:** build a repeatable, offline eval for the **f1 hero loop**:

- inputs:
  - brand snapshot
  - week-level external signals
  - fixed goldens + human labels
- pipeline under test:
  - F1: generate today board opportunities
  - F2: create content packages from top-N opportunities
  - F2.1: generate variants for those packages
- outputs:
  - numeric metrics per case (brand × week)
  - markdown report for human review
  - stable longitudinal view (you can compare runs over time)

**non-goals for PRD-1:**

- no eval for learning loop (that's a later harness)
- no "judge LLM" – all scoring is string / structure based
- no multi-channel expansion beyond `linkedin` and `x`

---

## 1. cases: brands × scenarios

each eval **case** is:

- `EvalBrand` (brand fixture)
- `EvalWeekSignals` (week-level signals fixture)
- `EvalGolden` (goldens for that brand/week)

cases live under `eval/hero_loop/fixtures/{brands,weeks,goldens}` as defined in `evalHarness.md`.

### 1.1 brand archetypes

we want coverage over typical B2B/B2C patterns. start with 5:

1. **revops saas**
   - ICP: head of revops / VP revenue operations
   - pillars: efficiency, attribution reality, tooling consolidation
   - channels: linkedin-heavy, some x

2. **developer tools**
   - ICP: staff+ engineers, eng managers, CTO
   - pillars: developer ux, reliability, infra economics
   - channels: x-heavy, some linkedin

3. **b2c lifestyle / wellness**
   - ICP: busy professionals; wellness-curious consumers
   - pillars: education, behind-the-scenes, social proof
   - channels: instagram/tiktok **in strategy**, but eval focuses on linkedin/x abstractions

4. **solo founder / creator**
   - ICP: solo SaaS / info-product founder
   - pillars: build-in-public, case studies, contrarian takes
   - channels: x-first, some linkedin

5. **corporate b2b**
   - ICP: director+ at large enterprises
   - pillars: thought leadership, compliance, risk
   - channels: linkedin-only in practice

### 1.2 week scenarios per brand

for each brand, define 2–3 weeks:

- **week A – "normal"**
  - a few medium-intensity trends
  - some web mentions
  - 1–2 competitor posts
- **week B – "spike"**
  - 1–2 very strong, time-sensitive trends ("why now" heavy)
  - obvious opportunities for "we have to talk about X this week"
- **week C – "quiet"** (optional)
  - weak external signals
  - tests whether engine falls back to evergreen / pattern-based opps instead of hallucinating fake trends

target: **10–12 total cases** (5 brands × 2 weeks, plus a quiet week or two where useful).

---

## 2. metrics overview

we evaluate on three levels:

1. **board-level (F1)**
   "is this a strong portfolio of opportunities for this brand, this week?"

2. **opportunity-level**
   "are individual opps on-rubric: clear, on-pillar, differentiated?"

3. **package/variant-level (F2)**
   "given a good opp, does the system produce reasonable packages and almost-usable copy?"

plus: overall **report-level** classification per case:

- `GOOD` / `PARTIAL` / `BAD` board (as per opportunity rubric doc §8)

this doc defines the **metrics + thresholds**.
`evalHarness.md` defines where scorers live (`eval/hero_loop/scorers.py`).

---

## 3. board-level metrics (F1)

these are computed from `TodayBoardDTO` (after the engine's filtering).

### 3.1 opportunity coverage vs goldens

**what:**
how many golden opps are "covered" by generated opportunities.

- for each `golden_opportunity`:
  - compute a simple similarity between `golden.title` and each generated `op.title`
    - e.g.: cosine over TF-IDF, or token Jaccard
  - require:
    - similarity ≥ `TITLE_SIM_THRESHOLD` (start at 0.4–0.5), **and**
    - pillar/persona compatible (same id or explicit mapping table)
- let `matched_golden_count` be the number of goldens with at least one match.

**metric:**

```text
opportunity_coverage = matched_golden_count / total_golden
```

**targets:**

- `GOOD`: ≥ 0.60
- `PARTIAL`: [0.30, 0.60)
- `BAD`: < 0.30

### 3.2 pillar / persona diversity

**what:**
board should not be single-pillar, single-persona unless the brand is intentionally that narrow.

for all generated opportunities:

- pillar distribution: freq of `primary_pillar_id`
- persona distribution: freq of `primary_persona_id`

**metrics:**

- `pillar_coverage = distinct_pillars_on_board / distinct_pillars_in_brand_fixture`
- `persona_coverage = distinct_personas_on_board / distinct_personas_in_brand_fixture`

**targets:**

- `pillar_coverage` ≥ 0.6 (unless brand fixture only has 1–2 pillars)
- `persona_coverage` ≥ 0.5 (unless brand fixture is single-persona)

### 3.3 redundancy

**what:**
avoid 8 opps that are all the same idea.

for each pair `(opp_i, opp_j)` in the board:

- compute title similarity (`sim_title`)
- compute "reason" similarity from thesis/angle if needed

flag "near duplicates" where `sim_title ≥ 0.75`.

**metric:**

```text
redundancy_rate = near_duplicate_pairs / total_pairs
```

**targets:**

- `GOOD`: `redundancy_rate` ≤ 0.20
- `PARTIAL`: 0.20 < `redundancy_rate` ≤ 0.35
- `BAD`: `redundancy_rate` > 0.35

### 3.4 board size and score distribution

using the scoring rubric (0–100) from the opportunities doc:

- **board size:** count of opps
  - hard minimum: 8
  - target: 8–16 (16 is a soft upper bound, not a hard cap)
- **score distribution** (targets, not hard gates):
  - at least 2 opps with score ≥ 80
  - at least 5 opps with score ≥ 65
  - no opp with `is_valid=false` or `score=0`

**classify:**

- `GOOD` board if:
  - size ≥ 8,
  - `opportunity_coverage` ≥ 0.6,
  - `redundancy_rate` ≤ 0.35,
  - at least 2 opps ≥ 80.
- `BAD` board if:
  - size < 5, or
  - `opportunity_coverage` < 0.3, or
  - any invalid opp appears (should never happen), or
  - all opps < 60.
- else `PARTIAL`.

---

## 4. opportunity-level metrics

computed on each valid opportunity (graph outputs with `is_valid=true`).

### 4.1 rubric compliance

hard requirements are already encoded in the rubric doc. here we measure:

- `%opp_passing_hard_checks = valid_opps / total_opps_generated` (before engine drops invalids)

where "hard checks" are:

- non-empty `title`, `thesis`, `why_now`
- valid `primary_pillar_id` and `primary_persona_id`
- `primary_channel` in `{linkedin, x}` for PRD-1
- no taboo / safety violations for the brand

**targets:**

- want ≥ 0.90 valid at the graph level
- anything below 0.75 is a red flag

### 4.2 clarity and "why now" (cheap proxies)

no judge LLM. we use cheap features:

- **length bounds** on `title`, `thesis`, `why_now`
  - e.g. title 5–20 words, thesis 20–80, why_now 10–50
- **presence of:**
  - temporal cues in `why_now` ("this week", "right now", "recent", etc.)
  - concrete nouns (from simple POS tagging or heuristics)
- **simple "boilerplate" detection:**
  - e.g. if the same `why_now` appears on > 3 opps → penalize

**metrics:**

- `clarity_pass_rate = opps_meeting_length_and_non_boilerplate_criteria / total_valid_opps`
- `why_now_signal_rate = opps_with_temporal_cues / total_valid_opps`

targets are soft; we mainly track trends across runs.

### 4.3 channel fit

we check:

- if `primary_channel == linkedin`:
  - is the title plausible as a linkedin post topic?
  - length, style (no raw hashtags spam, etc.)
- if `primary_channel == x`:
  - shorter, more "hooky" titles, char limit respected in variants (see below)

**metric:**

- `channel_fit_rate = opps_where_channel_matches_golden_or_brand_channel_preferences / total_valid_opps`

where "matches" is:

- channel ∈ brand's configured preferred channels in its strategy, or
- channel matches golden channel for that topic

---

## 5. package-level metrics (F2)

we evaluate packages generated from the top N opportunities per case (N ≈ 3).

### 5.1 structural correctness

each generated `ContentPackageDTO` must:

- have non-empty `thesis`
- reference a valid `opportunity_id`
- have `channels ⊆ {linkedin, x}`
- respect brand taboos in thesis

**metric:**

```text
package_structural_pass_rate = packages_passing / packages_generated
```

**target:**

- ≥ 0.9 for PRD-1

### 5.2 closeness to golden packages

for each `golden_package`:

- match the generated package whose opportunity best matches the `golden_opportunity` for that case
- compute similarity between `golden.thesis` and `generated.thesis` as in §3.1

**metric:**

```text
package_thesis_similarity_mean = mean(similarity over matched pairs)
```

this is descriptive; we don't hard gate in PRD-1, but we expect:

- "good" cases: mean similarity ≥ 0.5
- "bad" cases: mean similarity < 0.3

---

## 6. variant-level metrics (F2.1)

variants are the closest proxy for "accept / light edit".

### 6.1 structural constraints

per variant:

- **linkedin:**
  - char count ∈ [100, 1500]
- **x:**
  - char count ≤ 320
- no taboo terms
- must reference some concrete detail (cheap heuristic: at least X content words)

**metric:**

```text
variant_structural_pass_rate = structural_pass_variants / total_variants
```

**target:** ≥ 0.85.

### 6.2 "edit distance to golden" proxy

where golden variants exist:

- align each golden variant to the closest generated variant within same channel and package
- compute word-level normalized edit distance (Levenshtein / max_len)

**categorize:**

- `dist < 0.2` → accept-as-is proxy
- `0.2 ≤ dist < 0.5` → light-edit proxy
- `dist ≥ 0.5` → heavy-edit / off

**metrics:**

```text
variant_accept_proxy = %variants_with_dist<0.2
variant_light_edit_proxy = %variants_with_0.2<=dist<0.5
```

**targets (soft for PRD-1):**

- `variant_accept_proxy` ≥ 0.25
- `variant_light_edit_proxy` ≥ 0.6

---

## 7. goldens and human labels

### 7.1 goldens

we already defined the golden fixture shape in `evalHarness.md`. key points:

- `golden_opportunity_id`, `golden_package_id`, `golden_variant_id` are eval-only, not DB ids
- goldens should be written as "this is what a good week looks like" for each brand/scenario

### 7.2 human labels (later extension)

for v1, we keep it simple:

- numeric metrics only
- markdown report lists:
  - opportunities
  - packages
  - variants

later:

- add optional per-opportunity human fields:
  - `clarity_rating` (1–5)
  - `brand_fit_rating` (1–5)
  - `keep_edit_discard` label
- store them in goldens or a parallel `human_labels` file

for now: the harness should make it easy to annotate later:

- stable ordering
- stable IDs in output files
- same JSON shape every run

---

## 8. wiring to evalHarness.md

this section ties the spec to the concrete harness layout.

### 8.1 types

`eval/hero_loop/types.py` should define:

- `EvalBrand` – wraps brand fixture, knows how to hydrate DB via services
- `EvalWeekSignals` – wraps external signal fixtures
- `EvalGolden` – wraps per-level goldens
- `EvalCase` – `{ brand: EvalBrand, week_signals: EvalWeekSignals, goldens: EvalGolden, case_id: str }`
- `CaseResult` – metrics + references needed for the report

### 8.2 run_case

`run_case(case: EvalCase) -> CaseResult` must:

1. hydrate brand in DB (using real services)
2. inject external signals for that case (override service)
3. create a `RunContext` with a fresh `run_id`, flow `F1_today`, trigger `eval`
4. call:
   - `today_service.regenerate_today_board(brand_id, ctx=...)`
   - `content_packages_service.create_package_from_opportunity(...)`
   - `variants_service.generate_variants_for_package(...)`
5. compute all metrics from sections 3–6
6. dump raw artifacts:
   - JSON snapshot of:
     - today board
     - any packages/variants generated
     - computed metrics
   - include `run_id` in the JSON and markdown
7. return `CaseResult`

### 8.3 scorers

`eval/hero_loop/scorers.py` must expose something like:

- `score_board(case: EvalCase, today_board: TodayBoardDTO) -> BoardMetrics`
- `score_opportunities(...) -> OpportunityMetrics`
- `score_packages(...) -> PackageMetrics`
- `score_variants(...) -> VariantMetrics`

`CaseResult` aggregates:

- `board_metrics`
- `opportunity_metrics`
- `package_metrics`
- `variant_metrics`
- derived classification: `board_quality ∈ {GOOD, PARTIAL, BAD}`

---

## 9. usage and thresholds

### 9.1 day-to-day usage

- before changing prompts/graphs:
  - run eval on all cases, save report
- after changes:
  - run eval again, diff:
    - if coverage, diversity, or structural pass rates regress below thresholds:
      - don't ship; fix prompts/graph
  - store reports under `eval/hero_loop/out/` with dates

### 9.2 minimum bar to ship PRD-1 hero loop

for a change to be shippable, we want:

- no `BAD` boards
- at least 70% of cases classified as `GOOD`
- across all cases:
  - `opportunity_coverage` mean ≥ 0.6
  - `package_structural_pass_rate` mean ≥ 0.9
  - `variant_structural_pass_rate` mean ≥ 0.85

if any of these regress significantly vs previous run, the change is suspect.

---

## 10. future extensions (out of scope for PRD-1)

- add learning-loop eval: stability and improvement over time
- add embedding-based scorers for semantic coverage / style fit
- add light judge LLM for second-opinion scoring (with guardrails)
- wire a smoke eval into CI (1 brand/week, subset of metrics)

for now, this harness is manual, dev-triggered, and focused on catching obvious regressions and sanity-checking quality of F1 hero loop.
