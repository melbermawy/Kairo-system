# Kairo – Product Vision

Kairo is an AI-native content copilot for brands and content teams.

Its job is simple to state and hard to do:  
**turn a brand’s brain + external signals into a steady stream of on-brand opportunities and multi-channel drafts – faster and more reliably than a human team or a custom GPT setup.**

This doc explains why Kairo exists, who it serves, what we believe, and what “great” looks like over time.

---

## 1. Why Kairo exists (product thesis)

### The observed bottleneck

For serious content teams, the slow part is not “typing the post”.

The real bottleneck is **pre-production**:

- turning vague marketing priorities into angles,
- scanning feeds, competitors, and news,
- deciding “is this actually relevant to us?”,
- shaping those inputs into briefs and drafts.

In agencies and in-house teams, this shows up as:

- strategists, creators, and juniors spending hours to go from:
  - “we should talk about X” →  
  - to opportunity → outline → multi-channel drafts,
- lots of repeated thinking for each brand and each week,
- quality depending heavily on who had time and energy that day.

### The baselines we must beat

Kairo is not competing with “no tooling”. It must clearly beat:

1. **Manual process**  
   Strategist + creator + junior researcher working with docs, Slack, and feeds.

2. **A carefully set up custom GPT**  
   - brand dumped into a long system prompt,  
   - a few example posts copy-pasted,  
   - user typing: “give me 10 LinkedIn posts in this voice about [topic]”.

If Kairo is not better than (2) on **quality, control, speed, and repeatability**, it’s just a bloated wrapper.

### The thesis

We can treat pre-production as a **repeatable machine**, not ad-hoc chatter:

- encode the brand and its constraints into a **Brand Brain**,
- have engines that **hunt for external signals** and filter them through that brain,
- reuse patterns from what works across the brand and the wider ecosystem,
- generate structured opportunities → outlines → channel-specific variants,
- close the loop with a learning engine that gets sharper as teams use it.

Kairo is not a planner board with an “AI button”.  
It’s a chain of engines that does the **research, patterning, and drafting**, leaving humans to:

- pick from high-quality options,
- tweak for nuance,
- approve and ship.

### Why now

General-purpose LLMs are finally good enough to:

- understand tone and positioning,
- compress messy external content,
- imitate structural patterns.

But they are only useful at scale if you:

- fence them with structure (canonical objects, constrained IO),
- ground them in brand-specific memory,
- and build a **learning loop** instead of living inside ad-hoc chat prompts.

Kairo exists to do exactly that for content teams.

---

## 2. Who we serve and their core jobs

### Primary ICP (v1)

Kairo v1 is aimed at **content teams who operate like small factories**:

- agencies running multiple B2B/B2C brands, or
- in-house marketing teams for a single brand,

who:

- publish regularly on LinkedIn and X (and later other channels),
- already have some idea of their personas, pillars, and offers,
- are constrained by **how much pre-production the team can handle**, not ideas in the abstract.

### Secondary ICP (later)

- high-output solo creators who:
  - behave like a mini content team,
  - treat their personal brand as a product,
  - care about consistency and scale, not just “inspiration”.

### Core jobs Kairo must solve

For these teams, Kairo must reliably do the following jobs:

- **Job 1 – External signal digestion**  
  Continuously ingest and **hunt for signals** (news, posts, threads, competitor moves) and decide:  
  “is this a real opportunity for *this* brand, for *these* personas and pillars?”

- **Job 2 – Opportunity surfacing**  
  Turn those signals into **specific, on-brand opportunities**, not vague prompts:
  - “this change in regulation is a chance to show your POV to ICP-1 on Pillar ‘Strategy’”.

- **Job 3 – Drafting and channel rendering**  
  For a chosen opportunity:
  - generate **LLM-built outlines** and multi-variant, multi-channel drafts,
  - apply known patterns and hooks that fit the brand,
  - get to “approved candidate drafts” in minutes, not hours.

- **Job 4 – Learning from reality**  
  Without asking for huge extra effort:
  - capture which opportunities and variants were actually used,
  - capture explicit feedback (“this is gold”, “never again”),
  - later, incorporate performance signals,
  - and use all of that to sharpen future opportunities and drafts.

Kairo’s value is not “one nice prompt template”.  
It’s that **most of what gets shipped each week started life inside Kairo’s engines**, not from scratch in Google Docs.

