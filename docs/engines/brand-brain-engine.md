# brand brain engine

## 1. purpose

the brand brain engine is the **single source of structured brand identity** in kairo.

it turns messy brand inputs (onboarding answers, example posts, inspiration, calibration feedback) into:

- **CO-05 BrandBrainSnapshot** – versioned brand strategy and identity
- **CO-06 BrandRuntimeContext** – per-channel runtime knobs used by all engines
- **CO-07 BrandMemoryFragment** – fragment-level examples for retrieval

if this engine is weak, every other engine (opportunities, patterns, CE, learning) becomes generic or unstable.

---

## 2. position in the system

**upstream of everything:**

- runs **after** a Brand (CO-01) is created and basic onboarding is done.
- produces BrandBrainSnapshot / BrandRuntimeContext / BrandMemoryFragment for that brand.
- these are then consumed by:
  - **opportunities engine**: to score/match GlobalSourceDoc → OpportunityCard.
  - **patterns engine**: to interpret PatternSourcePost in brand terms.
  - **content engineering engine**: to lock persona, pillar, tone, taboos, style choices per ContentPackage.
  - **learning engine**: to update BrandPreferences (CO-19) and suggest brand-level adjustments.

**lifecycle:**

- **low frequency, high impact**:
  - heavy work at onboarding + occasional recalibration.
  - small updates when learning suggests changes (and user approves).

---

## 3. one-line definition

> brand brain engine turns messy brand inputs into structured, versioned **BrandBrainSnapshot + BrandRuntimeContext + BrandMemoryFragment** objects that reliably steer all other engines for that brand.

---

## 4. inputs

### 4.1 canonical objects

- **CO-01 Brand**
  - must exist and be `active`.
  - provides `id`, `name`, `primary_channels`.

- **CO-04 User**
  - the user who is driving onboarding/calibration (strategist / creator).
  - used for ownership, audit trails.

- **CO-19 BrandPreferences** (optional, may be null for new brands)
  - initial weights/priors if this brand has history or is re-onboarding.

- **CO-20 GlobalPriors**
  - cross-brand priors for patterns/tones/opportunity weighting, used as defaults.

### 4.2 engine-local / raw inputs

(these are *not* canonical objects; they live in engine-specific tables)

- **OnboardingForm**
  - minimal Qs (solo-creator v1 path):
    - `one_liner` – “what do you do?”
    - `audience_text` – “who do you talk to?”
    - `goals_text` – “what do you want content to achieve?”
    - `anti_voice_text` – “how do you not want to sound?”
    - `taboo_text` – “what do you never talk about?”
  - may have extra form fields later (vertical, product lines, regions).

- **ExamplePost[]**
  - 3–10 posts they mark as:
    - `"this_is_us"` or `"this_is_not_us"`.
  - for each:
    - channel,
    - raw text (and optional link),
    - label, optional notes.

- **InspirationPost[]** (optional)
  - external posts from other creators:
    - “this feels right”, “this is aspirational but not us yet”, etc.

- **CalibrationPreview[] + Feedback**
  - short preview posts generated from an initial draft BrandBrain snapshot.
  - user ratings + tags, e.g.:
    - rating 1–5 for “voice match”.
    - tags like “too corporate”, “too fluffy”, “too aggressive”, “too generic”.

### 4.3 guarantees to downstream

brand brain guarantees that **for any brand with a “ready” status**:

- there exists at least one **BrandBrainSnapshot (CO-05)** for that brand.
- there exists an associated **BrandRuntimeContext (CO-06)** with overrides for all `primary_channels`.
- there exists a minimal usable **BrandMemoryFragment (CO-07)** set:
  - ≥ N positive fragments (tunable, e.g. 10–30),
  - correctly tagged with `persona_id` / `pillar_id` where applicable.

if these cannot be satisfied, the brand is **explicitly marked “uncalibrated”**, and downstream engines must run in degraded mode.

---

## 5. outputs & storage

### 5.1 CO-05 BrandBrainSnapshot

**job**: versioned, structured identity + strategy for a brand at a point in time.

- created by: brand brain engine.
- mutated by: *never* – new versions only.

