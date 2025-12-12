# 10-variant-rubric

> quality rubric for variants produced by `graph_hero_variants_from_package` and persisted by `content_engine`.

---

## 1. purpose

this doc defines what constitutes a **good variant** per channel for PRD-1, and gives:

- global validity rules for all variants
- per-channel constraints (linkedin, x, newsletter; others stubbed)
- categories: **invalid**, **valid-but-weak**, **publish-ready**
- how this ties into `VariantDTO` and the content engine behavior

---

## 2. dto + channels

### 2.1 dto reference

`VariantDTO` (from `kairo.hero.dto`) core fields:

- `id: UUID`
- `package_id: UUID`
- `brand_id: UUID`
- `channel: Channel`
- `title: str | None` (some channels may not use a separate title)
- `body: str`
- `cta: str | None`
- `status: VariantStatus` (initially `draft`)
- `notes_for_humans: str | None`
- `meta: dict[str, Any]`

### 2.2 channels in scope (prd-1)

we care about:

- `linkedin`
- `x`
- `newsletter`

others exist in the enum (`instagram`, `tiktok`, `youtube`) but can have weaker rules for PRD-1.

---

## 3. global validity rules

a variant is **invalid** if any of these are true:

### 3.1 empty or junk body

- `body` is empty, whitespace, or extremely short (e.g. `< 10` non-space characters)
- `body` is clearly internal/debug text (“TODO: fill this”, “this is a placeholder”)

### 3.2 hallucinated or mismatched brand

- variant mentions a completely different brand or product than `brand_id`
- variant contradicts brand taboos (e.g. uses banned phrases / tones)

### 3.3 structural / formatting failure (obvious)

- includes raw prompt fragments (“as an ai language model…”)
- contains explicit instructions to the AI (“you should write about…”)
- uses obvious template residues (“[insert cta here]”, “{brand}” left unfilled)

### 3.4 no link to package thesis

- entirely ignores the package thesis (e.g. package is about pricing transparency, variant talks about hiring or random blog post)
- uses opportunity keywords without the intended framing (just keyword stuffing)

### 3.5 taboo / compliance issues

- violates `BrandSnapshot.taboos` on content level:
  - forbidden topics
  - forbidden claims
  - tone that’s explicitly disallowed
- for PRD-1, any taboo violation makes variant invalid. engine must **not** mark such variants as publish-ready.

---

## 4. rubric dimensions (global)

for variants that are not invalid, we grade along:

### 4.1 clarity & completeness (0–3)

- **0** – confusing, incomplete sentence fragments.
- **1** – understandable but clunky or overly generic.
- **2** – clear message with basic structure (problem → solution → CTA).
- **3** – crisp, engaging, and easy to read.

### 4.2 anchoring to package thesis (0–3)

- **0** – no visible connection.
- **1** – vague or indirect connection.
- **2** – clearly supports the package thesis.
- **3** – sharp, channel-optimized execution of the thesis.

### 4.3 channel form fit (0–3)

- assesses whether the variant uses the channel **as it is**, not as an email pasted everywhere.

- **0** – completely ignores channel conventions.
- **1** – roughly okay but tone/length is off.
- **2** – mostly channel-appropriate (length, formatting).
- **3** – feels native to the channel, including hooks, pacing, and structural norms.

### 4.4 CTA alignment (0–3)

- **0** – no CTA or confusing one.
- **1** – generic CTA not entirely out of place.
- **2** – clear CTA consistent with package’s CTA.
- **3** – strong CTA that fits the channel’s action (comment, DM, click, reply).

---

## 5. per-channel constraints

these are **additional** constraints layered on top of the global ones.

### 5.1 linkedin

#### 5.1.1 structural expectations

- should read like a **short post** or longish micro-article, not a tweet:
  - typically 2–8 paragraphs / line breaks.
  - first line should be a hook or clear statement, not buried.
- avoid:
  - all caps
  - spammy hashtag walls
  - emoji spam

#### 5.1.2 length bands (soft)

- recommended target: 120–800 words
- **invalid** if < ~25 words (too thin) unless explicitly a one-line announcement with context.

#### 5.1.3 rubric modifiers

- channel form fit **0** if:
  - looks like a tweet pasted (single short line with hashtags)
  - or looks like an email (greetings + signature block).
- channel form fit **3** if:
  - hook line, clear body, separated paragraphs
  - CTA is appropriate to linkedin (comment, DM, click a link).

### 5.2 x (twitter)

#### 5.2.1 structural expectations

- can be:
  - a single main tweet (for PRD-1, simplest)
  - or a very short pseudo-thread (we can keep it as one `body` text with line breaks)
- minimal fluff, strong hook, minimal hashtags.

#### 5.2.2 length bands (hard-ish)

- recommended: 100–260 characters (for single tweet feeling)
- **invalid** if:
  - > 600 characters (reads like a blog post)
  - < 20 characters (too thin).

