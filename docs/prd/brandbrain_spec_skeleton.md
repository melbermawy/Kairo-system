# BrandBrain Spec Skeleton (v0)

**Status:** Skeleton / Implementation Contract
**Goal:** Define the v1 BrandBrain IR + the minimal pipeline to compile it from tiered user inputs and optional Apify pulls (free-tier exploration first).
**Non-Goal:** This doc is not a full PRD. It is a "don't-hallucinate" contract for step 1.

---
## process + intent (how to read this doc)

this doc is an implementation contract for building **brandbrain** without hallucinating what platforms or data “must” look like.

we’re using a 3-step approach:

**step 0 (this doc):** define the *target* internal representation (BrandBrain IR) and the compiler contract (tiered inputs → schema-valid IR), plus what we will and won’t assume. this prevents us from building a pretty onboarding form that compiles to vibes.

**step 1 (apify exploration, free tier):** run a few cheap, capped pulls (hard budget cap) to see what we can *actually* extract from platforms. we store raw outputs first, then write a short “field observations” note. no schema changes are allowed unless they’re justified by real samples.

**step 2 (implementation):** implement the pipeline end-to-end:
tiered inputs + optional apify/web enrichment → normalization → IR compile → persist → view DTO, with tests and idempotency.

the reason for this order is simple: we want a brandbrain that is (a) executable, (b) auditable, and (c) grounded in reality of data availability—before we scale ingestion or polish UI.


## 1) Scope + Non-Goals

### In-Scope (v1)

- Define a **schema-valid BrandBrain IR** (internal representation) that can actually constrain downstream generation.
- Define **tiered onboarding inputs** (tier 0/1/2) that compile into the same IR shape.
- Define **Apify exploration pulls** (free tier) used to *enrich* the IR (not replace human intent).
- Define persistence + view DTO: store IR in DB, and render it back to frontend as a view DTO.

### Out-of-Scope (v1)