**fields (high level):**

- `id`, `brand_id`, `version`, `created_at`.
- `positioning` – short text.
- `tone_descriptors` – 3–7 adjectives and core tone dimensions (formality, aggression, humor, reading_level).
- `offers` – primary + secondary offers, benefits, objections.
- `taboos` – structured rules (incl. enforcement hints).
- `language_codes` – list, non-empty.
- `persona_ids` – references to CO-02 Persona.
- `pillar_ids` – references to CO-03 Pillar.

brand brain engine is responsible for **creating** those CO-02 / CO-03 objects and wiring them into this snapshot.

---

### 5.2 CO-06 BrandRuntimeContext

**job**: current per-channel knobs derived from BrandBrainSnapshot + BrandPreferences + user preferences.

- created by: brand brain engine.
- mutated by: brand brain engine (materialization) + learning engine (over time).

**fields (high level):**

- `id`, `brand_id`, `brand_brain_snapshot_id`.
- `channel_overrides` keyed by channel:
  - `tone_bias` (e.g. `story_vs_tactical`, `aggressive_vs_safe`),
  - `length_mode` (short / medium / long),
  - `risk_mode` (safe / balanced / spicy).
- `updated_at`.

this is the **single source of runtime knobs** that opportunities, patterns, and CE can rely on.

---

### 5.3 CO-07 BrandMemoryFragment

**job**: small on-brand snippets with embeddings + tags used for retrieval.

- created by:
  - brand brain engine (from imported examples / onboarding).
  - CE/patterns/learning engine (promoting “hits” later).
- mutated by:
  - rare – mostly re-tagging, never cross-brand.

**fields (high level):**

- `id`, `brand_id`.
- `source_type` – `imported_example | generated_hit | manual`.
- `raw_text` – short fragment.
- `embedding` – vector.
- `persona_id`, `pillar_id`, `pattern_template_id` (optional).
- `created_at`.

brand brain’s responsibility in v1: **seed** this library from ExamplePost / InspirationPost.

---

### 5.4 related learned objects

brand brain doesn’t own these, but it **interacts** with them:

- **CO-19 BrandPreferences**
  - learning owns, but brand brain:
    - reads to set defaults in BrandRuntimeContext.
    - exposes knobs in UI in a safe, minimal way.

- **CO-20 GlobalPriors**
  - learning owns, but brand brain uses for:
    - default pattern weights / tone biases for a new brand.

---

## 6. invariants

brand brain engine has **done its job** if all of this is true for an “active & calibrated” brand:

### 6.1 BrandBrainSnapshot invariants (CO-05)

- `persona_ids`:
  - between 1–5.
  - at most 3 with “high priority” (if priority is encoded).
- `pillar_ids`:
  - between 2–5 pillars.
- `tone_descriptors`:
  - 3–7 descriptors present.
  - tone dimension values (formality, aggression, etc.) are all set.
- `taboos`:
  - at least one TabooRule exists.
- `language_codes`:
  - non-empty; at least one supported language.

### 6.2 BrandRuntimeContext invariants (CO-06)

- for every **active channel** in `Brand.primary_channels`:
  - there is a corresponding entry in `channel_overrides`.
  - each override has:
    - `tone_bias`,
    - `length_mode`,
    - `risk_mode`.

### 6.3 BrandMemoryFragment invariants (CO-07)

- all fragments:
  - reference the **correct `brand_id`** (no cross-brand leakage).
  - have non-empty `raw_text`.
  - are tagged with `language` that matches `language_codes` of the brand.
- there are **at least N positive fragments** (brand-specific threshold).

### 6.4 snapshot invariants

- every downstream pipeline run (opportunities / CE / patterns) that uses brand brain **must** store `brand_brain_snapshot_id` or `brand_core_version` equivalently.
- no engine should run with a **half-baked** snapshot:
  - if invariants fail, brand brain must mark the brand as `uncalibrated` and set a flag consumed by downstream engines.

---

## 7. engine flow (v1)

high-level steps, ignoring implementation details:

1. **collect raw inputs**
   - gather `OnboardingForm`, `ExamplePost[]`, optional `InspirationPost[]`.
   - persist them as raw records linked to `brand_id`.

2. **initial extraction pass**
   - use LLM structured extraction on OnboardingForm to propose:
     - positioning,
     - tone descriptors,
     - offers,
     - initial taboo candidates,
     - rough ICP text.

3. **example classification**
   - for each ExamplePost:
     - classify:
       - tone features,
       - approximate structure / pattern type,
       - candidate persona/pillar alignment,
       - `is_positive` / `is_negative`.
   - use this to:
     - refine tone,
     - refine persona / pillar candidates,
     - seed BrandMemoryFragment proposals.

4. **draft identity construction**
   - synthesize:
     - 1–5 Persona objects (CO-02),
     - 2–5 Pillar objects (CO-03),
     - initial TabooRules list,
     - tone profile,
     - offers summary.
   - build a **draft BrandBrainSnapshot** (CO-05) not yet marked as “approved”.

5. **preview & calibration loop**
   - generate 3–5 preview posts and short descriptions, each tagged with persona/pillar.
   - surface to user:
     - rating 1–5 per preview,
     - tags like “too corporate / too fluffy / off ICP / wrong language / etc.”
   - convert these into **FeedbackEvent (CO-18)** records.
   - optionally adjust the draft snapshot based on calibrated signals.

6. **finalize snapshot**
   - once the user accepts:
     - persist BrandBrainSnapshot (CO-05) as version `N`.
     - mark brand as `calibrated` (if invariants are met).

7. **materialize runtime context**
   - using:
     - BrandBrainSnapshot,
     - BrandPreferences (if it exists),
     - default rules from GlobalPriors,
   - compute **BrandRuntimeContext (CO-06)** for all active channels.

8. **seed memory fragments**
   - from:
     - positive ExamplePost fragments,
     - high-signal parts of preview posts that user rated highly.
   - write **BrandMemoryFragment (CO-07)** rows with embeddings.

9. **emit learning hooks**
   - write FeedbackEvent (CO-18) for:
     - onboarding preview ratings,
     - later “saved as example” actions,
     - taboo violation confirmations.
   - learning engine uses these to adjust BrandPreferences and propose future BrandBrainSnapshot changes.

---

## 8. tech / dependencies (systems-level)

brand brain is **LLM-heavy but infrequent**:

- needs:
  - LLM structured extraction for:
    - onboarding parsing,
    - example classification,
    - persona/pillar/tone inference.
  - embeddings (pgvector) for BrandMemoryFragment.

- storage:
  - postgres tables mapped to:
    - BrandBrainSnapshot (CO-05),
    - BrandRuntimeContext (CO-06),
    - BrandMemoryFragment (CO-07),
    - onboarding raw inputs,
    - calibration previews & FeedbackEvent (CO-18) records.

- validation:
  - all LLM JSON outputs validated against schemas (backend layer).

---

## 9. quality dimensions

primary axes for brand brain engine (per brand):

1. **identity coherence**
   - personas, pillars, tone, offers, taboos don’t contradict each other.
   - snapshot reads like a single, coherent strategy, not a grab-bag of labels.

2. **persona clarity**
   - personas are distinct, non-overlapping, and tied to real economic roles or scenarios.
   - each persona can be “explained” in 1–2 lines without sounding generic.

3. **pillar usefulness**
   - pillars map to content types the brand actually wants to produce (strategy POV, case studies, BTS, etc.).
   - they’re not vague slogans that don’t inform what to write next week.

4. **voice fidelity**
   - preview posts feel like the brand:
     - target: ≥ 7/10 after one calibration loop.

5. **taboo correctness**
   - taboos reflect real “do-not-cross” lines.
   - they don’t over-block valid content and don’t miss obvious landmines.

approx measurement:

- LLM eval prompts:
  - “rate coherence of this BrandBrainSnapshot 1–10”.
  - “are these personas distinct and economically relevant?”.
- human evaluation on:
  - a fixed internal benchmark brand set.
- live metrics:
  - % of CE outputs flagged off-brand.
  - number of taboo violation flags over time.

---

