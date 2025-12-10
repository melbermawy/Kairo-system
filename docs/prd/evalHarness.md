# Eval Harness

> offline evaluation harness for the hero loop

---

## 0. What This Eval Harness Is and Isn't

**Is:**

- a scripted experiment that:
  - loads fixed fixtures (brand snapshots + external signals + goldens)
  - calls the real hero loop graphs/endpoints (with your real OpenAI key)
  - computes numeric scores + a human-readable report

**Isn't:**

- not part of pytest unit tests
- not asserting exact strings
- not using LLMs inside the harness (no "judge LLM" nonsense) for v1

---

## 1. Repo Layout

inside the system repo:

```text
eval/
  hero_loop/
    __init__.py
    run_eval.py           # main entrypoint (python script / cli)
    config.py             # constants, thresholds
    fixtures/
      brands/
        brand_revops_saas.json
        brand_devtools.json
        brand_b2c_lifestyle.json
        brand_solo_founder.json
        brand_corporate_b2b.json
      weeks/
        revops_saas_week1_signals.json
        revops_saas_week2_signals.json
        ...
      goldens/
        revops_saas_week1_golden.json
        ...
    scorers.py            # metric implementations
    report.py             # markdown / html report generator
    types.py              # pydantic/dataclasses for eval DTOs
```

later you can add `eval/learning/` etc. but keep PRD-1 focused on hero loop.

---

## 2. Fixtures: What You Actually Store

### 2.1 Brand Fixtures (`fixtures/brands/*.json`)

shape mirrors your canonical objects, but static:

```json
{
  "brand_id": "a-fixed-uuid-for-eval-only",
  "name": "Acme RevOps Intelligence",
  "snapshot": {
    "positioning_summary": "We help B2B SaaS revenue teams...",
    "tone_descriptors": ["direct", "nerdy", "slightly contrarian"],
    "taboos": ["cringe hustle culture", "10x", "magic"],
    "pillars": [
      {"id": "pillar-efficiency", "name": "RevOps efficiency", "description": "...", "weight": 1.0},
      {"id": "pillar-attribution", "name": "Attribution reality", "description": "...", "weight": 1.0}
    ],
    "personas": [
      {"id": "persona-revops-lead", "name": "RevOps leader", "role_title": "Head of RevOps", "summary": "..."}
    ]
  }
}
```

don't overcomplicate: 5 brands with solid snapshots is enough.

### 2.2 Week-Level External Signal Fixtures (`fixtures/weeks/*.json`)

one file per brand-week combination:

```json
{
  "brand_id": "a-fixed-uuid-for-eval-only",
  "as_of": "2025-03-10T00:00:00Z",
  "trends": [
    {
      "id": "trend-revops-consolidation",
      "topic": "revops tool consolidation",
      "normalized_score": 0.8,
      "direction": "up",
      "region": null,
      "channel_hint": "linkedin"
    }
  ],
  "web_mentions": [ ... ],
  "competitor_posts": [ ... ],
  "social_moments": []
}
```

this shape should match `ExternalSignalBundle` from the PRD.

### 2.3 Golden Annotations (`fixtures/goldens/*.json`)

one file per brand-week pair:

```json
{
  "brand_id": "...",
  "as_of": "2025-03-10T00:00:00Z",

  "golden_opportunities": [
    {
      "id": "golden-op-1",
      "title": "Why RevOps teams are drowning in low-quality dashboards",
      "pillar_id": "pillar-efficiency",
      "persona_id": "persona-revops-lead",
      "channel": "linkedin",
      "importance": "high"
    }
  ],

  "golden_packages": [
    {
      "golden_opportunity_id": "golden-op-1",
      "thesis": "Most RevOps dashboards are built for aesthetics, not decisions...",
      "channels": ["linkedin", "x"]
    }
  ],

  "golden_variants": [
    {
      "golden_package_id": "golden-op-1",
      "channel": "linkedin",
      "body": "Every Monday, a RevOps leader logs in to 14 dashboards...",
      "label": "example_good_linkedin_variant"
    }
  ]
}
```

optionally later add `human_ratings` here (clarity 1–5, etc.). for v1, you can seed a few by hand.

**Important:** `golden_opportunity_id`, `golden_package_id`, and `golden_variant_id` are stable, human-maintained IDs used only within the eval harness. They are not DB primary keys and are never written back into the product database.

---

## 3. Eval Types & Wiring

in `eval/hero_loop/types.py` define small dataclasses/pydantic models:

- `EvalBrand`
- `EvalWeekSignals`
- `EvalGolden` (opportunities, packages, variants)
- `EvalCase` (brand + week + golden)

so `run_eval.py` can do:

```python
cases = load_all_eval_cases()
for case in cases:
    run_case(case)
```

---

## 4. How `run_case` Should Work

assume you're running inside the django context so you can call services or HTTP. two options:

For eval runs, the harness must enforce determinism where possible:

- Set a global random seed at the start of the run
- Ensure any graph / LLM calls used for eval run with `temperature=0` and deterministic settings

This is to make repeated runs comparable over time.

- **option A (cleaner):** call django service functions directly
- **option B (closer-to-real):** hit your own HTTP endpoints via requests

for PRD-1, pick A to avoid auth/CSRF headaches, but keep the shape compatible with B.

### 4.1 Pipeline Per Case

for each (brand, week):

1. **hydrate brand in db** (or reset to seeded state)
   - create/update Brand, BrandSnapshot, pillars, personas from fixture
   - this should use your real service layer (`brands_service`)

2. **inject external signals stub**
   - override whatever `external_signals_service.get_bundle_for_brand` would return to instead return the fixture for this case
   - easiest: dependency injection / context manager:

   ```python
   with override_external_signals(case.week_signals):
       today_board = today_service.regenerate_today_board(brand_id)
   ```

