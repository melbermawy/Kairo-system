# Content Engineering Engine

> **one-line**: turns a brand-aware opportunity into a structured content package with a core argument, channel plans, and on-brand, pattern-backed variants that are fast to edit instead of rewrite.

The Content Engineering (CE) Engine is the **workhorse** that takes:
- a brand’s **Brain** (personas, pillars, tone, taboos),
- a specific **Opportunity**,
- the brand’s **patterns** and **memory fragments**,
- and the current **preferences / knobs**,

and produces a **ContentPackage**: clear core argument, per-channel plans, and concrete variants that a human can lightly edit and ship.

It’s where we must beat “smart human + custom GPT” on:
- **quality** (brand fit, specificity, pattern use),
- **control** (traceability, knobs that work),
- **speed** (idea → usable drafts),
- **repeatability** (same inputs → same class of outputs).

---

## 1. Definition

**Transformation**  
Given a brand + opportunity + runtime context → produce a fully structured `ContentPackage` with:

- `CoreArgument` (what we’re actually saying),
- one or more `ChannelPlan`s (per channel: which pattern(s), how beats map),
- one or more `ContentVariant`s per channel (actual drafts),
- traceable `PatternUsage` rows tied to patterns and variants.

It is responsible for:

1. **Planning**: locking persona/pillar, core thesis, and supporting points.
2. **Pattern binding**: selecting `PatternTemplate`s and mapping beats for each channel.
3. **Rendering**: generating channel-specific drafts + optional script skeletons.
4. **Self-eval + iteration hooks**: optional scores and regeneration hooks.
5. **Traceability**: making every variant traceable to:
   - `BrandBrainSnapshot`,
   - `OpportunityCard`,
   - `PatternTemplate`,
   - `CoreArgument`.

It **does not**:
- mine trends (Opportunities Engine),
- maintain long-term preferences (Learning Engine),
- do publishing / scheduling,
- decide analytics or success alone.

---

## 2. Inputs

All inputs are canonical objects:

- `CO-01 Brand`
- `CO-02 Persona`
- `CO-03 Pillar`
- `CO-05 BrandBrainSnapshot`
- `CO-06 BrandRuntimeContext`
- `CO-07 BrandMemoryFragment`
- `CO-08 GlobalSourceDoc` (via `OpportunityCard.source_refs`, not raw)
- `CO-09 OpportunityCard`
- `CO-10 OpportunityBatch` (for context; CE works per-card/package)
- `CO-11 PatternSourcePost` (indirect; via templates)
- `CO-12 PatternTemplate`
- `CO-14 ContentPackage` (existing when regenerating)
- `CO-15 CoreArgument` (existing when editing/regenerating)
- `CO-16 ChannelPlan` (existing when editing/regenerating)
- `CO-17 ContentVariant` (for regen / edits)
- `CO-18 FeedbackEvent` (for inline learning hooks)
- `CO-19 BrandPreferences` (pattern weights, tone biases)
- `CO-21 ChannelConfig` (what channels exist for brand)

**Guarantees it expects:**

- `OpportunityCard`:
  - has `persona_id`, `pillar_id` (or explicit “global” with flag),
  - has `angle_summary`, `opportunity_type`, `score`,
  - has at least one `source_ref`.
- `BrandBrainSnapshot`:
  - contains positioning, tone_descriptors, offers, taboos,
  - contains `persona_ids`, `pillar_ids` consistent with the opportunity.
- `BrandRuntimeContext`:
  - exposes per-channel knobs:
    - tone_bias (e.g. story_vs_tactical, aggressive_vs_safe),
    - length_mode,
    - risk_mode.
- `BrandPreferences`:
  - contains pattern_weights, persona_pillar_bias; can be default-initialized.
- `PatternTemplate`:
  - has structure, channel_constraints, example_source_post_ids.
- `ChannelConfig`:
  - tells us which channels are connected / allowed for generation.

CE assumes these inputs are internally consistent; it does not try to fix broken BrandBrain.

---

## 3. Outputs

Primary outputs (created/updated by CE):

1. **`CO-14 ContentPackage`**
   - created when user “opens” an opportunity or starts from a blank topic.
   - updated when:
     - regenerating package,
     - changing status (draft → in_review → approved, etc.),
     - changing channel scope.

2. **`CO-15 CoreArgument`**
   - created as part of initial package planning.
   - updated when user edits thesis / supporting points or when CE regenerates.

3. **`CO-16 ChannelPlan`**
   - created per channel when CE decides which channels to target.
   - updated when:
     - user toggles channels,
     - CE regenerates pattern bindings or beats.

4. **`CO-17 ContentVariant`**
   - created when CE renders drafts from ChannelPlans.
   - updated:
     - by CE on regen,
     - by user edits,
     - status changes (draft, edited, approved, rejected, published).

5. **`CO-13 PatternUsage`**
   - created per `(ContentVariant, PatternTemplate)` usage.
   - later enriched by Learning with outcomes.

Secondary effects (outside CE’s core, but CE must emit enough metadata):

- `BrandMemoryFragment`
  - may be created from variants explicitly “saved as example” in the UI (via Learning Engine).

