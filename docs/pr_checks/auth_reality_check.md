# Auth Reality Check: PR-7 Cross-Brand Security Tests

Analysis of authentication and ownership enforcement in the Kairo codebase.

---

## 1. Verbatim Code Findings

### 1.1 settings.py: INSTALLED_APPS, MIDDLEWARE, AUTH_* Settings

**File**: `kairo/settings.py:44-78`

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "corsheaders",
    # Kairo apps
    "kairo.core",
    "kairo.hero",
    "kairo.ingestion",
    # Integrations
    "kairo.integrations.apify.apps.ApifyConfig",
    # PR-1: BrandBrain data model
    "kairo.brandbrain.apps.BrandBrainConfig",
    # PRD-1: out of scope for PR-0 - future apps:
    # "kairo.engines.brand_brain",
    # "kairo.engines.opportunities",
    # "kairo.engines.patterns",
    # "kairo.engines.content",
    # "kairo.engines.learning",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

**File**: `kairo/settings.py:178-191`

```python
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]
```

**Observation**: Django's built-in `django.contrib.auth` is in INSTALLED_APPS and `AuthenticationMiddleware` is in MIDDLEWARE, but this is standard Django scaffolding. No custom auth configuration is present.

---

### 1.2 urls.py: Auth Routes

**File**: `kairo/urls.py` (complete)

```python
"""
URL configuration for Kairo backend.

PR-0: repo + env spine
- Only healthcheck endpoint
- No business logic routes
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("kairo.hero.urls")),
    # PR-5: BrandBrain API endpoints
    path(
        "api/brands/<str:brand_id>/brandbrain/",
        include("kairo.brandbrain.api.urls", namespace="brandbrain"),
    ),
]

# PRD-1: out of scope for PR-0 - future API routes:
# path("api/brands/", include("kairo.api.brands.urls")),
# path("api/packages/", include("kairo.api.packages.urls")),
# path("api/variants/", include("kairo.api.variants.urls")),
```

**Observation**: No login, logout, JWT, session, or token auth routes exist. Only `/admin/` (Django admin) and API routes.

---

### 1.3 Middleware/Decorators for API Auth

#### Only auth decorator found: `require_internal_token`

**File**: `kairo/hero/internal_views.py:129-157`

```python
def require_internal_token(view_func):
    """
    Decorator to require internal admin token.

    Checks X-Kairo-Internal-Token header against KAIRO_INTERNAL_ADMIN_TOKEN.
    Returns 404 if:
    - Env var is not set
    - Token is missing
    - Token is wrong

    NO dev mode. Always enforce 404.
    """

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        expected_token = _get_admin_token()

        # If no token configured, return 404 (no dev mode)
        if not expected_token:
            return HttpResponse(status=404)

        # Check token in header
        provided_token = request.headers.get("X-Kairo-Internal-Token", "")
        if provided_token != expected_token:
            return HttpResponse(status=404)

        return view_func(request, *args, **kwargs)

    return wrapper
```

**Observation**: This decorator is ONLY used on internal admin views (`/internal/*`), NOT on customer-facing API endpoints.

#### BrandBrain API Views (kairo/brandbrain/api/views.py)

```python
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

# ...

@csrf_exempt
@require_http_methods(["POST"])
def compile_kickoff(request, brand_id: str) -> JsonResponse:
    # ... no auth check ...

@require_http_methods(["GET"])
def compile_status(request, brand_id: str, compile_run_id: str) -> JsonResponse:
    # ... no auth check ...

@require_http_methods(["GET"])
def latest_snapshot(request, brand_id: str) -> JsonResponse:
    # ... no auth check ...

@require_http_methods(["GET"])
def snapshot_history(request, brand_id: str) -> JsonResponse:
    # ... no auth check ...

@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def overrides_view(request, brand_id: str) -> JsonResponse:
    # ... no auth check ...
```

**Observation**: No `@login_required`, no `@permission_required`, no custom auth decorator. Only `@require_http_methods` (HTTP method enforcement) and `@csrf_exempt` are used.

---

### 1.4 References to `request.user`

**Grep result**:

```
No matches found
```

**Observation**: `request.user` is never accessed anywhere in the codebase.

---

## 2. Search Pattern Results

### Pattern: `request.user`
```
No matches found
```

### Pattern: `login_required`
```
No matches found
```

### Pattern: `permission` (case-insensitive)
```
docs/technical/06-content-engine-deep-agent-spec.md:59:- manage user permissions or collaboration
docs/system/03-canonical-objects.md:195:frontend, learning (for per-user feedback), permissions
docs/system/03-canonical-objects.md:955:- MUST have `scopes` (permissions granted).
docs/engines/learning-engine.md:230:  - subtle reuse of patterns/tones that leak a very specific competitor's style into another brand without explicit permission.
docs/prd/kairo-v1-prd.md:47:- handle multi‑tenant orgs, complex roles/permissions, or SSO
docs/prd/kairo-v1-prd.md:426:> out-of-scope canonical objects for PRD 1 include: publishing integrations, calendar slots, multi-tenant orgs, user roles/permissions, and any asset/media objects.
docs/prd/kairo-v1-prd.md:872:  - orgs, roles/permissions, or SSO.
docs/prd/prd-map.md:247:- **F5.2**: permission checks on sensitive actions:
docs/prd/prd-map.md:262:  - permission bugs (a junior can override taboos).
```

