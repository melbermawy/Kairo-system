# Opportunities Engine

> **One-line:** turns raw external + internal signals into **brand-specific, scored OpportunityCards (CO-09)** grouped into **daily/weekly OpportunityBatches (CO-10)** that answer:  
> “What are the 3–10 most worthwhile things this brand could talk about *now* for each persona/pillar?”

---

## 1. Definition & Role

The Opportunities Engine is the **bridge between the outside world and a brand’s content pipeline**.

Given:
- a **Brand (CO-01)** with
  - **Personas (CO-02)**
  - **Pillars (CO-03)**
  - a current **BrandBrainSnapshot (CO-05)**
  - a current **BrandRuntimeContext (CO-06)** and **BrandPreferences (CO-19)**  
- and a stream of **GlobalSourceDocs (CO-08)** plus optional internal triggers,

it produces:
- **OpportunityCards (CO-09)** = “reasons to speak now”
- grouped into **OpportunityBatches (CO-10)** for a given day/week

and makes them available to:
- the **frontend “Today’s Opportunities” board**
- the **Content Engineering Engine** (when a user wants to spin a card into a ContentPackage)
- the **Patterns** and **Learning** engines (for feedback on which opportunities worked).

The core transformation is:

> **GlobalSourceDoc(s) + BrandBrainSnapshot + BrandPreferences → [OpportunityCard] + OpportunityBatch**

---

## 2. Inputs & Outputs (in canonical CO terms)

### 2.1 Inputs (read only)

- **Brand (CO-01)**
- **Persona (CO-02)**
- **Pillar (CO-03)**
- **BrandBrainSnapshot (CO-05)**
- **BrandRuntimeContext (CO-06)**
- **BrandPreferences (CO-19)**
- **GlobalPriors (CO-20)** (for default weights)
- **BrandMemoryFragment (CO-07)** (for on-brand examples / language)
- **GlobalSourceDoc (CO-08)**
  - from:
    - **scheduled scraping / ingestion** (news, social, blogs, etc.)
    - **user-submitted content** (pasted links/text)
- Optional:
  - **PatternTemplate (CO-12)** / **PatternSourcePost (CO-11)** for “this looks like pattern X” style awareness (v1.5+).

### 2.2 Outputs (created / mutated)

- **OpportunityCard (CO-09)**  
  - created by engine, later:
    - scored/updated by engine + Learning
    - labelled by users (pin / ignore / “too generic / off-brand”)
- **OpportunityBatch (CO-10)**
  - created by engine scheduler (e.g. “today’s cards”)
  - minimally edited by engine/user (add/remove/pin)

The engine **does not** create or mutate:
- **ContentPackage / CoreArgument / ContentVariant** → those are downstream.
- **Brand, Persona, Pillar** → it only reads them.
- **BrandPreferences** → it reads them; Learning updates them.

---

## 3. Invariants

If the Opportunities Engine is healthy, this must be true:

1. **Traceability**
   - Every **OpportunityCard** MUST reference:
     - `brand_id`
     - at least one `source_refs[].global_source_doc_id` **or** an explicit `internal_trigger` descriptor.
   - For each card you can answer: “Where did this idea come from?”

2. **Persona / Pillar grounding**
   - Every **OpportunityCard** MUST have:
     - `persona_id` and `pillar_id`,  
     - OR a **deliberate** `scope = "global"` with justification in `angle_summary`.
   - No “floating” cards that aren’t tied to a target audience or theme by default.

3. **Single source of score**
   - Each **OpportunityCard** MUST have a numeric `score` (0–100).
   - The score MUST be computed using a **single scoring function** that takes:
     - BrandPreferences.opportunity_scoring_weights
     - features like freshness, relevance, competitive angle, etc.
   - No ad-hoc one-off scoring logic scattered across the codebase.

4. **Batch completeness**
   - Every **OpportunityBatch** MUST:
     - belong to exactly one `brand_id`
     - have a well-defined `date_scope` (or week id)
     - reference **only** OpportunityCards with that `brand_id`.
   - A card can belong to multiple batches (e.g. “this week” + “today”), but those relationships are explicit.