- Perfect "learning engine" (autonomous improvement from outcomes).
- Enterprise-grade reliability, continuous ingestion, hourly scraping, etc.
- Full enforcement everywhere (we'll define hooks, not implement every guard).
- Full multi-tenant auth. Brand is addressed by `brand_id`; auth comes later.

---

## 2) Definitions

| Term | Definition |
|------|------------|
| **BrandBrain IR** | The canonical compiled representation we use at generation time (strict schema, executable constraints). |
| **Tiered Inputs** | Progressive levels of brand setup complexity (see below). |

### Tiered Inputs

| Tier | Name | Description |
|------|------|-------------|
| **Tier 0** | Minimum | Quick setup; enough to generate something plausibly on-brand. |
| **Tier 1** | Standard | Adds structured voice, audience, pillars, taboos. |
| **Tier 2** | Deep | Adds proof via examples, competitor set, claims, lexicon, "what good looks like". |

### Sources

| Source | Description |
|--------|-------------|
| **Human** | Answers + selected examples. |
| **Web/Crawl** | Brand site pages to understand positioning + claims. |
| **Apify** | Social post history + metadata to infer style + recurring patterns. |

---

## 3) V1 Supported Output Formats (Content Packages)

This is *not* the onboarding UI yet—just the target formats the IR must support constraining.

### Supported Formats (v1)

| Format | Priority Note |
|--------|---------------|
| `short_video` | Must be as easy to generate *well* as the others |
| `meme` | - |
| `thread` | - |
| `carousel` | - |
| `post` | Generic single post |

> **Note:** "Format > Channel". Channel/platform is provenance + distribution context, not the primary creative structure.

---

## 4) BrandBrain IR v1 Schema (Canonical)

### 4.1 Top-Level Object: `BrandBrainIR_v1`

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | `"v1"` | Schema version |
| `brand_id` | string (UUID) | Brand identifier |
| `compiled_at` | ISO datetime string | Compilation timestamp |
| `positioning` | object | See §4.2 |
| `voice` | object | See §4.3 |
| `audiences` | array | See §4.4 |
| `pillars` | array | See §4.5 |
| `formats` | object | Per supported format constraints (§4.6) |
| `taboos` | object | See §4.7 |
| `claims` | object | See §4.8 |
| `lexicon` | object | See §4.9 |
| `proof` | object | Examples + refs (§4.10) |

#### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `competitors` | array | Competitor information |
| `regions_languages` | object | Regional/language settings |
| `compliance` | object | Compliance requirements |

### 4.2 `positioning`

| Field | Type |
|-------|------|
| `one_liner` | string |
| `expanded` | string |
| `category` | string |
| `differentiators` | string[] |
| `value_props` | string[] |
| `what_we_do_not_do` | string[] |
| `primary_ctas` | string[] (e.g., "try it", "order now", "download") |
| `pricing_sensitivity` | `"low"` \| `"mid"` \| `"high"` \| `"unknown"` |

### 4.3 `voice`

| Field | Type | Notes |
|-------|------|-------|
| `tone_sliders` | object | See below |
| `style_rules` | string[] | Imperatives like "short sentences", "no emojis", "never sound corporate" |
| `signature_moves` | string[] | Recurring rhetorical moves |
| `banned_phrases` | string[] | - |
| `allowed_slang` | string[] | - |
| `reading_level` | `"simple"` \| `"general"` \| `"expert"` | - |

#### `tone_sliders` (all 0–5)

| Slider | Range |
|--------|-------|
| `humor` | 0–5 |
| `boldness` | 0–5 |
| `formality` | 0–5 |
| `snark` | 0–5 |
| `earnestness` | 0–5 |

### 4.4 `audiences[]` (Each Item)

| Field | Type | Required |
|-------|------|----------|
| `name` | string | Yes (e.g., "gen-z snackers", "busy parents") |
| `jobs_to_be_done` | string[] | Yes |
| `pains` | string[] | Yes |
| `desired_gains` | string[] | Yes |
| `objections` | string[] | Yes |
| `channels_context` | string[] | No (not a hard constraint) |

### 4.5 `pillars[]` (Each Item)

| Field | Type |
|-------|------|
| `name` | string |
| `why_it_matters` | string |
| `keywords` | string[] |
| `angles` | string[] (reusable angles) |
| `do_more_of` | string[] |
| `avoid_in_this_pillar` | string[] |

### 4.6 `formats` (Constraints by Format)

Common shape for each supported format key (e.g., `formats.short_video`):

| Field | Type | Notes |
|-------|------|-------|
| `structure.beats` | string[] | e.g., hook → tension → punchline → CTA |
| `structure.max_seconds` | number | `short_video` only |
| `structure.max_words` | number | `thread`/`post` |
| `creative_rules` | string[] | Format-specific |
| `cta_rules` | string[] | What CTA styles are allowed |
| `editing_notes` | string[] | `short_video` only (e.g., captions style, cut pacing) |
| `example_ids` | string[] | References into `proof.examples` |

### 4.7 `taboos`

| Field | Type |
|-------|------|
| `topics` | string[] |
| `claims` | string[] (explicit forbidden claims) |
| `tone` | string[] (e.g., "no dunking on customers") |
| `legal` | string[] (e.g., "no medical claims") |
| `competitor_mentions` | `"never"` \| `"allowed_no_dunks"` \| `"allowed"` |
| `safety_notes` | string[] (meta notes) |

### 4.8 `claims`

**Goal:** Constrain what we can safely assert.

| Field | Type |
|-------|------|
| `allowed_claims` | array of claim objects (see below) |
| `disallowed_claim_patterns` | string[] (regex-like natural language patterns; v1 = simple substrings) |

#### Claim Object

| Field | Type | Required |
|-------|------|----------|
| `claim` | string | Yes |
| `evidence_url` | string | No |
| `confidence` | `"high"` \| `"medium"` \| `"low"` | Yes |

### 4.9 `lexicon`

| Field | Type |
|-------|------|
| `must_use_terms` | string[] |
| `should_use_terms` | string[] |
| `must_avoid_terms` | string[] |
| `product_names` | string[] |
| `competitor_names` | string[] |
| `hashtag_bank` | string[] (optional) |

### 4.10 `proof`

#### `examples[]` (Each Item)

| Field | Type | Required |
|-------|------|----------|
| `id` | string | Yes |
| `source` | `"human"` \| `"apify"` \| `"web"` | Yes |
| `format` | one of supported formats | Yes |
| `url` | string | No |
| `text` | string | Yes (transcripts allowed) |
| `why_good` | string[] | Yes |
| `tags` | string[] | Yes |

#### `references[]` (Each Item)

| Field | Type |
|-------|------|
| `kind` | `"website"` \| `"social_profile"` \| `"doc"` |
| `url` | string |
| `note` | string |

---

## 5) Persistence + View DTOs

### 5.1 Database Storage (Minimal)

Add model: `BrandIR`

| Field | Type | Notes |
|-------|------|-------|
| `brand` | FK | One-to-one |
| `version` | string | - |
| `ir_json` | JSONB | - |
| `compiled_at` | datetime | - |
| `compiler_meta` | JSONB | tier, source counts, apify run ids |
| `checksum` | string | Hash of canonical JSON |

### 5.2 View DTOs (Frontend Consumption)

`BrandBrainViewDTO` (derived):

| Field | Source |
|-------|--------|
| `brand_id` | - |
| `tier` | - |
| `positioning.one_liner` | - |
| `voice_summary` | Small summary |
| `pillars_summary` | Names only |
| `formats_supported` | - |
| `taboos_count` | - |
| `examples_count` | - |
| `last_compiled_at` | - |

---

## 6) Onboarding Tiers → IR Mapping (Compiler Contract)

### Tier 0 (Minimum Viable)

**Inputs:**

- Positioning one-liner
- 3 tone sliders (humor/boldness/formality)
- 3 taboo topics
- 2 pillar names + keywords
- 3 example links OR pasted examples (any format)

**Compiler Behavior:**

- Fills missing fields with safe defaults (explicitly tracked in `compiler_meta.defaults_used`)
- Produces IR with **full schema**, but with low confidence in claims/lexicon unless supplied

### Tier 1 (Standard)

**Adds:**

- Full voice sliders + style rules + banned phrases
- 3–5 audiences
- 3–5 pillars with angles
- Lexicon: must_use / must_avoid
- CTA rules

**Compiler Behavior:**

- Derives format constraints from examples + user answers
- Generates initial `claims.allowed_claims` only if backed by provided sources (or mark low confidence)

### Tier 2 (Deep)

**Adds:**

- Competitor set + "how we differ"
- 10–20 examples tagged (including short_video transcripts if possible)
- "What good looks like" rubric answers (scoring criteria)
- Site crawl targets + key pages

**Compiler Behavior:**

- Builds richer lexicon + signature moves
- Tightens taboo patterns + disallowed claim patterns
- Produces more deterministic format constraints

---

## 7) Apify Integration Contract (Step 1 Exploration)

### Principles

- **Store raw first.** Do not bake assumptions into models.
- Normalization is a second pass producing `NormalizedBrandArtifact`.

### Required Artifacts

| Artifact | Fields |
|----------|--------|
| `ApifyRun` | actor_id, input_json, run_id, dataset_id, started_at, finished_at, item_count, cost_estimate (if available) |
| `RawApifyItem` | run_id, item_index, raw_json (JSONB) |

### API Primitives (Must Implement Exactly)

1. Start actor run
2. Poll run status
3. Fetch dataset items (paged)

### Documentation Links

| Resource | URL |
|----------|-----|
| Apify API v2 docs | https://docs.apify.com/api/v2 |
| Instagram actor readme | https://console.apify.com/actors/shu8hvrXbJbY3Eb9W/information/latest/readme |

> **Hard Rule:** If any field mapping is uncertain, label it `UNVERIFIED` and keep the raw JSON path reference.

---

## 8) Normalization Targets (From Raw Apify/Web)

### `NormalizedBrandPost` (v1)

| Field | Type | Required |
|-------|------|----------|
| `platform` | `"instagram"` \| `"tiktok"` \| `"linkedin"` \| `"x"` \| `"web"` \| `"unknown"` | Yes |
| `post_url` | string | No |
| `created_at` | ISO datetime | No |
| `text` | string | Yes (caption or transcript) |
| `format` | supported format enum | Yes (best-effort classifier) |

#### `metrics` (All Optional)

| Field | Type |
|-------|------|
| `views` | number |
| `likes` | number |
| `comments` | number |
| `shares` | number |

#### `media` (All Optional)

| Field | Type |
|-------|------|
| `thumbnail_url` | string |
| `video_url` | string (may be absent) |

#### `signals` (Derived)

| Field | Type |
|-------|------|
| `hashtags` | string[] |
| `mentions` | string[] |
| `audio_id_or_name` | string (optional) |

#### `raw_ref` (Required)

| Field | Type |
|-------|------|
| `run_id` | string |
| `item_index` | number |
| `json_pointer` | string (path into raw) |

### `NormalizedSiteDoc` (v1)

| Field | Type |
|-------|------|
| `url` | string |
| `title` | string |
| `text` | string |
| `raw_ref` | crawl source reference |

---

## 9) BrandBrain Compiler Pipeline (Backend Processing Pathway)

### Step A: Collect Inputs

- Tier answers + uploaded examples
- Optional: Apify pulls (profile posts / recent posts)
- Optional: Site crawl (small allowlist: about, product, pricing, faq)

### Step B: Normalize

- Parse raw Apify → `NormalizedBrandPost[]`
- Parse web pages → `NormalizedSiteDoc[]`
- Extract: recurring phrases, tone markers, CTA patterns, taboo hints (lightweight rules first)

### Step C: Compile IR

Fill IR schema deterministically:

| IR Section | Source |
|------------|--------|
| `positioning` | Tier answers + site docs |
| `voice` | Sliders + examples |
| `pillars` | Inputs + example tags |
| `formats` | Constraints from examples + user selections |
| `lexicon` | Extracted terms (with allow/avoid separation) |
| `claims` | Only from explicit user + site docs (tag confidence) |

### Step D: Persist + Render

- Store `BrandIR.ir_json`
- Return `BrandBrainViewDTO` + IR checksum

> **Note:** LLM usage is allowed for summarization/transcript cleanup, but IR must remain schema-valid and auditable (raw refs retained).

---

## 10) Step 1 Exploration Plan (Free Apify Tier, Hard Cap $5)

### Objective

Validate what we can reliably extract (fields + limits) from Apify for at least one brand, without designing fantasy schemas.

### Run Plan

1. Choose 1 brand for exploration (Wendy's is fine)
2. Pull:
   - Instagram profile posts (recent N)
   - TikTok profile posts (recent N)
   - LinkedIn profile posts (recent N) if feasible
3. Cap each actor run with:
   - Max items (N) = 20 (or lowest allowed)
   - Only 1 run per platform during exploration

### Outputs We Must Produce

| Output | Location |
|--------|----------|
| 3 raw sample items per platform | `var/apify_samples/<platform>/<actor>/<timestamp>_item#.json` |
| Field observations markdown | `docs/notes/apify_field_observations.md` |

The markdown note must list:
- Field availability
- What's missing
- What's unreliable

### Success Criteria

**We can produce `NormalizedBrandPost[]` with:**

- [ ] Text present for most items
- [ ] At least one metric present (likes/views/etc) if provided
- [ ] Stable url/id per item (for dedupe)

**We can compile Tier 0 IR with:**

- [ ] ≥3 examples auto-attached from normalized posts
- [ ] Voice + lexicon partially inferred (flagged)

---

## 11) Acceptance Tests (v0)

### Schema Tests

- [ ] BrandBrain IR validates against schema for tier 0/1/2 fixtures

### Persistence Tests

- [ ] Compiling twice with same inputs yields same checksum (idempotent)

### Raw Storage Tests

- [ ] Raw Apify items stored before normalization

### Normalization Tests

- [ ] Normalized objects always include `raw_ref`

### "On-Brand Constraints Present" Tests (Minimal)

- [ ] At least 3 taboos exist
- [ ] At least 2 pillars exist
- [ ] `formats.short_video` exists with beats + max_seconds

---

## 12) Definition of Done (For Step 0 Skeleton PR)

- [ ] This doc exists in repo as `docs/prd/brandbrain_spec_skeleton.md`
- [ ] IR schema is explicit enough that step 1 cannot invent fields without editing this doc
- [ ] Exploration plan is explicit (cap, outputs, success criteria)
- [ ] Downstream teams (you + Claude) can implement step 1 without guessing
