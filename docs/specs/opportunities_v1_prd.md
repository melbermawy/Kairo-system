# Opportunities v1 PRD

> **Version:** 3.5 (Budget Reality Lock)
> **Last Updated:** 2026-01-19
> **Status:** Locked for Implementation

---

## A. Inputs

This section defines the single entry point for the Opportunities system.

### A.1. Entry Point: BrandBrainSnapshot

**BrandBrain is DONE.** Its final output is `BrandBrainSnapshot`. This is the **only** input to Opportunities.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BRANDBRAIN (COMPLETE)                         │
│                                                                         │
│  BrandBrainSnapshot                                                     │
│  └── snapshot_json: {                                                   │
│        positioning: str                                                 │
│        tone_tags: list[str]                                             │
│        taboos: list[str]                                                │
│        persona_ids: list[UUID]                                          │
│        pillar_ids: list[UUID]                                           │
│      }                                                                  │
│  └── brand_id: UUID                                                     │
│  └── created_at: datetime                                               │
│                                                                         │
│  This is the ENTRY POINT. Nothing else enters Opportunities.            │
└─────────────────────────────────────────────────────────────────────────┘
```

### A.2. What Opportunities Does NOT Receive

The following are **explicitly excluded** from Opportunities input:

| Excluded | Reason |
|----------|--------|
| Raw Apify data from BrandBrain | BrandBrain's scrapes are for brand's OWN content |
| NormalizedEvidenceItem | BrandBrain internal type, not consumed by Opportunities |
| EvidenceBundle from BrandBrain | That bundle is for brand analysis, not trending content |
| FeatureReport | Internal BrandBrain artifact |

### A.3. SeedPack Derivation

From `BrandBrainSnapshot`, Opportunities derives a `SeedPack`:

```python
@dataclass(frozen=True)
class SeedPack:
    """
    Deterministic derivation from BrandBrainSnapshot.

    This struct drives all downstream source selection.
    Given the same BrandBrainSnapshot, produces the same SeedPack.
    """

    brand_id: UUID
    snapshot_id: UUID  # Audit trail back to BrandBrainSnapshot

    # From snapshot_json
    positioning: str
    tone_tags: list[str]
    taboos: list[str]

    # Derived: Keywords for discovery (from positioning)
    seed_keywords: list[str]  # Max 10, extracted from positioning

    # From Brand model
    industry_vertical: str | None

    # From SourceConnection (brand's connected platforms)
    preferred_platforms: list[str]  # e.g., ["instagram", "tiktok"]


def derive_seed_pack(brand_id: UUID) -> SeedPack | None:
    """
    Derive SeedPack from latest BrandBrainSnapshot.

    Returns None if no snapshot exists.
    """
    snapshot = (
        BrandBrainSnapshot.objects
        .filter(brand_id=brand_id)
        .order_by("-created_at")
        .first()
    )

    if not snapshot:
        return None

    sj = snapshot.snapshot_json

    return SeedPack(
        brand_id=brand_id,
        snapshot_id=snapshot.id,
        positioning=sj.get("positioning", ""),
        tone_tags=sj.get("tone_tags", []),
        taboos=sj.get("taboos", []),
        seed_keywords=extract_keywords(sj.get("positioning", ""), max_count=10),
        industry_vertical=snapshot.brand.industry_vertical,
        preferred_platforms=get_connected_platforms(brand_id) or ["instagram"],
    )
```

---

## B. SourceActivation (new subsystem)

### B.0. System Definition

**SourceActivation is a NEW system.** It did not exist prior to this PRD. It is introduced here for the first time.

SourceActivation sits **upstream** of Opportunity Synthesis. It is the **evidence factory** that transforms brand context into actionable trending content.

### B.0.1. Terminology & Ownership

| System | Role | Ownership |
|--------|------|-----------|
| **BrandBrain** | Immutable upstream input | Provides `BrandBrainSnapshot`. Complete. No changes. |
| **SourceActivation** | Evidence factory | Owns: source activation, evidence acquisition, enrichment, normalization |
| **Opportunity Synthesis** | Downstream consumer | Consumes `EvidenceBundle` + `BrandBrainSnapshot`. Owns: scoring, synthesis, ranking. |
| **TodayBoard** | Persistence + UI state | Owns: state machine, caching, API response. Does NOT own evidence or synthesis. |

### B.0.2. Ownership Boundaries

**SourceActivation OWNS:**
- Source activation (deciding which Apify actors to call)
- Evidence acquisition (executing Apify actors)
- Enrichment (Stage 2 calls for transcript retrieval)
- Normalization (raw Apify output → canonical `EvidenceItem`)

**SourceActivation does NOT own:**
- Scoring (happens in Opportunity Synthesis)
- Synthesis (LLM-based opportunity generation)
- Ranking (opportunity ordering)
- UI semantics (state machine, response formatting)
- LLM calls of any kind

### B.0.3. Forbidden Terms

The following terms are **explicitly forbidden** in this specification and codebase:
- ~~Hero~~ (legacy system name, do not use)
- ~~external_signals~~ (implies pre-existing upstream, does not exist)
- ~~NormalizedEvidenceItem~~ (BrandBrain internal type, not used here)
- Any phrasing implying "evidence already exists upstream"

Evidence does NOT exist until SourceActivation creates it.

### B.0.4. Data Flow Law (Non-Negotiable)

The following data flow is **locked**. Any implementation that deviates, collapses stages, or blurs responsibilities is invalid.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      LOCKED DATA FLOW                                    │
│                                                                          │
│   1. ENTRY                                                               │
│   ────────                                                               │
│   Input: BrandBrainSnapshot (ONLY)                                       │
│   Nothing else enters SourceActivation:                                  │
│   - No raw Apify output                                                  │
│   - No pre-existing evidence                                             │
│   - No UI-triggered data passed downstream                               │
│                                                                          │
│   2. SEED / INPUT BUILDER                                                │
│   ───────────────────────                                                │
│   BrandBrainSnapshot → SeedPack                                          │
│   SeedPack is:                                                           │
│   - Deterministic                                                        │
│   - Derived only from snapshot + brand metadata                          │
│   - Used only to construct inputs for search-capable scrapers            │
│   SeedPack does NOT contain:                                             │
│   - Scraped content                                                      │
│   - URLs                                                                 │
│   - Evidence                                                             │
│   - Opportunity semantics                                                │
│                                                                          │
│   3. PLATFORM ACQUISITION                                                │
│   ───────────────────────                                                │
│   Instagram: MANDATORY 2-stage (see B.2.1)                               │
│   TikTok/LinkedIn/YouTube: Single-stage (see B.2.2-B.2.4)                │
│                                                                          │
│   4. OUTPUT                                                              │
│   ────────                                                               │
│   SourceActivation outputs ONLY:                                         │
│   - EvidenceItem                                                         │
│   - EvidenceBundle                                                       │
│   SourceActivation does NOT:                                             │
│   - Generate opportunities                                               │
│   - Score content                                                        │
│   - Apply UI semantics                                                   │
│   - Make LLM calls                                                       │
│                                                                          │
│   Evidence is: canonical, deterministic, normalized, uninterpreted       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### B.1. System Position

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA FLOW                                       │
│                                                                          │
│   BrandBrainSnapshot                                                     │
│          │                                                               │
│          ▼                                                               │
│   derive_seed_pack()                                                     │
│          │                                                               │
│          ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    SOURCEACTIVATION                              │   │
│   │                                                                  │   │
│   │   SeedPack → Recipe Selection → Apify Calls → EvidenceBundle    │   │
│   │                                                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│          │                                                               │
│          ▼                                                               │
│   Opportunity Synthesis (Phase 0)                                        │
│          │                                                               │
│          ▼                                                               │
│   OpportunityDTO[]                                                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### B.2. Platform Acquisition Stages

**CRITICAL: Instagram requires TWO stages. Other platforms use single-stage.**

#### B.2.1. Instagram: MANDATORY 2-Stage Acquisition

Instagram's discovery actors return shallow metadata. To get transcripts (high-leverage signal), a second enrichment stage is required.

**HARD RULES (Violation = Invalid Implementation):**
1. Stage 2 inputs MUST be derived from Stage 1 outputs
2. No hardcoded URLs in Stage 2
3. No skipping enrichment for Instagram
4. No collapsing stages into a single call

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    INSTAGRAM 2-STAGE PATTERN (MANDATORY)                 │
│                                                                          │
│   STAGE 1: Discovery (Cheap, Wide)                                       │
│   ─────────────────────────────────                                      │
│   Actor: apify/instagram-scraper                                         │
│   Input: SeedPack.seed_keywords → search, hashtag, user, or place        │
│   Caps:                                                                  │
│     - resultsLimit: 20 (max items returned)                              │
│     - searchLimit: 1 (search results to expand)                          │
│   Output: Shallow metadata (URL, thumbnail, basic metrics)               │
│   Does NOT include: transcript                                           │
│                                                                          │
│   ▼▼▼ FILTER (Stage 1 → Stage 2 derivation) ▼▼▼                          │
│   ─────────────────────────────────────────────                          │
│   Filter criteria:                                                       │
│   - productType == "clips" (videos only)                                 │
│   - videoViewCount >= 1000                                               │
│   - not in blocklist                                                     │
│   Output: List of URLs (derived from Stage 1 items)                      │
│                                                                          │
│   STAGE 2: Enrichment (Expensive, Winners Only)                          │
│   ─────────────────────────────────────────────                          │
│   Actor: apify/instagram-reel-scraper                                    │
│   Input: directUrls[] (from Stage 1 filter output)                       │
│   Caps:                                                                  │
│     - resultsLimit: 5 (max items returned)                               │
│   Output: Full content WITH TRANSCRIPT                                   │
│                                                                          │
│   WHY TRANSCRIPTS MATTER:                                                │
│   - Transcripts contain spoken content (voice, tone, messaging)          │
│   - Captions are often minimal ("link in bio")                           │
│   - Transcripts enable semantic matching to brand positioning            │
│   - Without transcripts, opportunities are shallow                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Stage 1 → Stage 2 Input Derivation (REQUIRED):**

```python
def derive_stage2_inputs(stage1_items: list[dict]) -> list[str]:
    """
    Derive Stage 2 inputs from Stage 1 results.

    Input: Raw items from instagram-scraper (Stage 1)
    Output: List of URLs for instagram-reel-scraper (Stage 2)

    INVARIANT: Stage 2 inputs MUST be derived from Stage 1 outputs.
    - Never hardcode URLs
    - Never use external sources
    - Never skip this derivation step
    """
    candidates = []

    for item in stage1_items:
        # Only reels have transcripts
        if item.get("productType") != "clips":
            continue

        # Basic engagement filter
        views = item.get("videoViewCount") or 0
        if views < 1000:
            continue

        url = item.get("url")
        if url:
            candidates.append(url)

    # Sort by engagement, take top N
    # (engagement heuristic: views * 0.7 + likes * 0.3)
    return candidates[:5]
