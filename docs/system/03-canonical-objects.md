# canonical objects

this document defines the **canonical object model** for kairo’s systems repo.

- each object is given a **CO-xx id**, a **job**, and a small set of **MUST-level invariants**.
- engine docs and the PRD must only refer to these objects (or explicitly propose new ones).
- changes to these definitions are **breaking** and should be treated as such (review + explicit version bump).

---

## index

**A. brand & actors**

- CO-01 — Brand  
- CO-02 — Persona  
- CO-03 — Pillar  
- CO-04 — User  

**B. brand brain**

- CO-05 — BrandBrainSnapshot  
- CO-06 — BrandRuntimeContext  
- CO-07 — BrandMemoryFragment  

**C. trend / opportunity**

- CO-08 — GlobalSourceDoc  
- CO-09 — OpportunityCard  
- CO-10 — OpportunityBatch  

**D. patterns / inspiration**

- CO-11 — PatternSourcePost  
- CO-12 — PatternTemplate  
- CO-13 — PatternUsage  

**E. content production**

- CO-14 — ContentPackage  
- CO-15 — CoreArgument  
- CO-16 — ChannelPlan  
- CO-17 — ContentVariant  

**F. learning & control**

- CO-18 — FeedbackEvent  
- CO-19 — BrandPreferences  
- CO-20 — GlobalPriors  

**G. publishing**

- CO-21 — ChannelConfig  
- CO-22 — PublishingJob  

---

## A. brand & actors

### CO-01 — Brand

**job**  
root entity; everything else hangs off this.

**created by**  
manual onboarding (ui / admin)

**mutated by**  
admin / brand settings flows only (no engines)

**read by**  
all engines, frontend everywhere

**MUSTs**

- MUST have stable `id` (uuid).
- MUST have `name` (display name).
- MUST have `slug` (url/id-safe, unique).
- MUST have `status` in `{active, inactive}`.
- MUST have `created_at` / `updated_at`.
- MUST have at least one `owner_user_id`.
- MUST specify at least one `primary_channel` (e.g. `linkedin`, `x`) once setup completes.

**example**

```json
{
  "id": "b_123",
  "name": "Acme Analytics",
  "slug": "acme-analytics",
  "status": "active",
  "owner_user_ids": ["u_1"],
  "primary_channels": ["linkedin", "x"],
  "created_at": "2025-01-01T10:00:00Z",
  "updated_at": "2025-01-02T12:00:00Z"
}
```

---

### CO-02 — Persona

**job**  
one audience segment for a brand.

**created by**  
brand brain engine (from onboarding + calibration)

**mutated by**  
brand brain engine (re-clustering, edits), manual edits

**read by**  
opportunities, patterns, content engineering, learning, frontend

**MUSTs**

- MUST have `id` and `brand_id`.
- MUST have `name` (e.g. `"Data-driven CMO"`).
- MUST have short `description`.
- MUST have at least one `pain_points` entry.
- MUST have at least one `goals` entry.
- MUST have `status` in `{active, hidden}` (for v1, `hidden` = not used).
- MUST have `created_at` / `updated_at`.

**example**

```json
{
  "id": "persona_1",
  "brand_id": "b_123",
  "name": "Data-driven CMO",
  "description": "CMO at B2B SaaS trying to justify marketing spend with clear attribution.",
  "pain_points": ["Board pressure on CAC/LTV", "Frustration with noisy data"],
  "goals": ["Prove ROI of campaigns", "Increase qualified pipeline"],
  "status": "active",
  "created_at": "2025-01-01T10:05:00Z",
  "updated_at": "2025-01-01T10:05:00Z"
}
```

---

### CO-03 — Pillar

**job**  
durable theme a brand talks about.

**created by**  
brand brain engine

**mutated by**  
brand brain engine, manual edits

**read by**  
opportunities, content engineering, patterns, learning, frontend

**MUSTs**

