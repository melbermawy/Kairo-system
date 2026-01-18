"""
Core API URL routing.

PR-7: Frontend contract endpoints.
PR0: Added contract authority endpoints per opportunities_v1_prd.md §4.

URL patterns:
- GET /api/health - contract authority health check (PR0)
- GET /api/openapi.json - versioned OpenAPI schema (PR0)
- GET/POST /api/brands
- GET /api/brands/:brand_id
- GET /api/brands/:brand_id/bootstrap  (PR-7: single-request init)
- GET/PUT /api/brands/:brand_id/onboarding
- GET/POST /api/brands/:brand_id/sources
- PATCH/DELETE /api/sources/:source_id
"""

from django.urls import path

from kairo.core.api import views

app_name = "core_api"

urlpatterns = [
    # Contract Authority (PR0)
    path(
        "health",
        views.health_check,
        name="health-check",
    ),
    path(
        "openapi.json",
        views.openapi_schema,
        name="openapi-schema",
    ),
    # Brands
    path(
        "brands",
        views.brands_list_create,
        name="brands-list-create",
    ),
    path(
        "brands/<str:brand_id>",
        views.brand_detail,
        name="brand-detail",
    ),
    # Bootstrap (PR-7: single-request brand init - brand+onboarding+sources+overrides+latest)
    path(
        "brands/<str:brand_id>/bootstrap",
        views.brand_bootstrap,
        name="brand-bootstrap",
    ),
    # Onboarding
    path(
        "brands/<str:brand_id>/onboarding",
        views.onboarding_view,
        name="onboarding",
    ),
    # Sources (brand-scoped)
    path(
        "brands/<str:brand_id>/sources",
        views.sources_list_create,
        name="sources-list-create",
    ),
    # Sources (by source_id)
    path(
        "sources/<str:source_id>",
        views.source_detail,
        name="source-detail",
    ),
]