---

## 3. Core beliefs and design principles

This section encodes the non-negotiable philosophies behind Kairo.  
If a future decision fights these, it’s probably wrong.

### 3.1 AI-native, not “AI added on”

- Kairo is designed as a **graph of transformations**, not a CRUD app with an “AI field”.
- Engines (Brand Brain, Opportunities, Patterns, Content Engineering, Learning) map:
  - one set of canonical objects → another,
  - using LLMs where they’re strong (synthesis, style, pattern detection),
  - and simple code where it’s about control and invariants.

The goal is **agentic behavior**: Kairo proactively does work, not just waits for prompts.

### 3.2 Brand-first, not generic copy

- Every brand is represented by things like:
  - `BrandBrainSnapshot`, `BrandRuntimeContext`, `BrandMemoryFragment`,
  - plus stable structures: Personas, Pillars, BrandPreferences.
- Kairo never treats content as generic; everything flows through the brand brain.
- There is **no cross-brand leakage**:
  - brand-specific memories stay siloed,
  - global patterns (e.g. “3-mistakes hook”) live in separate, anonymised structures (GlobalPriors, PatternTemplate).

### 3.3 Human-in-the-loop at the right spots

- Kairo is a **copilot**, not an auto-poster.
- Humans should mainly:
  - choose and edit opportunities,
  - edit and approve packages/variants,
  - mark “golden examples” and “avoid this” cases.
- We explicitly minimise **energy cost**:
  - fewer, higher-quality options instead of 50 mediocre ones,
  - defaults and inference over asking for endless knobs and settings,
  - deliberate checkpoints where the human’s decision has maximum leverage.

### 3.4 Structured IO > prompt spaghetti

- All domain entities are **Canonical Objects (CO-xx)**.  
  Engines take CO-xx and return CO-xx – never raw text blobs.
- LLM outputs are:
  - constrained (e.g. JSON schemas),
  - validated,
  - stored in inspectable shapes (OpportunityCard, ContentPackage, ContentVariant, etc.).
- This makes the system:
  - debuggable (“what did the engine think was the persona/pillar here?”),
  - composable (engines can be rearranged / extended),
  - testable (we can run fixtures through pipelines offline).

### 3.5 Learn-or-die

- Kairo must **get better over time**, or it’s pointless.
- Learning inputs:
  - what was selected vs ignored,
  - which variants required minimal edits vs total rewrites,
  - which patterns were marked as “golden” vs “never again”,
  - later, performance metrics from channels.
- The Learning engine updates:
  - pattern / tone / structure weights,
  - sampling choices in future generations,
  - guardrails for known bad behaviors.
- All of this needs to happen with **low user friction**.  
  If learning requires a dashboard and manual labels, it won’t happen.

### 3.6 Proactive, not passive

- Kairo should not sit idle and wait for the user to paste links.
- Once a brand brain is configured and channels are connected, Kairo:
  - regularly ingests external content (via scraping/APIs),
  - filters and scores it against the brand,
  - surfaces only **high-opportunity triggers** to the human.
- The user’s mindset should be “review and steer an engine that’s always working”, not “remember to feed the bot”.

---

## 4. What “great” looks like (12–18 month horizon)

This is not a feature list. It’s a picture of success.

### For a content team

- Each brand has:
  - a living, versioned Brand Brain,
  - an always-updating stream of **Kairo-proposed opportunities**,
  - a calendar filled mostly with **Kairo-generated content packages**,
  - a pattern library built from what has actually worked.
- Weekly reality:
  - the team spends most of its time **reviewing, pruning, and sharpening**,
  - not inventing angles or staring at blank docs.
- Time from “we should talk about X” to “approved multi-channel draft”:
  - measured in **minutes**, not hours.

Most content that ships in a given week starts as:

- OpportunityCard → ContentPackage → ContentVariants generated inside Kairo,  
  with humans tweaking, not originating everything.

### For the manager

- Clear visibility into:
  - coverage across personas and pillars over time,
  - which patterns and hooks are driving wins,
  - where the bottleneck is (too few opportunities, too many unapproved packages, etc.).
- ability to answer:
  - “are we over-indexing on safe content?”
  - “are we neglecting a key persona or offer?”
  - “is the team actually leveraging Kairo or working around it?”