5. **Immutability of creation-time facts**
   - `created_at`, `source_refs`, `opportunity_type`, and `brand_id` on OpportunityCard MUST NOT be mutated after creation.
   - New information (better score, labels, etc.) is added via new fields or related rows, not by rewriting history.

---

## 4. Quality Dimensions & Baselines

### 4.1 Baselines we must beat

We are competing with:

1. **Manual strategist flow**
   - Strategist + creator scan feeds, newsletters, model accounts.
   - They pick 3–5 things per week, map them to personas/pillars, and propose angles in Notion/Sheets.

2. **Smart human + custom GPT**
   - They paste links into ChatGPT + a long “brand prompt”.
   - Ask: “give me 20 linkedin post ideas like me about [topic]”.
   - Manually triage / keep 2–3.

The Opportunities Engine has to be **strictly better** on:

- **Relevance:** fewer obviously off-brand or generic ideas.
- **Coverage:** better spread across personas/pillars and opportunity types.
- **Speed:** “good enough” set of 5–10 cards in seconds–minutes, not hours.
- **Repeatability:** same inputs → similar, stable opportunity set.

If we can’t beat (2) clearly, this engine is just a wrapper around ChatGPT.

### 4.2 Core quality axes (how we judge the engine)

1. **Brand relevance**
   - Does the card actually make sense for this brand’s positioning, offers, and taboos?
   - Would a strategist say “we *could* credibly talk about this”?

2. **Persona & pillar fidelity**
   - Does the angle genuinely speak to the specified persona and pillar?
   - Or is it generic “marketing advice” loosely slapped with a persona label?

3. **Timeliness / freshness**
   - For `opportunity_type = "trend"`:
     - we care about **recency** of GlobalSourceDocs + “moment” (e.g. debates, launches).
   - For evergreen / competitive:
     - freshness matters less; **strategic fit** matters more.

4. **Angle specificity**
   - Are `angle_summary` texts concrete and compelling (e.g. “Board hates your attribution charts — here’s how to fix them”)  
     vs generic (“Talk about attribution best practices”)?

We approximate these via:
- LLM self-eval scores (internal-only),
- periodic human eval on a small test set.

---

## 5. Failure Modes & Guardrails

### 5.1 Acceptable failures (user can easily fix)

- **Mild mis-targeting**
  - Correct topic, but wrong persona or slightly off pillar.
  - Fix: quick re-label in UI; Learning engine nudges mapping behavior.

- **Meh / boring angles**
  - Card is on-topic but not compelling.
  - Fix: user marks as “weak / generic”; engine learns to score similar features lower.

- **Over-supply**
  - Too many cards; user just ignores most.
  - Fix: user pins 3–5; engine treats unpinned cards as soft negative signal.

### 5.2 Unacceptable failures (brand-risk / time-wasters)

- **Off-brand or taboo-violating opportunities**
  - Suggesting topics that contradict positioning or taboos in BrandBrainSnapshot.
- **Factually wrong / hallucinated claims about competitors, partners, or the brand**
  - “Competitor X was just acquired” when that’s false.
- **Completely irrelevant noise**
  - Cards that clearly have nothing to do with the brand’s vertical or audience, on a regular basis.

Guardrails:

- Hard constraints in prompts:
  - “Never invent news or competitor claims; only use information explicitly in GlobalSourceDocs or brand-provided material.”
- Rule-based filters:
  - Don’t surface opportunities whose source docs fail basic filters (blocked domains, languages, off-vertical topics).
- Brand-level “blocked topics” list from BrandBrainSnapshot.taboo.
- Optional “low confidence” flag:
  - For borderline mappings, so UI can down-rank or visually flag.

---

## 6. Latency, Cost & Sequencing

### 6.1 High-level pipeline

For a batch run (e.g. “today’s ingest + opportunities”):

1. **Ingest**
   - Scrapers / APIs create **GlobalSourceDocs (CO-08)**.
2. **Filter**
   - Cheap keyword / rules / embeddings to drop obviously irrelevant docs.
3. **Summarize & feature extract (LLM)**
   - For surviving docs:
     - short summary,
     - candidate persona/pillar tags,
     - opportunity_type hints,
     - any competitive/product hooks.
