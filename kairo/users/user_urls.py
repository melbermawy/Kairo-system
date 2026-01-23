"""
User settings URL routes.

Phase 2: BYOK (API Keys)
"""

from django.urls import path

from .views import UserAPIKeysView, ValidateAPIKeysView

app_name = "users"

urlpatterns = [
    path("api-keys/", UserAPIKeysView.as_view(), name="api-keys"),
    path("api-keys/validate/", ValidateAPIKeysView.as_view(), name="api-keys-validate"),
]
