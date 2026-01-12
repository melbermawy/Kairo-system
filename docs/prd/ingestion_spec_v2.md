# Ingestion Spec v2: TikTok + Instagram Trend Detection

**Version:** 2.0
**Date:** 2025-12-22
**Status:** Phase 1 Implementation Spec

---

## 0. Header

### Purpose

Replace fixture-based `ExternalSignalBundleDTO` with real ingested trends from TikTok and Instagram. Feed fresh, timestamped trend signals into the F1 opportunities graph so it generates timely, non-stale content opportunities.

### Audience

- Backend engineers implementing the ingestion pipeline
- Engineers maintaining the hero loop (F1 graph, opportunities engine)

### Definition of Done (Phase 1)

- [ ] 1+ CaptureRun completes without error for each enabled Surface
- [ ] EvidenceItem rows persisted in DB with valid platform_item_id
- [ ] NormalizedArtifact rows created with cluster_key assigned
- [ ] ClusterBucket rows aggregated for 60-min windows
- [ ] TrendCandidate rows scored and lifecycle-transitioned
- [ ] F1 graph receives `ExternalSignalBundleDTO` with >=1 real `TrendSignalDTO`
- [ ] F1 generates >=1 Opportunity with `source="ingestion:{cluster_key}"`
- [ ] All above verified in a single end-to-end run

---

## 1. Phases

### Phase 1: Proof (This Spec)

**Goal:** 1-2 "perfect runs" proving the concept.

**Scope:**
- Manual/CLI-triggered capture runs (no scheduler)
- 6-8 surfaces total across TikTok + Instagram (+ optional X/Reddit baseline)
- Simple heuristic scoring (no ML)
- Brittle capture adapters acceptable
- Write to real DB
- No reliability guarantees

**Success Criteria:**
- CaptureRun → EvidenceItem → NormalizedArtifact → Cluster → Bucket → TrendCandidate → hero loop
- At least 1 non-garbage opportunity generated from a real detected trend

### Phase 2: MVP Loop (Future)

**Goal:** Recurring ingestion with stable operation.

**Scope (out of this spec):**
- Scheduled capture jobs (cron/celery)
- Retry/backoff logic for failed captures
- Proxy rotation and rate limit handling
- UI surfacing of trend candidates
- Feedback hooks (user marks trend as useful/not)
- Deduplication across capture runs
- Alert on capture degradation

---

## 2. Scope + Non-Goals

### In Scope (Phase 1)

| Item | Description |
|------|-------------|
| TikTok Discover page | Scrape trending sounds/videos |
| TikTok hashtag search | Scrape top posts for target hashtags |
| Instagram Explore Reels | Scrape trending audio from Explore |
| Instagram hashtag top posts | Scrape recent top posts for hashtags |
| X trending topics | (Optional) Baseline text trends |
| Reddit rising posts | (Optional) Baseline text trends |
| Cluster assignment | Rule-based: audio_id, hashtag, n-gram |
| Bucket aggregation | 60-minute windows |
| Heuristic scoring | Velocity + breadth + novelty |
| Hero integration | Map TrendCandidate → TrendSignalDTO |

### Non-Goals (Phase 1)

| Item | Reason |
|------|--------|
| Scheduled/cron jobs | Phase 2 |
| Proxy rotation | Phase 2; use single IP for proof |
| Rate limit recovery | Phase 2 |
| UI for trends | Phase 2 |
| User feedback on trends | Phase 2 |
| ML-based scoring | Phase 2; heuristics first |
| Competitor-specific scraping | Separate feature |
| Brand-filtered ingestion | All brands see same global trends |

---

## 3. Terminology + Objects + Invariants

### Core Objects

| Object | Definition |
|--------|------------|
| **Surface** | A specific scrape target (e.g., `tiktok:discover`, `instagram:explore_reels`, `tiktok:hashtag:{tag}`) |
| **CaptureRun** | One execution of a capture job for a Surface. Has start_ts, end_ts, status, item_count. |
| **EvidenceItem** | Raw scraped item (video, post, audio). Platform-native fields preserved. Immutable after creation. |
| **NormalizedArtifact** | Normalized representation of EvidenceItem (still 1:1). Contains engagement_score and normalized fields. Linked to clusters via ArtifactClusterLink. |
| **Cluster** | A grouping key for related content (audio_id, hashtag, phrase, entity). |
| **ArtifactClusterLink** | Join model linking NormalizedArtifact ↔ Cluster with: `role` (primary\|secondary), `key_type` (audio_id\|hashtag\|phrase\|entity), `key_value` (original extracted value), `rank` (optional ordering for secondary links). |
| **ClusterBucket** | Time-windowed aggregation of artifacts for a cluster. Contains counts and velocity metrics. |
| **TrendCandidate** | A cluster that exceeds detection thresholds. Eligible to become a trend signal. |

### Invariants

| Invariant | Rule |
|-----------|------|
| **Idempotency** | Re-running capture for same Surface + time window must not create duplicate EvidenceItems. Use `unique(platform, platform_item_id)`. |
| **Provenance** | Every NormalizedArtifact links to exactly one EvidenceItem. Every TrendCandidate links to exactly one Cluster. |
| **Primary Cluster Required** | Each NormalizedArtifact must have exactly 1 primary cluster link. Any number of secondary links allowed. |
| **Link Idempotency** | Artifact-cluster links enforce `unique(artifact, cluster, role)` to prevent duplicate links. Conditional unique constraint enforces exactly one primary per artifact. |
| **Unique Keys** | `EvidenceItem.platform_item_id` is unique per platform. `Cluster.cluster_key` is unique per `cluster_key_type`. |
| **Bucket Alignment** | All buckets align to clock boundaries (e.g., 14:00-15:00, not 14:23-15:23). |
| **Immutable Evidence** | EvidenceItem is append-only. Updates go to NormalizedArtifact or new evidence rows. |

---