## 10. failure modes

### 10.1 acceptable (user can fix quickly)

- personas slightly generic but directionally okay.
- tone adjectives ~70% right; user tweaks in UI.
- missing some taboos; user adds later via UI.
- minor mismatches between pillars and how they label them, but still usable.

### 10.2 unacceptable (engine is not doing its job)

- BrandBrainSnapshot pushes the brand to **target the wrong ICP**.
- pillars that don’t map to any content they’d actually post in the next quarter.
- tone profile so misaligned that preview posts feel like **3/10** on voice.
- BrandMemoryFragment mixing:
  - languages across brands,
  - or **cross-brand text reuse** (verbatim phrasing reused).

any unacceptable failure must:

- mark brand as `uncalibrated` / `needs_review`.
- trigger degraded mode warnings downstream (CE, opportunities).

---

## 11. how failures surface to the user

- **onboarding preview screen**
  - show 3–5 short posts tagged with persona+pillar.
  - ask:
    - “how close to your voice?” 1–5.
    - quick reasons.
  - if scores are low:
    - explicitly say:
      - “brand not calibrated; results may feel generic.”
    - give clear CTA to adjust tone/personas/pillars.

- **taboo violation flow**
  - when CE outputs something that trips a TabooRule:
    - flag: “this appears to violate your brand rule: [rule text].”
    - user marks:
      - false positive / true positive.
    - log as FeedbackEvent.

- **brand evolution suggestions**
  - when enough signals accumulate:
    - learning proposes updated BrandPreferences & BrandBrainSnapshot deltas:
      - “we think your tone is more X than Y based on recent approvals — accept?”
    - only on **explicit accept** do we:
      - bump BrandBrainSnapshot version.
      - update BrandRuntimeContext.

---

## 12. blind spots & mitigation

### 12.1 energy cost (user fatigue)

**risk:** onboarding turns into a “brand strategy workshop in a box”.

mitigation:

- cap default onboarding to:
  - 5 core questions,
  - 3–10 example posts,
  - 1 calibration preview loop.
- push everything else to:
  - “advanced settings”,
  - or later iterative refinement.

### 12.2 defaults vs knobs

**risk:** exposing too many knobs → user confusion; exposing too few → they feel boxed in.

mitigation:

- brand brain chooses:
  - **sane defaults**:
    - 2–4 pillars, 1–3 personas, modest tone.
  - **minimal visible knobs**:
    - per-channel sliders (story vs tactical, safe vs spicy),
    - optional campaign overlays later.

everything else stays internal (BrandPreferences / GlobalPriors).

### 12.3 multi-brand effects

**risk:** cross-brand leakage or subtle contamination.

mitigation:

- strict `brand_id` + `language` filtering in retrieval.
- no cross-brand text reuse in BrandMemoryFragment.
- global knowledge only lives in **GlobalPriors (CO-20)**:
  - statistical performance, no text.

### 12.4 data governance

principle:

- **BrandBrainSnapshot / BrandRuntimeContext / BrandMemoryFragment** are client-owned.

mitigation:

- must be fully deletable on churn.
- only anonymized stats roll into GlobalPriors:
  - e.g. “pattern X performs better on linkedin for B2B SaaS”.

---

## 13. evolution path

### 13.1 v1 (bare minimum)

- BrandBrainSnapshot (CO-05):
  - 1–3 personas,
  - 2–4 pillars,
  - simple tone descriptors,
  - basic taboo list.
- BrandRuntimeContext (CO-06):
  - basic per-channel defaults (tone, length, risk).
- BrandMemoryFragment (CO-07):
  - small positive fragment set.
- one onboarding pass + one calibration loop.

### 13.2 “great” version (12–18 months)

- multi-language support (per-brand).
- campaign overlays in BrandRuntimeContext.
- richer taboo enforcement (semantic models).
- global intelligence layer (via GlobalPriors, PatternTemplate performance).
- robust offline eval pipeline for BrandBrainSnapshot extraction:
  - benchmark brands,
  - regression tests across engine versions.

the split into **snapshot / runtime / memory** stays stable so the system can grow without rewriting everything.

---