- MUST have `id` and `brand_id`.
- MUST have `name` (e.g. `"Strategy POV"`, `"Behind the Scenes"`).
- MUST have short `description`.
- MUST have `status` in `{active, hidden}`.
- MUST have optional `priority` (int, default 0) used by learning/CE to bias coverage.
- MUST have `created_at` / `updated_at`.

**example**

```json
{
  "id": "pillar_strategy",
  "brand_id": "b_123",
  "name": "Strategy POV",
  "description": "Big-picture opinions on how to run modern B2B marketing.",
  "status": "active",
  "priority": 10,
  "created_at": "2025-01-01T10:10:00Z",
  "updated_at": "2025-01-01T10:10:00Z"
}
```

---

### CO-04 — User

**job**  
human operator (creator, strategist, manager).

**created by**  
auth system

**mutated by**  
auth/profile flows

**read by**  
frontend, learning (for per-user feedback), permissions

**MUSTs**

- MUST have `id`.
- MUST have `email`.
- MUST have `role` in `{creator, strategist, manager, admin}` (non-exclusive later).
- MUST have `status` in `{active, inactive}`.
- MUST have `created_at`.
- MUST relate to brands via a mapping table (user can belong to multiple brands).

**example**

```json
{
  "id": "u_1",
  "email": "strategist@acme.com",
  "role": "strategist",
  "status": "active",
  "created_at": "2025-01-01T09:00:00Z"
}
```

---

## B. brand brain

### CO-05 — BrandBrainSnapshot

**job**  
versioned, structured identity + strategy for a brand at a point in time.

**created by**  
brand brain engine (initial onboarding + recalibration)

**mutated by**  
only brand brain engine (new snapshot; previous ones are immutable)

**read by**  
opportunities, content engineering, patterns, learning, frontend (“view strategy”)

**MUSTs**

- MUST have `id` and `brand_id`.
- MUST have `version` (int, monotonically increasing per brand).
- MUST have `created_at`.
- MUST contain **resolved** references to `persona_ids` and `pillar_ids` (not nested full objects).
- MUST contain:
  - `positioning` (short text),
  - `tone_descriptors` (list of labels, e.g. `["direct", "analytical"]`),
  - `offers` (short strings),
  - `taboos` (things to avoid).
- MUST be immutable once created (changes create a new snapshot, not mutate).

**example**

```json
{
  "id": "bbs_3",
  "brand_id": "b_123",
  "version": 3,
  "created_at": "2025-02-01T12:00:00Z",
  "positioning": "We help B2B teams turn chaotic data into clear revenue stories.",
  "tone_descriptors": ["direct", "analytical", "supportive"],
  "offers": ["Attribution audit", "RevOps playbook"],
  "taboos": ["Overpromising AI magic", "Trashing competitors"],
  "persona_ids": ["persona_1"],
  "pillar_ids": ["pillar_strategy", "pillar_bts"]
}
```

---

### CO-06 — BrandRuntimeContext

**job**  
current per-channel knobs derived from BrandBrainSnapshot + preferences.

**created by**  
brand brain engine (materialization step)

**mutated by**  
learning engine (weights / risk level / channel biases), manual toggles

**read by**  
opportunities, content engineering, patterns

**MUSTs**

- MUST have `id`, `brand_id`, and reference `brand_brain_snapshot_id`.
- MUST have `channel_overrides` keyed by channel (`linkedin`, `x`, etc.).
- each channel override MUST specify:
  - `tone_bias` (e.g. `{story_vs_tactical: 0…1, aggressive_vs_safe: 0…1}`),
  - `length_mode` (e.g. `short`, `medium`, `long`),
  - `risk_mode` (e.g. `safe`, `balanced`, `spicy`).
- MUST have `updated_at`.
- MUST be the **single source** of runtime knobs used by engines (they don’t read freeform UI flags).

**example**