## 4. DB Schema (Django Models)

### Module Location

`kairo/ingestion/models.py`

### Model Definitions

```python
# kairo/ingestion/models.py

from django.db import models
import uuid

class Surface(models.Model):
    """Scrape target definition."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    platform = models.CharField(max_length=50)  # tiktok, instagram, x, reddit
    surface_type = models.CharField(max_length=100)  # discover, explore_reels, hashtag, trending
    surface_key = models.CharField(max_length=255, blank=True)  # hashtag value if applicable
    is_enabled = models.BooleanField(default=True)
    cadence_minutes = models.PositiveIntegerField(default=60)
    last_capture_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_surface"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "surface_type", "surface_key"],
                name="uniq_surface_identity"
            )
        ]


class CaptureRun(models.Model):
    """One execution of a capture job."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    surface = models.ForeignKey(Surface, on_delete=models.PROTECT, related_name="runs")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=50)  # running, success, failed, partial
    item_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        db_table = "ingestion_capture_run"
        indexes = [
            models.Index(fields=["surface", "started_at"]),
            models.Index(fields=["status", "started_at"]),
        ]


class EvidenceItem(models.Model):
    """Raw scraped item. Immutable after creation."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    capture_run = models.ForeignKey(CaptureRun, on_delete=models.CASCADE, related_name="items")
    platform = models.CharField(max_length=50)  # tiktok, instagram, x, reddit
    platform_item_id = models.CharField(max_length=255)  # video_id, post_id, etc.
    item_type = models.CharField(max_length=50)  # video, post, audio, comment

    # Platform-native fields (nullable, platform-dependent)
    author_id = models.CharField(max_length=255, blank=True)
    author_handle = models.CharField(max_length=255, blank=True)
    text_content = models.TextField(blank=True)
    audio_id = models.CharField(max_length=255, blank=True)
    audio_title = models.CharField(max_length=500, blank=True)
    hashtags = models.JSONField(default=list)  # list of strings
    view_count = models.BigIntegerField(null=True)
    like_count = models.BigIntegerField(null=True)
    comment_count = models.BigIntegerField(null=True)
    share_count = models.BigIntegerField(null=True)

    # Timestamps
    item_created_at = models.DateTimeField(null=True)  # when item was posted on platform
    captured_at = models.DateTimeField()  # when we scraped it

    # Raw storage
    raw_json = models.JSONField(default=dict)  # full platform response
    canonical_url = models.URLField(max_length=2000, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_evidence_item"
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "platform_item_id"],
                name="uniq_platform_item"
            )
        ]
        indexes = [
            models.Index(fields=["platform", "audio_id"]),
            models.Index(fields=["platform", "captured_at"]),
            models.Index(fields=["capture_run", "created_at"]),
        ]


class Cluster(models.Model):
    """Grouping key for related content."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    cluster_key_type = models.CharField(max_length=50)  # audio_id, hashtag, phrase, entity
    cluster_key = models.CharField(max_length=500)  # the actual key value
    display_name = models.CharField(max_length=500)  # human-readable name
    platforms = models.JSONField(default=list)  # platforms where this cluster appears
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_cluster"
        constraints = [
            models.UniqueConstraint(
                fields=["cluster_key_type", "cluster_key"],
                name="uniq_cluster_key"
            )
        ]
        indexes = [
            models.Index(fields=["cluster_key_type", "last_seen_at"]),
        ]


class NormalizedArtifact(models.Model):
    """Standardized artifact. Linked to clusters via ArtifactClusterLink."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    evidence_item = models.OneToOneField(EvidenceItem, on_delete=models.CASCADE, related_name="artifact")
    # Note: No direct FK to Cluster. All cluster associations via ArtifactClusterLink.

    # Normalized fields
    normalized_text = models.TextField(blank=True)
    engagement_score = models.FloatField(default=0)  # normalized 0-100

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_normalized_artifact"

    def get_primary_cluster(self):
        """Return the primary cluster for this artifact."""
        link = self.cluster_links.filter(role="primary").first()
        return link.cluster if link else None


class ArtifactClusterLink(models.Model):
    """Join model linking NormalizedArtifact ↔ Cluster."""
    ROLE_CHOICES = [
        ("primary", "Primary"),
        ("secondary", "Secondary"),
    ]
    KEY_TYPE_CHOICES = [
        ("audio_id", "Audio ID"),
        ("hashtag", "Hashtag"),
        ("phrase", "Phrase"),
        ("entity", "Entity"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    artifact = models.ForeignKey(NormalizedArtifact, on_delete=models.CASCADE, related_name="cluster_links")
    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name="artifact_links")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    key_type = models.CharField(max_length=50, choices=KEY_TYPE_CHOICES)
    key_value = models.CharField(max_length=500, blank=True)  # original extracted value
    rank = models.PositiveIntegerField(null=True, blank=True)  # ordering for secondary links
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_artifact_cluster_link"
        constraints = [
            # Each artifact can only have one primary role
            models.UniqueConstraint(
                fields=["artifact"],
                condition=models.Q(role="primary"),
                name="uniq_artifact_primary_role"
            ),
            # Prevent duplicate (artifact, cluster, role) combinations
            models.UniqueConstraint(
                fields=["artifact", "cluster", "role"],
                name="uniq_artifact_cluster_role"
            ),
        ]
        indexes = [
            models.Index(fields=["cluster", "created_at"]),
            models.Index(fields=["artifact", "role"]),
        ]


class ClusterBucket(models.Model):
    """Time-windowed aggregation for a cluster."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name="buckets")
    bucket_start = models.DateTimeField()
    bucket_end = models.DateTimeField()

    # Metrics
    artifact_count = models.PositiveIntegerField(default=0)
    unique_authors = models.PositiveIntegerField(default=0)
    total_views = models.BigIntegerField(default=0)
    total_engagement = models.BigIntegerField(default=0)
    avg_engagement_score = models.FloatField(default=0)

    # Velocity (calculated from previous bucket)
    velocity = models.FloatField(default=0)  # artifacts/hour change
    acceleration = models.FloatField(default=0)  # velocity change

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_cluster_bucket"
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "bucket_start"],
                name="uniq_cluster_bucket"
            )
        ]
        indexes = [
            models.Index(fields=["bucket_start", "velocity"]),
        ]


class TrendCandidate(models.Model):
    """A cluster that exceeds detection thresholds."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name="trend_candidates")

    # Lifecycle
    status = models.CharField(max_length=50, default="emerging")  # emerging, active, peaked, stale
    detected_at = models.DateTimeField()
    peaked_at = models.DateTimeField(null=True)
    stale_at = models.DateTimeField(null=True)

    # Scoring
    trend_score = models.FloatField(default=0)  # 0-100
    velocity_score = models.FloatField(default=0)
    breadth_score = models.FloatField(default=0)
    novelty_score = models.FloatField(default=0)

    # For hero integration
    last_emitted_at = models.DateTimeField(null=True)  # when last sent to hero loop
    emit_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_trend_candidate"
        indexes = [
            models.Index(fields=["status", "trend_score"]),
            models.Index(fields=["detected_at"]),
        ]
```

