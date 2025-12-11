# 02 – canonical objects (technical)

> single source of truth for system-level data shapes

---

## 1. purpose

this doc defines the **canonical data contracts** for kairo’s system repo:

- exact fields, ids, and enums for each core object
- invariants and relationships
- how these shapes map to:
  - db tables (supabase/postgres)
  - domain models (python)
  - api dtos (django serializers)

if another doc disagrees with this one, this doc wins.

---

## 2. global conventions

### 2.1 id & key conventions

- ids are **opaque strings** with type prefixes:
  - `brand_...`, `persona_...`, `pillar_...`, `opp_...`, `pkg_...`, `var_...`, `pat_...`, `exec_...`, `learn_...`
- generated as **uuid v4 or ulid** at creation time.
- **no semantic meaning** in ids beyond type and uniqueness.

shared fields on all top-level objects:

- `id: str` – canonical id with prefix
- `tenant_id: str` – org/workspace; initially single tenant but don’t cheat
- `brand_id: str` – for anything scoped to a brand
- `created_at: datetime`
- `updated_at: datetime`
- `deleted_at: datetime | null` – null = active (soft delete only)

### 2.2 time & currency

- all times stored as **utc** `timestamptz`.
- durations stored as integers in **seconds** unless otherwise noted.
- no monetary fields yet; when introduced:
  - base currency per tenant
  - amounts as **integer cents**.

### 2.3 enums & string literals

we standardize enums so they are identical in db, python and api:

- use **lowercase snake or kebab**; no spaces.
- example: `channel = 'linkedin' | 'x' | 'youtube' | 'instagram'`.

enums are defined once in:

- `core/enums.py`
- used both in:
  - django model `choices`
  - pydantic/domain models
  - serializers.

### 2.4 channels

for v1 hero slice, we support:

- `linkedin`
- `x`

we reserve:

- `youtube`
- `instagram`
- `tiktok`
- `newsletter`

but only the first two are required to be fully wired.

---

## 3. shared enums & value types

### 3.1 shared enums

```text
Channel:
  - linkedin
  - x
  - youtube
  - instagram
  - tiktok
  - newsletter

OpportunityType:
  - trend
  - evergreen
  - competitive
  - campaign

PackageStatus:
  - draft
  - in_review
  - scheduled
  - published
  - archived

VariantStatus:
  - draft
  - edited
  - approved
  - scheduled
  - published
  - rejected

PatternStatus:
  - active
  - experimental
  - deprecated

PatternCategory:
  - evergreen
  - launch
  - education
  - engagement

ExecutionEventType:
  - impression
  - click
  - like
  - comment
  - share
  - save
  - profile_visit
  - link_click

ExecutionSource:
  - platform_webhook
  - csv_import
  - manual_entry
  - test_fixture

LearningSignalType:
  - pattern_performance_update
  - opportunity_score_update
  - channel_preference_update
  - guardrail_violation

### 3.2 shared value types

not full models – but shapes that appear across objects.

**PersonaHandle**

- `id`: str (persona_id)
- `name`: str
- `role`: str | null

**PillarHandle**

- `id`: str (pillar_id)
- `name`: str
- `category`: str | null (e.g. authority, behind_the_scenes)

**ChannelHandle**

- `channel`: Channel
- `handle`: str | null (e.g. @acme_b2b)

**ScoreBand**

- `raw`: float – 0–100
- `band`: str – low | medium | high
- `explanation`: str | null – short text.

---

## 4. Brand

### 4.1 purpose

root object for all other brand-scoped data: personas, pillars, strategy, packages, etc.

### 4.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `brand_...` |
| `tenant_id` | str | yes | owning tenant |
| `name` | str | yes | human name ("Acme Analytics") |
| `slug` | str | yes | url-safe slug ("acme-analytics") |
| `primary_channel` | Channel | yes | main channel for focus strips |
| `channels` | list[ChannelHandle] | yes | connected channels & handles |
| `positioning` | str | yes | 1–3 sentence brand statement |
| `tone_tags` | list[str] | yes | words like "direct", "playful", "nerdy" |
| `taboos` | list[str] | yes | "never do this" rules |
| `metadata` | dict | no | misc structured data (industry, size, locale, etc.) |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | soft delete |

### 4.3 invariants

- `(tenant_id, slug)` must be unique.
- `primary_channel` must be in `channels.channel` set.
- no references (persona, pillar, opportunity…) without a valid `brand_id`.

---

## 5. Persona

### 5.1 purpose

target audience slices for a brand.

### 5.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `persona_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `name` | str | yes | e.g. "RevOps lead" |
| `role` | str | no | job/career label |
| `summary` | str | yes | 1–2 sentence description |
| `priorities` | list[str] | yes | top 3–7 things they care about |
| `pains` | list[str] | no | optional pain points list |
| `success_metrics` | list[str] | no | how they define success |
| `channel_biases` | dict[Channel,str] | no | notes like "no memes on LinkedIn" |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | |

### 5.3 invariants

- `brand_id` must reference existing Brand.
- persona must not be referenced by packages/opportunities if soft-deleted (we enforce via engine, not db).

---

## 6. ContentPillar

### 6.1 purpose

structural themes of the brand's content.

### 6.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `pillar_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `name` | str | yes | "Attribution Reality", "Launch & Promos" |
| `category` | str | no | loose tag if needed ("authority", "demand") |
| `description` | str | yes | short human description |
| `priority_rank` | int | no | 1 = highest priority |
| `is_active` | bool | yes | default true |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | |

### 6.3 invariants

- `(brand_id, name)` should be unique.
- `priority_rank` if present must be >= 1 and unique per brand.

---

## 7. PatternTemplate

### 7.1 purpose

reusable structures for messages – "beats" like hook → context → twist → cta.

### 7.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `pat_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str \| null | no | null = global pattern |
| `name` | str | yes | "Confessional story → lesson" |
| `category` | PatternCategory | yes | evergreen / launch / education / engagement |
| `status` | PatternStatus | yes | active / experimental / deprecated |
| `beats` | list[str] | yes | ordered beats ("Hook", "Context", …) |
| `supported_channels` | list[Channel] | yes | where this pattern can be used |
| `example_snippet` | str | no | example text (sanitized, short) |
| `performance_hint` | str | no | "overperforms for long-form on LinkedIn" |
| `usage_count` | int | yes | total times used |
| `last_used_at` | datetime \| null | no | |
| `avg_engagement_score` | float \| null | no | 0–100 normalized metric from learning engine |
| `metadata` | dict | no | room for more |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | |

### 7.3 invariants

- if `status = deprecated`, engines should never auto-select unless explicitly forced.
- if `brand_id` is null → pattern is global; brand-specific overrides can exist but need explicit handling in engines.

---

## 8. Opportunity

### 8.1 purpose

"atoms" on the Today board – candidate ideas to turn into packages.

### 8.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `opp_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `type` | OpportunityType | yes | trend / evergreen / competitive / campaign |
| `score` | float | yes | 0–100 opportunity score |
| `score_explanation` | str \| null | no | short human text |
| `title` | str | yes | concise label ("LinkedIn attribution rant is trending") |
| `angle` | str | yes | "why now" / core argument |
| `source` | str | yes | e.g. "LinkedIn post", "Some competitor campaign" |
| `source_url` | str \| null | no | optional link |
| `persona_id` | str \| null | no | target persona |
| `pillar_id` | str \| null | no | associated pillar |
| `primary_channel` | Channel | yes | recommended channel |
| `suggested_channels` | list[Channel] | yes | other channels it might fit |
| `is_pinned` | bool | yes | show at top of board |
| `is_snoozed` | bool | yes | deprioritized |
| `snoozed_until` | datetime \| null | no | |
| `created_by_user_id` | str \| null | no | |
| `created_via` | str | yes | manual, ingestion, llm_proposed |
| `last_touched_at` | datetime | yes | for staleness nudges |
| `metadata` | dict | no | structured extra |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | |

### 8.3 invariants

- `0 <= score <= 100`.
- if `is_snoozed = true`, `snoozed_until` must be non-null and >= now.
- `primary_channel` must be in `suggested_channels` or explicitly justified in engine (but data shape prefers consistency).

---

## 9. ContentPackage

### 9.1 purpose

coherent set of planned assets (variants) derived from one or more opportunities.

### 9.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `pkg_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `title` | str | yes | human name for package |
| `status` | PackageStatus | yes | draft / in_review / scheduled / published |
| `origin_opportunity_id` | str \| null | no | canonical source opp (if any) |
| `persona_id` | str \| null | no | target persona |
| `pillar_id` | str \| null | no | core pillar |
| `channels` | list[Channel] | yes | channels this package will touch |
| `planned_publish_start` | datetime \| null | no | earliest planned publish |
| `planned_publish_end` | datetime \| null | no | latest planned publish |
| `owner_user_id` | str \| null | no | primary human owner |
| `notes` | str \| null | no | optional human notes |
| `created_via` | str | yes | manual, from_opportunity, import |
| `metrics_snapshot` | dict | no | aggregated metrics (optional denorm) |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | |

### 9.3 invariants

- if `status = scheduled`, at least one variant must be scheduled.
- if `status = published`, there must be at least one ExecutionEvent tied to its variants.

---

## 10. Variant

### 10.1 purpose