#### 5.2.3 rubric modifiers

- channel form fit **0** if:
  - multi-paragraph essay style
  - includes greetings/sign-offs.
- **3** if:
  - concise, punchy, leads with the sharp part of the thesis, uses mentions/hashtags sparingly.

### 5.3 newsletter

#### 5.3.1 structural expectations

- feels like an email section or full email body:
  - possible outline: hook → setup → main content → CTA.
- should not look like a tweet or linkedin cross-post:
  - avoid “hey linkedin” tone.

#### 5.3.2 length bands

- recommended: 150–1000 words (flexible for PRD-1).
- invalid only if:
  - < ~50 words (no substance)
  - or it’s clearly a pasted linkedin post without adaptation.

#### 5.3.3 rubric modifiers

- channel form fit **0** if:
  - includes tweet-specific artifacts (RT, @ handles, etc.) without context.
- **3** if:
  - narrative or structured explanation that could plausibly live in a newsletter to the brand’s list.

### 5.4 other channels (instagram, tiktok, youtube)

for PRD-1, treat these as **weakly constrained**:

- they must not violate taboos or global rules.
- they should at least **describe** what the content is (e.g. “short video idea: …”).
- we don’t enforce strict length/structure yet.

the F2 rubric can evolve here later as we add more channel-specific detail.

---

## 6. classification bands

we define a **variant quality score**:

- `variant_score = clarity + anchoring + channel_fit + cta_alignment`

with each in `[0,3]`, total in `[0,12]`.

**bands:**

- **invalid:**
  - fails any global hard rule
  - fails any channel-specific hard rule
- **valid-but-weak:**
  - `valid=True` and `variant_score ∈ [1,6]`
- **publish-ready:**
  - `valid=True` and `variant_score ≥ 7`

for PRD-1:

- engine should prevent obviously invalid variants from being marked `approved` or `scheduled`.
- hero loop F2 metrics should count how many **publish-ready** vs **weak** variants we get per package.

---

## 7. taboo + safety

### 7.1 responsibilities

- **graph**:
  - must *try* to respect `BrandSnapshot.taboos` in prompts and outputs.
- **engine**:
  - must apply **hard checks** on the generated text:
    - simple keyword/regex for obvious banned terms (PRD-1)
    - structural checks for “AI disclaimers” or template leftovers.

any variant failing taboo or safety checks:

- is marked invalid
- is not considered publish-ready
- can still be logged under `meta` for debugging

---

## 8. engine vs graph responsibilities

### 8.1 graph responsibilities (`graph_hero_variants_from_package`)

- generate, for each channel in package.channels:
  - at least one draft variant
  - text that clearly attempts to implement the package thesis
- include enough hints for the engine to:
  - classify clarity, anchoring, and channel fit
  - detect obvious violations (e.g. via labels/tags in structured output)

graph must not:

- interact with ORM or DB
- decide variant statuses (that’s engine’s job)
- bypass the rubric (no unstructured “just trust me” blobs)

### 8.2 engine responsibilities (`content_engine.generate_variants_for_package`)

- call graph to get `VariantDraftDTO[]`
- run validation + scoring logic from this rubric:
  - filter out invalid variants
  - compute `variant_score` and store it in meta / DTO
- enforce:
  - **no regeneration** in PRD-1 if variants already exist for the package
  - no taboo-violating variants get approved/scheduled
- return a `VariantListDTO` with:
  - per-variant quality info (where appropriate)
  - enough meta for the eval harness to inspect decisions.

---

## 9. examples and anti-examples

### 9.1 linkedin – good

> “most customers don’t actually understand how your pricing works.
>  
> here’s how we re-framed our pricing page into three simple promises:
> 1) no surprise add-ons  
> 2) predictable monthly bill  
> 3) real-time usage dashboard  
>  
> this week we’re opening 5 free ‘pricing teardown’ sessions. want one?
> comment ‘PRICE’ and we’ll DM you details.”

- clear thesis → pricing clarity
- native linkedin shape → paragraphs, list, CTA
- strong call-to-action.

### 9.2 linkedin – invalid

> “write a good linkedin post about our product.”

this is obviously instruction text, not a variant.

### 9.3 x – good

> “your monthly bill shouldn’t feel like a jump scare.
>  
> we show you **exactly** what you pay for in real time.
>  
> if your current tool can’t do that, it’s not ‘transparent’, it’s lazy.”

concise, punchy, no email structure → good fit for x.

---

## 10. implementation notes (prd-1)

- `is_valid`, `variant_score`, and rubric breakdowns are DTO/`meta` concerns, **not** first-class DB columns in PRD-1.
- tests for F2 should use this rubric to:
  - assert no invalid variants survive persistence
  - count how many publish-ready variants we get in canonical fixtures.
- for eval harness, human labels should match these axes (clarity, anchoring, channel_fit, CTA) to calibrate LLM behavior over time.