### Example Rows

**Surface:**
```json
{
  "id": "a1b2c3...",
  "platform": "tiktok",
  "surface_type": "discover",
  "surface_key": "",
  "is_enabled": true,
  "cadence_minutes": 60
}
```

**EvidenceItem:**
```json
{
  "platform": "tiktok",
  "platform_item_id": "7298765432109876543",
  "item_type": "video",
  "audio_id": "6851234567890123456",
  "audio_title": "original sound - @creator",
  "hashtags": ["fyp", "viral", "trending"],
  "view_count": 1500000,
  "like_count": 85000
}
```

**Cluster (audio_id - primary):**
```json
{
  "id": "c1c1c1...",
  "cluster_key_type": "audio_id",
  "cluster_key": "tiktok:6851234567890123456",
  "display_name": "original sound - @creator",
  "platforms": ["tiktok"]
}
```

**Cluster (hashtag - secondary):**
```json
{
  "id": "c2c2c2...",
  "cluster_key_type": "hashtag",
  "cluster_key": "tiktok:#viral",
  "display_name": "#viral",
  "platforms": ["tiktok"]
}
```

**NormalizedArtifact:**
```json
{
  "id": "n1n1n1...",
  "evidence_item_id": "(references EvidenceItem above)",
  "normalized_text": "Check out this viral trend...",
  "engagement_score": 75.5
}
```

**ArtifactClusterLink (primary):**
```json
{
  "artifact_id": "n1n1n1...",
  "cluster_id": "c1c1c1...",
  "role": "primary",
  "key_type": "audio_id",
  "key_value": "6851234567890123456",
  "rank": null
}
```

**ArtifactClusterLink (secondary):**
```json
{
  "artifact_id": "n1n1n1...",
  "cluster_id": "c2c2c2...",
  "role": "secondary",
  "key_type": "hashtag",
  "key_value": "#viral",
  "rank": 0
}
```

### Migration Strategy

```bash
# PR-A: Create migrations
python manage.py makemigrations ingestion
python manage.py migrate

# Verify tables exist
python manage.py dbshell
\dt ingestion_*
```

### Implementation Notes

- All models use UUID primary keys for consistency with hero models
- JSONField for flexible metadata storage
- Explicit `db_table` names with `ingestion_` prefix
- Unique constraints enforce idempotency invariants

### Tests

- `tests/test_ingestion_models.py`:
  - `test_evidence_item_unique_constraint` - duplicate platform_item_id rejected
  - `test_cluster_unique_constraint` - duplicate cluster_key rejected
  - `test_bucket_unique_constraint` - duplicate bucket_start rejected
  - `test_cascade_delete_capture_run` - deleting run cascades to items

---

## 5. Ingestion Pipeline Stages

### Stage Overview

```
Surface → CaptureRun → EvidenceItem → NormalizedArtifact → Cluster → ClusterBucket → TrendCandidate → hero
```

### Stage 1: Capture

**Input:** Surface definition
**Output:** CaptureRun + EvidenceItems

**Process:**
1. Create CaptureRun with status="running"
2. Call platform adapter (e.g., `tiktok_discover_adapter.capture()`)
3. Adapter returns list of raw items
4. For each item: upsert EvidenceItem (skip if platform_item_id exists)
5. Update CaptureRun: item_count, status="success"/"partial"/"failed"

**Failure Handling:**
- Adapter timeout: status="failed", error_message captured
- Partial success (some items fail): status="partial", log failures

**Idempotency:**
- `get_or_create` on `(platform, platform_item_id)`
- Re-running capture skips existing items

**Location:** `kairo/ingestion/capture/`

### Stage 2: Normalize

**Input:** EvidenceItem (no artifact yet)
**Output:** NormalizedArtifact + Cluster (upsert)

**Process:**
1. Query EvidenceItems where `.artifact` is None
2. For each item:
   a. Extract cluster_key(s) based on platform/item_type
   b. Upsert Cluster for each key
   c. Create NormalizedArtifact linking to primary cluster
   d. Compute engagement_score (normalize view/like counts)

**Cluster Key Extraction Rules:**

| Platform | Item Type | Primary Key | Secondary Keys |
|----------|-----------|-------------|----------------|
| tiktok | video | `audio_id` if present | hashtags |
| instagram | reel | `audio_id` if present | hashtags |
| x | tweet | top hashtag or phrase | - |
| reddit | post | subreddit + flair | - |

**Failure Handling:**
- Missing required fields: skip item, log warning
- Invalid cluster_key: skip, log

**Idempotency:**
- NormalizedArtifact is OneToOne to EvidenceItem
- Re-running normalize is idempotent (checks if artifact exists)

