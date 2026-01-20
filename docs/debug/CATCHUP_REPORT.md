# CATCHUP_REPORT.md

> **Generated:** 2026-01-18
> **Branch:** `brandbrain-pr7`
> **Purpose:** Eliminate "context rot" by reconstructing the real current state of the codebase

---

## Preface: Purpose of This Report

This report reconstructs the real current state of the Kairo codebase, specifically around:
1. Apify actor input/output schemas
2. Evidence ingestion and normalization
3. The relationship between BrandBrain and Hero
4. What the PRD says vs. what actually exists

**Key discovery:** There are **two entirely separate evidence systems** in the codebase that do not communicate with each other.

---

## 1. Repo Findings: File Paths + Summaries

### A. Apify Actor Infrastructure (BrandBrain)

| File | Purpose | Key Symbols |
|------|---------|-------------|
| `kairo/brandbrain/actors/registry.py` | Actor registry with 7 actors (6 validated) | `ActorSpec`, `ACTOR_REGISTRY`, `get_actor_spec()` |
| `kairo/brandbrain/actors/inputs.py` | Input builders per actor | `build_instagram_posts_input()`, `build_tiktok_profile_videos_input()`, etc. |
| `kairo/brandbrain/normalization/adapters.py` | Output normalization adapters | `normalize_instagram_post()`, `normalize_tiktok_video()`, etc. |
| `kairo/brandbrain/normalization/service.py` | Normalization orchestration | `normalize_apify_run()` |
| `kairo/brandbrain/ingestion/service.py` | End-to-end ingestion | `ingest_source()`, `reuse_cached_run()` |
| `kairo/brandbrain/identifiers.py` | Platform-specific identifier normalization | `normalize_source_identifier()` |
| `kairo/integrations/apify/client.py` | Apify API client | `ApifyClient`, `start_actor_run()`, `poll_run()`, `fetch_dataset_items()` |
| `kairo/integrations/apify/models.py` | Run tracking models | `ApifyRun`, `RawApifyItem` |
| `var/apify_samples/` | Sample actor outputs (6 actor directories) | JSON files from real actor runs |
| `tests/helpers/apify_samples.py` | Test helpers for loading samples | `load_sample()`, `list_sample_dirs()` |

### B. BrandBrain Evidence Models

| File | Purpose | Key Models |
|------|---------|------------|
| `kairo/brandbrain/models.py` | All BrandBrain models | `SourceConnection`, `NormalizedEvidenceItem`, `EvidenceBundle`, `FeatureReport`, `BrandBrainCompileRun`, `BrandBrainSnapshot`, `BrandBrainJob` |
| `kairo/brandbrain/bundling/service.py` | Evidence bundling | `create_evidence_bundle()`, `create_feature_report()` |
| `kairo/brandbrain/compile/service.py` | Compile orchestration | `compile_brandbrain()`, `check_compile_gating()` |
| `kairo/brandbrain/compile/worker.py` | Background compile execution | `execute_compile_job()` |
| `kairo/brandbrain/jobs/queue.py` | Durable job queue | `enqueue_compile_job()`, `claim_next_job()` |

### C. Ingestion Pipeline (Separate System)

| File | Purpose | Key Models |
|------|---------|------------|
| `kairo/ingestion/models.py` | Trend/discovery evidence models | `Surface`, `CaptureRun`, `EvidenceItem`, `Cluster`, `NormalizedArtifact`, `ArtifactClusterLink`, `ClusterBucket`, `TrendCandidate` |
| `kairo/ingestion/services/trend_emitter.py` | Trend → TrendSignalDTO conversion | `get_external_signal_bundle()` |
| `kairo/ingestion/capture/adapters/` | Scrapers for TikTok discover, Reddit rising | `tiktok_discover.py`, `reddit_rising.py` |

### D. Hero App

