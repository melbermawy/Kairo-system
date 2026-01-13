"""
Core API URL routing.

PR-7: Frontend contract endpoints.

URL patterns:
- GET/POST /api/brands
- GET /api/brands/:brand_id
- GET/PUT /api/brands/:brand_id/onboarding
- GET/POST /api/brands/:brand_id/sources
- PATCH/DELETE /api/sources/:source_id
"""

from django.urls import path

from kairo.core.api import views

app_name = "core_api"

urlpatterns = [
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