**Location:** `kairo/ingestion/jobs/normalize.py`

### Stage 3: Bucket Aggregation

**Input:** NormalizedArtifacts + Clusters
**Output:** ClusterBuckets (updated)

**Process:**
1. Determine current bucket window (aligned to hour)
2. Query artifacts created since last aggregation
3. Group by cluster
4. For each cluster:
   a. Upsert ClusterBucket for current window
   b. Aggregate: artifact_count, unique_authors, totals
   c. Compute velocity from previous bucket

**Bucket Window:** 60 minutes, aligned to clock (e.g., 14:00-15:00)

**Velocity Calculation:**
```python
velocity = (current_bucket.artifact_count - prev_bucket.artifact_count) / hours_between
acceleration = (current_velocity - prev_velocity) / hours_between
```

**Failure Handling:**
- Missing previous bucket: velocity=0, acceleration=0
- Zero artifacts: still create bucket with zeros

**Idempotency:**
- Unique constraint on `(cluster, bucket_start)`
- Re-running updates existing bucket

**Location:** `kairo/ingestion/jobs/aggregate.py`

### Stage 4: Scoring + Lifecycle

**Input:** ClusterBuckets
**Output:** TrendCandidates (upsert, status transitions)

**Process:**
1. Query recent buckets (last 6 hours)
2. For each cluster with activity:
   a. Compute trend_score (see §9 for algorithm)
   b. If score > DETECTION_THRESHOLD (50): upsert TrendCandidate
   c. Transition lifecycle status based on velocity

**Lifecycle Transitions:**
- `emerging`: newly detected, velocity > 0
- `active`: sustained velocity, score > 60
- `peaked`: velocity < 0 for 2+ buckets
- `stale`: no activity for 6+ hours

**Failure Handling:**
- Scoring errors: log, skip cluster
- No buckets: no-op

**Idempotency:**
- TrendCandidate linked to cluster (can update)
- Status transitions are monotonic (emerging→active→peaked→stale)

**Location:** `kairo/ingestion/jobs/score.py`

### Stage 5: Emit to Hero

**Input:** TrendCandidates where status in (emerging, active)
**Output:** TrendSignalDTOs in ExternalSignalBundleDTO

**Process:**
1. Query active TrendCandidates ordered by trend_score
2. Limit to top N (default: 10)
3. For each: create TrendSignalDTO
4. Update last_emitted_at, emit_count

**Mapping:**
```python
TrendSignalDTO(
    id=str(candidate.cluster.id),
    topic=candidate.cluster.display_name,
    source=f"ingestion:{candidate.cluster.cluster_key_type}",
    relevance_score=candidate.trend_score,
    recency_days=0,  # all are recent
    url=best_evidence_url(candidate.cluster),
    snippet=top_artifact_text(candidate.cluster),
)
```

**Location:** `kairo/ingestion/services/trend_emitter.py`

### Implementation Notes

- Each stage is idempotent and can be re-run
- Stages can run independently (batch mode)
- CLI commands: `python manage.py ingest_capture`, `ingest_normalize`, etc.

### Tests

- `tests/test_ingestion_pipeline.py`:
  - `test_capture_creates_evidence_items`
  - `test_normalize_creates_clusters`
  - `test_bucket_aggregation_computes_velocity`
  - `test_scoring_creates_trend_candidates`
  - `test_emit_produces_trend_signals`
  - `test_end_to_end_pipeline`

---

## 6. Phase 1 Surfaces

### Selected Surfaces (8 total)

| # | Surface ID | Platform | Type | Key | Priority | Fragility |
|---|------------|----------|------|-----|----------|-----------|
| 1 | `tiktok:discover` | tiktok | discover | - | P0 | Medium |
| 2 | `tiktok:trending_sounds` | tiktok | trending_sounds | - | P0 | High |
| 3 | `tiktok:hashtag:marketing` | tiktok | hashtag | marketing | P1 | Low |
| 4 | `tiktok:hashtag:ai` | tiktok | hashtag | ai | P1 | Low |
| 5 | `instagram:explore_reels` | instagram | explore_reels | - | P0 | High |
| 6 | `instagram:hashtag:marketing` | instagram | hashtag | marketing | P1 | Medium |
| 7 | `x:trending` | x | trending | - | P2 | Low |
| 8 | `reddit:rising` | reddit | rising | r/marketing | P2 | Low |

### Surface Details

#### 1. TikTok Discover Page (`tiktok:discover`)

**Method:** Playwright headless browser
**URL:** `https://www.tiktok.com/explore` (requires login for some content)
**Expected Fields:**
- video_id, author_handle, audio_id, audio_title
- hashtags (from description)
- view_count, like_count (UNVERIFIED: may be hidden)
- thumbnail_url, video_url

**Fragility:** Medium - TikTok changes DOM frequently
**Validation:** Check for >=10 videos with audio_id

**UNVERIFIED:** Exact DOM selectors change frequently. Experiment: run Playwright, inspect DOM for `data-e2e` attributes.

#### 2. TikTok Trending Sounds (`tiktok:trending_sounds`)

**Method:** Playwright or API probe
**URL:** `https://www.tiktok.com/music` or internal API endpoint
**Expected Fields:**
- audio_id, audio_title, author_name
- use_count (number of videos using this sound)
- preview_url

**Fragility:** High - No stable public endpoint
**Validation:** Check for >=5 sounds with use_count

**UNVERIFIED:** TikTok's music page structure. Experiment: navigate to `/music`, inspect available data.

#### 3-4. TikTok Hashtag Search (`tiktok:hashtag:{tag}`)

**Method:** Playwright
**URL:** `https://www.tiktok.com/tag/{hashtag}`
**Expected Fields:**
- video_id, author_handle, audio_id
- hashtags (including the searched one)
- view_count (if visible)

**Fragility:** Low - Hashtag pages are stable
**Validation:** Check for >=20 videos