```json
{
  "id": "brc_3",
  "brand_id": "b_123",
  "brand_brain_snapshot_id": "bbs_3",
  "channel_overrides": {
    "linkedin": {
      "tone_bias": { "story_vs_tactical": 0.4, "aggressive_vs_safe": 0.3 },
      "length_mode": "medium",
      "risk_mode": "balanced"
    },
    "x": {
      "tone_bias": { "story_vs_tactical": 0.2, "aggressive_vs_safe": 0.6 },
      "length_mode": "short",
      "risk_mode": "spicy"
    }
  },
  "updated_at": "2025-02-05T10:00:00Z"
}
```

---

### CO-07 — BrandMemoryFragment

**job**  
small on-brand snippet with embedding + tags.

**created by**  
brand brain engine (from imported examples), CE/patterns (from “save as example”), learning engine (curation)

**mutated by**  
rarely; mostly append-only, maybe re-tagged

**read by**  
brand brain, content engineering, opportunities, patterns

**MUSTs**

- MUST have `id`, `brand_id`.
- MUST have `source_type` in `{imported_example, generated_hit, manual}`.
- MUST have `raw_text` (short; e.g. 50–400 chars).
- MUST have embedding (vector ref / column).
- MUST reference optional `persona_id`, `pillar_id`, `pattern_template_id`.
- MUST have `created_at`.

**example**

```json
{
  "id": "frag_42",
  "brand_id": "b_123",
  "source_type": "generated_hit",
  "raw_text": "If your board only hears about clicks and not pipeline, your marketing data is failing you.",
  "persona_id": "persona_1",
  "pillar_id": "pillar_strategy",
  "pattern_template_id": "pt_confessional_1",
  "embedding": "[..vector..]",
  "created_at": "2025-02-02T11:00:00Z"
}
```

---

## C. trend / opportunity

### CO-08 — GlobalSourceDoc

**job**  
normalized external content (article/post/thread).

**created by**  
ingestion/scraper pipeline, user paste/import

**mutated by**  
opportunities engine (e.g. tagging relevance), maybe learning (confidence scores)

**read by**  
opportunities, patterns, learning

**MUSTs**

- MUST have `id`.
- MUST have `source_type` (`linkedin_post`, `x_post`, `article`, etc.).
- MUST have `source_url` (nullable for some imports but preferred).
- MUST have `author_handle` or similar when applicable.
- MUST have `language`.
- MUST have cleaned `text` (main body, boilerplate stripped).
- MUST have `published_at` (best effort) and `ingested_at`.

**example**

```json
{
  "id": "gsd_1001",
  "source_type": "article",
  "source_url": "https://example.com/b2b-attribution",
  "author_handle": "revops_jane",
  "language": "en",
  "text": "Most B2B attribution models fail because they ignore offline touchpoints...",
  "published_at": "2025-02-01T08:00:00Z",
  "ingested_at": "2025-02-01T12:00:00Z"
}
```

---

### CO-09 — OpportunityCard

**job**  
brand-specific “reason to speak now” derived from one or more GlobalSourceDocs (or internal triggers).

**created by**  
opportunities engine

**mutated by**  
learning (scores/labels), user (snooze, pin, ignore)

**read by**  
frontend board, content engineering, patterns, learning

**MUSTs**

- MUST have `id`, `brand_id`.
- MUST have `persona_id` and `pillar_id` (or explicit `persona_id = null` with `scope: global`, as an exception).
- MUST have `source_refs` (list of `{global_source_doc_id | internal_trigger, relevance_note}`).
- MUST have `angle_summary` (short human-readable explanation).
- MUST have `opportunity_type` in `{trend, evergreen, competitive, product, campaign}` (v1 can be fewer, but type is mandatory).
- MUST have numeric `score` (0–100) representing internal “opportunity strength”.
- MUST have `lifecycle_state` in `{new, in_progress, used, snoozed, dismissed}`:
  - `new`: generated but untouched,
  - `in_progress`: has at least one ContentPackage,
  - `used`: at least one package published from it,
  - `snoozed`: temporarily hidden by user,
  - `dismissed`: explicitly ignored.
- MUST have `created_at`; MUST never change `created_at` (immutable).

