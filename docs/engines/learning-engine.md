# Learning Engine

> **one-line**: turns noisy feedback and performance data into stable, per-brand preferences and global priors that quietly steer all other engines without cross-brand leakage or chaos.

The Learning Engine is the **slow brain** of Kairo.  
It ingests:

- explicit user feedback (`FeedbackEvent`),
- observed pattern usage (`PatternUsage`),
- performance outcomes (later, via analytics),
- existing brand-level knobs (`BrandPreferences`, `BrandRuntimeContext`),
- cross-brand stats (`GlobalPriors`),

and updates how Kairo **scores opportunities, picks patterns, biases tone, and chooses personas/pillars** over time.

It does **not** generate content or opportunities itself; it **re-weights** the system.

---

## 1. Definition

**Transformation**  
Given a stream of `FeedbackEvent` and performance data:

- **per brand**:
  - update `BrandPreferences` (pattern weights, tone biases, persona/pillar bias, opportunity scoring weights),
  - optionally adjust `BrandRuntimeContext` (risk/tone modes, channel emphasis),
- **globally**:
  - maintain `GlobalPriors` (cross-brand pattern and opportunity priors).

It must:

- be **append-only** on raw feedback (no rewriting history),
- produce **interpretable, numeric knobs** other engines can consume,
- avoid **overreacting** to a few events while still learning over time,
- keep **brand isolation**: no bleeding one brand’s secrets into another’s behavior.

It **does not**:

- talk directly to users,
- own any primary user-facing UI,
- replace explicit human configs (it modulates them, doesn’t overwrite without rules).

---

## 2. Inputs

Primary canonical inputs:

- `CO-18 FeedbackEvent`
  - source of explicit signals:
    - `variant_rating`,
    - `edit_applied`,
    - `never_again`,
    - `saved_as_example`,
    - `performance_snapshot` (later).

- `CO-13 PatternUsage`
  - tie between `PatternTemplate` and `ContentVariant` plus outcomes.

- `CO-19 BrandPreferences`
  - current per-brand weights/knobs to be updated.

- `CO-20 GlobalPriors`
  - cross-brand default priors.

- `CO-06 BrandRuntimeContext`
  - current runtime knobs per brand/channel.

Indirect/contextual inputs:

- `CO-01 Brand`
- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-07 BrandMemoryFragment` (for “saved as example” events)
- `CO-09 OpportunityCard` (for opportunity scoring updates)
- `CO-14 ContentPackage`
- `CO-17 ContentVariant`
- `CO-21 ChannelConfig` (for channel-level performance stats)

**Assumed guarantees:**

- `FeedbackEvent` is **append-only**, with:
  - typed `feedback_type`,
  - structured `payload` per type.
- `PatternUsage` references valid `pattern_template_id`, `content_variant_id`, `brand_id`.
- `BrandPreferences` exists for each active `brand_id` (or can be lazily initialized from `GlobalPriors`).
- `GlobalPriors` never references specific brand ids (anonymized by design).

---

## 3. Outputs

Primary outputs (owned by Learning Engine):

1. **`CO-19 BrandPreferences`**
   - updated per brand:
     - `pattern_weights` (pattern_template_id → weight),
     - `tone_bias_overrides`,
     - `persona_pillar_bias`,
     - `opportunity_scoring_weights`.

2. **`CO-20 GlobalPriors`**
   - updated globally:
     - aggregate pattern stats (per pattern, per channel, possibly per vertical),
     - default tone biases per channel,
     - default opportunity scoring weights.

Secondary outputs / side-effects:

3. **Updates to `CO-06 BrandRuntimeContext`**
   - only on well-defined axes:
     - e.g. risk mode, subtle tone_bias tweaks, channel emphasis.
   - must be bounded and slow-changing (no wild oscillations).

4. **Promotion of `CO-07 BrandMemoryFragment`**
   - from `FeedbackEvent.saved_as_example`:
     - mark variant text as fragment,
     - attach persona/pillar/pattern tags.

5. **Internal analytics tables (non-canonical)**
   - e.g. per-brand performance summaries,
   - engine version comparisons.

Learning Engine **never**:

- edits raw `FeedbackEvent`,
- edits raw `ContentVariant` text,
- changes `BrandBrainSnapshot` semantics (Brand Brain owns that).

---

## 4. Invariants

If the Learning Engine is “correct”, the following MUST hold:

- **Single source of truth for preferences**
  - there is exactly one `BrandPreferences` row per active brand (possibly per segment later),
  - all engines (BrandBrain, Opportunities, CE, Patterns) read preferences **only** from `BrandPreferences` (and `GlobalPriors`), not hidden stores.

- **Feedback immutability**
  - once a `FeedbackEvent` is written:
    - it is never mutated or deleted by Learning Engine,
    - corrections are new events, not edits.

- **No cross-brand leakage**
  - `BrandPreferences` for brand A MUST NOT:
    - directly encode raw content, taboos, or patterns from brand B,
    - store any identifiers from other brands.
  - `GlobalPriors` MUST stay anonymized aggregate stats (no brand ids).

- **Monotonic evolution**
  - `BrandPreferences` and `GlobalPriors` changes must be:
    - versioned or timestamped,
    - explainable (we can say “weights changed because of events X/Y/Z over window T”).

- **Bounded influence**
  - a single outlier event is not allowed to:
    - zero out a pattern,
    - flip all tone biases,
    - explode opportunity scoring weights.
  - updates depend on **aggregated evidence** over windows.

Break these and you either get a spooky, unpredictable system or a privacy nightmare.

---

## 5. Quality Dimensions

For Learning Engine, “quality” is about **behavior over time**:

1. **Responsiveness**
   - when a pattern is consistently bad (low ratings, “never again”), its weight should drop in a **human-noticeable** timeframe.
   - when new “saved as example” patterns emerge, they should start appearing more often.

2. **Stability**
   - preferences should not oscillate week to week.
   - given similar inputs, engine behavior should feel predictable.

3. **Alignment with human feedback**
   - user intuition (“we like this style, hate that style”) should match what the system emphasizes over time.
   - designers should not feel like they are fighting the system.

4. **Safety / isolation**
   - no brand sees another brand’s proprietary content signature.
   - global priors feel like “industry knowledge”, not leaking secrets.

5. **Introspectability**
   - we can answer:
     - “why is this pattern weight so high for this brand?” with a rough explanation.
     - “what changed between last month and this month for this brand’s preferences?”

**Measurement (approximate):**

- track curves over time:
  - pattern usage vs. weight vs. feedback,
  - tone biases vs. edit patterns.
- periodic sanity checks:
  - does per-brand pattern usage distribution intuitively reflect their `saved_as_example` vs `never_again` events?
- log engine version + algorithm parameters for offline evaluation.

---

## 6. Failure Modes & Surfacing

**Acceptable / recoverable:**

- **Under-learning (too conservative)**
  - system reacts slowly; users see “same old patterns” longer than ideal.
  - impact: lower perceived intelligence, but safe.
  - mitigation: adjust learning rates or event windows; easy to fix.

- **Over-smoothing**
  - global priors dominate; subtle brand-specific quirks not reflected.
  - mitigation: re-balance weight between `GlobalPriors` and local `BrandPreferences`.

**Unacceptable:**

- **Mode collapse on a few patterns**
  - one high-performing pattern dominates everything, making content monotonous.
  - mitigation:
    - enforce diversity constraints in pattern sampling (Learning sets a max cap per pattern per window).

- **Overfitting to tiny samples**
  - a single viral post or a small run of `saved_as_example` events skew weights massively.
  - mitigation:
    - require minimum support (e.g. N events) before large weight shifts.

- **Cross-brand contamination**
  - subtle reuse of patterns/tones that leak a very specific competitor’s style into another brand without explicit permission.
  - mitigation:
    - keep `GlobalPriors` coarse (no brand-level or client-identifiable categories),
    - make “global patterns” strictly structural, not content-specific.

- **Invisible preference drift**
  - preferences drift a lot but no one can tell why.
  - mitigation:
    - version & log preference diffs,
    - provide internal-only explanation tooling.

**Surfacing (mostly internal tooling):**

- per-brand **Learning debug page** (internal/admin first):
  - current `BrandPreferences` summary:
    - top patterns,
    - key tone biases,
    - persona/pillar priorities,
    - opportunity scoring weights.
  - recent `FeedbackEvent` aggregates driving changes.

To users, we keep it simple:
- they feel “it’s learning us” as:
  - bad patterns show up less,
  - liked styles show up more,
  - tone drifts towards what they keep editing to.

---

## 7. Latency & Cost Constraints

Learning is **not** on the main UX hot path. Most updates can be:

- **batch / scheduled**:
  - e.g. per hour/day jobs recomputing:
    - BrandPreferences,
    - GlobalPriors.

- **lightweight incremental**:
  - small, bounded synchronous updates from critical events:
    - e.g. on `saved_as_example` or `never_again`, apply a **tiny** immediate adjustment to pattern weight,
    - full recompute happens later in batch.

LLM usage:

- v1: **optional**.
  - most learning can be non-LLM logic:
    - counts,
    - exponential moving averages,
    - simple bandit-like updates.
- later:
  - LLMs might help with:
    - meta-analysis (“explain why these patterns work”),
    - clustering variants into style families.

Cost target:

- per-brand per-day learning passes should be **cheap**:
  - mostly standard DB queries and arithmetic.
  - any LLM calls are rare and heavily cached.

---

## 8. Learning Hooks (Signals → Updates)

This engine **is** the learning loop, so we spell out the mapping.

**From `FeedbackEvent`:**

- `variant_rating`
  - updates:
    - pattern weights (for patterns used in that variant),
    - channel-level tone biases (if consistent patterns appear),
  - effect:
    - high-rated patterns get slightly higher `pattern_weights`,
    - low-rated ones decay.

- `edit_applied`
  - we don’t do full sequence-learning v1, but we can:
    - record magnitude of edit (token-level diff size),
    - correlate frequent edit directions (e.g. always softening tone).
  - later: feed these into more advanced tone / pattern refinements.

- `saved_as_example`
  - triggers:
    - creation of `BrandMemoryFragment`,
    - bump to associated pattern weight,
    - potential highlighting of this variant in internal test suites.

- `never_again`
  - triggers:
    - hard penalty for the associated pattern/knob for that brand,
    - optional hard constraint flag (e.g. “pattern_template_id X disabled for brand Y”),
    - may adjust risk_mode if attached to “too spicy” failures.

- `performance_snapshot`
  - from publishing/analytics:
    - attaches outcomes to `PatternUsage`,
    - updates:
      - per-pattern performance stats (per brand, per channel),
      - aggregated into `GlobalPriors`.

**What gets written where:**

- `BrandPreferences`:
  - pattern_weights: numeric map pattern → weight.
  - tone_bias_overrides: per-channel or global adjustments.
  - persona_pillar_bias: counts / weights driving better coverage.
  - opportunity_scoring_weights: biases to what kinds of opportunities the brand tends to pick & perform with.

- `GlobalPriors`:
  - aggregated pattern performance over all brands,
  - default tone/opportunity weights for new brands.

- `BrandRuntimeContext`:
  - selective, slow changes to risk_mode and tone_bias based on long-term feedback trends.

All updates are **bounded** and **logged**.

---

## 9. Baseline Comparison

**Baseline today:**

- A senior strategist and content lead:
  - watch analytics dashboards,
  - keep mental notes (“hooks that work well for us”, “topics that flop”),
  - occasionally adjust:
    - internal brand docs,
    - ad hoc “do more of this, less of that” instructions to the team,
    - maybe tweak a custom GPT prompt.

Problems:

- insights are:
  - **implicit** (in people’s heads),
  - **fragile** (leave when people churn),
  - **non-systematic** (hard to apply across many brands),
  - rarely translated into precise, consistent knobs.

**Kairo Learning Engine’s edge:**

- feedback and performance are:
  - normalized into `FeedbackEvent` and `PatternUsage`,
  - aggregated into explicit `BrandPreferences` and `GlobalPriors`,
  - automatically consumed by Opportunities, Patterns, BrandBrain, and CE.

- no one has to hand-edit a “master prompt” every week:
  - the system gradually nudges itself to:
    - pick higher-performing patterns more often,
    - honor “never again” constraints,
    - adjust tone and risk to what the brand actually ships.

- new team members and new brands start with:
  - strong default priors,
  - and a live learning loop, instead of an empty slate.

If Learning Engine doesn’t clearly outperform “smart human occasionally glancing at analytics and editing a prompt”, then it’s just overhead. Our design is explicitly built to exceed that baseline in **consistency**, **granularity**, and **cross-session memory**.

---