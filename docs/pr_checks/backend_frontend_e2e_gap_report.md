# Backend-Frontend E2E Gap Report

Contract and gap analysis for frontend integration.

---

## A) Current BrandBrain Endpoints (Verbatim)

### kairo/urls.py:12-20

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("kairo.hero.urls")),
    # PR-5: BrandBrain API endpoints
    path(
        "api/brands/<str:brand_id>/brandbrain/",
        include("kairo.brandbrain.api.urls", namespace="brandbrain"),
    ),
]
```

### kairo/brandbrain/api/urls.py (entire file)

```python
"""
BrandBrain API URL routing.

PR-5: Compile Orchestration endpoints.
PR-7: API Surface + Overrides endpoints.

URL patterns follow spec Section 10:
- POST /api/brands/:id/brandbrain/compile
- GET /api/brands/:id/brandbrain/compile/:compile_run_id/status
- GET /api/brands/:id/brandbrain/latest
- GET /api/brands/:id/brandbrain/history
- GET/PATCH /api/brands/:id/brandbrain/overrides
"""

from django.urls import path

from kairo.brandbrain.api import views

app_name = "brandbrain"

urlpatterns = [
    # Work-path: compile kickoff
    path(
        "compile",
        views.compile_kickoff,
        name="compile-kickoff",
    ),
    # Read-path: compile status
    path(
        "compile/<str:compile_run_id>/status",
        views.compile_status,
        name="compile-status",
    ),
    # Read-path: latest snapshot
    path(
        "latest",
        views.latest_snapshot,
        name="latest-snapshot",
    ),
    # Read-path: snapshot history
    path(
        "history",
        views.snapshot_history,
        name="snapshot-history",
    ),
    # Overrides: GET (read-path) + PATCH (work-path)
    path(
        "overrides",
        views.overrides_view,
        name="overrides",
    ),
]
```

### kairo/brandbrain/api/views.py Handler Signatures

```python
@csrf_exempt
@require_http_methods(["POST"])
def compile_kickoff(request, brand_id: str) -> JsonResponse:
    """POST /api/brands/:id/brandbrain/compile"""

@require_http_methods(["GET"])
def compile_status(request, brand_id: str, compile_run_id: str) -> JsonResponse:
    """GET /api/brands/:id/brandbrain/compile/:compile_run_id/status"""

@require_http_methods(["GET"])
def latest_snapshot(request, brand_id: str) -> JsonResponse:
    """GET /api/brands/:id/brandbrain/latest"""

@require_http_methods(["GET"])
def snapshot_history(request, brand_id: str) -> JsonResponse:
    """GET /api/brands/:id/brandbrain/history"""

@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def overrides_view(request, brand_id: str) -> JsonResponse:
    """GET/PATCH /api/brands/:id/brandbrain/overrides"""