#### 5. Instagram Explore Reels (`instagram:explore_reels`)

**Method:** Playwright (logged-in session recommended)
**URL:** `https://www.instagram.com/reels/` or Explore tab
**Expected Fields:**
- reel_id, author_handle, audio_id, audio_name
- view_count, like_count (UNVERIFIED: may require interaction)
- caption, hashtags

**Fragility:** High - Requires session, Instagram actively blocks
**Validation:** Check for >=5 reels with audio_id

**UNVERIFIED:** Whether audio_id is extractable from DOM. Experiment: inspect Reel elements for audio metadata.

#### 6. Instagram Hashtag (`instagram:hashtag:{tag}`)

**Method:** Playwright
**URL:** `https://www.instagram.com/explore/tags/{hashtag}/`
**Expected Fields:**
- post_id (shortcode), author_handle
- like_count, comment_count (from page)
- caption, hashtags

**Fragility:** Medium - Hashtag pages exist but change
**Validation:** Check for >=9 posts (3x3 grid)

#### 7. X Trending Topics (`x:trending`)

**Method:** requests (no JS needed) or Playwright
**URL:** `https://twitter.com/explore/tabs/trending` (UNVERIFIED current path)
**Expected Fields:**
- topic_name, tweet_count (if shown)
- category (optional)

**Fragility:** Low - X API or scraping is well-documented
**Validation:** Check for >=10 topics

**UNVERIFIED:** Current DOM structure after X rebrand. Experiment: inspect Explore page.

#### 8. Reddit Rising (`reddit:rising`)

**Method:** requests to JSON endpoint
**URL:** `https://www.reddit.com/r/{subreddit}/rising.json`
**Expected Fields:**
- post_id, title, author
- score, num_comments
- subreddit, flair

**Fragility:** Low - Reddit JSON endpoints are stable
**Validation:** Check for >=10 posts

### Implementation Notes

- Start with P0 surfaces; add P1/P2 if P0 works
- Each adapter is a separate file in `kairo/ingestion/capture/adapters/`
- Adapters return `list[dict]` of raw platform data

### Tests

- `tests/test_ingestion_adapters.py`:
  - `test_tiktok_discover_adapter_returns_videos`
  - `test_instagram_hashtag_adapter_returns_posts`
  - `test_reddit_adapter_returns_posts`

---

## 7. Capture Methods + Cost Model

### Capture Methods

| Method | Use Case | Cost | Reliability |
|--------|----------|------|-------------|
| **requests** | Reddit, X (some), static pages | Free | High |
| **Playwright** | TikTok, Instagram, JS-heavy | Free | Medium |
| **Oxylabs** | Blocked IPs, high-volume | $49/mo starter | High |

### Phase 1 Approach

Use **Playwright** for TikTok/Instagram, **requests** for Reddit/X.

No proxy service in Phase 1 - accept that some captures may fail due to rate limiting.

### Request Budget Table

| Surface | Cadence | Requests/Run | Runs/Day | Requests/Day |
|---------|---------|--------------|----------|--------------|
| tiktok:discover | 60 min | 5 | 24 | 120 |
| tiktok:trending_sounds | 60 min | 3 | 24 | 72 |
| tiktok:hashtag:marketing | 120 min | 3 | 12 | 36 |
| tiktok:hashtag:ai | 120 min | 3 | 12 | 36 |
| instagram:explore_reels | 60 min | 5 | 24 | 120 |
| instagram:hashtag:marketing | 120 min | 3 | 12 | 36 |
| x:trending | 60 min | 2 | 24 | 48 |
| reddit:rising | 30 min | 1 | 48 | 48 |
| **Total** | - | - | - | **516** |

**Daily budget:** ~500 requests/day (well under any rate limit concern for personal use)

### Implementation Notes

- Use async Playwright for parallel browser tabs
- Reuse browser session across surfaces of same platform
- Respect `robots.txt` where practical (but brittle capture is acceptable in Phase 1)

### Tests

- `tests/test_capture_methods.py`:
  - `test_playwright_launches_browser`
  - `test_requests_reddit_json`

---

## 8. Cadence + Bucket Strategy

### Capture Cadence

| Surface Type | Cadence | Rationale |
|--------------|---------|-----------|
| Discover/Explore | 60 min | Fast-moving, need frequent updates |
| Trending sounds | 60 min | Audio trends emerge quickly |
| Hashtag search | 120 min | Slower churn, reduce load |
| X/Reddit baseline | 30-60 min | Text trends vary |

### Bucket Size

**Primary bucket:** 60 minutes

**Rationale:**
- Matches capture cadence (1 capture = 1 bucket typically)
- Enough granularity to detect velocity changes
- Not so small that noise dominates

### 30-Minute Scrape Rumor Discussion

**Claim:** "Scraping every 30 minutes catches trends earlier."

**Reality:**
- For audio trends: 60 min is sufficient. Audio trends don't peak in <60 min windows.
- For text trends (X/Reddit): 30 min helps for breaking news, but not core use case.
- Cost: 2x request volume, 2x browser sessions.

**Phase 1 Decision:** Use 60-min for TikTok/Instagram, 30-min optional for X/Reddit if needed.

### Implementation Notes

- Bucket boundaries: `bucket_start = floor(capture_time, 60 min)`
- Example: capture at 14:23 → bucket_start=14:00, bucket_end=15:00

### Tests

- `tests/test_bucket_alignment.py`:
  - `test_bucket_start_aligns_to_hour`
  - `test_bucket_end_is_start_plus_window`

---

## 9. Trend Detection + Lifecycle

### Cluster Key Types (Phase 1)

| Type | Format | Example |
|------|--------|---------|
| `audio_id` | `{platform}:{audio_id}` | `tiktok:6851234567890123456` |
| `hashtag` | `{platform}:{hashtag}` | `instagram:#marketing` |
| `phrase` | `phrase:{normalized_text}` | `phrase:nobody_wants_to_work` |

