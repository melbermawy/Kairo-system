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
