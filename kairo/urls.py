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
    # PR-7: Core API endpoints (brands, onboarding, sources)
    path(
        "api/",
        include("kairo.core.api.urls", namespace="core_api"),
    ),
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