### Features per Bucket

| Feature | Calculation | Range |
|---------|-------------|-------|
| `velocity` | `(count - prev_count) / hours` | -inf to +inf |
| `acceleration` | `(velocity - prev_velocity) / hours` | -inf to +inf |
| `breadth` | `unique_authors / artifact_count` | 0 to 1 |
| `novelty` | `1 - (hours_since_first_seen / 168)` | 0 to 1 |
| `concentration` | `max_author_artifacts / artifact_count` | 0 to 1 |
| `cross_surface` | `len(unique_surfaces) / len(all_surfaces)` | 0 to 1 |

### Scoring Paths

Scoring chooses a path **per cluster per bucket** based on available data:

| Path | Condition | Description |
|------|-----------|-------------|
| **Path A (Counter-based)** | Bucket has meaningful counters (total_views > 0 OR total_engagement > 0) | Uses platform counters (views/likes/engagement) as primary signal |
| **Path B (Sampling-based)** | No counters available | Relies on recurrence/breadth/concentration/velocity of captures |

Both paths output a score in range 0-100.

#### Path Selection

```python
def select_scoring_path(bucket: ClusterBucket) -> str:
    """Select scoring path based on available data."""
    if bucket.total_views > 0 or bucket.total_engagement > 0:
        return "counters"  # Path A
    return "sampling"  # Path B
```

#### Path A: Counter-Based Scoring

When platform counters are available (TikTok views, likes, etc.):

```python
def compute_score_path_a(cluster, buckets, now):
    """Counter-based scoring (Path A)."""
    latest = buckets[-1]

    # Engagement component (35%) - from platform counters
    views_norm = min(latest.total_views / 1_000_000, 1.0)  # 1M views = max
    engagement_norm = min(latest.total_engagement / 100_000, 1.0)  # 100K engagement = max
    engagement_score = ((views_norm + engagement_norm) / 2) * 35

    # Velocity component (25%)
    velocity_norm = min(latest.velocity / 10, 1.0)
    velocity_score = velocity_norm * 25

    # Breadth component (20%)
    breadth = latest.unique_authors / max(latest.artifact_count, 1)
    breadth_score = breadth * 20

    # Novelty component (20%)
    hours_since_first = (now - cluster.first_seen_at).total_seconds() / 3600
    novelty = max(0, 1 - hours_since_first / 168)
    novelty_score = novelty * 20

    return engagement_score + velocity_score + breadth_score + novelty_score
```

#### Path B: Sampling-Based Scoring

When no counters available (e.g., Reddit text, some scraped sources):

```python
def compute_score_path_b(cluster, buckets, now):
    """Sampling-based scoring (Path B)."""
    latest = buckets[-1]

    # Velocity component (40%) - primary signal when no counters
    velocity_norm = min(latest.velocity / 10, 1.0)
    velocity_score = velocity_norm * 40

    # Breadth component (30%) - author diversity
    breadth = latest.unique_authors / max(latest.artifact_count, 1)
    breadth_score = breadth * 30

    # Novelty component (20%)
    hours_since_first = (now - cluster.first_seen_at).total_seconds() / 3600
    novelty = max(0, 1 - hours_since_first / 168)
    novelty_score = novelty * 20

    # Volume/concentration component (10%)
    volume_norm = min(latest.artifact_count / 50, 1.0)
    volume_score = volume_norm * 10

    return velocity_score + breadth_score + novelty_score + volume_score
```

#### Combined Scoring Flow

```python
def compute_trend_score(cluster, buckets, now):
    """Compute trend score 0-100 using appropriate path."""
    if len(buckets) == 0:
        return 0, {"path": "none"}

    latest = buckets[-1]
    path = select_scoring_path(latest)

    if path == "counters":
        score = compute_score_path_a(cluster, buckets, now)
    else:
        score = compute_score_path_b(cluster, buckets, now)

    return score, {"path": path, ...}
```

### Lifecycle States

| State | Condition | Transitions To |
|-------|-----------|----------------|
| `emerging` | score > 50, velocity > 0 | active, stale |
| `active` | score > 60, sustained 2+ buckets | peaked |
| `peaked` | velocity < 0 for 2+ buckets | stale |
| `stale` | no artifacts for 6+ hours | (terminal) |

### Detection Threshold

**DETECTION_THRESHOLD = 50**

Clusters scoring below 50 are not promoted to TrendCandidate.

### False Trend Filters

| Filter | Rule | Action |
|--------|------|--------|
| Single-author | breadth < 0.2 AND artifact_count > 5 | Reject |
| Bot pattern | concentration > 0.8 | Reject |
| Old trend | novelty < 0.1 AND velocity < 1 | Reject |
| Too small | artifact_count < 3 | Reject |

### Implementation Notes

- Scoring runs after every bucket aggregation
- Lifecycle transitions are logged for debugging
- TrendCandidate.status is updated atomically

### Tests

- `tests/test_trend_scoring.py`:
  - `test_high_velocity_increases_score`
  - `test_single_author_filtered`
  - `test_lifecycle_transitions`
  - `test_path_a_selected_when_counters_available`
  - `test_path_b_selected_when_no_counters`
  - `test_score_in_valid_range` (0-100)

---

## 10. Hero Integration

### Mapping: TrendCandidate → ExternalSignalBundleDTO

**Location:** `kairo/ingestion/services/trend_emitter.py`

```python
def build_external_signal_bundle(brand_id: UUID) -> ExternalSignalBundleDTO:
    """Build bundle from active TrendCandidates."""
    candidates = TrendCandidate.objects.filter(
        status__in=["emerging", "active"]
    ).order_by("-trend_score")[:10]

    trends = []
    for c in candidates:
        trends.append(TrendSignalDTO(
            id=str(c.cluster.id),
            topic=c.cluster.display_name,
            source=f"ingestion:{c.cluster.cluster_key_type}",
            relevance_score=c.trend_score,
            recency_days=0,
            url=_get_best_url(c.cluster),
            snippet=_get_snippet(c.cluster),
        ))
        # Update emit tracking
        c.last_emitted_at = timezone.now()
        c.emit_count += 1
        c.save(update_fields=["last_emitted_at", "emit_count", "updated_at"])

    return ExternalSignalBundleDTO(
        brand_id=brand_id,
        fetched_at=timezone.now(),
        trends=trends,
        web_mentions=[],
        competitor_posts=[],
        social_moments=[],
    )
```