---

## 4. Invariants

If CE is “healthy”, the following MUST hold:

- **Package–opportunity linkage**
  - every non-manual `ContentPackage`:
    - MUST reference exactly one `OpportunityCard` **or**
    - MUST explicitly declare `origin_type = manual` with `origin_note`.
  - you can always trace “why does this piece exist?” back to an opportunity or manual origin.

- **Argument consistency**
  - every `ContentPackage` MUST have exactly one active `CoreArgument`.
  - the `CoreArgument.persona_id` and `pillar_id` MUST match the package’s persona/pillar choice.
  - all `ChannelPlan`s and `ContentVariant`s for that package MUST reference the same persona/pillar.

- **Pattern traceability**
  - if a `ContentVariant` claims a `pattern_template_id`, there MUST be:
    - a real `PatternTemplate`,
    - a `PatternUsage` row binding them.
  - CE must not silently generate “pattern-less” variants unless explicitly allowed.

- **Brand snapshot traceability**
  - each `ChannelPlan` MUST reference a `brand_brain_snapshot_id`.
  - given a variant, you can know **which version** of the brand brain was used to generate it.

- **Status coherence**
  - `ContentVariant.status` cannot be `approved` if its `ContentPackage.status` is still `draft`.
  - publishing jobs (outside CE) can only be created from `approved` variants.

If these invariants break, you lose debuggability and your learning loop collapses.

---

## 5. Quality Dimensions

For v1, CE is judged on at least these **5 axes**:

1. **Brand alignment**
   - tone, taboos, positioning honored.
   - no generic AI voice, no obvious violations of “don’t say this” rules.

2. **Persona & pillar fidelity**
   - content speaks clearly to the selected persona (pain, goals, vocabulary).
   - content clearly matches the pillar (strategy POV vs tactical tip vs behind-the-scenes).

3. **Specificity vs fluff**
   - drafts contain concrete claims, examples, numbers, or scenarios—not content soup.
   - hooks are sharp, not vague.

4. **Pattern application**
   - the stated pattern in `ChannelPlan.pattern_bindings` is actually reflected in the variant’s structure.
   - beats map cleanly from pattern → content sections.

5. **Editability (revision effort)**
   - a competent strategist/creator should be able to:
     - take a variant from CE,
     - make small edits (10–20%),
     - and feel comfortable shipping,
   - rather than rewriting from scratch.

**How we approximate measurement:**

- **LLM self-eval step (optional, internal)**:
  - after generation, ask a separate prompt to grade:
    - brand alignment,
    - persona match,
    - pillar match,
    - specificity,
    - pattern correctness,
  - record these in internal metadata (even if not stored long-term).

- **FeedbackEvent aggregation**:
  - distribution of:
    - `variant_rating`,
    - `saved_as_example`,
    - `never_again`,
  - per brand, per channel, per pattern, per engine version.

- **Time-to-approve (later UX metric)**:
  - we won’t track this immediately in v1, but structure should allow it later.

---

## 6. Failure Modes & Surfacing

**Acceptable / recoverable failures:**

- **Near-miss tone**
  - variant is slightly off in tone (too casual or too formal) but conceptually fine.
  - impact: user tweaks; still faster than custom GPT.
  - surface: user marks rating slightly lower, or edits text.

- **Overly generic examples**
  - content is structurally correct but lacking specific brand examples.
  - impact: user injects concrete examples.
  - mitigation: incremental improvements to prompt including BrandMemoryFragments.

**Unacceptable failures:**

- **Taboo violations / brand risk**
  - violating explicit taboos:
    - e.g. attacking competitors, making disallowed claims, touching forbidden topics.
  - mitigation:
    - run a dedicated “compliance / taboo check” pass (LLM or rules) before surfacing variant.
    - mark variants as `rejected` automatically if they fail.

- **Persona / pillar mismatch**
  - Opportunity says “CFO persona, Strategy pillar” but draft talks to junior marketers with tactical listicle.
  - mitigation:
    - require persona/pillar self-check in eval step;
    - if mismatch > threshold, don’t surface variant; instead, regenerate.

- **Structure mismatch**
  - ChannelPlan says pattern: confessional → harsh truth → lesson, but variant is just a bland tip list.
  - mitigation:
    - enforce beat-level checks: for each pattern beat, the model must explicitly generate a segment and label it in intermediate JSON before final text.

- **Opaque failures**
  - no link from variants back to:
    - OpportunityCard,
    - BrandBrainSnapshot,
    - PatternTemplate.
  - mitigation:
    - hard DB constraints on foreign keys,
    - debugging views in backend (not user-facing at first).

**How failures surface to the user:**

- **Variant view**
  - show:
    - “Opportunity: [short label]”,
    - “Persona / Pillar: X / Y”,
    - “Pattern: Confessional story → harsh truth → lesson”,
    - “Brand Brain v3”.
  - user actions:
    - “regenerate variant” (same argument/plan),
    - “regenerate channel plan” (different pattern bindings),
    - “never use this pattern again for this brand”.

