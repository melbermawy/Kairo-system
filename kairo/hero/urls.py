"""
URL routes for the hero app.

PR-0: Only healthcheck endpoint.
"""

from django.urls import path

from . import views

app_name = "hero"

urlpatterns = [
    path("health/", views.healthcheck, name="healthcheck"),
]

# PRD-1: out of scope for PR-0 - future routes:
# path("api/brands/<uuid:brand_id>/today/", views.today_board, name="today_board"),
# path("api/brands/<uuid:brand_id>/today/regenerate/", views.regenerate_today, name="regenerate_today"),
# path("api/brands/<uuid:brand_id>/opportunities/<uuid:opp_id>/packages/", views.create_package, name="create_package"),
