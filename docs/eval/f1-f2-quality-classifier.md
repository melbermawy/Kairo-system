# F1 / F2 Quality Classifier (Hero Loop)

Spec for classifying hero loop runs as **good** / **partial** / **bad** based on F1 (opportunities) and F2 (packages + variants) quality.

---

## 1. Purpose

This document defines concrete metrics and thresholds for judging the quality of the hero loop:

- **F1**: Opportunities board (from `opportunities_engine.generate_today_board`)
- **F2**: Content packages + variants (from `content_engine.create_package_from_opportunity` and `content_engine.generate_variants_for_package`)

And how these roll up into a run-level label:

| Label | Meaning |
|-------|---------|
| **good** | You'd happily work from this output with light edits |
| **partial** | Salvageable but inconsistent |
| **bad** | You'd rather start from scratch |

This is eval-harness only logic. Nothing in here should gate real-time behavior directly; instead, it informs iteration and CI-style quality checks.

---

## 2. Scope and Inputs

We assume the eval harness produces, per run (`HeroEvalResult`-like object):

### Structural Stage Status

- `f1_status` ∈ `{"ok", "degraded", "failed"}`
- `f2_status` ∈ `{"ok", "degraded", "failed"}`
- `is_structurally_valid()` → `bool`
  - Returns `False` if `f1_status == "failed"` or `f2_status == "failed"`

### Metrics Dict

#### F1 Metrics (Opportunities Board)

| Metric | Type | Description |
|--------|------|-------------|
| `board_size` | `int` | Number of opportunities on the board |
| `strong_fraction` | `float` | Fraction of opportunities with score ≥ 80 |
| `weak_fraction` | `float` | Fraction with score < 60 |
| `invalid_fraction` | `float` | Fraction with `is_valid == False` (after graph, before engine filtering) |
| `redundancy_rate` | `float` | Fraction of pairs deemed redundant (high Jaccard similarity) |
| `taboo_violations_count` | `int` | Count of opportunities with taboo violations |
| `opportunity_coverage` | `float \| None` | Fraction of golden opportunities represented on the board (if goldens exist) |

#### F2 Metrics (Packages + Variants)

**Package-level:**

| Metric | Type | Description |
|--------|------|-------------|
| `mean_package_score` | `float` | Average package score (0–15) |
| `board_ready_package_fraction` | `float` | Fraction of packages with `quality_band == "board_ready"` |
| `execution_clarity_rate` | `float \| None` | Fraction of packages that satisfy a basic "execution clarity" heuristic (e.g. non-empty thesis, explicit CTA, at least one concrete structure element) |
| `faithful_package_fraction` | `float \| None` | Fraction of packages where a judge labels thesis as "faithful" to source opportunity |

**Variant-level:**

| Metric | Type | Description |
|--------|------|-------------|
| `publish_ready_fraction` | `float` | Fraction of variants with `quality_band == "publish_ready"` |
| `invalid_variant_fraction` | `float` | Fraction with `quality_band == "invalid"` |
| `voice_alignment_ok_fraction` | `float \| None` | Fraction where judge labels brand voice as `{strong, ok}` |
| `channel_fit_ok_fraction` | `float \| None` | Fraction where judge labels channel fit as `{strong, ok}` |

> **Note:** Fields marked `| None` may be absent in early PRD-1. The classifier must degrade gracefully if a metric is missing (see §5.3).

---

## 3. F1 Quality Classification (Opportunities)

### 3.1 Intuition

An F1 "good" board should:

- Have enough opportunities (at least 8)
- Have mostly strong opportunities
- Have low redundancy
- Have no taboo violations
- Have no invalid junk slipping through
- Ideally, cover a decent chunk of goldens

### 3.2 Thresholds

We define:

- `strong_fraction = strong_count / board_size`
- `weak_fraction = weak_count / board_size`
- `invalid_fraction = invalid_count / raw_candidate_count`
- `redundancy_rate ∈ [0, 1]`
- `opportunity_coverage ∈ [0, 1]` or `None`

