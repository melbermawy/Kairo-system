"""
User authentication and settings URL routes.

Phase 1: Authentication System
Phase 2: BYOK (API Keys)
"""

from django.urls import path

from .views import (
    AuthCallbackView,
    AuthMeView,
    AuthLogoutView,
    UserAPIKeysView,
    ValidateAPIKeysView,
)

# Auth routes (mounted at /api/auth/)
auth_urlpatterns = [
    path("callback/", AuthCallbackView.as_view(), name="auth-callback"),
    path("me/", AuthMeView.as_view(), name="auth-me"),
    path("logout/", AuthLogoutView.as_view(), name="auth-logout"),
]

# User settings routes (mounted at /api/user/)
user_urlpatterns = [
    path("api-keys/", UserAPIKeysView.as_view(), name="user-api-keys"),
    path("api-keys/validate/", ValidateAPIKeysView.as_view(), name="user-api-keys-validate"),
]

# Default urlpatterns for backwards compatibility (auth routes)
urlpatterns = auth_urlpatterns
