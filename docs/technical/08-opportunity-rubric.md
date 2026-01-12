# opportunity quality rubric (F1 – hero loop)

> canonical definition of what a "good" opportunity is for kairo's F1 today board, and how we judge it.

---

## 1. what an "opportunity" is in kairo

**working definition**

an *opportunity* is a **specific, actionable content idea** that:

- is written for **one primary channel** (linkedin / x for now),
- targets **one primary persona** (with optional secondary personas),
- sits clearly inside **one content pillar** and the brand's strategy,
- has **one clear content thesis** ("the point" of the post),
- includes a **why now / hook** (trend, campaign, timing, or evergreen rationale),
- is **immediately shippable** as a post, thread, or series with minimal extra thinking.

mentally: "if i handed this opportunity to a strong social marketer, they'd say: *i know exactly what i'd post and why, for whom, and on which channel*."

---

## 2. non-goals: what an opportunity is *not*

an opportunity is **not**:

- a vague topic like "talk about ai in marketing".
- a business initiative: "launch a newsletter", "start a podcast".
- pure strategy advice: "clarify your ICP", "audit your funnel".
- a generic "post regularly about X".
- a copy draft (that's later, in variants).
- a fully-fledged campaign plan with 10 steps (that belongs in a different engine).

if a marketer can't:

1. tell which pillar + persona + channel it belongs to, and
2. imagine at least one concrete post format in under ~10 seconds,

it's **not** a valid kairo opportunity.

---

## 3. required fields & semantics (opportunitydraftdto)

this rubric is grounded in the fields we actually use in `OpportunityDraftDTO`. each opportunity **must** fill these fields coherently:

in PRD-1 we treat fields as follows:

- **required (non-empty)**
  `id`, `brand_id`, `opportunity_type`, `created_via`,
  `primary_pillar_id`, `primary_persona_id`, `primary_channel`,
  `title`, `thesis`, `angle`, `why_now`.

- **required but may be an empty list**
  `suggested_patterns`, `evidence_hints`, `risk_flags`.
  (empty is allowed, but see §3.4 / §4 / §8 for what "good" looks like.)

- **optional**
  `secondary_pillar_ids`, `secondary_persona_ids`, `secondary_channels`,
  `learning_signals`, `effort_estimate`.

later PRDs may tighten these, but this is the contract for PRD-1.

### 3.1 identity & classification

- `id: UUID`
  - **purpose:** stable identifier for the opportunity across runs.
  - **requirement:** deterministic for the same "concept" within a brand in PRD-1.

- `brand_id: UUID`
  - brand owning this opportunity.

- `opportunity_type: OpportunityType`
  - one of: `trend | evergreen | competitive | campaign`.
  - must reflect *why now* (see §6).

- `created_via: CreatedVia`
  - `ai_suggested` for graph-generated opportunities (PRD-1).

### 3.2 strategic context

- `primary_pillar_id: UUID`
  - maps to an existing `ContentPillar` for the brand.
  - must be consistent with the content thesis (no "performance marketing" pillar for an employer branding idea).

- `secondary_pillar_ids: list[UUID]` (optional)
  - only when there is a genuine cross-pillar rationale.
  - avoid "pillar stuffing".

- `primary_persona_id: UUID`
  - a single, clearly targeted persona.

- `secondary_persona_ids: list[UUID]` (optional)
  - use sparingly; opportunities should be persona-sharp.

- `primary_channel: Channel`
  - in PRD-1: `linkedin` or `x`.
  - must be justified by the thesis (threads vs carousels vs short punchy posts).

- `secondary_channels: list[Channel]` (optional)
  - candidate channels where the same thesis could live later.
  - not required in PRD-1, but if filled, must be plausible.

### 3.3 core idea & execution hinting

- `title: str`
  - a **concise label** a marketer would understand at a glance.
  - not clickbait; not full copy; no emojis spam.

- `thesis: str`
  - 1–2 sentence **core idea** of the content.
  - must answer: "what is the one main point we want to land?"

- `angle: str`
  - how we choose to **frame** the thesis (e.g. "confessional lesson", "counter-narrative", "behind the scenes").

- `why_now: str`
  - explicit justification for timing:
    - for `trend`: refer to a concrete trend / news / pattern.
    - for `campaign`: refer to the campaign moment or lifecycle phase.
    - for `evergreen`: explain the enduring, repeatable value.
    - for `competitive`: link to competitor behavior or category shift.

- `suggested_patterns: list[PatternHint]`
  - references to known pattern templates (`PatternTemplate` ids or pattern names) that would work for this opp.

### 3.4 evidence & external hooks

- `evidence_hints: list[EvidenceHint]`
  - references / ids to:
    - trends from `ExternalSignalBundle.trends`,
    - competitor posts,
    - internal performance patterns, etc.
  - must be concrete enough to trace back in logs/eval.
  - in PRD-1:
    - `evidence_hints` **may** be empty (no hard failure),
    - but we prefer that at least some of the **top-scoring** opportunities (e.g. the top 3–5) have concrete grounding in real signals.
    - this is an eval dimension, even if not a hard validity check yet.

- `learning_signals: list[LearningSignalHint]` (optional)
  - how past performance (LearningSummary) influenced this opp:
    - "carousels on founder stories overperform for persona X"
    - "threads on pricing experiments underperform; avoid that pattern".
  - for PRD-1, absence of `learning_signals` does **not** make an opp invalid; it simply means the opp wasn't explicitly steered by past performance.

### 3.5 risk & constraints

- `risk_flags: list[str]`
  - e.g. "might feel too self-promotional", "requires legal check for claims".

- `taboo_conflicts: list[str]`
  - **must** remain empty in PRD-1 (taboo enforcement is hard rule: no generated opp may violate brand taboos).
  - if any taboo conflict is detected, downstream engine should **reject** the opp or mark it unusable.

- `effort_estimate: Literal["low","medium","high"]` (optional)
  - rough content production effort; used for ranking and planning.

---

## 4. hard quality requirements (pass/fail)

an opportunity **fails** the rubric if any of these are violated.

### 4.1 single clear content thesis

- thesis must be:
  - **singular**: not two unrelated ideas stapled together.
  - **specific**: "behind the scenes of how we fixed X bottleneck", not "share behind the scenes".
- red flags:
  - "talk about A and B and C" with no unifying thread.
  - "overview of everything we do in Q4".

### 4.2 explicit who + where

- `primary_persona_id` must be set and consistent with:
  - the pain / desire described in thesis.
  - the vocabulary used in title / angle.
- `primary_channel` must be:
  - explicitly chosen (no "any channel").
  - consistent with the execution hint (threads vs carousels vs single post).

if we can't answer "who is this for" + "where will it live" from the fields, the opp fails.

### 4.3 clear why-now / hook

for **every** opportunity, `why_now` must be non-empty and non-vacuous:

- bad:
  > "this is always relevant"
- good evergreen rationale:
  > "founders consistently ask this in sales calls; recurring pain point worth codifying."

for `trend` / `campaign` / `competitive` types, `why_now` should **explicitly** reference:

- the trend / event / campaign, or
- the competitor move / category shift.

### 4.4 on-brand, on-pillar

- fields must be mutually consistent:
  - pillar + persona + thesis + angle + patterns.
- if the idea doesn't clearly fall into one pillar, it's likely too vague.
- no generic "ai for everyone" opps for a brand whose positioning is, say, "boutique b2c ecommerce marketing".

### 4.5 actionable as content

- a strong marketer should be able to:
  - pick a pattern from `suggested_patterns`,
  - choose a format (post / thread / carousel),
  - and draft copy **without** doing strategy work first.

if the opp requires revisiting strategy, ICP, pricing, or org structure, it belongs elsewhere.

### 4.6 safety / taboos respected

- opp must **not**:
  - contradict explicit `Brand.taboos` (once wired).
  - propose controversial, off-brand, or legally sensitive stunts without marking risk flags.

violation → opp is considered **invalid** in PRD-1.

### 4.7 validity categories (how engines should treat opps)

we distinguish three levels:

- **invalid**
  violates any hard rule in §4 (or explicit safety/taboo rules).
  these must **not** appear on the today board.

- **valid but weak**
  passes all hard checks in §4 but scores low on the ranking dimensions (see §5 and §7).
  these can exist in the candidate set but should rarely surface near the top of the board.

- **board-eligible**
  passes hard checks **and** has a final score above our quality bar (see §7.3 and §8).
  these are the ones we want to routinely show to marketers.

implementation rules:

- the **graph** must mark each generated opportunity with an `is_valid: bool` flag and optionally a `rejection_reasons: list[str]`.
- the **scoring node** must **not** "rescue" invalid opportunities. if `is_valid=false`, the final score must be `0`.
- the **engine** is responsible for:
  - dropping all `is_valid=false` opps, and
  - using the scores only to rank among valid ones.

---

## 5. soft ranking attributes (for scores & ordering)

the scoring LLM node should rank valid opportunities using these dimensions. these do **not** decide validity, only priority.

### 5.1 impact potential

how much we expect this opp to move a needle (awareness, demand, consideration, trust).

- high: tackles a pivotal belief / risk / objection with a novel angle.
- low: minor housekeeping tips, generic inspiration.

### 5.2 timeliness & leverage

- for `trend` / `competitive` / `campaign`:
  - recency, momentum, and relevance of the triggering event.
- for `evergreen`:
  - durability + reusability over time.

### 5.3 portfolio balance

we want a **board** that:

- spans multiple pillars, not 10 variants of the same topic.
- spans funnel stages: awareness, consideration, conversion, post-purchase.

opportunities that help **rebalance** a skewed portfolio get a soft boost.

### 5.4 diversity & redundancy

- penalize near-duplicates:
  - same thesis / angle / persona / pillar with slightly different wording.
- favor opportunities that introduce new:
  - angles,
  - formats,
  - stories.

### 5.5 feasibility vs impact

for two equally impactful opps, prefer:

- lower effort → faster shipping.
- or, explicitly flag high-effort ones so the marketer can plan.

---

## 6. opportunity types – type-specific rules

### 6.1 trend opportunities

**definition:** anchored in an external, time-bound trend (news, platform change, cultural moment).

**requirements:**

- `why_now` must reference:
  - what the trend is,
  - how it affects the brand's audience.
- must suggest at least one pattern that works well for recency:
  - "hot take thread", "reactive carousel", "mini-case study".
- must avoid pure news-recap ("X announced Y") without a brand-specific POV.

bad:
> "post about the latest openai release."

good:
> "confessional thread from the CMO about how the latest openai release will change how they brief creatives this quarter."

### 6.2 evergreen opportunities

**definition:** ideas that stay relevant for months+.

**requirements:**

- `why_now` must explain enduring value:
  - recurring questions from customers,
  - foundational beliefs, frameworks, or playbooks.
- should explicitly state:
  - when / how often it can be reused or remixed.

### 6.3 competitive opportunities

**definition:** content built around competitor moves or category norms.

**requirements:**

- must avoid direct attacks / pettiness.
- instead:
  - reframe competitor move into a lesson, comparison, or category insight.
- `why_now` must anchor in:
  - specific competitor action or pattern.

### 6.4 campaign opportunities

**definition:** attached to an ongoing or upcoming campaign (launch, seasonal push, event).

**requirements:**

- reference the campaign:
  - theme, objective, phase (pre-launch, launch, post-mortem).
- clarify where in campaign arc this opp sits:
  - tease → announce → proof → debrief, etc.

---

## 7. scoring rubric (for LLM scoring node)

the scoring node should assign **sub-scores** and a normalized **final score**.

### 7.1 sub-scores (0–4 scale)

each opportunity receives integer scores:

- `clarity` (0–4)
- `strategic_fit` (0–4)
- `timeliness` (0–4)
- `differentiation` (0–4)
- `execution_readiness` (0–4)

**rough guide:**

- `0` – invalid / fails hard requirement.
- `1` – very weak; would not recommend shipping.
- `2` – acceptable but generic; needs work.
- `3` – good; shippable with minor tweaks.
- `4` – strong; high-priority slot candidate.

### 7.2 aggregating to 0–100

weights (can be tuned later, but define a starting point):

- clarity: 0.25
- strategic_fit: 0.25
- timeliness: 0.20
- differentiation: 0.15
- execution_readiness: 0.15

formula:

```text
raw = 25*c + 25*s + 20*t + 15*d + 15*e      # using normalized 0–1 per dimension
score = round(raw)                           # integer in [0,100]
```

in practice:

- convert each 0–4 sub-score to [0,1] by dividing by 4,
- apply weights, multiply by 100, round.

equivalently: `score = round(100 * (0.25*c + 0.25*s + 0.20*t + 0.15*d + 0.15*e) / 4)` when c,s,t,d,e are 0–4 integers.

### 7.3 invariants

- score ∈ [0,100] always.
- any sub-score 0 in clarity or strategic_fit → force score ≤ 40.
- opps that fail hard requirements (§4) must be marked `is_valid=false` and receive score `0` (see §4.7 for how engines handle them).

---

## 8. board-level rubric (today board quality)

a board is the set of opportunities returned by F1 for a given brand + run.

### 8.1 minimum viable board (good)

a good board (F1) should:

- contain 8–16 opportunities (8 is the hard minimum; 16 is the target upper bound).
- include at least:
  - 2 distinct pillars,
  - 2 personas (where brand has ≥2 personas),
  - both channels (linkedin and x) when brand uses both.
- have a score distribution with:
  - ≥ 4 opps scoring ≥ 70,
  - no more than 30% of opps scoring < 40.

### 8.2 partial board

partial if:

- size is acceptable, but:
  - too skewed to one pillar or persona, or
  - too many low-score opps, or
  - missing one channel entirely (given brand supports it).

(a partial board is still usable; the engine will return it with `meta.degraded=false` but may include warning notes.)

### 8.3 bad board

bad if:

- < 6 valid opportunities, or
- 50% opps fail hard requirements, or
- severe misalignment with brand's defined pillars/strategy.

these board-level criteria feed into the classification rules (good/partial/bad) tracked by observability (see 07-observability.md).

---

## 9. anti-patterns & examples

### 9.1 generic topic dumping

> "post about ai in marketing and how it changes everything"

issues:

- no persona.
- no pillar.
- no thesis beyond "ai matters".

### 9.2 multi-idea soup

> "share how you built the company, your pricing strategy, lessons from fundraising, and team culture in one thread"

issue: four different series of content, not one opportunity.

### 9.3 strategy disguised as content

> "rethink your ICP and rebuild your product positioning"

this is a strategy project; content might talk about it, but the opportunity needs to frame a specific public artifact (e.g. teardown of the repositioning).

### 9.4 off-channel concepts

> "host a three-day in-person workshop" as an "opportunity"

this is an event / offer concept, not social content; we only want content that resolves into linkedin/x artifacts in PRD-1.

---

## 10. implementation notes for graphs & prompts

this rubric must be enforced by graph schema + prompts, not just human judgment.

### 10.1 schema enforcement

- `OpportunityDraftDTO` must:
  - expose all fields in §3 explicitly.
  - mark required fields as non-optional.
  - include `is_valid: bool` and `rejection_reasons: list[str]` so the graph can flag invalid opportunities (see §4.7).
- LLM nodes must be instructed to:
  - always return exactly N structured opportunities.
  - fill every required field.
  - set types consistently (trend vs evergreen).

### 10.2 prompt constraints

synthesis node prompt must:

- define "opportunity" using §1 and §2.
- list hard requirements (§4) as musts, not suggestions.
- explicitly forbid:
  - generic topics,
  - business initiatives,
  - strategy work disguised as content.

scoring node prompt must:

- use the sub-score definitions in §7.1.
- compute final score per §7.2.
- set `score=0` for any opp where `is_valid=false`; never rescue an invalid opp.
- never override schema constraints (e.g. can't mark an invalid opp as high-score).

### 10.3 engine responsibilities

- engine filters:
  - drop all `is_valid=false` opps before returning the board.
  - rank remaining opps by score descending.
- engine logs:
  - per-opportunity reasons for rejection (using `rejection_reasons` from graph output).

---

## 11. usage

- **graph authors**: use this rubric as the source of truth for prompts + field definitions.
- **eval harness**: use it to define:
  - labeling guidelines for human raters,
  - metrics for board-level and opportunity-level quality.
- **future PRDs**: reference this doc by path when touching F1 opportunities.