**Observation**: All permission references are in documentation describing **future scope** ("out-of-scope for PRD 1").

### Pattern: `IsAuthenticated`
```
No matches found
```

### Pattern: `authenticate` (case-insensitive)
```
docs/technical/01-system-architecture.md:44:   - handles authenticated requests from ui.
docs/technical/01-system-architecture.md:378:   - every api call must carry an authenticated `user_id`.
```

**Observation**: Architecture docs mention authentication as a requirement, but it is **not implemented**.

### Pattern: `JWT`
```
No matches found
```

### Pattern: `SessionAuthentication`
```
No matches found
```

### Pattern: `rest_framework`
```
No matches found
```

**Observation**: Django REST Framework is not used.

---

## 3. Explicit Answers

### Is auth actually enforced on API requests today?

**NO.**

Evidence:
1. No `@login_required` or custom auth decorators on any customer API endpoints
2. `request.user` is never accessed
3. No JWT, session tokens, or API keys required
4. Django REST Framework is not installed
5. Only auth mechanism is `require_internal_token` for internal admin views (not customer APIs)
6. PRD explicitly marks permissions/auth as "out-of-scope for PRD 1"

### If YES: what is the canonical "brand ownership/tenant enforcement" pattern?

**N/A** - Auth is not enforced.

### If NO: confirm that PR-7's "cross-brand security" tests cannot represent real ownership enforcement

**CONFIRMED.**

PR-7's `TestCrossBrandSecurity` tests (5 tests) verify **data isolation by brand_id**, NOT ownership enforcement.

**Current behavior (from test file)**:

```python
class TestCrossBrandSecurity:
    """Test brand ownership enforcement across all endpoints."""

    def test_latest_returns_404_for_other_brands_snapshot(
        self, client, db, brand_with_onboarding, brand_b, ...
    ):
        """GET /latest for Brand B returns 404 (Brand A has the snapshot)."""
        # ...
        response = client.get(f"/api/brands/{brand_b.id}/brandbrain/latest")
        assert response.status_code == 404
```

**What these tests actually verify**:
- Querying `/api/brands/{brand_a_id}` returns only brand_a's data
- Querying `/api/brands/{brand_b_id}` returns only brand_b's data
- The URL path `brand_id` is respected in database queries

**What these tests do NOT verify**:
- That the caller is authorized to access brand_a or brand_b
- That the caller is logged in
- That the caller owns the brand they're querying
- Any authentication whatsoever

**Reality**: Any unauthenticated HTTP client can access any brand's data if they know the brand UUID.

---

## 4. Conclusion

### Current State

| Component | Status |
|-----------|--------|
| User auth (login/session) | **NOT IMPLEMENTED** |
| API token auth | **NOT IMPLEMENTED** |
| Brand ownership enforcement | **NOT IMPLEMENTED** |
| Cross-brand data isolation | **IMPLEMENTED** (via brand_id in URL path) |

### Test Naming Recommendation

The PR-7 test class `TestCrossBrandSecurity` with the docstring "Test brand ownership enforcement" is **misleadingly named**.

**Current name**: `TestCrossBrandSecurity`
**Current docstring**: "Test brand ownership enforcement across all endpoints."

**Recommended name**: `TestCrossBrandDataIsolation`
**Recommended docstring**: "Test that data is isolated by brand_id in URL path (no auth enforcement)."

### Security Note

Until auth is implemented:
- All API endpoints are publicly accessible
- Any client knowing a brand UUID can read/write that brand's data
- The only protection is UUID obscurity (which is NOT security)

### PRD Reference

From `docs/prd/kairo-v1-prd.md:47`:
> **Out of scope:** handle multi‑tenant orgs, complex roles/permissions, or SSO

From `docs/prd/kairo-v1-prd.md:872`:
> **v1 out-of-scope:** orgs, roles/permissions, or SSO.

This confirms auth is intentionally deferred to a future phase.

---

## 5. Verbatim Hero API Code (shows stub brand_id pattern)

**File**: `kairo/hero/api_views.py:354-357`

```python
    # Stub brand_id for now (real implementation would extract from context)
    stub_brand_id = UUID("12345678-1234-5678-1234-567812345678")
```

This pattern appears 3 times in `api_views.py`, confirming that user→brand association is explicitly stubbed/deferred.

---

## Summary

**PR-7's "cross-brand security" tests should be reframed as "data isolation by brand_id" only.** They verify that database queries are correctly scoped to the brand_id in the URL path, but they do NOT verify any authentication, authorization, or ownership enforcement—because none exists in the codebase today.