3. **run hero loop F1: Today board**
   - call `regenerate_today_board(brand_id)`
   - get back `TodayBoardDTO`

4. **run F2 on top N opportunities**
   - pick e.g. top 3 opportunities from Today
   - for each:
     - `create_package_from_opportunity`
     - `generate_variants_for_package`
   - collect packages + variants

5. **compute metrics**
   - pass `today_board`, generated packages/variants, and goldens into scorer functions

6. **store outputs for inspection**
   - dump per-case output to `eval/hero_loop/out/<brand>_<week>.json` plus a markdown summary

7. **tie into run_id / RunContext**
   - each case must create a `run_id` and pass it through the engines (via the existing RunContext)
   - the stored JSON + markdown for the case must include that `run_id`, so logs and eval outputs can be cross-referenced

---

## 5. Scorers: Concrete Metrics and How to Compute Them

keep v1 simple but non-trivial. don't try to overfit everything at once.

### 5.0 Handling Missing Metrics

Not every eval case will have goldens for every level (opportunities, packages, variants).

Rules:

- If a scorer cannot compute a metric due to missing goldens, it should mark that metric as "N/A" for that case, not 0.
- The markdown report must clearly distinguish "N/A" metrics from low scores.
- Missing metrics should be logged as a warning, but must not crash the eval run.

### 5.1 Opportunity-Level Scorers

implemented in `scorers.py`.

#### 5.1.1 Coverage vs Golden (semantic-ish, but cheap)

minimum viable version (no embeddings):

- for each golden opportunity:
  - compute string similarity between `golden.title` and each generated `op.title` using a simple metric (e.g. Jaccard on word sets or cosine over TF-IDF)
  - treat as "matched" if similarity > threshold (e.g. 0.4–0.5) and pillar/persona align (same or compatible id)
- metric:
  - `coverage = matched_golden_count / total_golden`

later you can switch to embeddings, but this is good enough to start.

#### 5.1.2 Pillar/Persona Alignment

- for each generated `Opportunity`:
  - check if its `pillar_id` / `persona_id` exist in the brand fixture
- metric:
  - `alignment_rate = aligned_op_count / total_ops`

bonus: track distribution of pillars/personas to check diversity.

#### 5.1.3 Clarity (human-rated, optional first pass)

you can:

- store `clarity_score` 1–5 in the golden file per generated opportunity id after manual review, or
- manually review in a separate pass and not wire clarity into numeric scoring yet

v1: skip automatic clarity, but the harness should output a markdown list of opportunities so you can manually annotate later.

### 5.2 Package-Level Scorers

for packages generated from the top N opportunities:

#### 5.2.1 Structural Correctness

auto-check:

- package has non-empty thesis
- channels ⊆ {linkedin, x}
- package links to a valid `opportunity_id`
- taboo phrases not present in thesis

this is basically a boolean; you track % passing.

#### 5.2.2 "Close Enough" to Golden Package

cheap similarity again:

- for each golden package:
  - match to generated package whose opportunity best matches the golden opportunity
  - compute similarity between golden thesis and generated thesis
- track:
  - mean similarity over matched packages

don't obsess, this is just a sanity metric.

### 5.3 Variant-Level Scorers

this is where you measure "accept / light edit" proxy.

#### 5.3.1 Length + Structure

for each variant:

- **linkedin:**
  - character count between [100, 1500]
- **x:**
  - character count <= 320
- taboo check

track % that pass these basic constraints.

#### 5.3.2 "Edit Distance to Golden" Proxy

for cases where you have golden variants:

- align each golden variant to the closest generated variant (within same channel & package) by simple similarity
- compute normalized token-level Levenshtein distance (you can implement a simple word-level edit distance)
- categorize:
  - `dist < 0.2` → "accept-as-is proxy"
  - `0.2 <= dist < 0.5` → "light edit proxy"
- metric:
  - `%approx_accept`, `%approx_light_edit`

this is crude but much better than nothing.

---

## 6. Report Generation

in `report.py`, have a function:

```python
def generate_markdown_report(case_results: list[CaseResult]) -> str:
    ...
```

where `CaseResult` includes:

- `brand_name`, `week_id`
- metrics:
  - `opportunity_coverage`
  - `alignment_rate`
  - `package_structural_pass_rate`
  - `variant_accept_proxy_rate`
- any warnings

the report should have:

- per-case section with key numbers + top 3 best/worst opportunities for eyeballing
- an overall summary that averages metrics across cases and flags when a threshold is violated

thresholds pulled from `config.py`, e.g.:

```python
MIN_OPPORTUNITY_COVERAGE = 0.6
MIN_ALIGNMENT_RATE = 0.8
MIN_VARIANT_ACCEPT_PROXY = 0.25
MIN_VARIANT_LIGHT_EDIT_PROXY = 0.6
```

if any metric falls below, mark it in red or with a `FAIL` label in markdown.

---

## 7. How You Actually Use This Day-to-Day

1. **wire this as a django management command or plain python script:**

   ```bash
   poetry run python -m eval.hero_loop.run_eval \
     --cases all \
     --out eval/hero_loop/out/report_2025-03-10.md
   ```

2. **workflow:**
   - before making prompt/graph changes:
     - run once, save report
   - after changes:
     - run again, diff reports
   - if metrics fall below thresholds:
     - you don't ship; you iterate prompts/graph logic

3. **don't over-automate yet:**
   - v1: human-triggered runs before big changes
   - later you can add a lightweight "smoke eval" in CI that:
     - runs on 1 brand-week
     - checks a minimal subset of metrics
     - fails CI if something is obviously broken