**example**

```json
{
  "id": "opp_501",
  "brand_id": "b_123",
  "persona_id": "persona_1",
  "pillar_id": "pillar_strategy",
  "source_refs": [
    { "global_source_doc_id": "gsd_1001", "note": "Article about broken attribution models" }
  ],
  "opportunity_type": "trend",
  "angle_summary": "Everyone is complaining about attribution dashboards; we show what a good one actually looks like.",
  "score": 82,
  "created_at": "2025-02-01T12:30:00Z"
}
```

---

### CO-10 — OpportunityBatch

**job**  
grouping of OpportunityCards for a time window for a brand.

**created by**  
opportunities engine scheduler

**mutated by**  
opportunities engine (re-score, add/remove cards), user actions (pin/unpin)

**read by**  
frontend “today’s board”, learning

**MUSTs**

- MUST have `id`, `brand_id`.
- MUST have `date_scope` (e.g. `2025-02-01` or a week id).
- MUST have `opportunity_ids` (list).
- MUST have `created_at`.
- MUST not be the only way to access cards (cards also queryable by brand/time).

**example**

```json
{
  "id": "batch_2025_02_01_b_123",
  "brand_id": "b_123",
  "date_scope": "2025-02-01",
  "opportunity_ids": ["opp_501", "opp_502"],
  "created_at": "2025-02-01T12:35:00Z"
}
```

---

## D. patterns / inspiration

### CO-11 — PatternSourcePost

**job**  
post used to extract a pattern from (internal hit or external model account).

**created by**  
patterns engine (when mining), data import

**mutated by**  
rarely (re-tagging), learning (attach outcome metrics)

**read by**  
patterns, learning

**MUSTs**

- MUST have `id`.
- MUST have `brand_id` OR `is_global` flag for external/model accounts.
- MUST have `channel`.
- MUST have `raw_text` (full post text).
- MUST have `created_at` (post time).
- MUST have optional metrics (`impressions`, `engagements`) if available.

**example**

```json
{
  "id": "psp_77",
  "brand_id": "b_123",
  "channel": "linkedin",
  "raw_text": "Last quarter, our CAC went up 40% because we trusted the wrong attribution model...",
  "impressions": 12000,
  "engagements": 350,
  "created_at": "2025-01-15T09:00:00Z"
}
```

---

### CO-12 — PatternTemplate

**job**  
reusable structural template (hook, beats, roles) with evidence.

**created by**  
patterns engine

**mutated by**  
patterns/learning (merge/split/refine; update stats, not semantics lightly)

**read by**  
content engineering, opportunities, brand brain, learning

**MUSTs**

- MUST have `id`.
- MUST have `name` (e.g. `"Confessional Story → Lesson → Call-to-Action"`).
- MUST have `channel_constraints` (allowed channels or `*`).
- MUST have `structure` (e.g. `["hook", "context", "inflection", "lesson", "cta"]`).
- MUST have `example_source_post_ids` (non-empty list referencing PatternSourcePost).
- MUST have aggregate `usage_stats` (count, avg performance) once used.
- MUST have `status` in `{active, experimental, deprecated}`.

**example**

```json
{
  "id": "pt_confessional_1",
  "name": "Confessional story → harsh truth → lesson",
  "channel_constraints": ["linkedin"],
  "structure": ["hook", "confession", "inflection_point", "lesson", "cta"],
  "example_source_post_ids": ["psp_77"],
  "usage_stats": { "times_used": 23, "avg_engagement_rate": 0.042 },
  "status": "active"
}
```

---

### CO-13 — PatternUsage

**job**  
log of pattern P used in variant V with outcome O.

**created by**  
content engineering (when generating variants) + learning (when backfilling metrics)

**mutated by**  
learning (attach outcomes as they arrive)

**read by**  
patterns, learning, analytics

**MUSTs**

- MUST have `id`.
- MUST have `pattern_template_id`, `content_variant_id`, `brand_id`.
- MUST have `channel`.
- MUST have `created_at`.
- MUST eventually store `outcome` once available (e.g. impressions, clicks, etc.), but can start null.