- **Confidence flags (internal first)**
  - if self-eval scores are low on brand alignment or persona match:
    - tag variant as `low_confidence`,
    - optionally hide by default or badge it.

We want the user to feel like they’re **editing a strong first draft**, not debugging a black box.

---

## 7. Latency & Cost Constraints

This engine sits on the **critical path** from idea → usable drafts. It cannot feel sluggish.

Rough constraints:

- **From user clicking “Open in Kairo” on an opportunity to:**
  - seeing a `CoreArgument` and initial channel selection:
    - target: **< 3 seconds** total.
  - seeing first variants:
    - acceptable: **5–10 seconds** for multi-channel, multi-variant runs,
    - but surface progressive loading (argument → channel plan → variants).

**LLM call structure (v1 suggestion):**

1. **CoreArgument stage**
   - 1 call:
     - input: BrandBrainSnapshot + BrandRuntimeContext + OpportunityCard + relevant BrandMemoryFragments.
     - output: thesis + 3–7 supporting points + locked persona/pillar sanity check.
   - context size constrained (no “dump all memory fragments”).

2. **ChannelPlan stage**
   - 1 call per group of channels (or 1 call for all channels):
     - input: CoreArgument + BrandRuntimeContext + BrandPreferences.pattern_weights + PatternTemplates (summary, not full examples).
     - output: selected patterns + beats for each channel.

3. **Variant rendering stage**
   - 1 call per channel or per small batch:
     - input: ChannelPlan + BrandBrainSnapshot + BrandRuntimeContext + BrandMemoryFragments (short, top-k).
     - output: N variants per channel.

4. **Self-eval stage (optional)**
   - can be merged with rendering or done with cheap follow-up calls.

Cost controls:

- limit:
  - number of variants per channel (e.g. default 2),
  - context size (fragments and pattern metadata),
  - number of channels per default package.
- consider:
  - caching CoreArgument when regenerating only variants,
  - caching ChannelPlan when changing only text.

Design target: cost per **ContentPackage** in the cents range, not dollars.

---

## 8. Learning Hooks

CE is where many **direct feedback events** originate.

**Signals:**

- `FeedbackEvent.variant_rating`
  - quality ratings across dimensions (tone_match, specificity, etc.).
- `FeedbackEvent.edit_applied`
  - diff between original variant and user-edited version (for later analysis).
- `FeedbackEvent.saved_as_example`
  - variant should become a `BrandMemoryFragment`.
- `FeedbackEvent.never_again`
  - typically attached to:
    - pattern_template_id,
    - or a specific variant style.

**What updates (via Learning Engine, not CE itself):**

- **BrandPreferences**
  - pattern_weights:
    - patterns used in highly rated / “saved as example” variants get bumped,
    - patterns associated with `never_again` get penalized for that brand.
  - tone_bias_overrides:
    - if user systematically adjusts tone in one direction, biases get nudged.

- **BrandRuntimeContext**
  - some knobs (e.g. risk_mode) may be updated based on repeated feedback (“too spicy”, “too generic”).

- **BrandMemoryFragment**
  - created from “save as example” actions:
    - gives CE better concrete examples for future generations.

- **Prompt versioning / evaluations**
  - we keep engine version ids in:
    - `ContentVariant.origin.generated_by`,
    - so we can compare v1 vs v2 performance on fixed test sets later.

CE must **emit enough metadata** (IDs, engine version, pattern IDs) so Learning can do its job; it doesn’t run the learning logic itself.

---

## 9. Baseline Comparison

**Baseline: smart human + custom GPT**

Today, with a strong strategist and a configured GPT:

- they:
  - read some trend / idea,
  - decide persona/pillar in their head,
  - write a one-liner core angle,
  - paste a brand prompt + a few examples,
  - ask GPT:
    - “give me 3 linkedin posts and 3 X posts on this topic in this voice”.

Pros:
- GPT is fast,
- a good strategist can iterate prompts to get decent output.

Cons:
- everything is:
  - **ephemeral** (no persistent pattern library),
  - **non-traceable** (no structured record of what worked),
  - **non-reusable** (no per-brand memory beyond manual docs),
  - **non-systematic** (no shared framework across a team),
- no clean way to say:
  - “we discovered this pattern works for us, bake it into everything from now on”.

**Kairo CE Engine’s edge:**

- **Structured packages**:
  - every piece of content is a `ContentPackage` with:
    - `CoreArgument`,
    - `ChannelPlan`s,
    - `ContentVariant`s,
    - pattern bindings,
    - and a clear lineage back to an Opportunity and BrandBrainSnapshot.

- **Pattern-aware generation**:
  - drafts are generated **in the shape of** proven patterns, not generic “good writing”.

- **Learning loop baked in**:
  - what users approve, edit, or reject feeds directly into:
    - BrandPreferences,
    - BrandMemoryFragments,
    - pattern weights.

- **Team-scale reproducibility**:
  - a new strategist inherits:
    - the same patterns,
    - the same knobs,
    - the same brand memory,
    - instead of starting from zero with “their own” GPT prompt file.

If CE doesn’t sustainably beat that baseline on **time-to-good-draft**, **edit effort**, and **consistency over weeks**, we failed.

---