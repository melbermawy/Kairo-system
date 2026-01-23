"""
User authentication and settings API views.

Phase 1: Authentication System
- /api/auth/callback/ - Sync user after Supabase auth
- /api/auth/me/ - Get current user info
- /api/auth/logout/ - Server-side logout (placeholder for now)

Phase 2: BYOK (Bring Your Own Key)
- /api/user/api-keys/ - GET/PUT user API keys
- /api/user/api-keys/validate/ - Test if API keys work
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone

from kairo.middleware.supabase_auth import get_current_user
from kairo.users.models import User, UserAPIKeys
from kairo.users.encryption import encrypt_api_key, decrypt_api_key, get_last4, is_encryption_configured
from kairo.core.models import Tenant

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class AuthCallbackView(View):
    """
    Handle post-authentication callback from frontend.

    Called after successful Supabase auth to ensure user exists in our DB
    and to set up any necessary server-side state.

    POST /api/auth/callback/
    Body: { "supabase_uid": "...", "email": "...", "display_name": "..." }

    This endpoint is called with a valid JWT, so the middleware will have
    already created the user. This just allows setting additional fields.
    """

    def post(self, request: HttpRequest) -> JsonResponse:
        # User should already be authenticated via middleware
        user = get_current_user(request)

        if user is None and not getattr(settings, "AUTH_DISABLED", False):
            return JsonResponse(
                {"error": "unauthorized", "message": "Authentication required"},
                status=401,
            )

        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            data = {}

        # If auth is disabled (dev mode), we might need to create/get user from body
        if user is None and getattr(settings, "AUTH_DISABLED", False):
            supabase_uid = data.get("supabase_uid")
            email = data.get("email")

            if not supabase_uid or not email:
                return JsonResponse(
                    {"error": "bad_request", "message": "supabase_uid and email required"},
                    status=400,
                )

            user, created = User.objects.get_or_create(
                supabase_uid=supabase_uid,
                defaults={"email": email},
            )

            if created:
                logger.info("Created user in dev mode: %s", email)

        # Update optional fields if provided
        display_name = data.get("display_name")
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            user.save(update_fields=["display_name", "updated_at"])

        # Ensure user has a tenant (create one if needed)
        if user.tenant is None:
            tenant = Tenant.objects.create(
                name=f"{user.email}'s Workspace",
                slug=f"user-{user.id.hex[:8]}",
            )
            user.tenant = tenant
            user.save(update_fields=["tenant", "updated_at"])
            logger.info("Created tenant for user: %s", user.email)

        return JsonResponse({
            "success": True,
            "user": _user_to_dict(user),
        })


class AuthMeView(View):
    """
    Get current authenticated user info.

    GET /api/auth/me/

    Returns user profile and API key status.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        user = get_current_user(request)

        if user is None:
            if getattr(settings, "AUTH_DISABLED", False):
                # In dev mode, return null user
                return JsonResponse({
                    "authenticated": False,
                    "user": None,
                    "auth_disabled": True,
                })
            return JsonResponse(
                {"error": "unauthorized", "message": "Authentication required"},
                status=401,
            )

        return JsonResponse({
            "authenticated": True,
            "user": _user_to_dict(user),
            "auth_disabled": False,
        })


@method_decorator(csrf_exempt, name="dispatch")
class AuthLogoutView(View):
    """
    Handle server-side logout.

    POST /api/auth/logout/

    Currently a placeholder - actual logout is handled by Supabase on the frontend.
    This endpoint exists for any future server-side session cleanup.
    """

    def post(self, request: HttpRequest) -> JsonResponse:
        # Nothing to do server-side currently
        # Supabase handles token invalidation
        return JsonResponse({"success": True})


def _user_to_dict(user: User) -> dict:
    """Convert user to API response dict."""
    # Check API key status
    try:
        api_keys = user.api_keys
        has_apify = api_keys.has_apify_token
        has_openai = api_keys.has_openai_key
        apify_last4 = api_keys.apify_token_last4
        openai_last4 = api_keys.openai_key_last4
    except UserAPIKeys.DoesNotExist:
        has_apify = False
        has_openai = False
        apify_last4 = None
        openai_last4 = None

    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name or user.email.split("@")[0],
        "tenant_id": str(user.tenant.id) if user.tenant else None,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "api_keys": {
            "has_apify": has_apify,
            "has_openai": has_openai,
            "apify_last4": apify_last4,
            "openai_last4": openai_last4,
            "has_all_keys": has_apify and has_openai,
        },
    }


# =============================================================================
# PHASE 2: BYOK (API Keys Management)
# =============================================================================