**example**

```json
{
  "id": "pu_9001",
  "pattern_template_id": "pt_confessional_1",
  "content_variant_id": "cv_300",
  "brand_id": "b_123",
  "channel": "linkedin",
  "created_at": "2025-02-03T14:00:00Z",
  "outcome": {
    "impressions": 8000,
    "engagements": 260
  }
}
```

---

## E. content production

### CO-14 — ContentPackage

**job**  
full lifecycle unit for one opportunity (or manually created topic).

**created by**  
content engineering engine (when user “opens” or “generate package” from an OpportunityCard, or manually)

**mutated by**  
content engineering (regenerations), learning (labels), user edits (status, labels)

**read by**  
frontend “workspace”, learning, publishing

**MUSTs**

- MUST have `id`, `brand_id`.
- MUST reference either `opportunity_id` OR explicit `origin_type` (`manual`, `evergreen_seed`) with `origin_note`.
- MUST have `core_argument_id`.
- MUST have `status` in `{draft, in_review, approved, scheduled, published, archived}`.
- MUST have `created_at`, `updated_at`.
- MUST have `channel_plan_ids` (one or more planned channels) OR be explicitly flagged as `channel_scope: single` with one channel.

**example**

```json
{
  "id": "cp_100",
  "brand_id": "b_123",
  "opportunity_id": "opp_501",
  "origin_type": "opportunity",
  "core_argument_id": "ca_100",
  "status": "draft",
  "channel_plan_ids": ["chp_100_lk", "chp_100_x"],
  "created_at": "2025-02-01T13:00:00Z",
  "updated_at": "2025-02-01T13:05:00Z"
}
```

---

### CO-15 — CoreArgument

**job**  
channel-agnostic message for a package (“what we’re actually saying”).

**created by**  
content engineering engine

**mutated by**  
content engineering engine regenerations, user edits (inline)

**read by**  
content engineering (when rendering channels), opportunities (for back references), learning

**MUSTs**

- MUST have `id`, `content_package_id`.
- MUST have short `thesis` (1–2 sentences).
- MUST have `supporting_points` (3–7 bullets).
- MUST reference `persona_id`, `pillar_id` (locked for the package).
- MUST have `created_at`, `updated_at`.

**example**

```json
{
  "id": "ca_100",
  "content_package_id": "cp_100",
  "persona_id": "persona_1",
  "pillar_id": "pillar_strategy",
  "thesis": "Attribution dashboards should tell a revenue story, not just show pretty charts.",
  "supporting_points": [
    "Most tools dump channel metrics with no pipeline context.",
    "Your board cares about pipeline and bookings, not CTR.",
    "A good attribution model surfaces a few clear levers you can pull."
  ],
  "created_at": "2025-02-01T13:00:00Z",
  "updated_at": "2025-02-01T13:00:00Z"
}
```

---

### CO-16 — ChannelPlan

**job**  
per-channel plan: which pattern(s), how beats map, and how many variants to produce.

**created by**  
content engineering engine

**mutated by**  
content engineering engine (regens), user toggles (enable/disable channels, pattern choice)

**read by**  
content engineering when rendering variants, frontend

**MUSTs**

- MUST have `id`, `content_package_id`.
- MUST have `channel` in `{linkedin, x, youtube_script, …}`.
- MUST have `pattern_bindings` list; each binding MUST have:
  - `pattern_template_id`,
  - `beats` (mapping from pattern structure elements to descriptions),
  - `target_variants` (int).
- MUST reference `brand_brain_snapshot_id` used to generate (for traceability).
- MUST have `created_at`, `updated_at`.

**example**

