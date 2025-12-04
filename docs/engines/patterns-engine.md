# Patterns Engine

> **one-line**: turns high-performing posts into reusable, named structural templates and applies them back into the system with evidence and stats.

The Patterns Engine is the layer that gives Kairo a **reusable playbook** instead of “one-off good posts”. It mines posts (internal + external), extracts structural patterns, names and tracks them, and feeds them back into Content Engineering (CE), Opportunities, Brand Brain, and Learning as **PatternTemplates** with clear provenance and performance.

It should feel, to a strategist, like having a living internal “swipe file” that is:
- structured,
- searchable,
- tied to outcomes,
- and actually used by the generation engine.

---

## 1. Definition

**Transformation**  
Raw posts (from brands + model accounts) → normalized **PatternSourcePosts** → clustered/named **PatternTemplates** → **PatternUsage** logs tied to outcomes → per-brand pattern weights and priors.

The engine is responsible for:

1. **Mining** posts into `CO-11 PatternSourcePost` (internal hits + selected external).
2. **Extracting** structural patterns into `CO-12 PatternTemplate` (hook, beats, narrative roles, constraints, examples).
3. **Attaching** pattern usage to concrete variants via `CO-13 PatternUsage`.
4. **Looping back** performance and feedback into pattern stats and per-brand weights (with the Learning Engine).

It **does not**:
- generate copy (that’s CE),
- decide per-opportunity persona/pillar (that’s Brand Brain + CE),
- decide final pattern choice alone (it proposes; CE + BrandPreferences ultimately pick).

---

## 2. Inputs

All inputs are canonical objects:

- `CO-01 Brand`
- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-05 BrandBrainSnapshot`
- `CO-07 BrandMemoryFragment`
- `CO-11 PatternSourcePost`
- `CO-12 PatternTemplate` (existing)
- `CO-13 PatternUsage` (existing rows to update)
- `CO-17 ContentVariant`
- `CO-18 FeedbackEvent` (esp. saved_as_example, variant_rating, performance_snapshot)
- `CO-19 BrandPreferences`
- `CO-20 GlobalPriors`

**Guarantees it expects:**
- each `PatternSourcePost` has:
  - channel,
  - raw_text,
  - created_at,
  - (optional) metrics (impressions/engagements) when known,
  - brand_id or is_global=true.
- each `ContentVariant` has:
  - channel,
  - pattern_template_id (if already assigned) or null (v1 can backfill),
  - persona_id, pillar_id.
- feedback + performance events are normalized into `FeedbackEvent` with correct foreign keys.

The engine will **not** try to parse arbitrary freeform logs. It only works off these objects.

---

## 3. Outputs

Primary outputs:

1. **`CO-11 PatternSourcePost`**
   - created from:
     - imported model accounts,
     - brand internal “hit posts,”
     - optionally curated external posts.
   - enriched with:
     - minimal metrics where available,
     - tags (e.g. source_origin: {brand_hit, model_account, curated_external}).

2. **`CO-12 PatternTemplate`**
   - **new** templates mined from `PatternSourcePost`.
   - **updates** to:
     - `usage_stats` (times_used, avg engagement),
     - `status` (active/experimental/deprecated),
     - `channel_constraints`, if a pattern is clearly channel-specific.

3. **`CO-13 PatternUsage`**
   - one row per `(ContentVariant, PatternTemplate)` usage.
   - enriched later with outcomes (impressions, engagement) as they arrive.

4. **Secondary updates via Learning Engine:**
   - `CO-19 BrandPreferences.pattern_weights` updated based on:
     - per-pattern performance per brand,
     - per-pattern “never again” / “saved as example” signals.
   - `CO-20 GlobalPriors.pattern_stats` updated from cross-brand aggregated PatternUsage.

All of this is **batch-friendly**: no hard need to run synchronously on every user action.

---

## 4. Invariants

If the Patterns Engine is “healthy”, the following MUST be true:

- **Template grounding**
  - every `PatternTemplate` has at least **one** `PatternSourcePost` as evidence.
  - `example_source_post_ids` are real `PatternSourcePost` rows, not imaginary.

- **Structural clarity**
  - every active template has a **non-empty** `structure` array describing beats in order.
  - beats are descriptive enough that CE can map them to `ChannelPlan.beats` without guessing.

- **Usage traceability**
  - every `ContentVariant` that was generated **with** a pattern has:
    - a non-null `pattern_template_id` **and**
    - a corresponding `PatternUsage` row.
  - no “ghost patterns” (pattern IDs in variants that don’t exist in PatternTemplate).

- **Outcome wiring**
  - when performance metrics arrive for a variant (via `FeedbackEvent` / analytics ingest), downstream jobs eventually:
    - update the corresponding `PatternUsage.outcome`,
    - and indirectly roll those stats into:
      - `PatternTemplate.usage_stats`,
      - `BrandPreferences.pattern_weights`,
      - `GlobalPriors.pattern_stats`.

- **Channel constraints**
  - templates mark their `channel_constraints` consistently:
    - if a pattern is obviously X-specific (e.g. “multi-tweet thread with numbered tweets”), it must not be used for LinkedIn by default.

If any of these invariants break, CE and Learning become noisy and unreliable.

---

## 5. Quality Dimensions

For v1, **4 core axes** define “good” pattern behavior:

1. **Pattern correctness**
   - the described structure actually matches the source posts.
   - the “hook”, “turn”, “lesson” labels are not fantasy.

2. **Pattern usefulness**
   - patterns are **general enough** to be reused across multiple topics,
   - but **specific enough** to give CE concrete guidance (“this is a confessional story” vs “vaguely story-like”).

3. **Pattern diversity**
   - each brand doesn’t end up with just 1–2 templates used 90% of the time.
   - across a brand’s variants in a month, you see a healthy mix of pattern families.

4. **Pattern–channel fit**
   - per-channel, the top-usage templates actually work with that channel’s constraints.
   - no 800-word essay structure being used for X by default.

**How to approximate measurement:**

- **LLM self-check on extraction**:
  - given a `PatternSourcePost` + its assigned `PatternTemplate`, ask a separate eval-prompt:
    - “does this template correctly describe the structure of this post?” → score 0–5.

- **Pattern usage stats**:
  - distribution of `PatternTemplate` usage per brand/channel:
    - if one pattern is >70% of uses, that’s a red flag (unless explicitly wanted).

- **Performance lift vs baseline**:
  - compare engagement of variants using a template vs:
    - variants generated without that template (where available),
    - or vs brand/channel baseline.

---

## 6. Failure Modes & Surfacing

**Acceptable / recoverable failures:**

- **Too many similar patterns**
  - many templates that are minor variations of the same “listicle” pattern.
  - impact: CE has noisy choices but still works.
  - mitigation:
    - periodic dedup/merge jobs,
    - heuristic clustering: “if structure + channel + similar examples, merge”.

- **Slightly wrong labels**
  - pattern structure is mostly right, labels are slightly off.
  - impact: no catastrophic UX hit; content still reads fine.

**Unacceptable failures:**

- **Pattern hallucinations**
  - templates defined with no real support:
    - `example_source_post_ids` empty or bogus.
  - mitigation:
    - enforce DB constraints: non-empty `example_source_post_ids`.
    - extraction pipeline refuses to save templates without backing posts.

- **Channel mismatch**
  - using X thread patterns for LinkedIn long-form, or vice versa, by default.
  - mitigation:
    - strict `channel_constraints` checks in CE,
    - error if CE tries to bind a template to an unsupported channel.

- **Feedback ignored**
  - user repeatedly flags a pattern “never again” and it keeps being sampled at high weight.
  - mitigation:
    - Learning Engine must update `BrandPreferences.pattern_weights` on every relevant `FeedbackEvent`.
    - UI can show pattern weight changes over time for debugging.

**How failures surface:**

- **Developer/debug view**
  - internal “Patterns Inspector”:
    - see templates, their example posts, stats, and current per-brand weights.
    - inspect recent PatternUsage for a brand/channel.

- **User-facing**
  - ability to:
    - see which pattern a variant used (“Pattern: Confessional → Lesson”),
    - click “never use this pattern again for this brand”,
    - optionally: “boost patterns like this”.

If you can’t see which pattern produced a bad post **and** can’t tell the system to stop using it, the engine is failing at its job.

---

## 7. Latency & Cost Constraints

Patterns Engine is mostly **offline / batch**:

- **Extraction**
  - triggered on:
    - import of new PatternSourcePosts,
    - or on demand for curated posts.
  - can run as background jobs; user doesn’t wait for it in the main interaction.

- **Sampling / selection**
  - runtime path is cheap:
    - CE only needs:
      - a small list of candidate `PatternTemplate` IDs,
      - some metadata (name, structure, stats).
  - these can be cached per brand/channel in memory or Redis.

Rough constraints:

- **Extraction**:
  - cost: dependent on how many posts you mine, but:
    - you don’t need to mine everything; a few hundred strong examples per brand/vertical are enough early.
  - latency: can be minutes; not user-visible.

- **Runtime pattern selection (per package)**:
  - 0–1 LLM calls:
    - often just deterministic logic using `BrandPreferences.pattern_weights` + `PatternTemplate` metadata.
  - should add **< 200ms** overhead to CE pipeline.

If we find ourselves spending dollars per pattern extraction for marginal lift, we’d revisit scope.

---

## 8. Learning Hooks

Patterns Engine doesn’t learn alone; it plugs into the Learning Engine.

**Signals it cares about:**

- `FeedbackEvent.feedback_type = saved_as_example`
  - implies that the variant’s pattern is desirable.
- `feedback_type = never_again`
  - implies that the pattern is undesirable for this brand/channel.
- `feedback_type = variant_rating`
  - allows more nuanced adjustments (tone_match, specificity, etc.).
- `feedback_type = performance_snapshot`
  - attaches engagement metrics to variants and thus to PatternUsage.

**What actually updates:**

- **PatternUsage**
  - Learning Engine:
    - links performance snapshots to `PatternUsage` rows,
    - aggregates to `PatternTemplate.usage_stats`.

- **BrandPreferences.pattern_weights**
  - for each brand:
    - increment weights for patterns associated with high-rated / high-performing variants,
    - decrement for patterns associated with “never again” or consistently low performance.

- **GlobalPriors.pattern_stats**
  - aggregated across brands, anonymized:
    - informs default pattern weights for new brands,
    - informs “recommended patterns” for similar verticals later.

We explicitly avoid clever ML here in v1; simple counts & moving averages are enough.

---

## 9. Baseline Comparison

**How would a smart human + custom GPT do this today?**

- The strategist keeps:
  - a Notion / Google Doc “swipe file” of good posts,
  - some mental categories (“confessional story”, “hot take”, “tactical list”),
  - occasional screenshots from model accounts.
- When they brief a writer, they paste:
  - 2–3 reference posts,
  - say “do something like this structurally but for our topic”.

With a custom GPT:

- They might paste references into the prompt:
  - “Here are 3 posts I like. Copy the style and structure.”

Limitations:

- no shared, evolving pattern library across the team,
- no explicit tracking of “this structural pattern led to X% lift for this brand”,
- no per-brand weights that shift as performance/feedback comes in,
- no systemic connection between:
  - pattern choice,
  - learning,
  - and future generation.

**Kairo’s Patterns Engine edge:**

- patterns are **first-class objects** (`PatternTemplate`, `PatternUsage`), not vibes.
- they’re:
  - named,
  - structured,
  - grounded in real posts,
  - tied to performance,
  - and fed directly into CE pipelines and BrandPreferences.
- a new strategist joining a brand can see:
  - “these 4 patterns are our workhorses on LinkedIn”,
  - “these 2 patterns we tried and abandoned”,
  - and use them immediately—no tribal knowledge required.

If Patterns Engine doesn’t deliver that kind of explicit, reusable playbook, we’re just re-implementing a messy swipe file with extra steps.

---