| File | Purpose | Key Symbols |
|------|---------|-------------|
| `kairo/hero/engines/opportunities_engine.py` | TodayBoard generation | `generate_today_board()`, `_build_brand_snapshot()` |
| `kairo/hero/services/today_service.py` | Thin wrapper | `get_today_board()`, `regenerate_today_board()` |
| `kairo/hero/services/external_signals_service.py` | External signals bundle | `get_bundle_for_brand()` |
| `kairo/hero/dto.py` | All DTOs | `TodayBoardDTO`, `OpportunityDTO`, `TrendSignalDTO`, `ExternalSignalBundleDTO` |
| `kairo/hero/graphs/opportunities_graph.py` | LLM-based opportunity generation | `graph_hero_generate_opportunities()` |

---

## 2. What Exists vs What's Missing

| Component | Status | Details |
|-----------|--------|---------|
| **ActorRegistry** | ✅ Exists | 7 actors defined (6 validated, 1 behind feature flag) |
| **Actor Input Schemas** | ✅ Exists | Per-actor input builders in `actors/inputs.py` |
| **Actor Output Normalization** | ✅ Exists | Per-actor adapters in `normalization/adapters.py` |
| **NormalizedEvidenceItem (BrandBrain)** | ✅ Exists | Full model with dedupe, raw_refs, flags_json |
| **EvidenceBundle** | ✅ Exists | Deterministic selection with caps |
| **FeatureReport** | ✅ Exists | Stats extraction (emoji density, CTA freq, etc.) |
| **BrandBrainCompileRun** | ✅ Exists | Full lifecycle tracking |
| **BrandBrainSnapshot** | ✅ Exists | Final compiled output storage |
| **BrandBrainJob (Durable Queue)** | ✅ Exists | Atomic locking, retry, heartbeat |
| **Source Activation** | ✅ Exists | `ingest_source()` with TTL freshness checks |
| **EvidenceItem (Ingestion)** | ✅ Exists | **SEPARATE** from NormalizedEvidenceItem |
| **TrendCandidate → TrendSignalDTO** | ✅ Exists | Via `trend_emitter.py` |
| **Hero ↔ BrandBrain Connection** | ❌ **MISSING** | Hero does NOT read BrandBrainSnapshot |
| **Hero ↔ NormalizedEvidenceItem Connection** | ❌ **MISSING** | Hero reads via ingestion, not BrandBrain |
| **OpportunitiesBoard State Machine** | ❌ **MISSING** | No TodayBoardState enum exists |
| **OpportunitiesJob** | ❌ **MISSING** | No durable job queue for opportunities |
| **ready_reason Field** | ❌ **MISSING** | Not in any model |
| **MIN_EVIDENCE_ITEMS Gate** | ❌ **MISSING** | No evidence quality gate in Hero |
| **LLM Compile (BrandBrain)** | ❌ Stubbed | Returns hardcoded stub in `worker.py` |
| **QA Checks (BrandBrain)** | ❌ Stubbed | Returns stub report |

---

## 3. Actor Schema Snapshot

### A. Actor Registry (7 Actors)

| Actor ID | Platform | Capability | Validated | Feature Flag |
|----------|----------|------------|-----------|--------------|
| `apify~instagram-scraper` | Instagram | posts | ✅ | None |
| `apify~instagram-reel-scraper` | Instagram | reels | ✅ | None |
| `apimaestro~linkedin-company-posts` | LinkedIn | company_posts | ✅ | None |
| `apimaestro~linkedin-profile-posts` | LinkedIn | profile_posts | ⚠️ | `BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS` |
| `clockworks~tiktok-scraper` | TikTok | profile_videos | ✅ | None |
| `streamers~youtube-scraper` | YouTube | channel_videos | ✅ | None |
| `apify~website-content-crawler` | Web | crawl_pages | ✅ | None |

### B. Input Schemas (Per Actor)

#### Instagram Posts (`apify~instagram-scraper`)
```json
{
  "directUrls": ["<profile_url>"],
  "resultsType": "posts",
  "resultsLimit": "<cap>",
  "addParentData": false
}
```

