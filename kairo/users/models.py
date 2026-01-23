"""
User models for Kairo authentication.

Phase 1: Authentication System
- User model links to Supabase Auth via supabase_uid
- UserAPIKeys stores encrypted API keys for BYOK (Phase 2)
- Users belong to Tenants for multi-tenancy
"""

import uuid

from django.db import models

from kairo.core.models import Tenant, TimestampedModel


class User(TimestampedModel):
    """
    Kairo user account.

    Links to Supabase Auth for actual authentication.
    The supabase_uid is the unique identifier from Supabase Auth.

    Users belong to a Tenant for multi-tenant isolation.
    A user can access all Brands within their Tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    supabase_uid = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique identifier from Supabase Auth",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,  # Temporarily nullable for initial migration
        blank=True,
    )

    # Profile info (synced from Supabase or set by user)
    display_name = models.CharField(max_length=255, blank=True)

    # Account status
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "kairo_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return self.email


class UserAPIKeys(TimestampedModel):
    """
    Encrypted API keys for a user (BYOK - Bring Your Own Key).

    Phase 2: Users provide their own Apify and OpenAI keys.
    Keys are encrypted at rest using Fernet symmetric encryption.

    We store the last 4 characters of each key for display purposes
    so users can identify which key they've connected.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )

    # Encrypted API keys (binary data)
    apify_token_encrypted = models.BinaryField(null=True, blank=True)
    openai_key_encrypted = models.BinaryField(null=True, blank=True)

    # Last 4 characters for display (e.g., "...3Bvt")
    apify_token_last4 = models.CharField(max_length=4, null=True, blank=True)
    openai_key_last4 = models.CharField(max_length=4, null=True, blank=True)

    # Validation timestamps (when keys were last verified to work)
    apify_token_validated_at = models.DateTimeField(null=True, blank=True)
    openai_key_validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "kairo_user_api_keys"
        verbose_name = "User API Keys"
        verbose_name_plural = "User API Keys"

    def __str__(self) -> str:
        return f"API Keys for {self.user.email}"

    @property
    def has_apify_token(self) -> bool:
        """Check if user has an Apify token configured."""
        return self.apify_token_encrypted is not None

    @property
    def has_openai_key(self) -> bool:
        """Check if user has an OpenAI key configured."""
        return self.openai_key_encrypted is not None

    @property
    def has_all_keys(self) -> bool:
        """Check if user has both required keys configured."""
        return self.has_apify_token and self.has_openai_key