single piece of channel-specific content inside a package.

### 10.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `var_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `package_id` | str | yes | parent package |
| `channel` | Channel | yes | linkedin / x |
| `status` | VariantStatus | yes | draft / edited / approved / scheduled / published |
| `pattern_template_id` | str \| null | no | pattern used (if any) |
| `raw_prompt_context` | dict \| null | no | input context used for generation |
| `draft_text` | str \| null | no | original llm draft |
| `edited_text` | str \| null | no | human-edited body |
| `approved_text` | str \| null | no | final locked version (if workflow demands) |
| `generated_by_model` | str \| null | no | llm model id (for audit) |
| `proposed_at` | datetime \| null | no | when first generated |
| `scheduled_publish_at` | datetime \| null | no | |
| `published_at` | datetime \| null | no | |
| `last_evaluated_at` | datetime \| null | no | last time learning engine scored this variant |
| `eval_score` | float \| null | no | numeric eval (0–100) |
| `eval_notes` | str \| null | no | short notes |
| `metadata` | dict | no | per-channel details (e.g. asset ids) |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |
| `deleted_at` | datetime \| null | no | |

### 10.3 invariants

- exactly one of `draft_text`, `edited_text`, `approved_text` must be considered "active" for rendering depending on status. the content engine defines the rule, but the data shape must support all three.
- if `status = scheduled`, `scheduled_publish_at` must be non-null.
- if `status = published`, `published_at` must be non-null.

---

## 11. ExecutionEvent

### 11.1 purpose

raw performance data from platforms; used by learning engine.

### 11.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `exec_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `variant_id` | str | yes | which variant |
| `channel` | Channel | yes | |
| `event_type` | ExecutionEventType | yes | impression / click / like / comment / share… |
| `event_value` | float | no | optional numeric value (e.g. dwell seconds) |
| `count` | int | yes | count of events (usually 1) |
| `source` | ExecutionSource | yes | platform_webhook / csv_import / manual… |
| `occurred_at` | datetime | yes | when it happened on platform |
| `received_at` | datetime | yes | when we ingested it |
| `metadata` | dict | no | raw ids, post url, etc. |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |

### 11.3 invariants

- `(variant_id, event_type, occurred_at, source, metadata.platform_event_id)` should be de-duplicated where possible to avoid double counting.
- learning engine should only consume events where `occurred_at <= now`.

---

## 12. LearningEvent

### 12.1 purpose

internal, aggregated signals the learning engine uses to update priors/weights.

### 12.2 fields

| field | type | required | description |
|-------|------|----------|-------------|
| `id` | str | yes | `learn_...` |
| `tenant_id` | str | yes | |
| `brand_id` | str | yes | |
| `signal_type` | LearningSignalType | yes | pattern_performance_update, etc. |
| `pattern_id` | str \| null | no | populated for pattern signals |
| `opportunity_id` | str \| null | no | populated for opp score signals |
| `variant_id` | str \| null | no | optional |
| `payload` | dict | yes | structured data (aggregates, ratios, features) |
| `derived_from` | list[str] | no | ids of ExecutionEvents or other inputs |
| `effective_at` | datetime | yes | when this signal should be applied |
| `created_at` | datetime | yes | |
| `updated_at` | datetime | yes | |

### 12.3 invariants

- at least one of `pattern_id`, `opportunity_id`, `variant_id` must be non-null.
- `effective_at` must be >= max of `derived_from.occurred_at` (if we track that).

---

## 13. api dtos vs domain vs db

for each canonical object we will maintain:

1. **db model**
   - lives in `persistence/models/*.py`
   - 1:1 with postgres table columns.
2. **domain model**
   - pydantic or dataclass in `engines/*/models.py` or `core/dto.py`
   - uses rich enums and nested types (PersonaHandle, ScoreBand, etc.).
3. **api dto**
   - serializer schema in `api/schemas/*.py`
   - can be:
     - thinner (hide internal fields like `tenant_id`)
     - richer (bundle multiple objects into one response dto).

rule: fields defined here are the superset; layers are allowed to hide or aggregate but not invent incompatible shapes.

---

## 14. relationships (high-level)

- Brand 1-n Persona
- Brand 1-n ContentPillar
- Brand 1-n PatternTemplate
- Brand 1-n Opportunity
- Brand 1-n ContentPackage
- ContentPackage 1-n Variant
- Variant 1-n ExecutionEvent
- ExecutionEvent 1-n LearningEvent (aggregated, not strict)

for engines, we'll define view models later (e.g. `TodayBoardDTO`, `PackageWorkspaceDTO`) built on top of these canonical objects.

this doc's job is to guarantee that all those views compose from a consistent underlying set of shapes.