#### Instagram Reels (`apify~instagram-reel-scraper`)
```json
{
  "username": ["<profile_url_or_username>"],
  "resultsLimit": "<cap>",
  "includeTranscript": true,
  "includeSharesCount": false,
  "includeDownloadedVideo": false,
  "skipPinnedPosts": true
}
```

#### TikTok Profile Videos (`clockworks~tiktok-scraper`)
```json
{
  "profiles": ["<handle_without_@>"],
  "profileSorting": "latest",
  "resultsPerPage": "<cap>",
  "excludePinnedPosts": true,
  "profileScrapeSections": ["videos"]
}
```

#### YouTube Channel Videos (`streamers~youtube-scraper`)
```json
{
  "startUrls": [{"url": "<channel_url>"}],
  "maxResults": "<cap>",
  "maxResultsShorts": 0,
  "maxResultsStreams": 0
}
```

#### LinkedIn Company Posts (`apimaestro~linkedin-company-posts`)
```json
{
  "sort": "recent",
  "limit": "<cap>",
  "company_name": "<company_slug>"
}
```

#### Web Crawl (`apify~website-content-crawler`)
```json
{
  "startUrls": [{"url": "<url>"}],
  "maxCrawlDepth": 1,
  "maxCrawlPages": "<cap>"
}
```

### C. Output Schema (NormalizedEvidenceItem)

All actors normalize to this common structure:

```python
{
    "platform": str,           # instagram|linkedin|tiktok|youtube|web
    "content_type": str,       # post|reel|text_post|short_video|video|web_page
    "external_id": str | None,
    "canonical_url": str,
    "published_at": datetime | None,
    "author_ref": str,
    "title": str | None,
    "text_primary": str,       # caption/body/title
    "text_secondary": str | None,  # description/transcript
    "hashtags": list[str],
    "metrics_json": dict,      # likes, comments, views, etc.
    "media_json": dict,        # type, duration, thumbnails, etc.
    "flags_json": dict         # has_transcript, is_low_value, is_collection_page
}
```

### D. Sample Data Location

```
var/apify_samples/
├── apify_instagram-scraper/       (2 runs, 3+ items)
├── apify_instagram-reel-scraper/  (1 run)
├── apimaestro_linkedin-company-posts/  (1 run, 3 items)
├── clockworks_tiktok-scraper/     (1 run)
├── streamers_youtube-scraper/     (1 run)
└── apify_website-content-crawler/ (2 runs)
```

---

## 4. Implications for PRD

### A. Critical Misalignment: Two Evidence Systems

**The PRD (and previous session context) assumed:**
- Hero reads from `NormalizedEvidenceItem` (BrandBrain)
- Evidence gates enforce MIN_EVIDENCE_ITEMS
- TodayBoard has a state machine with `ready_reason`

**Reality in code:**
- Hero reads from `TrendCandidate` → `EvidenceItem` (Ingestion module)
- BrandBrain's `NormalizedEvidenceItem` is **completely separate**
- No evidence gates exist in Hero
- No TodayBoardState or ready_reason exists