### For the product itself

- Engines are modular and inspectable:
  - we can add a new stage (e.g. a claim-checking pass, a visual suggestion pass) without rewriting everything.
- Adding a new channel or content type is evolutionary:
  - mostly new ChannelConfig + pattern mappings + a renderer for that surface,
  - not a full system redesign.

---

## 5. What v1 is (and is not)

This keeps us honest and ties into the PRD.

### v1 **is**

- **Channels**:
  - Focus on 1–2 channels (likely LinkedIn + X) for v1.
- **Engines**:
  - Brand Brain engine:
    - structured onboarding,
    - example ingestion,
    - a usable BrandBrainSnapshot + BrandRuntimeContext.
  - Content Engineering engine:
    - outline → variants for chosen opportunities,
    - strong control over tone, structure, and patterns.
  - Opportunities engine (v1 level):
    - at minimum, smart processing of user-curated external content,
    - and a path to proactive ingestion (starting small).
  - Learning engine (v1 level):
    - feedback capture (used/unused, “golden”, “never again”),
    - basic weighting of patterns and tone knobs.
- **Scope**:
  - enough to run multiple brands in parallel for a small team,
  - with Kairo responsible for the majority of ideas + first drafts.

### v1 **is not**

- A full-blown analytics suite or growth platform.
- An “auto-poster” that pushes content without human approval.
- A full internet-scale trend mining system – v1 will start narrower and grow.
- A do-everything content OS with tasks, tickets, billing, etc.

v1 is a **strong core**: Brand Brain + Opportunities + Content Engineering + basic Learning, wired for later expansion.

---

## 6. North-star and supporting metrics

We need a small, opinionated scoreboard.

### North-star metric

- **Time from “idea / trigger” → “approved multi-channel draft”**,  
  **per team, pre-vs-post Kairo**.

If Kairo doesn’t significantly compress this, we’ve missed the point.

### Supporting metrics

- **Usage of generated output**
  - % of Kairo-generated content packages that:
    - are used at all,
    - are saved as “good examples”.
- **Revision effort**
  - % of variants that:
    - required only minor edits before publishing,
    - required full rewrites,
    - were discarded.
- **Coverage**
  - distribution of content across personas and pillars over a period,
  - ability to avoid over-focusing on 1–2 “safe” themes.
- **Brand alignment (calibration set)**
  - small, fixed eval set per brand:
    - human scores on “does this feel like us?” at onboarding and after iterations.

These metrics should be simple to compute from objects we already track (ContentPackage, ContentVariant, FeedbackEvent, etc.).

---

## 7. Evolution path of the system

This is how Kairo’s world should grow, independent of any single backlog.

### Engine layering (high level)

- **Phase 1 – Brand Brain + CE core**
  - Strong Brand Brain engine:
    - reliable BrandBrainSnapshots from onboarding + examples.
  - Strong Content Engineering engine:
    - outlines and channel-specific variants from a chosen opportunity.
  - Opportunities:
    - mainly user-fed external content and simple manual triggers.

- **Phase 2 – Opportunities + Patterns**
  - Opportunities engine:
    - proactive ingestion of external signals (scraping/APIs),
    - scoring and surfacing of OpportunityCards per brand.
  - Patterns engine:
    - mining pattern templates from model accounts and internal hits,
    - mapping patterns to brand personas/pillars,
    - feeding CE with better, more targeted templates.

- **Phase 3 – Learning + scale**
  - Learning engine:
    - integrating performance metrics and feedback events to adjust:
      - pattern weights,
      - tone/styles,
      - opportunity scoring.
  - More channels and formats:
    - additional surfaces (e.g. YouTube scripts, email, etc.) plugged in via ChannelConfig and renderers.
  - Richer analytics:
    - pattern effectiveness by brand and vertical,
    - better guardrails and risk management.

### Surface evolution

- Start as:
  - a per-brand workspace where most work happens inside Kairo.
- Grow into:
  - a multi-brand command center:
    - shared patterns,
    - cross-brand analytics at a safe, anonymised level.
- Always preserve:
  - the mental model that **Kairo is doing active work**, not just storing content.

---

This vision is the north star.  
The canonical objects, engine specs, and PRD describe **how** we walk toward it; they should always be read in light of this document.