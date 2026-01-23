"""
Supabase JWT Authentication Middleware.

Phase 1: Authentication System

This middleware validates Supabase JWT tokens on incoming requests and
attaches the authenticated user to the request object.

How it works:
1. Extract JWT from Authorization header (Bearer token)
2. Decode and validate the JWT using Supabase's JWT secret
3. Look up or create the corresponding User in our database
4. Attach the user to request.kairo_user

Excluded paths (no auth required):
- /health/ - Health check endpoint
- /api/auth/ - Auth endpoints (login, signup callbacks)
- Admin paths if in dev mode
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import jwt
from django.conf import settings
from django.http import JsonResponse

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


# Paths that don't require authentication
AUTH_EXEMPT_PATHS = [
    "/health/",
    "/api/auth/",
]

# Paths that are exempt in development only
DEV_EXEMPT_PATHS = [
    "/admin/",
]


class SupabaseAuthMiddleware:
    """
    Middleware to authenticate requests using Supabase JWT tokens.

    Validates the JWT and attaches the user to the request.
    Returns 401 for unauthenticated requests to protected endpoints.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip auth for exempt paths
        if self._is_exempt_path(request.path):
            return self.get_response(request)

        # Skip auth if AUTH_DISABLED is true (dev mode)
        if getattr(settings, "AUTH_DISABLED", False):
            # In dev mode without auth, we don't attach a user
            # Views should handle request.kairo_user being None
            request.kairo_user = None
            return self.get_response(request)

        # Extract and validate the JWT
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._unauthorized_response("Missing or invalid Authorization header")

        token = auth_header[7:]  # Remove "Bearer " prefix

        try:
            user = self._authenticate_token(token)
            request.kairo_user = user
        except AuthenticationError as e:
            logger.warning("Authentication failed: %s", str(e))
            return self._unauthorized_response(str(e))

        return self.get_response(request)

    def _is_exempt_path(self, path: str) -> bool:
        """Check if the path is exempt from authentication."""
        for exempt in AUTH_EXEMPT_PATHS:
            if path.startswith(exempt):
                return True

        # Dev-only exemptions
        if settings.DEBUG:
            for exempt in DEV_EXEMPT_PATHS:
                if path.startswith(exempt):
                    return True

        return False

    def _authenticate_token(self, token: str):
        """
        Validate the JWT and return the corresponding User.

        Raises AuthenticationError if validation fails.
        """
        # Get JWT secret from settings
        jwt_secret = getattr(settings, "SUPABASE_JWT_SECRET", "")
        if not jwt_secret:
            # Try to extract from service key if not explicitly set
            # Supabase JWTs are signed with the project's JWT secret
            raise AuthenticationError("SUPABASE_JWT_SECRET not configured")

        try:
            # Decode the JWT
            # Supabase uses HS256 by default
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {e}")

        # Extract user info from payload
        supabase_uid = payload.get("sub")
        email = payload.get("email")

        if not supabase_uid:
            raise AuthenticationError("Token missing 'sub' claim")

        # Get or create the user in our database
        from kairo.users.models import User

        user, created = User.objects.get_or_create(
            supabase_uid=supabase_uid,
            defaults={
                "email": email or f"{supabase_uid}@unknown.local",
            },
        )

        if created:
            logger.info("Created new user from Supabase: %s", email)
        elif email and user.email != email:
            # Update email if it changed in Supabase
            user.email = email
            user.save(update_fields=["email", "updated_at"])

        return user

    def _unauthorized_response(self, message: str) -> JsonResponse:
        """Return a 401 Unauthorized response."""
        return JsonResponse(
            {"error": "unauthorized", "message": message},
            status=401,
        )


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


def get_current_user(request: HttpRequest):
    """
    Get the authenticated user from the request.

    Returns None if not authenticated or auth is disabled.
    Use this in views to access the current user.
    """
    return getattr(request, "kairo_user", None)


def require_auth(view_func):
    """
    Decorator to require authentication for a view.

    Use this on views that should always require auth,
    even if the path might be configured as exempt.
    """
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if user is None and not getattr(settings, "AUTH_DISABLED", False):
            return JsonResponse(
                {"error": "unauthorized", "message": "Authentication required"},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return wrapper
