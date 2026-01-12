# Kairo System Documentation

**Version:** 0.1.0
**Branch:** ingestion-phase1
**Generated:** January 2026

---

## 1. System Overview

Kairo is a **per-brand pre-production factory** for content creation. It ingests brand definitions and external signals, transforms them through specialized engines, and outputs structured opportunities and content packages.

### Core Philosophy
- **Per-brand isolation**: All operations scoped via Brand FK
- **Engine-based architecture**: Separation of concerns between pure computation and persistence
- **DTO contracts**: Pydantic v2 models as API boundaries
- **Immutability**: Snapshots and evidence items are frozen for reproducibility

### System Layers
```
┌─────────────────────────────────────────────────────────────┐
│                      HTTP API (views.py)                    │
├─────────────────────────────────────────────────────────────┤
│                    Services Layer (services/)               │
├─────────────────────────────────────────────────────────────┤
│                    Engines Layer (engines/)                 │
├─────────────────────────────────────────────────────────────┤
│              DTOs (dto.py) + Canonical Models (models.py)   │
├─────────────────────────────────────────────────────────────┤
│                      Database (PostgreSQL (SupaBase))       │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Project Structure

```
Kairo-system/
├── kairo/                          # Django project root
│   ├── settings.py                 # Configuration (env-driven)
│   ├── urls.py                     # URL routing
│   ├── wsgi.py                     # WSGI entry point
│   ├── core/                       # Canonical domain models
│   │   ├── models.py               # All core models (Brand, Persona, etc.)
│   │   ├── enums.py                # All domain enums
│   │   └── migrations/
│   ├── hero/                       # Hero loop (F1/F2 flows)
│   │   ├── dto.py                  # Pydantic DTOs
│   │   ├── views.py                # HTTP endpoints
│   │   ├── urls.py                 # Routes
│   │   ├── services/               # Business logic
│   │   ├── engines/                # Pure computation
│   │   ├── graphs/                 # LangGraph workflows
│   │   ├── eval/                   # Evaluation harness
│   │   └── fixtures/               # Test fixtures
│   ├── ingestion/                  # Ingestion pipeline
│   │   ├── models.py               # Pipeline models
│   │   ├── services/               # Trend emitter
│   │   ├── capture/                # Platform adapters
│   │   ├── jobs/                   # Pipeline stages
│   │   └── management/commands/    # CLI commands
│   └── integrations/               # External integrations
│       └── apify/                  # Apify scraping
│           ├── models.py           # ApifyRun, RawApifyItem
│           ├── client.py           # HTTP client
│           └── management/commands/
├── tests/                          # Pytest test suite
├── docs/                           # Documentation
│   ├── prd/                        # Product requirements
│   ├── technical/                  # Architecture docs
│   ├── engines/                    # Engine specs
│   └── eval/                       # Evaluation reports
├── scripts/                        # Utility scripts
├── manage.py                       # Django CLI
└── pyproject.toml                  # Dependencies
```

---

## 3. Core Domain Models (kairo/core/models.py)

### 3.1 Scoping Hierarchy
```
Tenant → Brand → all child models
```
- **Tenant**: Top-level organization
- **Brand**: Central identity, all content scoped here
- Child models use Brand FK (not direct tenant_id)

### 3.2 Model Definitions

#### Tenant
```python
class Tenant(TimestampedModel):
    id: UUID (primary key)
    name: str
    slug: str (unique)
```

#### Brand
```python
class Brand(TimestampedModel):
    id: UUID (primary key)
    tenant: FK(Tenant)
    name: str
    slug: str (unique per tenant)
    primary_channel: Channel (nullable)
    channels: list[str]            # JSON
    positioning: str
    tone_tags: list[str]           # JSON
    taboos: list[str]              # JSON
    metadata: dict                 # JSON
    deleted_at: datetime (nullable)