4. **Map to brand(s)**
   - For each brand:
     - use BrandBrainSnapshot + BrandPreferences + doc features to decide:
       - relevant? (yes/no)
       - candidate persona/pillar
5. **Score & create OpportunityCards (LLM + non-LLM)**
   - LLM proposes `angle_summary`.
   - Non-LLM scoring combines:
     - freshness, relevance, competitive angle, BrandPreferences weights, etc.
6. **Batch generation**
   - Group new cards into **OpportunityBatch (CO-10)** for each brand/day.
7. **Post-process**
   - Deduplicate near-duplicates.
   - Enforce caps: e.g. 5–15 cards per brand per day.

### 6.2 Latency expectations (from user POV)

- **Live user-triggered “analyze this link”**
  - User pastes link → see **1–3 cards** in ~3–8 seconds.
- **Background hourly/daily runs**
  - Can take longer; user just sees ready cards when they log in.

### 6.3 Cost constraints

- LLM-heavy portions:
  - summarization + feature extraction per GlobalSourceDoc,
  - angle generation per OpportunityCard.
- Controls:
  - early cheap filtering (keywords, embeddings) to reduce LLM calls,
  - cap docs per brand per time window,
  - cap opportunity variants per doc (e.g. max N cards per doc per brand),
  - reuse doc-level summaries/embeddings across multiple brands.

---

## 7. Learning Hooks & Evolution

### 7.1 Signals (FeedbackEvents)

The Opportunities Engine consumes:

- **FeedbackEvent (CO-18)** where:
  - `feedback_type = "opportunity_rating"` (v1.5+)
    - rating, notes (“too generic”, “not our ICP”, “off-brand”)
  - `feedback_type = "opportunity_used"`  
    - when a ContentPackage is created from OpportunityCard
  - `feedback_type = "opportunity_ignored"` (implicit):
    - card is repeatedly shown but never used → soft negative.
  - **Performance snapshots** from downstream posts
    - when content tied to an OpportunityCard performs well/poorly.

### 7.2 What actually changes

- Updates to **BrandPreferences (CO-19)**:
  - `opportunity_scoring_weights`:
    - e.g. for one brand, competitive angles might be weighted higher if they perform.
  - persona/pillar bias:
    - if a persona/pillar combo repeatedly gets used and performs, tilt more future cards there (within constraints).
- Adjusted internal heuristics:
  - lower thresholds for certain domains/topics that empirically work,
  - raise thresholds for those that never get used.

### 7.3 Evolution path

- **v1**
  - Hand-tuned rules + single LLM per doc for summary/features.
  - LLM per OpportunityCard for angle.
  - Simple scoring using BrandPreferences weights.

- **v1.5**
  - Better feedback loop:
    - explicit opportunity ratings in UI,
    - more systematic use of performance data.
  - Cross-brand GlobalPriors (CO-20) to seed new brands with smart defaults.

---

## 8. Baseline Comparison (Concrete Edge)

How a **smart human + custom GPT** would do this step:

- subscribe to feeds / newsletters / social accounts,
- periodically dump links into ChatGPT with a big brand prompt,
- ask for “20 post ideas for this brand,”
- then manually:
  - map ideas to personas/pillars,
  - decide which are good,
  - track nothing systematically.

Our concrete edge:

1. **Structured, persistent representation**
   - Opportunities are **first-class objects** (OpportunityCard, OpportunityBatch), not ephemeral chat answers.
   - They’re linked to BrandBrainSnapshot, Personas, Pillars, and source docs.

2. **Multi-brand, multi-day memory**
   - We can:
     - avoid repeating the same weak angles,
     - deliberately fill persona/pillar gaps over time.

3. **Scoring + triage**
   - Users see a **small, prioritized set** (e.g. 5–10) instead of 20–50 unranked ideas.

4. **Tight integration into the rest of the system**
   - One click from OpportunityCard → ContentPackage → multi-channel drafts,
   - With Learning feeding back to improve future opportunity selection.

If this engine doesn’t clearly deliver these edges over “human + custom GPT”, it’s mis-designed.

---