```

---

## B) Frontend-Required Endpoints: Status

| Endpoint | Method | Status | Location |
|----------|--------|--------|----------|
| `/api/brands` | GET | **MISSING** | - |
| `/api/brands` | POST | **MISSING** | - |
| `/api/brands/:brand_id` | GET | **MISSING** | - |
| `/api/brands/:brand_id/onboarding` | GET | **MISSING** | - |
| `/api/brands/:brand_id/onboarding` | PUT | **MISSING** | - |
| `/api/brands/:brand_id/sources` | GET | **MISSING** | - |
| `/api/brands/:brand_id/sources` | POST | **MISSING** | - |
| `/api/sources/:source_id` | PATCH | **MISSING** | - |
| `/api/sources/:source_id` | DELETE | **MISSING** | - |

### Detailed Search Results

#### GET /api/brands
**MISSING** - No route found. Comment in urls.py suggests future route:
```python
# path("api/brands/", include("kairo.api.brands.urls")),
```

#### POST /api/brands
**MISSING** - No route found.

#### GET /api/brands/:brand_id
**MISSING** - No route found. BrandBrain endpoints exist under `/api/brands/:brand_id/brandbrain/` but not the brand itself.

#### GET /api/brands/:brand_id/onboarding
**MISSING** - No route found. Model exists: `kairo.brandbrain.models.BrandOnboarding`

#### PUT /api/brands/:brand_id/onboarding
**MISSING** - No route found.

#### GET /api/brands/:brand_id/sources
**MISSING** - No route found. Model exists: `kairo.brandbrain.models.SourceConnection`

#### POST /api/brands/:brand_id/sources
**MISSING** - No route found.

#### PATCH /api/sources/:source_id
**MISSING** - No route found.

#### DELETE /api/sources/:source_id
**MISSING** - No route found.

---

## C) Backend Models (Verbatim Snippets)

### Brand (kairo/core/models.py:87-132)

```python
class Brand(TimestampedModel):
    """
    Brand entity - the central identity object.

    Per §3.1.1: "id, tenant_id, name, slug, primary_channel?, channels[],
    positioning, tone_tags[], taboos[], metadata{}, created_at, updated_at, deleted_at?"

    Scoped to Tenant via FK. All child models (personas, pillars, etc.) are
    scoped via Brand, not directly by tenant_id.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="brands",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100)
    primary_channel = models.CharField(
        max_length=50,
        choices=Channel.choices,
        blank=True,
        null=True,
    )
    channels = models.JSONField(default=list, blank=True)
    positioning = models.TextField(blank=True)
    tone_tags = models.JSONField(default=list, blank=True)
    taboos = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "brand"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "slug"],
                name="uniq_tenant_brand_slug",
            ),
        ]
```

**Note**: Brand requires a `tenant` FK. Frontend API will need to handle this (use default tenant or create one).

### BrandOnboarding (kairo/brandbrain/models.py:35-69)

```python
class BrandOnboarding(models.Model):
    """
    Tiered onboarding answers for a brand.

    Per spec Section 2.1:
    - 1:1 relationship with Brand
    - tier: 0, 1, or 2
    - answers_json: keyed by stable question_id
    """

    TIER_CHOICES = [
        (0, "Tier 0 - Required"),
        (1, "Tier 1 - Recommended"),
        (2, "Tier 2 - Optional"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.OneToOneField(
        Brand,
        on_delete=models.CASCADE,
        related_name="onboarding",
    )
    tier = models.PositiveSmallIntegerField(choices=TIER_CHOICES, default=0)
    answers_json = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.UUIDField(null=True, blank=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_onboarding"
```

### SourceConnection (kairo/brandbrain/models.py:77-153)

```python
class SourceConnection(models.Model):
    """
    Configuration for a content source connection.

    Per spec Section 2.2:
    - Links a brand to a platform/capability with an identifier
    - settings_json for per-source knobs (e.g., extra_start_urls for web)

    PR-1: Identifier is normalized on save() to ensure uniqueness constraint works.
    """

    PLATFORM_CHOICES = [
        ("instagram", "Instagram"),
        ("linkedin", "LinkedIn"),
        ("tiktok", "TikTok"),
        ("youtube", "YouTube"),
        ("web", "Web"),
    ]

    CAPABILITY_CHOICES = [
        # Instagram
        ("posts", "Posts"),
        ("reels", "Reels"),
        # LinkedIn
        ("company_posts", "Company Posts"),
        ("profile_posts", "Profile Posts"),
        # TikTok
        ("profile_videos", "Profile Videos"),
        # YouTube
        ("channel_videos", "Channel Videos"),
        # Web
        ("crawl_pages", "Crawl Pages"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="source_connections",
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    capability = models.CharField(max_length=30, choices=CAPABILITY_CHOICES)
    identifier = models.CharField(max_length=500)  # handle/url/channel id
    is_enabled = models.BooleanField(default=True)
    settings_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_source_connection"
        constraints = [
            # Unique source per brand/platform/capability/identifier
            models.UniqueConstraint(
                fields=["brand", "platform", "capability", "identifier"],
                name="uniq_source_brand_platform_cap_id",
            ),
        ]

    def save(self, *args, **kwargs):
        """Normalize identifier before saving to ensure uniqueness constraint works."""
        from kairo.brandbrain.identifiers import normalize_source_identifier

        self.identifier = normalize_source_identifier(
            self.platform, self.capability, self.identifier
        )
        super().save(*args, **kwargs)
```

### Tenant (kairo/core/models.py:62-79)

```python
class Tenant(TimestampedModel):
    """
    Top-level tenant / organization.

    All brand-scoped data flows through Brand → Tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)

    class Meta:
        db_table = "tenant"
```

---

## D) Implementation Decision

**Tenant Handling**: Since frontend doesn't have tenant management yet, the API will:
1. Use `get_or_create` with a default tenant `slug="default"` for all brand operations
2. This is minimal and non-breaking
3. Can be extended later for multi-tenancy

**Website URL**: Brand model has `metadata` JSONField but no `website_url` field. Will store in `metadata["website_url"]` and expose as top-level field in API response.

---

## E) Summary of Required Implementation

| Component | Action |
|-----------|--------|
| `kairo/core/api/urls.py` | CREATE - new file with brand/onboarding/sources routes |
| `kairo/core/api/views.py` | CREATE - new file with view handlers |
| `kairo/urls.py` | MODIFY - add include for core API |
| Tests | CREATE - `tests/brandbrain/test_pr7_frontend_contract_min_api.py` |