```

#### BrandSnapshot
Immutable point-in-time snapshot for LLM prompts:
```python
class BrandSnapshot(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    snapshot_at: datetime
    positioning_summary: str
    tone_descriptors: list[str]    # JSON
    taboos: list[str]              # JSON
    pillars: list[dict]            # JSON (PillarDTO shapes)
    personas: list[dict]           # JSON (PersonaDTO shapes)
```

#### Persona
```python
class Persona(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    name: str (unique per brand)
    role: str
    summary: str
    priorities: list[str]          # JSON
    pains: list[str]               # JSON
    success_metrics: list[str]     # JSON
    channel_biases: dict           # JSON
```

#### ContentPillar
```python
class ContentPillar(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    name: str (unique per brand)
    category: str
    description: str
    priority_rank: int
    is_active: bool
```

#### PatternTemplate
```python
class PatternTemplate(TimestampedModel):
    id: UUID
    brand: FK(Brand, nullable)     # null = global pattern
    name: str
    category: PatternCategory
    status: PatternStatus
    beats: list[str]               # JSON
    supported_channels: list[str]  # JSON
    example_snippet: str
    performance_hint: str
    usage_count: int
    last_used_at: datetime
    avg_engagement_score: float
```

#### Opportunity
```python
class Opportunity(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    type: OpportunityType
    score: float (0-100)
    score_explanation: str
    title: str
    angle: str
    source: str
    source_url: str
    persona: FK(Persona, nullable)
    pillar: FK(ContentPillar, nullable)
    primary_channel: Channel
    suggested_channels: list[str]  # JSON
    is_pinned: bool
    is_snoozed: bool
    snoozed_until: datetime
    created_via: CreatedVia
    last_touched_at: datetime
```

#### ContentPackage
```python
class ContentPackage(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    title: str
    status: PackageStatus
    origin_opportunity: FK(Opportunity, nullable)
    persona: FK(Persona, nullable)
    pillar: FK(ContentPillar, nullable)
    channels: list[str]            # JSON
    planned_publish_start: datetime
    planned_publish_end: datetime
    owner_user_id: UUID
    notes: str
    created_via: CreatedVia
```

#### Variant
```python
class Variant(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    package: FK(ContentPackage)
    channel: Channel
    status: VariantStatus
    pattern_template: FK(PatternTemplate, nullable)
    raw_prompt_context: dict       # JSON
    draft_text: str
    edited_text: str
    approved_text: str
    generated_by_model: str
    proposed_at: datetime
    scheduled_publish_at: datetime
    published_at: datetime
    eval_score: float
    eval_notes: str
```

#### ExecutionEvent
```python
class ExecutionEvent(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    variant: FK(Variant)
    channel: Channel
    event_type: ExecutionEventType
    decision_type: DecisionType (nullable)
    event_value: str
    count: int
    source: ExecutionSource
    occurred_at: datetime
    received_at: datetime
```

#### LearningEvent
```python
class LearningEvent(TimestampedModel):
    id: UUID
    brand: FK(Brand)
    signal_type: LearningSignalType
    pattern: FK(PatternTemplate, nullable)
    opportunity: FK(Opportunity, nullable)
    variant: FK(Variant, nullable)
    payload: dict                  # JSON
    derived_from: list[UUID]       # JSON
    effective_at: datetime
```

---

## 4. Enums (kairo/core/enums.py)

All enums are Django TextChoices stored as lowercase strings:

```python
class Channel(TextChoices):
    LINKEDIN = "linkedin"
    X = "x"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    NEWSLETTER = "newsletter"

class OpportunityType(TextChoices):
    TREND = "trend"
    EVERGREEN = "evergreen"
    COMPETITIVE = "competitive"
    CAMPAIGN = "campaign"

class PackageStatus(TextChoices):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class VariantStatus(TextChoices):
    DRAFT = "draft"
    EDITED = "edited"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    REJECTED = "rejected"

class PatternStatus(TextChoices):
    ACTIVE = "active"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"

class PatternCategory(TextChoices):
    EVERGREEN = "evergreen"
    LAUNCH = "launch"
    EDUCATION = "education"
    ENGAGEMENT = "engagement"

class ExecutionEventType(TextChoices):
    IMPRESSION = "impression"
    CLICK = "click"
    LIKE = "like"
    COMMENT = "comment"
    SHARE = "share"
    SAVE = "save"
    PROFILE_VISIT = "profile_visit"
    LINK_CLICK = "link_click"

class ExecutionSource(TextChoices):
    PLATFORM_WEBHOOK = "platform_webhook"
    CSV_IMPORT = "csv_import"
    MANUAL_ENTRY = "manual_entry"
    TEST_FIXTURE = "test_fixture"

class LearningSignalType(TextChoices):
    PATTERN_PERFORMANCE_UPDATE = "pattern_performance_update"
    OPPORTUNITY_SCORE_UPDATE = "opportunity_score_update"
    CHANNEL_PREFERENCE_UPDATE = "channel_preference_update"
    GUARDRAIL_VIOLATION = "guardrail_violation"

class CreatedVia(TextChoices):
    MANUAL = "manual"
    AI_SUGGESTED = "ai_suggested"
    IMPORTED = "imported"

class DecisionType(TextChoices):
    OPPORTUNITY_PINNED = "opportunity_pinned"
    OPPORTUNITY_SNOOZED = "opportunity_snoozed"
    OPPORTUNITY_IGNORED = "opportunity_ignored"
    PACKAGE_CREATED = "package_created"
    PACKAGE_APPROVED = "package_approved"
    VARIANT_EDITED = "variant_edited"
    VARIANT_APPROVED = "variant_approved"
    VARIANT_REJECTED = "variant_rejected"
```

---

## 5. Ingestion Pipeline (kairo/ingestion/)

### 5.1 Pipeline Stages
```
Capture → Normalize → Aggregate → Score → Emit
```

### 5.2 Ingestion Models (kairo/ingestion/models.py)

#### Surface
Scrape target definition:
```python
class Surface:
    id: UUID
    platform: str               # tiktok, instagram, x, reddit
    surface_type: str           # discover, hashtag, trending
    surface_key: str            # hashtag value if applicable
    is_enabled: bool
    cadence_minutes: int
    last_capture_at: datetime
```

#### CaptureRun
```python
class CaptureRun:
    id: UUID
    surface: FK(Surface)
    started_at: datetime
    ended_at: datetime
    status: "running" | "success" | "failed" | "partial"
    item_count: int
    error_message: str
```

#### EvidenceItem (immutable)
```python
class EvidenceItem:
    id: UUID
    capture_run: FK(CaptureRun)
    platform: str
    platform_item_id: str       # unique per platform
    item_type: str              # video, post, audio, comment
    author_id: str
    author_handle: str
    text_content: str
    audio_id: str
    audio_title: str
    hashtags: list[str]         # JSON
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    item_created_at: datetime
    captured_at: datetime
    raw_json: dict              # JSON
    canonical_url: str
```

#### Cluster
```python
class Cluster:
    id: UUID
    cluster_key_type: str       # audio_id, hashtag, phrase, entity
    cluster_key: str
    display_name: str
    platforms: list[str]        # JSON
    first_seen_at: datetime
    last_seen_at: datetime
```

#### NormalizedArtifact
```python
class NormalizedArtifact:
    id: UUID
    evidence_item: OneToOne(EvidenceItem)
    normalized_text: str
    engagement_score: float     # 0-100
```

#### ArtifactClusterLink
```python
class ArtifactClusterLink:
    id: UUID
    artifact: FK(NormalizedArtifact)
    cluster: FK(Cluster)
    role: "primary" | "secondary"
    key_type: str
    key_value: str
    rank: int
```

#### ClusterBucket
Time-windowed aggregation:
```python
class ClusterBucket:
    id: UUID
    cluster: FK(Cluster)
    bucket_start: datetime
    bucket_end: datetime
    artifact_count: int
    unique_authors: int
    total_views: int
    total_engagement: int
    avg_engagement_score: float
    velocity: float             # artifacts/hour change
    acceleration: float         # velocity change
```

#### TrendCandidate
```python
class TrendCandidate:
    id: UUID
    cluster: FK(Cluster)
    status: "emerging" | "active" | "peaked" | "stale"
    detected_at: datetime
    peaked_at: datetime
    stale_at: datetime
    trend_score: float          # 0-100
    velocity_score: float
    breadth_score: float
    novelty_score: float
    last_emitted_at: datetime
    emit_count: int
```

### 5.3 Pipeline Commands

```bash
# Stage 1: Capture items from a surface
python manage.py ingest_capture --surface tiktok_discover --dry-run

# Stage 2: Normalize evidence items
python manage.py ingest_normalize

# Stage 3: Aggregate into time buckets
python manage.py ingest_aggregate

# Stage 4: Score clusters and create trend candidates
python manage.py ingest_score

# Full pipeline (normalize → aggregate → score)
python manage.py ingest_pipeline --skip-capture
```

### 5.4 Scoring Algorithm

Two scoring paths (Path A: counter-based, Path B: sampling-based):

**Path A weights:**
- Engagement: 35%
- Velocity: 25%
- Breadth: 20%
- Novelty: 20%

**Thresholds:**
- DETECTION_THRESHOLD = 50 (min score to become TrendCandidate)
- PEAK_THRESHOLD = 80
- STALE_HOURS = 48

---

## 6. Apify Integration (kairo/integrations/apify/)

### 6.1 Models

#### ApifyRun
```python
class ApifyRun:
    id: UUID
    actor_id: str
    input_json: dict            # JSON
    apify_run_id: str (unique)
    dataset_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    item_count: int
    error_summary: str
```

#### RawApifyItem
```python
class RawApifyItem:
    id: UUID
    apify_run: FK(ApifyRun)
    item_index: int (unique per run)
    raw_json: dict              # JSON
```

### 6.2 Client (kairo/integrations/apify/client.py)

```python
class ApifyClient:
    def __init__(self, token: str, base_url: str)
    def start_actor_run(actor_id: str, input_json: dict) -> RunInfo
    def poll_run(run_id: str, timeout_s: int, interval_s: int) -> RunInfo
    def fetch_dataset_items(dataset_id: str, limit: int, offset: int) -> list[dict]
```

### 6.3 Management Command

```bash
# Mode 1: Start new run (spends budget)
python manage.py brandbrain_apify_explore \
    --actor-id "apify~instagram-scraper" \
    --input-json '{"username": ["wendys"], "resultsLimit": 20}' \
    --limit 20 \
    --save-samples 3

# Mode 2: Resume existing run (budget-safe)
python manage.py brandbrain_apify_explore \
    --existing-run-id "abc123xyz" \
    --dataset-id "def456uvw" \
    --actor-id "apify~instagram-scraper" \
    --limit 20
```

---

## 7. Hero Loop (kairo/hero/)

### 7.1 Two Main Flows

**F1: Today Board (Opportunities)**
```
ExternalSignals → OpportunitiesEngine → OpportunityCards → TodayBoard
```

**F2: Package Generation**
```
SelectedOpportunity → ContentEngine → Package + Variants
```

### 7.2 Services (kairo/hero/services/)

```python
# today_service.py
def get_today_board(brand_id: UUID) -> TodayBoardDTO
def regenerate_today_board(brand_id: UUID) -> TodayBoardDTO

# opportunities_service.py
def create_package_for_opportunity(brand_id: UUID, opportunity_id: UUID) -> CreatePackageResponseDTO

# content_packages_service.py
def get_package(package_id: UUID) -> ContentPackageDTO

# variants_service.py
def generate_variants_for_package(package_id: UUID) -> GenerateVariantsResponseDTO
def list_variants_for_package(package_id: UUID) -> VariantListDTO
def update_variant(variant_id: UUID, payload: dict) -> VariantDTO

# external_signals_service.py
def get_bundle_for_brand(brand_id: UUID) -> ExternalSignalBundleDTO
# Mode-aware: "fixtures" or "ingestion" based on EXTERNAL_SIGNALS_MODE setting

# learning_service.py
# Process execution events, generate learning events

# decisions_service.py
# Record user decisions (pin, snooze, approve, etc.)
```

### 7.3 Engines (kairo/hero/engines/)

Pure Python computation modules (no Django ORM mutations):

```python
# opportunities_engine.py
def generate_today_board(brand_id: UUID) -> TodayBoardDTO

# content_engine.py
def create_package_from_opportunity(brand_id, opportunity_id) -> Package
def generate_variants_for_package(package_id) -> list[Variant]

# learning_engine.py
def process_execution_events(brand_id)
def summarize_learning_for_brand(brand_id) -> LearningSummaryDTO  # in-memory DTO
```

### 7.4 Eval Command

```bash
python manage.py run_hero_eval \
    --brand-slug wendys \
    --llm-enabled \
    --max-opportunities 5
```

Outputs JSON + Markdown to `docs/eval/hero_loop/`.

---

## 8. DTOs (kairo/hero/dto.py)

### 8.1 Brand Context

```python
class BrandSnapshotDTO(BaseModel):
    brand_id: UUID
    brand_name: str
    positioning: str | None
    pillars: list[PillarDTO]
    personas: list[PersonaDTO]
    voice_tone_tags: list[str]
    taboos: list[str]

class PersonaDTO(BaseModel):
    id: UUID
    name: str
    role: str | None
    summary: str
    priorities: list[str]
    pains: list[str]
    success_metrics: list[str]
    channel_biases: dict[str, str]

class PillarDTO(BaseModel):
    id: UUID
    name: str
    category: str | None
    description: str
    priority_rank: int | None
    is_active: bool
```

### 8.2 Opportunity

```python
class OpportunityDTO(BaseModel):
    id: UUID
    brand_id: UUID
    title: str
    angle: str
    type: OpportunityType
    primary_channel: Channel
    score: float  # 0-100
    score_explanation: str | None
    source: str
    source_url: str | None
    persona_id: UUID | None
    pillar_id: UUID | None
    suggested_channels: list[Channel]
    is_pinned: bool
    is_snoozed: bool
    snoozed_until: datetime | None
    created_via: CreatedVia
    created_at: datetime
    updated_at: datetime

class OpportunityDraftDTO(BaseModel):
    proposed_title: str
    proposed_angle: str
    type: OpportunityType
    primary_channel: Channel
    suggested_channels: list[Channel]
    score: float
    score_explanation: str | None
    source: str
    source_url: str | None
    persona_hint: str | None
    pillar_hint: str | None
    raw_reasoning: str | None
    is_valid: bool
    rejection_reasons: list[str]
    why_now: str | None
```

### 8.3 Package & Variant

```python
class ContentPackageDTO(BaseModel):
    id: UUID
    brand_id: UUID
    title: str
    status: PackageStatus
    origin_opportunity_id: UUID | None
    persona_id: UUID | None
    pillar_id: UUID | None
    channels: list[Channel]
    planned_publish_start: datetime | None
    planned_publish_end: datetime | None
    created_via: CreatedVia
    created_at: datetime
    updated_at: datetime

class VariantDTO(BaseModel):
    id: UUID
    package_id: UUID
    brand_id: UUID
    channel: Channel
    status: VariantStatus
    pattern_template_id: UUID | None
    body: str
    call_to_action: str | None
    generated_by_model: str | None
    eval_score: float | None
    created_at: datetime
    updated_at: datetime
```

### 8.4 External Signals

```python
class ExternalSignalBundleDTO(BaseModel):
    brand_id: UUID
    fetched_at: datetime
    trends: list[TrendSignalDTO]
    web_mentions: list[WebMentionSignalDTO]
    competitor_posts: list[CompetitorPostSignalDTO]
    social_moments: list[SocialMomentSignalDTO]

class TrendSignalDTO(BaseModel):
    id: str
    topic: str
    source: str
    relevance_score: float  # 0-100
    recency_days: int
    url: str | None
    snippet: str | None
```

### 8.5 Today Board

```python
class TodayBoardDTO(BaseModel):
    brand_id: UUID
    snapshot: BrandSnapshotDTO
    opportunities: list[OpportunityDTO]
    meta: TodayBoardMetaDTO

class TodayBoardMetaDTO(BaseModel):
    generated_at: datetime
    source: str
    degraded: bool
    total_candidates: int | None
    reason: str | None
    notes: list[str]
    opportunity_count: int
    dominant_pillar: str | None
    dominant_persona: str | None
    channel_mix: dict[str, int]
```

---

## 9. Configuration (kairo/settings.py)

### Environment Variables

```bash
# Core Django
DJANGO_SECRET_KEY      # Secret key (has dev default)
DJANGO_DEBUG           # Debug mode (default: False)
ALLOWED_HOSTS          # Comma-separated hosts

# Database
DATABASE_URL           # PostgreSQL connection string (default: sqlite)

# CORS
CORS_ALLOWED_ORIGINS   # Comma-separated origins (default: localhost:3000)

# Logging
LOG_LEVEL              # DEBUG, INFO, WARNING, ERROR (default: INFO)

# External Signals Mode
EXTERNAL_SIGNALS_MODE  # "fixtures" or "ingestion" (default: fixtures)

# Apify Integration
APIFY_TOKEN            # Apify API token
APIFY_BASE_URL         # API base URL (default: https://api.apify.com)
```

### Installed Apps

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "kairo.core",
    "kairo.hero",
    "kairo.ingestion",
    "kairo.integrations.apify.apps.ApifyConfig",
]
```

---

## 10. Test Structure

```
tests/
├── conftest.py                     # Pytest configuration
├── fixtures/                       # Test data
├── test_healthcheck.py             # Smoke tests
├── test_models_schema.py           # Model validation
├── test_dto_roundtrip.py           # DTO serialization
├── test_services_*.py              # Service layer tests
├── test_engines_stub_behavior.py   # Engine stubs
├── test_opportunities_engine_integration.py  # F1 flow
├── test_content_engine_integration.py        # F2 flow
├── test_learning_pipeline.py       # Learning loop
├── test_external_signals_service.py
├── test_llm_client.py
├── test_quality_classifier.py
├── test_package_graph.py
├── test_opportunities_graph.py
├── test_eval_hero_loop.py          # End-to-end eval
├── test_management_commands.py
├── ingestion/                      # Ingestion tests
│   ├── test_models.py
│   ├── test_jobs.py
│   ├── test_adapters.py
│   └── test_trend_emitter.py
└── integrations/apify/             # Apify tests
    ├── test_client.py
    ├── test_models.py
    └── test_command.py
```

### Running Tests

```bash
# All tests
DATABASE_URL=sqlite://:memory: pytest -v

# Specific module
DATABASE_URL=sqlite://:memory: pytest tests/integrations/apify/ -v

# With coverage
DATABASE_URL=sqlite://:memory: pytest --cov=kairo --cov-report=html
```

---

## 11. Key Design Principles

### 11.1 Separation of Concerns
- **Views/APIs**: Never touch DB directly for domain logic - call engines
- **Engines**: Pure Python modules (no Django ORM mutation)
- **Services**: Wrap engines for cross-cutting concerns

### 11.2 Immutability & Reproducibility
- BrandSnapshots are immutable once created
- EvidenceItems & RawApifyItems are immutable
- Use snapshots for LLM prompts for determinism

### 11.3 Scoping Hierarchy
- Everything scoped via Brand FK, not direct tenant_id
- Tenant → Brand → all child models
- Multi-tenancy via Tenant isolation

### 11.4 Enum Single Source of Truth
- All enums defined once in core/enums.py
- Django TextChoices (stored as lowercase strings)
- Imported directly by DTOs (avoid duplication)

### 11.5 DTO Contracts
- Once defined, fields are breaking changes
- Use Pydantic v2 BaseModels
- Explicit validation at API boundaries

---

## 12. Management Commands Summary

```bash
# Hero Loop
python manage.py run_hero_eval --brand-slug <slug> [--llm-enabled]

# Ingestion Pipeline
python manage.py ingest_capture --surface <type> [--dry-run]
python manage.py ingest_normalize
python manage.py ingest_aggregate
python manage.py ingest_score
python manage.py ingest_pipeline [--skip-capture]

# Apify Exploration
python manage.py brandbrain_apify_explore \
    --actor-id "apify~instagram-scraper" \
    --input-json '{"username": ["wendys"]}' \
    --limit 20
```

---

## 13. API Endpoints (Planned)

```
GET  /api/health                           # Health check
GET  /api/brands/{brand_id}/today          # Get today board
POST /api/brands/{brand_id}/today/regenerate
POST /api/brands/{brand_id}/opportunities/{opp_id}/packages
GET  /api/packages/{package_id}
POST /api/packages/{package_id}/variants/generate
GET  /api/packages/{package_id}/variants
PATCH /api/variants/{variant_id}
POST /api/opportunities/{opp_id}/decision
POST /api/packages/{pkg_id}/decision
POST /api/variants/{var_id}/decision
```

---

## 14. Dependencies

```toml
[project]
name = "kairo"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "django>=5.0,<6.0",
    "dj-database-url>=2.1.0",
    "psycopg2-binary>=2.9.9",
    "python-dotenv>=1.0.0",
    "django-cors-headers>=4.3.0",
    "markdown>=3.5.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-django>=4.8.0",
]
```

---

## 15. Quick Start

```bash
# 1. Clone and setup
cd Kairo-system
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, APIFY_TOKEN, etc.

# 3. Run migrations
python manage.py migrate

# 4. Verify setup
python manage.py check

# 5. Run tests
DATABASE_URL=sqlite://:memory: pytest -v

# 6. Run hero eval (with fixtures)
python manage.py run_hero_eval --brand-slug wendys --list-brands
```

---

## 16. Current Branch Status (ingestion-phase1)

### Modified Files
- `kairo/settings.py` - EXTERNAL_SIGNALS_MODE config
- `kairo/hero/services/external_signals_service.py` - Mode-aware signals
- `tests/test_external_signals_service.py` - Signal service tests

### New Directories
- `kairo/ingestion/` - Full ingestion pipeline
- `docs/audits/` - Audit documentation

### Pending Work
- Phase 2: Scheduled ingestion, retry logic, rate limiting
- LLM Integration for agents/generators
- Multi-tenant isolation enhancements
- UI/Frontend integration

---

## 17. File Quick Reference

| File | Purpose |
|------|---------|
| `kairo/core/models.py` | All canonical domain models |
| `kairo/core/enums.py` | All domain enums |
| `kairo/hero/dto.py` | All Pydantic DTOs |
| `kairo/hero/services/` | Business logic layer |
| `kairo/hero/engines/` | Pure computation modules |
| `kairo/ingestion/models.py` | Pipeline models |
| `kairo/ingestion/jobs/` | Pipeline stages (normalize, aggregate, score) |
| `kairo/integrations/apify/` | Apify scraping integration |
| `kairo/settings.py` | Configuration |
| `docs/system/01-overall-system.md` | System overview |
| `docs/prd/ingestion_spec_v2.md` | Ingestion specification |

---

*End of System Documentation*
