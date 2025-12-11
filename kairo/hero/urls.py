"""
URL routes for the hero app.

PR-0: Healthcheck endpoint.
PR-2: Hero loop API endpoints with stub responses.

Note on URL design (see docs/contracts/api.md "Versioning & Path Scoping"):
- URLs are currently unversioned (no /v1 prefix).
- Package/variant endpoints are not brand-scoped in the path but are scoped in the DB via FK.
- This is a conscious choice for PRD-1 and may change when we expose these externally.
"""

from django.urls import path

from . import api_views, views

app_name = "hero"

urlpatterns = [
    # PR-0: Healthcheck
    path("health/", views.healthcheck, name="healthcheck"),

    # PR-2: Today Board endpoints
    path(
        "api/brands/<str:brand_id>/today/",
        api_views.get_today_board,
        name="today_board",
    ),
    path(
        "api/brands/<str:brand_id>/today/regenerate/",
        api_views.regenerate_today_board,
        name="regenerate_today",
    ),

    # PR-2: Package endpoints
    path(
        "api/brands/<str:brand_id>/opportunities/<str:opportunity_id>/packages/",
        api_views.create_package_from_opportunity,
        name="create_package",
    ),
    path(
        "api/packages/<str:package_id>/",
        api_views.get_package,
        name="get_package",
    ),

    # PR-2: Variant endpoints
    path(
        "api/packages/<str:package_id>/variants/generate/",
        api_views.generate_variants,
        name="generate_variants",
    ),
    path(
        "api/packages/<str:package_id>/variants/",
        api_views.get_variants,
        name="get_variants",
    ),
    path(
        "api/variants/<str:variant_id>/",
        api_views.update_variant,
        name="update_variant",
    ),

    # PR-2: Decision endpoints
    path(
        "api/opportunities/<str:opportunity_id>/decision/",
        api_views.record_opportunity_decision,
        name="opportunity_decision",
    ),
    path(
        "api/packages/<str:package_id>/decision/",
        api_views.record_package_decision,
        name="package_decision",
    ),
    path(
        "api/variants/<str:variant_id>/decision/",
        api_views.record_variant_decision,
        name="variant_decision",
    ),
]