```

#### B.2.2. TikTok: Single-Stage Acquisition

TikTok's scraper is **semantically rich**. Search output already includes subtitleLinks (transcript equivalent). No enrichment stage required.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TIKTOK SINGLE-STAGE                                   │
│                                                                          │
│   Actor: clockworks/tiktok-scraper                                       │
│   Input: SeedPack.seed_keywords → hashtags[] or searchQueries[]          │
│   Caps:                                                                  │
│     - resultsPerPage: 15 (videos per hashtag/search)                     │
│   Output: Full content with subtitleLinks, hashtags, engagement          │
│                                                                          │
│   WHY SINGLE STAGE:                                                      │
│   - TikTok actor returns subtitleLinks (transcript equivalent)           │
│   - Search results are already semantically rich                         │
│   - No enrichment step needed                                            │
│                                                                          │
│   CONSTRAINTS:                                                           │
│   - Results are still capped (resultsPerPage)                            │
│   - Inputs still originate from SeedPack                                 │
│   - Output is still normalized evidence only                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### B.2.3. LinkedIn: Single-Stage Acquisition

LinkedIn's company posts actor is **semantically rich**. Post text is the primary content (no video/transcript). No enrichment stage required.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    LINKEDIN SINGLE-STAGE                                 │
│                                                                          │
│   Actor: apimaestro/linkedin-company-posts                               │
│   Input: company_name from SeedPack or competitor list                   │
│   Caps:                                                                  │
│     - limit: 20 (result limit per request, max 100)                      │
│   Output: Post text, engagement stats (total_reactions, like, love)      │
│                                                                          │
│   WHY SINGLE STAGE:                                                      │
│   - LinkedIn posts are text-heavy (no transcript needed)                 │
│   - Company posts actor returns full content                             │
│   - Search results are already semantically rich                         │
│                                                                          │
│   CONSTRAINTS:                                                           │
│   - Results are still capped (limit)                                     │
│   - Inputs still originate from SeedPack                                 │
│   - Output is still normalized evidence only                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### B.2.4. YouTube: Single-Stage Acquisition

YouTube's scraper is **semantically rich**. Descriptions are typically detailed, and subtitles can be requested. No enrichment stage required.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    YOUTUBE SINGLE-STAGE                                  │
│                                                                          │
│   Actor: streamers/youtube-scraper                                       │
│   Input: SeedPack.seed_keywords → searchQueries[]                        │
│   Caps:                                                                  │
│     - maxResults: 10 (limit regular videos per search term)              │
│   Output: Video metadata, description, optional subtitles                │
│                                                                          │
│   WHY SINGLE STAGE:                                                      │
│   - YouTube actor supports downloadSubtitles option in same call         │
│   - Description field (text) is typically detailed                       │
│   - Search results are already semantically rich                         │
│                                                                          │
│   CONSTRAINTS:                                                           │
│   - Results are still capped (maxResults)                                │
│   - Inputs still originate from SeedPack                                 │
│   - Output is still normalized evidence only                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### B.3. Recipe Registry

A **Recipe** defines one complete acquisition pattern. Recipes are deterministic given a SeedPack.

**Cost control is enforced via conservative policy constants + result caps:**
- Each recipe specifies item limits using Apify's native input fields
- These caps are enforced at the actor input level
- Budget enforcement uses policy constants + minimal ledger (not real-time billing telemetry)
- See Section G.1 for full budget policy details

```python
@dataclass(frozen=True)
class RecipeSpec:
    """
    Deterministic acquisition recipe.

    Given SeedPack, produces the same Apify calls every time.
    Cost is controlled via result caps + USD policy constants (see Section G.1).
    """

    recipe_id: str  # e.g., "IG-1"
    platform: str
    description: str

    # Stage 1 config
    stage1_actor: str
    stage1_input_builder: Callable[[SeedPack], dict]
    stage1_result_limit: int  # Maps to actor's resultsLimit/limit/maxResults

    # Stage 2 config (None for single-stage platforms)
    stage2_actor: str | None
    stage2_input_builder: Callable[[list[str]], dict] | None
    stage2_result_limit: int | None  # Maps to actor's resultsLimit

    # Filter between stages (None for single-stage)
    stage1_to_stage2_filter: Callable[[list[dict]], list[str]] | None