@method_decorator(csrf_exempt, name="dispatch")
class UserAPIKeysView(View):
    """
    Manage user API keys.

    GET /api/user/api-keys/ - Get current API key status
    PUT /api/user/api-keys/ - Save/update API keys
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """Get current API key status (not the actual keys)."""
        user = get_current_user(request)
        if user is None:
            return JsonResponse(
                {"error": "unauthorized", "message": "Authentication required"},
                status=401,
            )

        try:
            api_keys = user.api_keys
            return JsonResponse({
                "has_apify_token": api_keys.has_apify_token,
                "has_openai_key": api_keys.has_openai_key,
                "apify_last4": api_keys.apify_token_last4,
                "openai_last4": api_keys.openai_key_last4,
            })
        except UserAPIKeys.DoesNotExist:
            return JsonResponse({
                "has_apify_token": False,
                "has_openai_key": False,
                "apify_last4": None,
                "openai_last4": None,
            })

    def put(self, request: HttpRequest) -> JsonResponse:
        """Save or update API keys."""
        user = get_current_user(request)
        if user is None:
            return JsonResponse(
                {"error": "unauthorized", "message": "Authentication required"},
                status=401,
            )

        if not is_encryption_configured():
            return JsonResponse(
                {"error": "server_error", "message": "Encryption not configured"},
                status=500,
            )

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"error": "bad_request", "message": "Invalid JSON"},
                status=400,
            )

        # Get or create UserAPIKeys record
        api_keys, created = UserAPIKeys.objects.get_or_create(user=user)

        # Update Apify token if provided
        apify_token = data.get("apify_token")
        if apify_token is not None:
            if apify_token == "":
                # Clear the token
                api_keys.apify_token_encrypted = None
                api_keys.apify_token_last4 = None
                api_keys.apify_token_validated_at = None
            else:
                # Encrypt and save
                api_keys.apify_token_encrypted = encrypt_api_key(apify_token)
                api_keys.apify_token_last4 = get_last4(apify_token)
                # Clear validation since key changed
                api_keys.apify_token_validated_at = None

        # Update OpenAI key if provided
        openai_key = data.get("openai_key")
        if openai_key is not None:
            if openai_key == "":
                # Clear the key
                api_keys.openai_key_encrypted = None
                api_keys.openai_key_last4 = None
                api_keys.openai_key_validated_at = None
            else:
                # Encrypt and save
                api_keys.openai_key_encrypted = encrypt_api_key(openai_key)
                api_keys.openai_key_last4 = get_last4(openai_key)
                # Clear validation since key changed
                api_keys.openai_key_validated_at = None

        api_keys.save()

        logger.info("Updated API keys for user %s", user.email)

        return JsonResponse({
            "has_apify_token": api_keys.has_apify_token,
            "has_openai_key": api_keys.has_openai_key,
            "apify_last4": api_keys.apify_token_last4,
            "openai_last4": api_keys.openai_key_last4,
        })


@method_decorator(csrf_exempt, name="dispatch")
class ValidateAPIKeysView(View):
    """
    Validate that API keys actually work.

    POST /api/user/api-keys/validate/
    Body: { "apify_token": "...", "openai_key": "..." }

    Tests provided API keys by making simple API calls.
    Keys are passed directly (not from storage) so users can test before saving.
    """

    def post(self, request: HttpRequest) -> JsonResponse:
        user = get_current_user(request)
        if user is None:
            return JsonResponse(
                {"error": "unauthorized", "message": "Authentication required"},
                status=401,
            )

        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse(
                {"error": "bad_request", "message": "Invalid JSON"},
                status=400,
            )

        apify_token = data.get("apify_token")
        openai_key = data.get("openai_key")

        # Response format matching frontend contract
        response = {
            "apify_valid": None,
            "apify_error": None,
            "openai_valid": None,
            "openai_error": None,
        }

        # Validate Apify if provided
        if apify_token:
            apify_result = self._validate_apify_token(apify_token)
            response["apify_valid"] = apify_result["valid"]
            response["apify_error"] = apify_result.get("error")

        # Validate OpenAI if provided
        if openai_key:
            openai_result = self._validate_openai_key(openai_key)
            response["openai_valid"] = openai_result["valid"]
            response["openai_error"] = openai_result.get("error")

        return JsonResponse(response)

    def _validate_apify_token(self, token: str) -> dict:
        """Test Apify token by fetching user info."""
        import requests

        try:
            response = requests.get(
                "https://api.apify.com/v2/users/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )

            if response.status_code == 200:
                return {"valid": True}
            elif response.status_code == 401:
                return {"valid": False, "error": "Invalid token"}
            else:
                return {"valid": False, "error": f"API error: {response.status_code}"}

        except Exception as e:
            logger.exception("Error validating Apify token")
            return {"valid": False, "error": str(e)}

    def _validate_openai_key(self, key: str) -> dict:
        """Test OpenAI key by listing models."""
        import requests

        try:
            response = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )

            if response.status_code == 200:
                return {"valid": True}
            elif response.status_code == 401:
                return {"valid": False, "error": "Invalid API key"}
            else:
                return {"valid": False, "error": f"API error: {response.status_code}"}

        except Exception as e:
            logger.exception("Error validating OpenAI key")
            return {"valid": False, "error": str(e)}