```json
{
  "id": "chp_100_lk",
  "content_package_id": "cp_100",
  "channel": "linkedin",
  "brand_brain_snapshot_id": "bbs_3",
  "pattern_bindings": [
    {
      "pattern_template_id": "pt_confessional_1",
      "beats": {
        "hook": "Highlight the pain of noisy dashboards",
        "confession": "We shipped vanity dashboards for years.",
        "inflection_point": "Board asked a simple pipeline question we couldn't answer.",
        "lesson": "Tie every chart to pipeline stages.",
        "cta": "DM for our attribution sanity check."
      },
      "target_variants": 2
    }
  ],
  "created_at": "2025-02-01T13:01:00Z",
  "updated_at": "2025-02-01T13:01:00Z"
}
```

---

### CO-17 — ContentVariant

**job**  
concrete draft/script/asset for [opportunity/core argument, channel, pattern].

**created by**  
content engineering engine

**mutated by**  
user edits (text), CE (regens, alternate versions), learning (labels only)

**read by**  
frontend editor, publishing, learning, patterns

**MUSTs**

- MUST have `id`, `content_package_id`, `channel_plan_id`.
- MUST have `brand_id`, `channel`.
- MUST reference `pattern_template_id`, `persona_id`, `pillar_id`.
- MUST store `body` (text; later structured for scripts).
- MUST have `status` in `{draft, edited, approved, rejected, published}`.
- MUST have `created_at`, `updated_at`.
- MUST have origin info: `{generated_by: "ce_v1", source_variant_id: null | other}`.

**example**

```json
{
  "id": "cv_300",
  "content_package_id": "cp_100",
  "channel_plan_id": "chp_100_lk",
  "brand_id": "b_123",
  "channel": "linkedin",
  "pattern_template_id": "pt_confessional_1",
  "persona_id": "persona_1",
  "pillar_id": "pillar_strategy",
  "status": "draft",
  "body": "For 3 years, we shipped gorgeous marketing dashboards that our board quietly ignored...",
  "origin": {
    "generated_by": "ce_v1",
    "source_variant_id": null
  },
  "created_at": "2025-02-01T13:02:00Z",
  "updated_at": "2025-02-01T13:02:00Z"
}
```

---

## F. learning & control

### CO-18 — FeedbackEvent

**job**  
normalized feedback/learning signal.

**created by**  
frontend (user actions), backend hooks (performance ingestion)

**mutated by**  
never; append-only

**read by**  
learning engine, analytics

**MUSTs**

- MUST have `id`.
- MUST have `brand_id`, `user_id` (nullable for system-generated events), and optionally `content_variant_id`, `pattern_template_id`, `opportunity_id`.
- MUST have `feedback_type` in `{variant_rating, edit_applied, never_again, saved_as_example, performance_snapshot}`.
- MUST have `payload` (typed per `feedback_type`).
- MUST have `created_at`.
- MUST be immutable after creation.

**example**

```json
{
  "id": "fb_900",
  "brand_id": "b_123",
  "user_id": "u_1",
  "content_variant_id": "cv_300",
  "feedback_type": "variant_rating",
  "payload": { "rating": 4, "dimensions": { "tone_match": 5, "specificity": 4 } },
  "created_at": "2025-02-01T13:10:00Z"
}
```

---

### CO-19 — BrandPreferences

**job**  
learned per-brand preferences (weights, biases, risk).

**created by**  
learning engine (initial defaults based on GlobalPriors)

**mutated by**  
learning engine only

**read by**  
brand brain (when building runtime), opportunities, content engineering, patterns

**MUSTs**

- MUST have `id`, `brand_id`.
- MUST have `pattern_weights` (map `pattern_template_id → weight`).
- MUST have `tone_bias_overrides` (map tone dimensions → biases).
- MUST have `persona_pillar_bias` (how much to prioritize certain combinations).
- MUST have `opportunity_scoring_weights` (how to weight freshness vs brand relevance vs competitive, etc.).
- MUST have `updated_at`.
- MUST be the **only** place that long-term learned knobs are persisted; engines don’t invent their own preference stores.

**example**