RECIPE_REGISTRY: dict[str, RecipeSpec] = {
    # Instagram recipes (2-stage MANDATORY)
    "IG-1": RecipeSpec(
        recipe_id="IG-1",
        platform="instagram",
        description="Hashtag search → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_hashtag_input,
        stage1_result_limit=20,  # resultsLimit in actor input
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=5,  # resultsLimit in actor input
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    "IG-2": RecipeSpec(
        recipe_id="IG-2",
        platform="instagram",
        description="Profile posts → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_profile_input,
        stage1_result_limit=15,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=5,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    "IG-3": RecipeSpec(
        recipe_id="IG-3",
        platform="instagram",
        description="Search query → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_search_input,
        stage1_result_limit=20,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=5,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    "IG-4": RecipeSpec(
        recipe_id="IG-4",
        platform="instagram",
        description="Competitor watch → Reel enrichment",
        stage1_actor="apify/instagram-scraper",
        stage1_input_builder=build_ig_competitor_input,
        stage1_result_limit=10,
        stage2_actor="apify/instagram-reel-scraper",
        stage2_input_builder=build_ig_reel_enrichment_input,
        stage2_result_limit=3,
        stage1_to_stage2_filter=filter_ig_reels_by_engagement,
    ),

    # TikTok recipes (single-stage, semantically rich)
    "TT-1": RecipeSpec(
        recipe_id="TT-1",
        platform="tiktok",
        description="Hashtag search",
        stage1_actor="clockworks/tiktok-scraper",
        stage1_input_builder=build_tt_hashtag_input,
        stage1_result_limit=15,  # resultsPerPage in actor input
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),

    "TT-2": RecipeSpec(
        recipe_id="TT-2",
        platform="tiktok",
        description="Profile videos",
        stage1_actor="clockworks/tiktok-scraper",
        stage1_input_builder=build_tt_profile_input,
        stage1_result_limit=10,
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),

    # LinkedIn recipes (single-stage, semantically rich)
    "LI-1": RecipeSpec(
        recipe_id="LI-1",
        platform="linkedin",
        description="Company posts",
        stage1_actor="apimaestro/linkedin-company-posts",
        stage1_input_builder=build_li_company_input,
        stage1_result_limit=20,  # limit in actor input
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),

    # YouTube recipes (single-stage, semantically rich)
    "YT-1": RecipeSpec(
        recipe_id="YT-1",
        platform="youtube",
        description="Search videos",
        stage1_actor="streamers/youtube-scraper",
        stage1_input_builder=build_yt_search_input,
        stage1_result_limit=10,  # maxResults in actor input
        stage2_actor=None,
        stage2_input_builder=None,
        stage2_result_limit=None,
        stage1_to_stage2_filter=None,
    ),
}
```

### B.4. Recipe Execution

```python
async def execute_recipe(
    recipe: RecipeSpec,
    seed_pack: SeedPack,
    run_id: UUID,
) -> list[EvidenceItem]:
    """
    Execute a recipe and return normalized evidence.

    Cost control is via result_limit caps in the actor input,
    plus USD policy constants (see Section G.1).

    For 2-stage recipes (Instagram ONLY):
    1. Execute Stage 1 (discovery)
    2. Filter results
    3. Derive Stage 2 inputs from Stage 1 outputs (MANDATORY)
    4. Execute Stage 2 (enrichment)
    5. Merge and normalize

    For single-stage recipes (TikTok, LinkedIn, YouTube):
    1. Execute Stage 1 (semantically rich output)
    2. Normalize
    """
    results = []

    # Stage 1: Build input with result limit cap
    stage1_input = recipe.stage1_input_builder(seed_pack)
    # Result limit is enforced in input (e.g., resultsLimit, limit, maxResults)
    stage1_output = await call_apify_actor(
        actor_id=recipe.stage1_actor,
        input_data=stage1_input,
    )

    # Normalize Stage 1
    stage1_items = normalize_actor_output(
        raw_items=stage1_output,
        actor_id=recipe.stage1_actor,
        recipe_id=recipe.recipe_id,
        stage=1,
        run_id=run_id,
    )
    results.extend(stage1_items)

    # Stage 2 (Instagram 2-stage ONLY)
    if recipe.stage2_actor and recipe.stage1_to_stage2_filter:
        # INVARIANT: Stage 2 inputs MUST be derived from Stage 1 outputs
        # This is enforced by the filter function
        stage2_urls = recipe.stage1_to_stage2_filter(stage1_output)

        if not stage2_urls:
            logger.info("No winners from %s stage 1, skipping stage 2", recipe.recipe_id)
            return results

        # Build Stage 2 input with result limit cap
        stage2_input = recipe.stage2_input_builder(stage2_urls)
        stage2_output = await call_apify_actor(
            actor_id=recipe.stage2_actor,
            input_data=stage2_input,
        )

        # Normalize Stage 2 (replaces Stage 1 items for same URLs)
        stage2_items = normalize_actor_output(
            raw_items=stage2_output,
            actor_id=recipe.stage2_actor,
            recipe_id=recipe.recipe_id,
            stage=2,
            run_id=run_id,
        )

        # Merge: Stage 2 items replace Stage 1 items with same URL
        results = merge_stage_results(results, stage2_items)

    return results
```

### B.5. EvidenceItem (Canonical Output)

SourceActivation produces `EvidenceItem` as its canonical output type.

**SourceActivation does NOT:**
- Generate opportunities
- Score content
- Apply UI semantics
- Make LLM calls

Evidence is: **canonical, deterministic, normalized, uninterpreted**.

```python
@dataclass
class EvidenceItem:
    """
    Canonical evidence type from SourceActivation.

    This is the OUTPUT of SourceActivation.
    This is the INPUT to Opportunity Synthesis.

    LLMs do NOT touch this data. Normalization is deterministic.
    """

    id: UUID
    run_id: UUID  # ActivationRun.id

    # Source identification
    platform: str  # instagram, tiktok, youtube, linkedin
    actor_id: str  # Which Apify actor produced this
    acquisition_stage: int  # 1 or 2
    recipe_id: str  # Which recipe produced this

    # Content
    canonical_url: str
    external_id: str | None  # Platform-specific ID
    author_ref: str  # Username or handle
    title: str | None
    text_primary: str  # Caption, body, description
    text_secondary: str | None  # Transcript (high-value signal)
    hashtags: list[str]

    # Metrics (all optional)
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None

    # Timestamps
    published_at: datetime | None
    fetched_at: datetime

    # Quality flags
    has_transcript: bool

    # Raw payload retention (for debugging)
    raw_json: dict


@dataclass
class EvidenceBundle:
    """
    Complete evidence package from SourceActivation.

    This is what Phase 0 Opportunity Synthesis receives.
    """

    run_id: UUID
    brand_id: UUID
    seed_pack: SeedPack

    items: list[EvidenceItem]

    # Metadata
    recipes_executed: list[str]
    fetch_started_at: datetime
    fetch_ended_at: datetime

    # Quality summary
    item_count: int
    items_with_transcript: int
    platforms_covered: list[str]
```

### B.6. Invariants

| ID | Invariant | Enforcement |
|----|-----------|-------------|
| **SA-1** | Instagram MUST use 2-stage acquisition | Recipe registry enforces stage2_actor for IG recipes |
| **SA-2** | Stage 2 inputs MUST be derived from Stage 1 outputs | `stage1_to_stage2_filter` produces URLs from stage1 items |
| **SA-3** | EvidenceItem.has_transcript is ground truth for transcript presence | Set by normalizer, never assumed |
| **SA-4** | LLMs do NOT interpret evidence in SourceActivation | No LLM calls in this subsystem |
| **SA-5** | All Apify calls go through a centralized client wrapper | Wrapper enforces actor-specific result caps at input-build time; fixture-only mode bypasses Apify entirely |

---

## C. Opportunity Synthesis (refactored Phase 0)

This section describes the **minimal splice** that wires SourceActivation output into the existing synthesis pipeline.

**NOTE: This section specifies required changes, not the current state.** Schema changes are additive (new tables), and DTO changes are required extensions (new fields).

### C.1. Call Graph: BEFORE vs AFTER

The splice point is a single function replacement. Everything else remains identical.

**BEFORE (current code):**
```
generate_today_board(brand_id)
├── _build_brand_snapshot(brand_id)
├── _get_learning_summary_safe(brand_id)
├── _get_external_signals_safe(brand_id)          ← returns []
├── graph_generate_opportunities(snapshot, learning_summary, signals)
│   ├── node_generate_ideas(...)
│   ├── node_score_opportunities(...)
│   └── node_validate_opportunities(...)
├── _filter_invalid_opportunities(...)
├── _filter_redundant_opportunities(...)
├── _persist_opportunities(...)
└── _build_today_board_dto(...)
```

**AFTER (refactored):**
```
generate_today_board(brand_id, mode)
├── _build_brand_snapshot(brand_id)               ← UNCHANGED
├── _get_learning_summary_safe(brand_id)          ← UNCHANGED
├── derive_seed_pack(brand_id)                    ← NEW (from Section A)
├── get_or_create_evidence_bundle(brand_id, seed_pack, mode)  ← NEW SEAM
├── convert_evidence_bundle_to_signals(evidence_bundle)       ← NEW ADAPTER
├── graph_generate_opportunities(snapshot, learning_summary, signals)  ← UNCHANGED
│   ├── node_generate_ideas(...)                  ← UNCHANGED
│   ├── node_score_opportunities(...)             ← UNCHANGED
│   └── node_validate_opportunities(...)          ← UNCHANGED
├── _filter_invalid_opportunities(...)            ← UNCHANGED
├── _filter_redundant_opportunities(...)          ← UNCHANGED
├── _persist_opportunities(...)                   ← UPDATED (stores evidence_ids in metadata)
└── _build_today_board_dto(...)                   ← UPDATED (reads evidence_ids from metadata)
```

### C.2. The Two New Seams (Exact Signatures)

Only two new functions are introduced. They are the **only** additions to the engine.

#### C.2.1. Evidence Acquisition Seam

```python
# kairo/sourceactivation/services.py

def get_or_create_evidence_bundle(
    brand_id: UUID,
    seed_pack: SeedPack,
    mode: Literal["fixture_only", "live_cap_limited"],
) -> EvidenceBundle:
    """
    Returns EvidenceBundle for the given brand and mode.

    Args:
        brand_id: The brand requesting evidence
        seed_pack: Deterministic derivation from BrandBrainSnapshot
        mode: Execution mode
            - fixture_only: Load pre-recorded fixtures, no Apify calls
            - live_cap_limited: Execute recipes with result caps

    Returns:
        EvidenceBundle containing normalized EvidenceItems

    Idempotency:
        For a given (brand_id, seed_pack hash, mode, date_bucket),
        returns the same bundle if already cached/persisted.

    Mode selection rule:
        - Auto-generation (onboarding, first visit): fixture_only
        - Explicit regenerate (POST /regenerate/): live_cap_limited
    """
    ...
```

#### C.2.2. Evidence → Signals Adapter

```python
# kairo/hero/engines/opportunities_engine.py

def convert_evidence_bundle_to_signals(
    evidence_bundle: EvidenceBundle,
) -> list[dict]:
    """
    Deterministically convert EvidenceBundle to prompt-expected signal format.

    This adapter is PURE and DETERMINISTIC:
    - Same input always produces same output
    - No side effects
    - No LLM calls
    - No opportunity semantics added

    The output shape matches what synthesis prompts expect.
    """
    signals = []

    for item in evidence_bundle.items:
        signals.append({
            # Identity
            "id": str(item.id),
            "platform": item.platform,
            "url": item.canonical_url,
            "author": item.author_ref,

            # Content
            "text": item.text_primary,
            "transcript": item.text_secondary,  # High-value when present
            "hashtags": item.hashtags,

            # Metrics
            "metrics": {
                "views": item.view_count,
                "likes": item.like_count,
                "comments": item.comment_count,
                "shares": item.share_count,
            },

            # Timestamps
            "published_at": item.published_at.isoformat() if item.published_at else None,

            # Quality flag
            "has_transcript": item.has_transcript,
        })

    return signals
```

### C.3. UNCHANGED vs CHANGED Table

| UNCHANGED | CHANGED (Required) |
|-----------|--------------------|
| `_build_brand_snapshot(brand_id)` | Source of "signals" into synthesis (was: empty list, now: EvidenceBundle via adapter) |
| `_get_learning_summary_safe(brand_id)` | `_persist_opportunities()` - stores `evidence_ids` AND `why_now` in metadata JSONB |
| `graph_generate_opportunities(...)` | `_build_today_board_dto()` - reads `evidence_ids` AND `why_now` from metadata |
| All graph nodes and ordering | `OpportunityDTO` - **extended** to include `why_now`, `evidence_ids` (see Section F) |
| Prompt templates (no changes) | Schema - **additive**: new `ActivationRun` and `EvidenceItem` tables |
| Scoring rubric and thresholds | |
| Validation rules (INV-1, INV-2, INV-3) | |
| Dedup logic (`_filter_redundant_opportunities`) | |

**Summary of changes:**
1. Where signals come from (EvidenceBundle instead of empty list)
2. One adapter function to convert the format
3. Persistence updated to store evidence_ids AND why_now in metadata
4. DTO builder updated to read evidence_ids AND why_now from metadata
5. OpportunityDTO extended with required fields (see Section F)

### C.4. Evidence ID and why_now Traceability

**Persist evidence_ids AND why_now in Opportunity.metadata (JSONB)**

The existing `Opportunity` model has a `metadata` JSONB field. Both evidence traceability and the required `why_now` field are stored there (no new DB columns):

```python
# In _persist_opportunities():

opportunity = Opportunity.objects.update_or_create(
    id=deterministic_uuid5(brand_id, opp_hash),
    defaults={
        ...
        "metadata": {
            **existing_metadata,
            "evidence_ids": [str(eid) for eid in draft.evidence_ids],
            "why_now": draft.why_now,  # REQUIRED persisted contract
        },
    },
)
```

**Persist-time validation (REQUIRED):**
- `draft.why_now` must be non-empty and >= 10 characters (aligns with INV-2 rubric requiring concrete anchors)
- If `why_now` is missing, empty, or < 10 chars, the draft MUST be dropped (or the job fails with invariant violation)
- NO silent default is permitted - missing `why_now` is an implementation bug

**Reading evidence_ids and why_now for DTO:**
```python
# In _build_opportunity_dto():

def _build_opportunity_dto(opp: Opportunity) -> OpportunityDTO:
    metadata = opp.metadata or {}
    evidence_ids = metadata.get("evidence_ids", [])
    why_now = metadata.get("why_now")

    # Invariant enforcement at read-time
    if not why_now or len(why_now.strip()) < 10:
        raise ValueError("Invariant violation: persisted opportunity missing why_now")

    return OpportunityDTO(
        ...
        why_now=why_now,
        evidence_ids=[UUID(eid) for eid in evidence_ids],
        evidence_preview=_fetch_evidence_previews(evidence_ids) if evidence_ids else [],
    )
```

**Frontend contract compatibility:**
- `OpportunityDTO.evidence_ids` is populated from metadata at read-time
- `OpportunityDTO.why_now` is populated from metadata at read-time (not a DB column)
- `OpportunityDTO.evidence_preview` is derived from `EvidenceItem` rows via a read-time join (not stored redundantly)

### C.5. Mode Selection Rule (Deterministic)

| Trigger | Mode | Apify Calls |
|---------|------|-------------|
| Auto-generation (first visit, onboarding job) | `fixture_only` | None |
| Explicit regenerate (POST /regenerate/) | `live_cap_limited` | Yes, capped |
| GET /today/ | N/A (read-only) | Never |

This aligns with Sections D and G invariants:
- GET /today/ never directly executes Apify actors
- Auto-enqueued jobs run in fixture_only mode
- Only explicit user action triggers live runs

### C.6. Synthesis Pipeline (Structure)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      SYNTHESIS PIPELINE                                  │
│                                                                          │
│   EvidenceBundle + BrandSnapshotDTO + LearningSummary                    │
│          │                                                               │
│          ▼                                                               │
│   convert_evidence_bundle_to_signals()  ← NEW ADAPTER (pure, no LLM)     │
│          │                                                               │
│          ▼                                                               │
│   graph_generate_opportunities(snapshot, learning_summary, signals)      │
│          │                                      ↑ UNCHANGED              │
│          ▼                                                               │
│   node_generate_ideas (LLM)                 ← UNCHANGED                  │
│          │                                                               │
│          ▼                                                               │
│   node_score_opportunities (LLM)            ← UNCHANGED                  │
│          │                                                               │
│          ▼                                                               │
│   node_validate_opportunities               ← UNCHANGED                  │
│          │                                                               │
│          ▼                                                               │
│   _filter_invalid_opportunities             ← UNCHANGED                  │
│          │                                                               │
│          ▼                                                               │
│   _filter_redundant_opportunities           ← UNCHANGED                  │
│          │                                                               │
│          ▼                                                               │
│   _persist_opportunities                    ← UPDATED (stores evidence_ids + why_now)
│          │                                                               │
│          ▼                                                               │
│   OpportunityDTO[] → TodayBoardDTO          ← UPDATED (reads evidence_ids + why_now)
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### C.7. Invariants (Preserved)

| ID | Invariant | Status |
|----|-----------|--------|
| **INV-1** | Every opportunity MUST have `evidence_ids` referencing real evidence | PRESERVED (stored in metadata, validated on persist) |
| **INV-2** | `why_now` MUST contain concrete anchor (number, date, velocity) | PRESERVED (enforced at graph validation AND persist-time; metadata must contain `why_now` >= 10 chars) |
| **INV-3** | No stub/fake opportunities | PRESERVED (unchanged validation) |
| **INV-4** | Prompts receive signals in expected format | PRESERVED (adapter ensures compatibility) |

---

## D. Persistence + TodayBoard

### D.1. TodayBoard State Machine

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      TODAYBOARD STATE MACHINE                            │
│                                                                          │
│  ┌──────────────────┐                                                    │
│  │ not_generated_yet│ ─────── GET first time + snapshot exists ────────▶ │
│  └──────────────────┘         (auto-enqueue job)                         │
│           │                            │                                 │
│           │ GET (no snapshot)          ▼                                 │
│           ▼                   ┌──────────────┐                           │
│  ┌────────────────────────┐   │  generating  │ ◀── POST /regenerate/     │
│  │ insufficient_evidence  │   └──────────────┘                           │
│  │ (remediation shown)    │           │                                  │
│  └────────────────────────┘           │ job completes                    │
│           ▲                           ▼                                  │
│           │              ┌────────────┴────────────┐                     │
│           │              │                         │                     │
│           │              ▼                         ▼                     │
│           │      ┌─────────────┐          ┌─────────────────────────┐    │
│           │      │    ready    │          │ insufficient_evidence   │    │
│           │      │ (fresh/stale)│          │ (from failed gates)     │    │
│           │      └─────────────┘          └─────────────────────────┘    │
│           │              │                                               │
│           │              │ error during generation                       │
│           │              ▼                                               │
│           │      ┌─────────────┐                                         │
│           └───── │    error    │                                         │
│                  │(retry avail)│                                         │
│                  └─────────────┘                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### D.2. State Definitions

| State | Trigger | Response |
|-------|---------|----------|
| `not_generated_yet` | First GET, no board, snapshot exists | Enqueue job (fixture-only mode), return `{state, job_id}` |
| `generating` | Job running | Return `{state, job_id}` |
| `ready` | Board exists, valid | Return full TodayBoardDTO |
| `insufficient_evidence` | Evidence gates failed | Return `{state, remediation, shortfall}` |
| `error` | Job failed after retries | Return `{state, remediation}` |

### D.2.1. Onboarding Behavior

On first brand onboarding, TodayBoard is created in `generating` state and a background job is enqueued.

**CRITICAL:** This auto-enqueued job runs in **fixture-only mode** by default. It does NOT call Apify actors.

Apify-backed SourceActivation may only run when:
1. **Explicit user action** - User clicks "Regenerate" button (POST /regenerate/)
2. **Controlled policy gate** - A future admin-controlled setting allows spend

This ensures first-visit behavior never violates budget invariants.

### D.3. Database Tables

#### D.3.1. Existing Tables (REUSED)

| Table | Status | Notes |
|-------|--------|-------|
| `Opportunity` | REUSED | Evidence_ids stored in existing metadata JSONB field |
| `OpportunitiesBoard` | REUSED | No schema changes |
| `OpportunitiesJob` | REUSED | No schema changes |

#### D.3.2. New Tables (ADDITIVE)

**Schema changes are additive: we add `ActivationRun` and `EvidenceItem` tables; existing Opportunity tables remain unchanged.**

| Table | Purpose |
|-------|---------|
| `ActivationRun` | Tracks one SourceActivation execution |
| `EvidenceItem` | Stores normalized evidence from Apify |

```python
# kairo/hero/models.py (additions)

class ActivationRun(models.Model):
    """
    One execution of SourceActivation.

    Links to OpportunitiesJob. Tracks recipes executed, result counts, and estimated cost.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    job = models.ForeignKey(OpportunitiesJob, on_delete=models.CASCADE, related_name="activation_runs")
    brand_id = models.UUIDField()

    # Input snapshot
    seed_pack_json = models.JSONField()
    snapshot_id = models.UUIDField()

    # Execution
    recipes_selected = models.JSONField(default=list)  # ["IG-1", "IG-2"]
    recipes_executed = models.JSONField(default=list)

    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True)

    # Outcome
    item_count = models.PositiveIntegerField(default=0)
    items_with_transcript = models.PositiveIntegerField(default=0)

    # Budget tracking (see Section G.1.3)
    estimated_cost_usd = models.DecimalField(
        max_digits=6, decimal_places=4, default=0.0
    )  # Estimated Apify cost for this run

    class Meta:
        db_table = "hero_activation_run"


class EvidenceItem(models.Model):
    """
    Normalized evidence from SourceActivation.

    Immutable after creation. Referenced by Opportunity.evidence_ids.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    activation_run = models.ForeignKey(ActivationRun, on_delete=models.CASCADE, related_name="items")
    brand_id = models.UUIDField()

    # Source
    platform = models.CharField(max_length=50)
    actor_id = models.CharField(max_length=100)
    acquisition_stage = models.PositiveSmallIntegerField()
    recipe_id = models.CharField(max_length=20)

    # Content
    canonical_url = models.URLField(max_length=2000)
    external_id = models.CharField(max_length=255, blank=True)
    author_ref = models.CharField(max_length=255)
    title = models.CharField(max_length=500, blank=True)
    text_primary = models.TextField()
    text_secondary = models.TextField(blank=True)  # Transcript
    hashtags = models.JSONField(default=list)

    # Metrics
    view_count = models.BigIntegerField(null=True)
    like_count = models.BigIntegerField(null=True)
    comment_count = models.BigIntegerField(null=True)
    share_count = models.BigIntegerField(null=True)

    # Timestamps
    published_at = models.DateTimeField(null=True)
    fetched_at = models.DateTimeField()

    # Quality
    has_transcript = models.BooleanField(default=False)

    # Raw
    raw_json = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hero_evidence_item"
        indexes = [
            models.Index(fields=["brand_id", "created_at"]),
            models.Index(fields=["platform", "fetched_at"]),
        ]
```

#### D.3.3. Deprecated (TO BE REMOVED)

| Item | Status |
|------|--------|
| `_get_external_signals_safe()` | DEPRECATED, replaced by `get_or_create_evidence_bundle()` + `convert_evidence_bundle_to_signals()` |

### D.4. Caching

| Parameter | Value |
|-----------|-------|
| Cache backend | Redis |
| Cache key | `today_board:v2:{brand_id}` |
| TTL | 6 hours (21600 seconds) |
| Invalidation | On job completion or POST /regenerate/ |

---

## E. API Surface

### E.1. Endpoints

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/api/brands/{brand_id}/today/` | Read-only. Returns current state. May enqueue fixture-only job on first visit. **Never directly executes Apify actors or LLM synthesis inline.** |
| POST | `/api/brands/{brand_id}/today/regenerate/` | Enqueues job with Apify-backed SourceActivation (if budget allows). Returns job_id. |

**Clarification:** GET /today/ may enqueue a background job on first visit, but that job runs in fixture-only mode. Only POST /regenerate/ can trigger Apify spend.

#### E.1.1. Implementation Delta (Current vs Required)

| Aspect | Current Implementation | Required Behavior |
|--------|------------------------|-------------------|
| GET /today/ | May trigger inline LLM generation | Read-only; may enqueue fixture-only job on first visit |
| LLM synthesis | Can run inline during GET | Runs only in background jobs |
| Apify calls | Not implemented | Only via POST /regenerate/ with result caps |
| Evidence source | Returns empty signals list | Evidence from SourceActivation via adapter |

**This is a behavioral change.** The current codebase runs generation inline on GET; this PRD requires generation to happen exclusively in background jobs, with GET being read-only (except for enqueueing a fixture-only job on first visit).

### E.2. GET /today/ Response Examples

```json
// state: "ready"
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "snapshot": { "brand_name": "Acme", "positioning": "..." },
  "opportunities": [ { "id": "...", "title": "...", "why_now": "...", "evidence_ids": ["..."] } ],
  "meta": {
    "state": "ready",
    "ready_reason": "cache_hit",
    "generated_at": "2026-01-17T10:30:00Z",
    "opportunity_count": 8
  },
  "evidence_summary": { "item_count": 24, "platforms": ["instagram", "tiktok"] }
}

// state: "generating"
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "opportunities": [],
  "meta": { "state": "generating", "job_id": "abc-123" }
}

// state: "insufficient_evidence"
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "opportunities": [],
  "meta": {
    "state": "insufficient_evidence",
    "remediation": "Run BrandBrain compile to establish brand context.",
    "evidence_shortfall": { "required_items": 8, "found_items": 2 }
  }
}
```

### E.3. POST /regenerate/ Response

```json
{
  "status": "accepted",
  "job_id": "abc-123-def",
  "poll_url": "/api/brands/550e8400/today/"
}
```

---

## F. Frontend Contract

**NOTE: The current codebase DTOs differ from this specification. This PRD requires extending OpportunityDTO to include `why_now` and `evidence_ids` as required fields. This is a deliberate product requirement for evidence-grounded opportunity cards.**

### F.1. TodayBoardDTO (Backend → Frontend)

```python
class TodayBoardDTO(BaseModel):
    brand_id: UUID
    snapshot: BrandSnapshotDTO
    opportunities: list[OpportunityDTO] = []
    meta: TodayBoardMetaDTO
    evidence_summary: EvidenceSummaryDTO | None = None


class TodayBoardMetaDTO(BaseModel):
    state: Literal["not_generated_yet", "generating", "ready", "insufficient_evidence", "error"]
    ready_reason: Literal["fresh_generation", "cache_hit", "stale_cache_with_refresh_available"] | None = None
    job_id: str | None = None
    generated_at: datetime | None = None
    opportunity_count: int = 0
    remediation: str | None = None
    evidence_shortfall: EvidenceShortfallDTO | None = None


class OpportunityDTO(BaseModel):
    """
    Opportunity contract for frontend.

    REQUIRED EXTENSIONS (vs current codebase):
    - why_now: str (REQUIRED, evidence-grounded explanation; persisted in Opportunity.metadata JSONB, not a column)
    - evidence_ids: list[UUID] (REQUIRED, min_length=1, references EvidenceItem rows)
    - evidence_preview: list[EvidencePreviewDTO] (populated at read-time, not stored)

    PERSISTENCE SOURCE:
    - why_now and evidence_ids are stored in Opportunity.metadata JSONB (see Section C.4)
    - No new DB columns are added to the Opportunity model
    """
    id: UUID
    brand_id: UUID
    title: str
    angle: str
    why_now: str  # REQUIRED, evidence-grounded
    type: OpportunityType
    primary_channel: Channel
    suggested_channels: list[Channel] = []
    score: float
    evidence_ids: list[UUID]  # REQUIRED, min_length=1
    evidence_preview: list[EvidencePreviewDTO] = []  # Derived at read-time from EvidenceItem rows
    created_at: datetime
    updated_at: datetime


class EvidencePreviewDTO(BaseModel):
    """
    Lightweight preview of evidence for UI display.

    Derived at read-time from EvidenceItem rows. NOT stored redundantly in Opportunity.
    """
    id: UUID
    platform: str
    canonical_url: str
    author_ref: str
    text_snippet: str  # First 200 chars of text_primary
    has_transcript: bool
```

### F.2. State-to-UI Mapping

| State | UI Treatment |
|-------|--------------|
| `ready` | Render opportunities grid |
| `generating` | Show skeleton, poll every 2s |
| `not_generated_yet` | Show "Preparing..." spinner, poll |
| `insufficient_evidence` | Show empty state with remediation |
| `error` | Show error banner with retry button |

### F.3. Contract Authority

Backend DTOs (Pydantic) are the single source of truth. Frontend types are generated from OpenAPI.

---

## G. Performance + Budgets

### G.1. Spend Budget + Cap Controls

**We control Apify spend with two mechanisms:**
1. **Hard USD budgets** (daily + per-run) - policy guardrails
2. **Hard result caps** (actor input caps) - technical enforcement

Both are required. Caps without budgets allow unlimited runs. Budgets without caps allow expensive single runs.

**Project Budget Reality:**

| Metric | Value |
|--------|-------|
| **Total project budget** | $5.00 USD |
| **Remaining as of PRD date** | ~$2.77 USD |
| **Budget tracking method** | Policy constants + minimal ledger (not billing telemetry) |

The remaining amount is an **operator-configured constant**. We are NOT building runtime billing telemetry. Budget enforcement is done by **policy + caps**, not by trusting developers "to be careful."

**Result Caps (Technical Enforcement):**

Each Apify actor has native input fields that limit results:

| Actor | Cap Field | Our Limit | Actor Max |
|-------|-----------|-----------|-----------|
| `apify/instagram-scraper` | `resultsLimit` | 20 | 200 |
| `apify/instagram-reel-scraper` | `resultsLimit` | 5 | 200 |
| `clockworks/tiktok-scraper` | `resultsPerPage` | 15 | 1,000,000 |
| `apimaestro/linkedin-company-posts` | `limit` | 20 | 100 |
| `streamers/youtube-scraper` | `maxResults` | 10 | 999,999 |

These caps are enforced at the actor input level.

#### G.1.1. Budget Policy Constants

The following constants govern all Apify spend:

| Constant | Default Value | Description |
|----------|---------------|-------------|
| `APIFY_BUDGET_TOTAL_USD` | 5.00 | Total project budget (fixed) |
| `APIFY_BUDGET_REMAINING_USD` | 2.77 | Remaining budget as of 2026-01-19 (operator-managed) |
| `APIFY_DAILY_SPEND_CAP_USD` | 0.50 | Maximum spend per calendar day |
| `APIFY_PER_REGENERATE_CAP_USD` | 0.25 | Maximum spend per POST /regenerate/ execution |
| `APIFY_HARD_STOP_ON_EXHAUSTION` | true | If budget exhausted, block all Apify runs |

**Environment Configuration:**

```python
# These are environment-configurable values with the defaults above.
# Operators can adjust via env vars or Django settings.

APIFY_BUDGET_TOTAL_USD = float(os.environ.get("APIFY_BUDGET_TOTAL_USD", "5.00"))
APIFY_BUDGET_REMAINING_USD = float(os.environ.get("APIFY_BUDGET_REMAINING_USD", "2.77"))
APIFY_DAILY_SPEND_CAP_USD = float(os.environ.get("APIFY_DAILY_SPEND_CAP_USD", "0.50"))
APIFY_PER_REGENERATE_CAP_USD = float(os.environ.get("APIFY_PER_REGENERATE_CAP_USD", "0.25"))
APIFY_HARD_STOP_ON_EXHAUSTION = os.environ.get("APIFY_HARD_STOP_ON_EXHAUSTION", "true") == "true"
```

#### G.1.2. Per-Regenerate Execution Plan

A single `POST /regenerate/` executes at most:

| Step | Recipe(s) | Result Caps | Estimated Cost |
|------|-----------|-------------|----------------|
| 1 | IG-1 (Hashtag search) | Stage1: resultsLimit=20, Stage2: resultsLimit=5 | ~$0.08 |
| 2 | IG-3 (Search query) | Stage1: resultsLimit=20, Stage2: resultsLimit=5 | ~$0.08 |
| 3 | TT-1 (Hashtag search) | resultsPerPage=15 | ~$0.05 |
| **Total** | 2 IG recipes + 1 TT recipe | — | ~$0.21 (under $0.25 cap) |

**Execution Rules:**

1. **Instagram 2-stage law intact**: Each IG recipe executes Stage 1 → Filter → Stage 2. Stages are NEVER merged.
2. **Early-exit on evidence sufficiency**: If evidence gates are met (≥8 items, ≥30% transcripts) after Step 2, skip Step 3.
3. **Early-exit on budget exhaustion**: If per-run cap is reached, stop executing recipes.
4. **Recipe priority order**: IG-1 → IG-3 → TT-1 (Instagram prioritized for transcript richness).

**Transcript Quota Gate:**

```python
def should_continue_recipes(evidence_so_far: list[EvidenceItem]) -> bool:
    """
    Returns True if more recipes should execute.
    Returns False if evidence gates are already met (early-exit).
    """
    if len(evidence_so_far) >= 8:
        transcript_count = sum(1 for e in evidence_so_far if e.has_transcript)
        if transcript_count / len(evidence_so_far) >= 0.30:
            return False  # Gates met, stop executing
    return True
```

#### G.1.3. Daily Spend Guardrail

**Minimal Ledger Approach:**

Track daily spend in `ActivationRun` rows (no new tables):

```python
# In ActivationRun (existing model from Section D.3.2):
# Add field to track estimated cost per run

class ActivationRun(models.Model):
    # ... existing fields ...
    estimated_cost_usd = models.DecimalField(
        max_digits=6, decimal_places=4, default=0.0
    )


def get_daily_spend(date: date = None) -> Decimal:
    """
    Sum estimated_cost_usd for all ActivationRuns on the given date.
    """
    target_date = date or timezone.now().date()
    return (
        ActivationRun.objects
        .filter(started_at__date=target_date)
        .aggregate(total=Sum("estimated_cost_usd"))["total"]
        or Decimal("0.00")
    )


def is_daily_cap_reached() -> bool:
    """Check if daily spend cap has been reached."""
    return get_daily_spend() >= Decimal(str(APIFY_DAILY_SPEND_CAP_USD))
```

**When Daily Cap is Reached:**

If `POST /regenerate/` is called when daily cap is reached:

1. Job is accepted (HTTP 202)
2. Job transitions immediately to `insufficient_evidence` state
3. Board remediation message: `"Daily budget cap reached. Try again tomorrow."`
4. No Apify calls are made

```python
# In job executor:
if is_daily_cap_reached():
    return complete_job_insufficient_evidence(
        job_id=job.id,
        remediation="Daily budget cap reached. Try again tomorrow.",
        shortfall=EvidenceShortfallDTO(
            required_items=8,
            found_items=0,
            reason="budget_exhausted",
        ),
    )
```

**When Per-Run Cap is Reached:**

If estimated cost during execution reaches per-run cap:

1. Stop executing remaining recipes
2. Use evidence collected so far
3. Proceed to synthesis if evidence gates met
4. Otherwise, `insufficient_evidence` with reason `"per_run_budget_exhausted"`

### G.2. Execution Invariants

**CRITICAL INVARIANTS:**

| ID | Invariant | Enforcement |
|----|-----------|-------------|
| **INV-G1** | GET /today/ never directly executes Apify actors or inline LLM synthesis | GET is read-only; may enqueue fixture-only job on first visit |
| **INV-G2** | Apify-backed SourceActivation may only run via POST /regenerate/ | Mode selection rule (Section C.5) |
| **INV-G3** | Auto-enqueued jobs (first visit) run in fixture-only mode | Default mode is `fixture_only` |
| **INV-G4** | LLM synthesis runs only in background jobs, never inline during GET | Job executor owns synthesis |
| **INV-G5** | Only POST /regenerate/ may trigger Apify spend | No other UI path, no GET path, no scheduled job spends |
| **INV-G6** | First-visit/onboarding jobs run fixture-only and never spend | `mode=fixture_only` is mandatory default |
| **INV-G7** | If budget exhausted (per-run or daily), system degrades deterministically | Returns `insufficient_evidence` with budget-specific remediation |
| **INV-G8** | CI tests must never call Apify | `SOURCEACTIVATION_FIXTURE_MODE=true` in CI |

### G.3. Fixture-Only Mode (Mandatory for CI + Default for Onboarding)

**Fixture mode is the primary execution path for most scenarios.**

| Scenario | Mode | Apify Calls | Fixture Mode |
|----------|------|-------------|--------------|
| CI tests | `fixture_only` | Never | **MANDATORY** |
| Local development | `fixture_only` (default) | Never (unless opted in) | Default |
| First visit / onboarding | `fixture_only` | Never | **MANDATORY** |
| POST /regenerate/ | `live_cap_limited` | Yes, capped | Not used |

**Enforcement:**

```python
# Environment variable controls mode
SOURCEACTIVATION_FIXTURE_MODE = os.environ.get("SOURCEACTIVATION_FIXTURE_MODE", "true") == "true"

# CI: Always true (set in CI config)
# Local: True by default; developer must explicitly set "false" for live runs
# Production: False only for POST /regenerate/ jobs

def get_execution_mode(trigger: str) -> Literal["fixture_only", "live_cap_limited"]:
    """
    Determine execution mode based on trigger source.

    Args:
        trigger: "first_visit", "onboarding", "regenerate", "ci"

    Returns:
        Execution mode
    """
    if SOURCEACTIVATION_FIXTURE_MODE:
        return "fixture_only"  # Override all to fixture

    if trigger in ("first_visit", "onboarding", "ci"):
        return "fixture_only"  # MANDATORY fixture for these

    if trigger == "regenerate":
        return "live_cap_limited"  # Only regenerate can go live

    return "fixture_only"  # Default safe
```

**Fixture Loading:**

```python
if mode == "fixture_only":
    # Load pre-recorded Apify responses from fixtures/
    # No actual Apify calls
    # Zero budget spend
    # Zero cost recorded
    return load_fixture_bundle(brand_id, seed_pack)
```

**MANDATORY:** All CI tests use fixture mode. No Apify calls in tests. Ever.

### G.4. Time Budgets

| Operation | Hard Cap | Fail Behavior |
|-----------|----------|---------------|
| Total job time | 120s | Fail job, create error board |
| SourceActivation | 60s | Use partial results |
| Per-actor timeout | 30s | Skip actor, continue |
| LLM synthesis | 30s | Fail job |
| GET /today/ | 500ms | Return cached state |

### G.5. Evidence Quality Gates

| Gate | Threshold | Failure Mode |
|------|-----------|--------------|
| Total items | ≥ 8 | `insufficient_evidence` |
| Items with text | ≥ 6 | `insufficient_evidence` |
| Transcript coverage | ≥ 30% | `insufficient_evidence` |
| Platform diversity | ≥ 1 from {instagram, tiktok} | `insufficient_evidence` |
| Freshness | ≥ 1 item < 7 days old | `insufficient_evidence` |

---

## H. Test Plan

### H.1. Unit Tests

| Test | Validates |
|------|-----------|
| `test_derive_seed_pack_from_snapshot` | SeedPack derivation is deterministic |
| `test_recipe_input_includes_result_limit` | Recipe input builder sets correct limit field |
| `test_stage1_to_stage2_filter_produces_urls` | Filter derives valid URLs from stage 1 |
| `test_evidence_normalization` | All actor outputs normalize to EvidenceItem |
| `test_seedpack_contains_no_evidence` | SeedPack has no scraped content, URLs, or evidence |

### H.2. Integration Tests

| Test | Validates |
|------|-----------|
| `test_instagram_2stage_execution` | Stage 2 inputs derived from Stage 1 outputs |
| `test_tiktok_singlestage_execution` | Single stage returns full content |
| `test_synthesis_receives_evidence_bundle` | Evidence bundle wired correctly to synthesis |
| `test_opportunity_evidence_ids_valid` | All `evidence_ids` reference real EvidenceItem rows |

### H.3. Contract Tests

| Test | Validates |
|------|-----------|
| `test_todayboard_dto_matches_openapi` | Response matches generated types |
| `test_opportunity_dto_evidence_ids_required` | `evidence_ids` cannot be empty |
| `test_opportunity_dto_why_now_required` | `why_now` cannot be empty |

### H.4. Result Cap Tests

| Test | Validates |
|------|-----------|
| `test_result_limit_enforced_in_input` | Actor inputs include correct limit fields |
| `test_fixture_mode_no_apify_calls` | Fixture mode makes no Apify calls |
| `test_stage2_inputs_derived_from_stage1` | Instagram Stage 2 URLs come from Stage 1 output |

### H.5. Behavior Delta Tests

| Test | Validates |
|------|-----------|
| `test_get_today_is_read_only` | GET does not trigger inline LLM synthesis |
| `test_get_today_enqueues_fixture_job_on_first_visit` | First visit enqueues job in fixture-only mode |
| `test_regenerate_triggers_live_mode` | POST /regenerate/ enqueues job with live_cap_limited mode |

### H.6. Budget Tests

| Test | Validates |
|------|-----------|
| `test_daily_cap_blocks_regenerate` | POST /regenerate/ returns insufficient_evidence when daily cap reached |
| `test_per_run_cap_stops_recipes` | Recipe execution stops when per-run cap is reached |
| `test_budget_constants_configurable` | Policy constants can be set via environment variables |
| `test_activation_run_tracks_estimated_cost` | ActivationRun.estimated_cost_usd is populated after execution |
| `test_first_visit_never_spends` | First visit jobs run fixture-only and record $0 cost |
| `test_only_regenerate_can_spend` | Only POST /regenerate/ path can trigger Apify calls |

---

## I. PR Execution Plan

This plan is a direct execution map of PRD v3.5. No redesign, no reinterpretation.

### I.0. Critical Warning

**The current backend regenerates on GET /today/.**

PRD v3.5 explicitly forbids this (INV-G1). GET must be read-only and generation must occur only in background jobs. If this is not fixed early, all downstream work becomes invalid.

### I.1. PR-0 — Baseline + Guardrails (Preparation)

**Goal:** Make it impossible to violate PRD invariants accidentally.

**Changes:**
- Introduce feature flags / config toggles:
  - `TODAY_GET_READ_ONLY = true`
  - `SOURCEACTIVATION_MODE_DEFAULT = "fixture_only"`
  - `APIFY_ENABLED = false` (default)
- Add a single invariants test module that will be extended in later PRs.

**Acceptance Criteria:**
- CI proves:
  - No Apify calls are possible by default.
  - No live acquisition paths are reachable without explicit enablement.
- Existing system can still run unchanged when flags are disabled.

**Status:** Optional but recommended.

### I.2. PR-1 — Make GET /today Read-Only + Move Generation to Jobs

**Goal:** Align runtime behavior with Sections E and G of the PRD before wiring SourceActivation.

**Changes:**
- GET /today/:
  - Returns existing TodayBoard if present.
  - If no board exists and a snapshot exists:
    - Enqueue a fixture-only background job.
    - Return `state = generating`.
  - Never executes LLMs inline.
- POST /today/regenerate/:
  - Enqueues a background job.
  - Does not run synthesis inline.
- Confirm / introduce a job runner path that is the only place where:
  - LLM synthesis runs.
  - SourceActivation is executed.

**Acceptance Criteria:**
- Unit test: GET /today never calls graph or LLM.
- Unit test: POST /regenerate enqueues a job and returns immediately.
- Integration test:
  - First GET returns `generating`.
  - Subsequent poll returns `ready` after job completion.

**If this PR slips, all subsequent PRs are invalid.**

### I.3. PR-2 — DTO + Persistence Extensions (why_now, evidence_ids)

**Goal:** Enforce the Phase-0 → UI contract in code.

**Changes:**
- Extend OpportunityDTO:
  - `why_now` (required)
  - `evidence_ids` (required, min length = 1)
  - `evidence_preview` (derived at read-time)
- Update `_persist_opportunities()`:
  - Persist `metadata.evidence_ids`
  - Persist `metadata.why_now`
  - Enforce persist-time validation (drop invalid drafts; no silent defaults)
- Update DTO builder:
  - Read fields from metadata.
  - Raise on invariant violation.

**Acceptance Criteria:**
- Opportunities missing `why_now` or `evidence_ids` cannot be returned in ready state.
- TodayBoard rendering still works (fixtures acceptable at this stage).

### I.4. PR-3 — Add SourceActivation Tables (Schema Additive)

**Goal:** Prepare storage for evidence and budget tracking.

**Changes:**
- Add models + migrations:
  - `ActivationRun` (includes `estimated_cost_usd`)
  - `EvidenceItem`
- Add indexes matching expected query patterns (brand, time, platform).

**Acceptance Criteria:**
- Migrations apply cleanly.
- CRUD operations work.
- Batch join for evidence preview queries is performant.

### I.5. PR-4 — SourceActivation (Fixture-Only) End-to-End

**Goal:** Wire the full new data path without any Apify usage.

**Changes:**
- Implement `derive_seed_pack()`.
- Implement `get_or_create_evidence_bundle(..., mode="fixture_only")`:
  - Load fixtures.
  - Write `ActivationRun`.
  - Write `EvidenceItem` rows.
  - Return `EvidenceBundle`.
- Implement `convert_evidence_bundle_to_signals()` adapter.
- Wire SourceActivation inside job execution, replacing `_get_external_signals_safe()`.

**Acceptance Criteria:**
- Job execution produces:
  - One `ActivationRun`.
  - Multiple `EvidenceItem` rows.
- Opportunity drafts include:
  - `evidence_ids`
  - `why_now`
- Opportunities persist metadata correctly.
- TodayBoard returns populated `OpportunityDTO`.
- Deterministic behavior:
  - Same fixtures → same evidence IDs → same outputs.

### I.6. PR-5 — Evidence Preview Read-Time Join + UI Stability

**Goal:** Make evidence previews real and stable.

**Changes:**
- Implement `_fetch_evidence_previews(evidence_ids)`:
  - Batch query `EvidenceItem`.
  - Map to preview DTO.
  - Preserve ordering of `evidence_ids`.
- Ensure API response exactly matches frontend contract.

**Acceptance Criteria:**
- API response includes:
  - Preview snippets.
  - Transcript presence flags.
- No N+1 queries.
  - One batch query per TodayBoard response.

### I.7. PR-6 — Live-Cap-Limited Apify Path (POST /regenerate Only)

**Goal:** Enable real acquisition without exceeding remaining ~$2.77 budget.

**Changes:**
- Central Apify client wrapper:
  - Enforces actor result caps at input-build time.
  - Enforces per-run spend cap ($0.25).
  - Enforces daily cap ($0.50) via sum of `ActivationRun.estimated_cost_usd`.
  - Hard stop on exhaustion.
- Implement recipe execution:
  - Instagram 2-stage law (IG-1 → IG-3).
  - TikTok TT-1.
  - Early exits on sufficiency or budget exhaustion.
- Restrict `mode="live_cap_limited"` to POST /regenerate only.

**Acceptance Criteria:**
- Tests prove:
  - GET /today never spends.
  - Onboarding jobs are fixture-only.
  - Regenerate enforces caps and degrades deterministically.
- One real run produces transcripts where expected (Instagram stage 2).

### I.8. PR-7 — Hardening (UI-Decider Reliability)

**Goal:** Ensure the UI behaves predictably under real usage.

**Changes:**
- Redis caching for TodayBoard.
- Polling guidance + server-side throttles.
- Basic rate limiting for regenerate.
- Clear state transitions and error surfaces.

**Acceptance Criteria:**
- UI does not thrash or trigger accidental regen loops.
- Repeated GET /today calls are cheap and stable.

### I.9. Strict Execution Order

| Order | PR | Description | Blocking? |
|-------|-----|-------------|-----------|
| 0 | PR-0 | Baseline + Guardrails | Optional |
| 1 | **PR-1** | GET read-only + jobs | **BLOCKING** |
| 2 | PR-2 | DTO + persistence invariants | Required |
| 3 | PR-3 | Schema (additive) | Required |
| 4 | PR-4 | SourceActivation (fixture-only) | Required |
| 5 | PR-5 | Evidence preview join | Required |
| 6 | PR-6 | Apify live path + budgets | Required |
| 7 | PR-7 | Hardening | Required |

**PR-1 is the gate.** If it slips, all subsequent PRs are invalid.

### I.10. UI Decider (Non-Negotiable)

The UI test fails for exactly two reasons:

1. **GET /today still regenerates** (flicker, cost bleed, nondeterminism).
2. **Evidence fields are missing or inconsistent** (`why_now`, previews, IDs).

This plan fixes (1) first (PR-1) and enforces (2) before live acquisition (PR-2 through PR-5).

---

## Self-Check Checklist

| Requirement | Status |
|-------------|--------|
| Structure matches A-I sections exactly | ✅ |
| No forbidden names (Hero, external_signals, NormalizedEvidenceItem, BrandBrainEvidence) | ✅ |
| Instagram 2-stage explicitly documented (Section B.2.1) | ✅ |
| Instagram 2-stage is MANDATORY (hard rules listed) | ✅ |
| Stage 2 inputs MUST be derived from Stage 1 outputs only | ✅ |
| TikTok/LinkedIn/YouTube explicitly marked as single-stage, semantically rich | ✅ |
| Phase 0 bridge shown (Section C.1) | ✅ |
| Upstream (SourceActivation) is new, downstream (synthesis) is refactored | ✅ |
| Cost control via result caps + USD policy constants (Section G.1) | ✅ |
| Replay via fixtures documented (Section G.3) | ✅ |
| EvidenceItem is first-class artifact (Section B.5) | ✅ |
| SourceActivation outputs evidence only, no opportunity semantics | ✅ |
| SourceActivation does NOT make LLM calls | ✅ |
| No speculative prose, no "future ideas" | ✅ |
| Onboarding-triggered generation does not trigger Apify calls | ✅ |
| GET /today/ never directly executes Apify actors | ✅ |
| SourceActivation defined as NEW system (Section B.0) | ✅ |
| Terminology & Ownership table present (Section B.0.1) | ✅ |
| Ownership boundaries explicit (Section B.0.2) | ✅ |
| Forbidden terms listed (Section B.0.3) | ✅ |
| Data Flow Law documented (Section B.0.4) | ✅ |
| SeedPack does NOT contain scraped content, URLs, evidence, or opportunity semantics | ✅ |
| No PRD structure changes occurred | ✅ |
| **Engine Bridge Lock** | |
| Call graph BEFORE vs AFTER documented (Section C.1) | ✅ |
| Exact splice point identified (`_get_external_signals_safe` → new seams) | ✅ |
| Only two seams introduced (C.2.1 + C.2.2) | ✅ |
| `get_or_create_evidence_bundle` signature defined | ✅ |
| `convert_evidence_bundle_to_signals` signature defined (pure, deterministic) | ✅ |
| UNCHANGED vs CHANGED table present (Section C.3) | ✅ |
| Evidence ID traceability path specified (metadata JSONB) | ✅ |
| Mode selection rule documented (Section C.5) | ✅ |
| No prompts rewritten | ✅ |
| Adapter adds no opportunity semantics | ✅ |
| **Consistency Repair (v3.3)** | |
| OpportunityDTO extension explicitly required (`why_now`, `evidence_ids`) | ✅ |
| DTO differences from current codebase acknowledged (Section F note) | ✅ |
| Schema changes described as additive (not "no changes") | ✅ |
| Evidence traceability consistent end-to-end (metadata → DTO read-time) | ✅ |
| SA-5 references centralized client wrapper with caps (not budget tracker) | ✅ |
| Cap field names consistent between B.2.x and G.1 | ✅ |
| GET behavior delta explicitly documented (Section E.1.1) | ✅ |
| GET never triggers inline LLM synthesis (Section G.2) | ✅ |
| **Step 4 Completion (v3.4)** | |
| `why_now` persisted in Opportunity.metadata JSONB (not a column) | ✅ |
| `why_now` read-path specified in `_build_opportunity_dto()` | ✅ |
| Persist-time validation: `why_now` >= 10 chars, no silent default | ✅ |
| INV-2 enforced at both graph validation AND persist-time | ✅ |
| **Budget Reality Lock (v3.5)** | |
| Section G explicitly states $5 total and ~$2.77 remaining | ✅ |
| Per-run USD cap is explicit and conservative ($0.25) | ✅ |
| Daily USD cap is explicit and conservative ($0.50) | ✅ |
| Result caps remain present and mapped to actor input fields | ✅ |
| POST /regenerate/ is the only Apify spend path (INV-G5) | ✅ |
| GET /today/ never spends and never runs inline LLM (INV-G1) | ✅ |
| Fixture-only mode is mandatory for CI and default for onboarding (G.3) | ✅ |
| Budget exhaustion behavior is deterministic and documented (G.1.3) | ✅ |
| **PR Execution Plan (Section I)** | |
| Critical warning about current GET behavior included | ✅ |
| PR-1 (GET read-only) identified as blocking gate | ✅ |
| Strict execution order defined (PR-0 through PR-7) | ✅ |
| Each PR has explicit goal, changes, and acceptance criteria | ✅ |
| UI Decider failure reasons documented | ✅ |

---

*End of Specification*