### Provenance Flow

When F1 graph creates an Opportunity from a TrendSignal:

```python
OpportunityDraftDTO(
    proposed_title="...",
    source=f"ingestion:{cluster_key_type}",  # e.g., "ingestion:audio_id"
    source_url=trend.url,  # e.g., "https://tiktok.com/..."
    why_now=f"Trending on {platform} with score {trend.relevance_score}",
)
```

After persistence:

```python
Opportunity(
    source="ingestion:audio_id",
    source_url="https://tiktok.com/@creator/video/123",
    # why_now is in score_explanation or metadata
)
```

### Integration Point

Replace `external_signals_service.get_bundle_for_brand()` with mode-aware version:

```python
# kairo/hero/services/external_signals_service.py

# EXTERNAL_SIGNALS_MODE controls signal source:
# - "fixtures": Use fixture-based loader (current behavior)
# - "ingestion": Use real ingested TrendCandidates only (NO FALLBACK)

def get_bundle_for_brand(brand_id: UUID) -> ExternalSignalBundleDTO:
    """Get external signals bundle for a brand."""
    mode = getattr(settings, "EXTERNAL_SIGNALS_MODE", "fixtures")

    if mode == "ingestion":
        from kairo.ingestion.services.trend_emitter import build_external_signal_bundle
        # NO FALLBACK: return empty bundle if no candidates, never fixtures
        return build_external_signal_bundle(brand_id)

    # mode == "fixtures": use fixture loader
    return _load_fixture_bundle(brand_id)
```

### Mode Semantics (EXTERNAL_SIGNALS_MODE)

| Mode | Behavior |
|------|----------|
| `"fixtures"` | Use current fixture bundle loader. Default for tests. |
| `"ingestion"` | Build bundle from TrendCandidates only. If zero candidates exist, return empty bundle (still valid DTO). **Never fall back to fixtures.** |

**Setting:**
```python
# kairo/settings.py
EXTERNAL_SIGNALS_MODE = os.environ.get("EXTERNAL_SIGNALS_MODE", "fixtures")
```

### Implementation Notes

- `EXTERNAL_SIGNALS_MODE` replaces the old `INGESTION_ENABLED` boolean
- No fallback in ingestion mode: empty TrendCandidates = empty bundle (not fixtures)
- hero loop code unchanged (just receives different bundle contents)

### Tests

- `tests/test_hero_integration.py`:
  - `test_ingestion_mode_returns_ingested_trends`
  - `test_ingestion_mode_empty_candidates_returns_empty_bundle` (NOT fixtures)
  - `test_fixtures_mode_uses_fixtures`
  - `test_opportunity_source_has_ingestion_prefix`

---

## 11. Eval Plan

### Definition: "Perfect Run"

A perfect run satisfies:

1. >=1 Surface captures successfully (status=success)
2. >=10 EvidenceItems created
3. >=5 Clusters created or updated
4. >=3 ClusterBuckets with artifact_count > 0
5. >=1 TrendCandidate with status in (emerging, active)
6. ExternalSignalBundleDTO.trends has >=1 item
7. F1 generates >=1 Opportunity with `source` starting with "ingestion:"
8. Opportunity is not rejected by rubric validation
9. **At least 1 opportunity must be sourced from TikTok or Instagram ingestion surfaces** (Reddit/X alone doesn't count)

**Note:** If TikTok/Instagram adapters are still stubbed, requirement #9 is **blocked until adapters implemented**. This remains the target DoD for Phase 1 completion.

### Metrics

| Metric | Definition | Target (Phase 1) |
|--------|------------|------------------|
| Time-to-detect | Bucket window of first detection | <2 hours from content creation |
| Freshness | Age of newest artifact in trend | <4 hours |
| Novelty | % trends not seen in previous 24h | >50% |
| Precision@10 | Human-judged "real trend" / top 10 | >60% |
| Duplication rate | % duplicate EvidenceItems rejected | <5% (idempotency working) |

### Surfacing via Internal Pages

Add new internal views:

- `/hero/internal/ingestion/` - list recent CaptureRuns
- `/hero/internal/ingestion/trends/` - list active TrendCandidates
- `/hero/internal/ingestion/clusters/{id}/` - cluster detail with artifacts

### Implementation Notes

- Eval is manual in Phase 1 (inspect DB, run queries)
- Consider adding a `python manage.py ingest_eval` command for summary stats

### Tests

- `tests/test_ingestion_eval.py`:
  - `test_perfect_run_criteria`

---

## 12. Implementation Plan (PR Plan)

### PR-A: Schema + Migrations + Admin

**Scope:**
- Create `kairo/ingestion/` app
- Add models from §4
- Generate migrations
- Register models in Django admin
- Add `INGESTION_ENABLED` setting

**Files:**
- `kairo/ingestion/__init__.py`
- `kairo/ingestion/models.py`
- `kairo/ingestion/admin.py`
- `kairo/ingestion/migrations/0001_initial.py`
- `kairo/settings.py` (add to INSTALLED_APPS)

**Tests:**
- `tests/test_ingestion_models.py`

### PR-B: Capture Adapters

**Scope:**
- Base adapter interface
- TikTok discover adapter (Playwright)
- TikTok hashtag adapter
- Reddit adapter (requests)
- CLI command: `python manage.py ingest_capture`

**Files:**
- `kairo/ingestion/capture/__init__.py`
- `kairo/ingestion/capture/base.py`
- `kairo/ingestion/capture/adapters/__init__.py`
- `kairo/ingestion/capture/adapters/tiktok_discover.py`
- `kairo/ingestion/capture/adapters/tiktok_hashtag.py`
- `kairo/ingestion/capture/adapters/reddit_rising.py`
- `kairo/ingestion/management/commands/ingest_capture.py`

**Tests:**
- `tests/test_ingestion_adapters.py`

### PR-C: Normalize + Cluster Assignment

**Scope:**
- Normalization logic
- Cluster key extraction
- Idempotent artifact creation
- CLI command: `python manage.py ingest_normalize`

**Files:**
- `kairo/ingestion/jobs/__init__.py`
- `kairo/ingestion/jobs/normalize.py`
- `kairo/ingestion/management/commands/ingest_normalize.py`

**Tests:**
- `tests/test_ingestion_normalize.py`

### PR-D: Buckets + Scoring + Lifecycle

**Scope:**
- Bucket aggregation logic
- Trend scoring algorithm
- Lifecycle state machine
- CLI commands: `ingest_aggregate`, `ingest_score`

**Files:**
- `kairo/ingestion/jobs/aggregate.py`
- `kairo/ingestion/jobs/score.py`
- `kairo/ingestion/management/commands/ingest_aggregate.py`
- `kairo/ingestion/management/commands/ingest_score.py`

**Tests:**
- `tests/test_ingestion_buckets.py`
- `tests/test_ingestion_scoring.py`

### PR-E: Hero Integration + Eval Harness

**Scope:**
- Trend emitter service
- Replace fixture bundle with ingestion bundle
- Internal views for ingestion
- End-to-end eval command

**Files:**
- `kairo/ingestion/services/__init__.py`
- `kairo/ingestion/services/trend_emitter.py`
- `kairo/hero/services/external_signals_service.py` (modify)
- `kairo/ingestion/internal_views.py`
- `kairo/ingestion/management/commands/ingest_eval.py`

**Tests:**
- `tests/test_ingestion_hero_integration.py`
- `tests/test_ingestion_end_to_end.py`

---

## 13. Acceptance Tests

### DB Constraints

```python
def test_evidence_item_unique_constraint():
    """Duplicate platform_item_id is rejected."""
    EvidenceItem.objects.create(platform="tiktok", platform_item_id="123", ...)
    with pytest.raises(IntegrityError):
        EvidenceItem.objects.create(platform="tiktok", platform_item_id="123", ...)

def test_cluster_unique_constraint():
    """Duplicate cluster_key is rejected."""
    Cluster.objects.create(cluster_key_type="audio_id", cluster_key="tiktok:123", ...)
    with pytest.raises(IntegrityError):
        Cluster.objects.create(cluster_key_type="audio_id", cluster_key="tiktok:123", ...)
```

### Idempotency

```python
def test_capture_idempotent():
    """Re-running capture does not duplicate items."""
    run_capture("tiktok:discover")
    count1 = EvidenceItem.objects.count()
    run_capture("tiktok:discover")  # same items
    count2 = EvidenceItem.objects.count()
    assert count1 == count2
```

### Bucket Math

```python
def test_bucket_alignment():
    """Bucket start aligns to hour."""
    captured_at = datetime(2025, 1, 1, 14, 23, 45)
    bucket_start = compute_bucket_start(captured_at, window_minutes=60)
    assert bucket_start == datetime(2025, 1, 1, 14, 0, 0)
```

### End-to-End

```python
def test_end_to_end_ingest_to_opportunity():
    """Full pipeline produces opportunity."""
    # 1. Capture
    run_capture("tiktok:discover")
    assert EvidenceItem.objects.count() > 0

    # 2. Normalize
    run_normalize()
    assert NormalizedArtifact.objects.count() > 0
    assert Cluster.objects.count() > 0

    # 3. Aggregate
    run_aggregate()
    assert ClusterBucket.objects.count() > 0

    # 4. Score
    run_score()
    assert TrendCandidate.objects.filter(status__in=["emerging", "active"]).exists()

    # 5. Hero integration
    bundle = build_external_signal_bundle(brand_id)
    assert len(bundle.trends) > 0

    # 6. F1 generates opportunity
    board = generate_today_board(brand_id)
    ingestion_opps = [o for o in board.opportunities if o.source.startswith("ingestion:")]
    assert len(ingestion_opps) > 0
```

### Lifecycle Sanity

```python
def test_lifecycle_transitions():
    """Lifecycle states transition correctly."""
    # Create emerging candidate
    c = create_trend_candidate(status="emerging", velocity=5)

    # Sustained activity → active
    add_bucket(c.cluster, velocity=6)
    run_score()
    c.refresh_from_db()
    assert c.status == "active"

    # Velocity drops → peaked
    add_bucket(c.cluster, velocity=-2)
    add_bucket(c.cluster, velocity=-3)
    run_score()
    c.refresh_from_db()
    assert c.status == "peaked"
```

---

## Appendix: Module Layout

```
kairo/
├── ingestion/
│   ├── __init__.py
│   ├── models.py
│   ├── admin.py
│   ├── capture/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── adapters/
│   │       ├── __init__.py
│   │       ├── tiktok_discover.py
│   │       ├── tiktok_hashtag.py
│   │       ├── instagram_explore.py
│   │       ├── instagram_hashtag.py
│   │       ├── x_trending.py
│   │       └── reddit_rising.py
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── normalize.py
│   │   ├── aggregate.py
│   │   └── score.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── trend_emitter.py
│   ├── internal_views.py
│   └── management/
│       └── commands/
│           ├── ingest_capture.py
│           ├── ingest_normalize.py
│           ├── ingest_aggregate.py
│           ├── ingest_score.py
│           └── ingest_eval.py
└── hero/
    └── services/
        └── external_signals_service.py  # modified
```

---

*End of Ingestion Spec v2*