#### 3.2.1 Hard Failure Gates

These immediately mark F1 as **bad**:

| Condition | Threshold |
|-----------|-----------|
| `taboo_violations_count` | > 0 |
| `board_size` | < 4 |
| `invalid_fraction` | > 0.05 (more than 5% of raw candidates invalid) |

#### 3.2.2 "Good" Band

F1 is **good** if ALL of:

- `board_size >= 8`
- `strong_fraction >= 0.5`
- `invalid_fraction == 0` (or ≤ 0.01 if kept)
- `redundancy_rate <= 0.3`
- If `opportunity_coverage` is available: `opportunity_coverage >= 0.6`

#### 3.2.3 "Partial" Band

F1 is **partial** if not good, but:

- `board_size >= 6`
- `strong_fraction >= 0.25`
- `invalid_fraction <= 0.05`
- `redundancy_rate <= 0.5`
- If `opportunity_coverage` is available: `opportunity_coverage >= 0.4`

Anything else (that isn't hard-failed) is **bad**.

### 3.3 Pseudocode

```python
def classify_f1_quality(m: F1Metrics) -> str:
    # Hard failures
    if m.taboo_violations_count > 0:
        return "bad"
    if m.board_size < 4:
        return "bad"
    if m.invalid_fraction is not None and m.invalid_fraction > 0.05:
        return "bad"

    coverage = m.opportunity_coverage  # may be None

    # Good
    if (
        m.board_size >= 8
        and m.strong_fraction >= 0.5
        and (m.invalid_fraction is None or m.invalid_fraction <= 0.01)
        and m.redundancy_rate <= 0.3
        and (coverage is None or coverage >= 0.6)
    ):
        return "good"

    # Partial
    if (
        m.board_size >= 6
        and m.strong_fraction >= 0.25
        and (m.invalid_fraction is None or m.invalid_fraction <= 0.05)
        and m.redundancy_rate <= 0.5
        and (coverage is None or coverage >= 0.4)
    ):
        return "partial"

    return "bad"
```

---

## 4. F2 Quality Classification (Packages + Variants)

### 4.1 Intuition

F2 is "good" if:

- Most packages are board-ready, clearly executable, and faithful to the opportunity
- Most variants are ship-ready (`publish_ready`), on-brand, and channel-appropriate
- There are no systemic invalids or obvious garbage texts

### 4.2 Thresholds

#### 4.2.1 Hard Failure Gates

F2 is **bad** if:

| Condition | Threshold |
|-----------|-----------|
| `invalid_variant_fraction` | > 0.05 |
| `publish_ready_fraction` | < 0.2 (almost nothing shippable) |
| Taboo violations at variant level | Any (if tracked separately) |

#### 4.2.2 Package Quality

Metrics used:

- `mean_package_score ∈ [0, 15]`
- `board_ready_package_fraction ∈ [0, 1]`
- `execution_clarity_rate ∈ [0, 1]` or `None`
- `faithful_package_fraction ∈ [0, 1]` or `None`

**"Good" package layer** if ALL of:

- `board_ready_package_fraction >= 0.7`
- `mean_package_score >= 11.0`
- If `execution_clarity_rate` is available: `>= 0.7`
- If `faithful_package_fraction` is available: `>= 0.8`

**"Partial" package layer** if not good, but:

- `board_ready_package_fraction >= 0.4`
- `mean_package_score >= 8.0`
- If `execution_clarity_rate` is available: `>= 0.5`
- If `faithful_package_fraction` is available: `>= 0.6`

Otherwise package layer is **bad**.

#### 4.2.3 Variant Quality

Metrics used:

- `publish_ready_fraction ∈ [0, 1]`
- `invalid_variant_fraction ∈ [0, 1]`
- `voice_alignment_ok_fraction ∈ [0, 1]` or `None`
- `channel_fit_ok_fraction ∈ [0, 1]` or `None`

**"Good" variant layer** if ALL of:

- `publish_ready_fraction >= 0.6`
- `invalid_variant_fraction == 0` (or ≤ 0.01)
- If `voice_alignment_ok_fraction` is available: `>= 0.8`
- If `channel_fit_ok_fraction` is available: `>= 0.8`

**"Partial" variant layer** if not good, but:

- `publish_ready_fraction >= 0.3`
- `invalid_variant_fraction <= 0.05`
- If `voice_alignment_ok_fraction` is available: `>= 0.6`
- If `channel_fit_ok_fraction` is available: `>= 0.6`

Otherwise variant layer is **bad**.

#### 4.2.4 Combining Package + Variant Layers

We classify F2 as:

| F2 Label | Condition |
|----------|-----------|
| **good** | Package layer is good AND variant layer is good |
| **partial** | At least one is partial AND neither is bad |
| **bad** | Package layer is bad OR variant layer is bad |

### 4.3 Pseudocode

```python
def _layer_label_from_thresholds(...):  # left abstract for brevity
    ...

def classify_f2_quality(m: F2Metrics) -> str:
    # Hard failure from invalids / extremely low readiness
    if m.invalid_variant_fraction is not None and m.invalid_variant_fraction > 0.05:
        return "bad"
    if m.publish_ready_fraction < 0.2:
        return "bad"

    package_label = classify_package_layer(m)
    variant_label = classify_variant_layer(m)

    if package_label == "good" and variant_label == "good":
        return "good"

    if package_label == "bad" or variant_label == "bad":
        return "bad"

    return "partial"
```

Where `classify_package_layer` and `classify_variant_layer` directly implement the thresholds above.

---

## 5. Run-Level Classification

### 5.1 Inputs

For each eval run we have:

- `structural_valid: bool` = `is_structurally_valid()`
- `f1_label ∈ {"good", "partial", "bad"}` from `classify_f1_quality`
- `f2_label ∈ {"good", "partial", "bad"}` from `classify_f2_quality`

### 5.2 Mapping

| Condition | Run Status |
|-----------|------------|
| `structural_valid == False` | `"invalid"` (structural bug: we do not interpret quality metrics) |
| `f1_label == "good"` AND `f2_label == "good"` | `"good"` |
| `"bad" in {f1_label, f2_label}` | `"bad"` |
| Otherwise | `"partial"` |

### 5.3 Missing Metrics Behavior

Some metrics may not be present initially (e.g. `faithful_package_fraction`, `voice_alignment_ok_fraction`).

**Rules:**

- If a metric is `None` or missing:
  - We do **not** fail the run because of that metric
  - We simply skip its constraint in the corresponding band condition
  - We must **never** silently treat `None` as `0.0` – that would misclassify early versions as bad

This keeps the classifier usable while we incrementally enrich eval annotations.

### 5.4 Pseudocode

```python
def classify_run(
    structural_valid: bool,
    f1_metrics: F1Metrics,
    f2_metrics: F2Metrics,
) -> str:
    if not structural_valid:
        return "invalid"

    f1_label = classify_f1_quality(f1_metrics)
    f2_label = classify_f2_quality(f2_metrics)

    if f1_label == "good" and f2_label == "good":
        return "good"

    if "bad" in {f1_label, f2_label}:
        return "bad"

    return "partial"
```

---

## 6. Calibration and Human Labels

This spec is intentionally conservative and should be calibrated with human judgment:

1. Run the eval harness on a small set of brands/scenarios
2. For each run, have a human answer:
   - "Would I work from this board + package/variants?" with `{yes, maybe, no}`
3. Compare with:
   - `run_status ∈ {"good", "partial", "bad"}`
4. Adjust thresholds if there is systematic mismatch:
   - Too many "good" labels for outputs you'd personally throw away → **tighten**
   - Too many "bad" labels where you'd actually be fine using it → **relax**

Once calibrated, this classifier can:

- **Gate CI** (e.g. "no PR may merge if eval good fraction drops below X%")
- **Measure regression / improvement** across prompt / graph changes