```json
{
  "id": "bp_b_123",
  "brand_id": "b_123",
  "pattern_weights": {
    "pt_confessional_1": 1.4,
    "pt_listicle_1": 0.8
  },
  "tone_bias_overrides": {
    "story_vs_tactical": 0.5,
    "aggressive_vs_safe": 0.3
  },
  "persona_pillar_bias": {
    "persona_1::pillar_strategy": 1.2
  },
  "opportunity_scoring_weights": {
    "freshness": 0.6,
    "brand_relevance": 1.0,
    "competitive_angle": 0.4
  },
  "updated_at": "2025-02-05T11:00:00Z"
}
```

---

### CO-20 — GlobalPriors

**job**  
cross-brand priors for patterns/tones/opportunities.

**created by**  
learning engine batch jobs

**mutated by**  
learning engine only

**read by**  
learning (seeding), BrandPreferences init, maybe analytics

**MUSTs**

- MUST have `id` (single row or per-segment).
- MUST have aggregate stats per `pattern_template_id`, `channel`, maybe vertical.
- MUST have default weights for tone dimensions and opportunity scoring.
- MUST have `updated_at`.
- MUST never reference specific brand IDs (anonymized).

**example**

```json
{
  "id": "global_priors_default",
  "pattern_stats": {
    "pt_confessional_1": { "avg_engagement_rate": 0.035, "times_used": 800 },
    "pt_listicle_1": { "avg_engagement_rate": 0.028, "times_used": 500 }
  },
  "default_tone_bias": {
    "linkedin": { "story_vs_tactical": 0.4, "aggressive_vs_safe": 0.3 }
  },
  "default_opportunity_weights": {
    "freshness": 0.5,
    "brand_relevance": 1.0
  },
  "updated_at": "2025-02-01T00:00:00Z"
}
```

---

## G. publishing

### CO-21 — ChannelConfig

**job**  
auth + constraints per brand/channel.

**created by**  
auth/connect flow

**mutated by**  
connect/disconnect, token refresh

**read by**  
publishing, opportunities (what channels exist), frontend

**MUSTs**

- MUST have `id`, `brand_id`, `channel`.
- MUST have `status` in `{connected, disconnected, error}`.
- MUST have `scopes` (permissions granted).
- MUST have `rate_limits` (optional, but structure reserved).
- MUST have `created_at`, `updated_at`.

**example**

```json
{
  "id": "chcfg_b123_lk",
  "brand_id": "b_123",
  "channel": "linkedin",
  "status": "connected",
  "scopes": ["post", "read_analytics"],
  "rate_limits": { "posts_per_day": 20 },
  "created_at": "2025-01-10T10:00:00Z",
  "updated_at": "2025-02-01T09:00:00Z"
}
```

---

### CO-22 — PublishingJob

**job**  
scheduled publish task for a variant.

**created by**  
frontend (schedule button) or immediate publish action

**mutated by**  
publishing logic (status changes), retries

**read by**  
frontend (status), analytics

**MUSTs**

- MUST have `id`, `brand_id`.
- MUST have `content_variant_id`, `channel`.
- MUST have `scheduled_at` (time to publish).
- MUST have `status` in `{pending, running, success, failed, canceled}`.
- MUST have `created_at`, `updated_at`.
- MUST have `last_error` (nullable) for failures.

**example**

```json
{
  "id": "pub_700",
  "brand_id": "b_123",
  "content_variant_id": "cv_300",
  "channel": "linkedin",
  "scheduled_at": "2025-02-02T09:00:00Z",
  "status": "pending",
  "last_error": null,
  "created_at": "2025-02-01T13:20:00Z",
  "updated_at": "2025-02-01T13:20:00Z"
}
```

---

## notes on evolution

- if an engine needs a new object, propose a **CO-xx** with:
  - job,
  - invariants,
  - example,
  - and how it relates to existing COs.
- if you find yourself adding ad-hoc JSON blobs to existing objects “for this one feature”, stop and either:
  - add a proper field here, or
  - introduce a new CO and link to it.

this doc is the **single source of truth** for the backend data model at the concept level.