### B. Evidence Flow Diagram (Actual)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BRANDBRAIN SYSTEM                            │
│  (Brand-specific content from their own channels)                   │
├─────────────────────────────────────────────────────────────────────┤
│  SourceConnection (brand's IG/TikTok/YouTube/LinkedIn handles)      │
│         ↓                                                           │
│  ingest_source() → ApifyRun → RawApifyItem                         │
│         ↓                                                           │
│  normalize_apify_run() → NormalizedEvidenceItem                    │
│         ↓                                                           │
│  create_evidence_bundle() → EvidenceBundle + FeatureReport         │
│         ↓                                                           │
│  [STUB] LLM Compile → BrandBrainSnapshot                           │
│         ↓                                                           │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ OUTPUT: BrandBrainSnapshot.snapshot_json                       │ │
│  │ (brand voice, positioning, tone from their OWN content)        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│         ↓                                                           │
│  ❌ NOT CONNECTED TO HERO                                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION SYSTEM                             │
│  (Platform-wide trending content discovery)                         │
├─────────────────────────────────────────────────────────────────────┤
│  Surface (TikTok discover, Reddit rising, etc.)                     │
│         ↓                                                           │
│  CaptureRun → EvidenceItem (raw scraped items)                     │
│         ↓                                                           │
│  NormalizedArtifact → ArtifactClusterLink → Cluster                │
│         ↓                                                           │
│  ClusterBucket (time-windowed aggregation)                         │
│         ↓                                                           │
│  TrendCandidate (when cluster exceeds thresholds)                  │
│         ↓                                                           │
│  trend_emitter.py → TrendSignalDTO                                 │
└─────────────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────────────┐
│                          HERO SYSTEM                                │
├─────────────────────────────────────────────────────────────────────┤
│  external_signals_service.get_bundle_for_brand()                   │
│         ↓                                                           │
│  ExternalSignalBundleDTO (trends from Ingestion)                   │
│         ↓                                                           │
│  _build_brand_snapshot() ← Brand model (NOT BrandBrainSnapshot!)   │
│         ↓                                                           │
│  graph_hero_generate_opportunities() (LLM)                         │
│         ↓                                                           │
│  Opportunity rows (persisted to DB)                                │
│         ↓                                                           │
│  TodayBoardDTO                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### C. Sections of PRD That Are Wrong/Misleading

1. **Any reference to PR0/PR1/PR1.1 for Opportunities:**
   - These PRs do NOT exist in the codebase
   - There is no `OpportunitiesBoard` state machine
   - There is no `OpportunitiesJob` durable queue
   - There is no `ready_reason` field
   - There is no `MIN_EVIDENCE_ITEMS` gate

2. **"Evidence gates" for Hero:**
   - No evidence quality gates exist in Hero
   - BrandBrain has gating (Tier0 fields + ≥1 enabled source), but Hero doesn't use it

3. **"BrandBrain compile produces NormalizedEvidenceItem for Hero":**
   - FALSE. BrandBrain produces `BrandBrainSnapshot` (brand voice/positioning)
   - Hero uses `TrendSignalDTO` from the separate Ingestion system
   - These are fundamentally different data:
     - BrandBrain evidence = brand's OWN content (their IG posts, their YouTube videos)
     - Ingestion evidence = TRENDING content across platforms (discover feeds, rising posts)

4. **Source Activation Strategy:**
   - BrandBrain source activation EXISTS and works
   - BUT it's for the brand's own channels, not for opportunity discovery
   - Opportunity discovery comes from the Ingestion system's Surface→TrendCandidate pipeline

---

## 5. Prereqs for Rewriting PR Map

Before the PRD can be rewritten, these clarifications are needed:

### A. Architectural Decision Required

**Question:** Should Hero read brand context from BrandBrainSnapshot or continue using Brand model directly?

| Option | Pros | Cons |
|--------|------|------|
| **A: Wire Hero → BrandBrainSnapshot** | Evidence-backed brand voice, richer context | Compile must succeed first, adds dependency |
| **B: Keep Hero → Brand model** | Simpler, no new dependency | Miss evidence-based insights |

### B. Evidence Sources for Opportunities

**Question:** What evidence feeds opportunity generation?

Currently:
- **Ingestion system** (TrendCandidate) → TrendSignalDTO → opportunities

Should it also include:
- **BrandBrain** NormalizedEvidenceItem? (competitor posts, industry trends)
- If so, how? Different evidence types serve different purposes.

### C. Prerequisite PRs (In Order)

1. **PR-X: Wire Hero → BrandBrainSnapshot**
   - `_build_brand_snapshot()` should optionally read from latest BrandBrainSnapshot
   - Fallback to Brand model if no snapshot exists

2. **PR-Y: Unified Evidence Abstraction (Optional)**
   - If we want Hero to use both Ingestion trends AND BrandBrain evidence
   - Create a common `EvidenceSignalDTO` that both systems can produce

3. **PR-Z: Opportunities State Machine (If Needed)**
   - Only if we actually need `TodayBoardState` semantics
   - Currently Hero just returns computed board on-demand

4. **PR-W: Evidence Gates for Hero (If Needed)**
   - Only if we want MIN_EVIDENCE_ITEMS before allowing generation
   - Currently Hero falls back to stub opportunities on failure

### D. What the PRD Should Actually Reflect

| Area | Current PRD Assumption | Actual State | Recommended |
|------|------------------------|--------------|-------------|
| Evidence source for opportunities | BrandBrain NormalizedEvidenceItem | Ingestion TrendCandidate | Clarify both systems |
| Brand context | BrandBrainSnapshot | Brand model directly | Wire to BrandBrainSnapshot |
| State machine | TodayBoardState enum | None (computed on-demand) | Keep simple unless needed |
| Evidence gates | MIN_EVIDENCE_ITEMS | None | Add if quality matters |
| Durable job queue | OpportunitiesJob | None | Add if async generation needed |

---

## 6. Summary

### What's Real and Working

1. **BrandBrain compile pipeline** - Full end-to-end: sources → ingestion → normalization → bundling → (stub) compile → snapshot
2. **Actor infrastructure** - 6 validated actors with input/output schemas, sample data, and tests
3. **Ingestion pipeline** - Surface → EvidenceItem → Cluster → TrendCandidate
4. **Hero opportunities engine** - Brand → LLM graph → Opportunity rows → TodayBoardDTO

### What's Missing

1. **Connection between BrandBrain and Hero** - These are isolated systems
2. **PR0/PR1/PR1.1 infrastructure** - Does not exist (TodayBoardState, OpportunitiesJob, ready_reason, evidence gates)
3. **LLM compile** - Stubbed in BrandBrain

### Key Insight

The PRD's "Source Activation Strategy" concept is **already implemented** in BrandBrain, but it serves a different purpose than assumed:

- **BrandBrain source activation:** Fetches the brand's OWN content from their channels → used to understand their voice/positioning
- **Ingestion trend detection:** Discovers TRENDING content across platforms → used to find opportunities

These are complementary, not the same thing. The PRD should reflect this distinction.

---

## Appendix: Key File Locations

### BrandBrain Actor System
```
kairo/brandbrain/
├── actors/
│   ├── registry.py      # ActorSpec definitions
│   └── inputs.py        # Per-actor input builders
├── normalization/
│   ├── adapters.py      # Per-actor output normalizers
│   └── service.py       # normalize_apify_run()
├── ingestion/
│   └── service.py       # ingest_source()
├── bundling/
│   └── service.py       # create_evidence_bundle()
├── compile/
│   ├── service.py       # compile_brandbrain()
│   └── worker.py        # execute_compile_job()
├── jobs/
│   └── queue.py         # BrandBrainJob queue
├── identifiers.py       # Identifier normalization
└── models.py            # All BrandBrain models
```

### Ingestion System
```
kairo/ingestion/
├── models.py            # Surface, EvidenceItem, Cluster, TrendCandidate
├── capture/
│   └── adapters/        # Platform scrapers
├── jobs/
│   ├── aggregate.py     # Clustering
│   ├── normalize.py     # Artifact normalization
│   └── score.py         # Trend scoring
└── services/
    └── trend_emitter.py # TrendCandidate → TrendSignalDTO
```

### Hero System
```
kairo/hero/
├── engines/
│   └── opportunities_engine.py  # generate_today_board()
├── services/
│   ├── today_service.py         # get_today_board()
│   └── external_signals_service.py
├── graphs/
│   └── opportunities_graph.py   # LLM graph
└── dto.py                       # All DTOs
```

### Apify Integration
```
kairo/integrations/apify/
├── client.py            # ApifyClient
└── models.py            # ApifyRun, RawApifyItem

var/apify_samples/       # Sample actor outputs
```

---

*End of report.*
