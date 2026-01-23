"""
Encryption utilities for API keys.

Phase 2: BYOK (Bring Your Own Key)

Uses Fernet symmetric encryption to encrypt API keys at rest.
The encryption key is stored in ENCRYPTION_KEY environment variable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Cache the Fernet instance
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Get or create the Fernet instance for encryption/decryption."""
    global _fernet

    if _fernet is not None:
        return _fernet

    encryption_key = getattr(settings, "ENCRYPTION_KEY", "")
    if not encryption_key:
        raise ValueError(
            "ENCRYPTION_KEY is not configured. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    try:
        _fernet = Fernet(encryption_key.encode())
        return _fernet
    except Exception as e:
        raise ValueError(f"Invalid ENCRYPTION_KEY: {e}")


def encrypt_api_key(plaintext: str) -> bytes:
    """
    Encrypt an API key for storage.

    Args:
        plaintext: The API key to encrypt

    Returns:
        Encrypted bytes that can be stored in BinaryField
    """
    if not plaintext:
        raise ValueError("Cannot encrypt empty string")

    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode())


def decrypt_api_key(encrypted: bytes | memoryview) -> str:
    """
    Decrypt an API key from storage.

    Args:
        encrypted: The encrypted bytes from BinaryField (may be memoryview from PostgreSQL)

    Returns:
        The decrypted API key string

    Raises:
        ValueError: If decryption fails (wrong key or corrupted data)
    """
    if not encrypted:
        raise ValueError("Cannot decrypt empty data")

    # PostgreSQL bytea fields return memoryview, convert to bytes
    if isinstance(encrypted, memoryview):
        encrypted = bytes(encrypted)

    fernet = _get_fernet()
    try:
        return fernet.decrypt(encrypted).decode()
    except InvalidToken:
        raise ValueError("Failed to decrypt API key - encryption key may have changed")


def get_last4(key: str) -> str:
    """Get the last 4 characters of an API key for display."""
    if not key or len(key) < 4:
        return ""
    return key[-4:]


def is_encryption_configured() -> bool:
    """Check if encryption is properly configured."""
    encryption_key = getattr(settings, "ENCRYPTION_KEY", "")
    return bool(encryption_key)


def get_user_apify_token(user_id) -> str | None:
    """
    Get decrypted Apify token for a user.

    Args:
        user_id: UUID of the user

    Returns:
        Decrypted Apify token or None if not configured
    """
    from kairo.users.models import UserAPIKeys

    if not user_id:
        return None

    try:
        api_keys = UserAPIKeys.objects.get(user_id=user_id)
        if api_keys.apify_token_encrypted:
            return decrypt_api_key(api_keys.apify_token_encrypted)
    except UserAPIKeys.DoesNotExist:
        pass
    except Exception as e:
        logger.warning("Failed to get user Apify token: %s", e)

    return None


def get_user_openai_key(user_id) -> str | None:
    """
    Get decrypted OpenAI API key for a user.

    Args:
        user_id: UUID of the user

    Returns:
        Decrypted OpenAI API key or None if not configured
    """
    from kairo.users.models import UserAPIKeys

    if not user_id:
        return None

    try:
        api_keys = UserAPIKeys.objects.get(user_id=user_id)
        if api_keys.openai_key_encrypted:
            return decrypt_api_key(api_keys.openai_key_encrypted)
    except UserAPIKeys.DoesNotExist:
        pass
    except Exception as e:
        logger.warning("Failed to get user OpenAI key: %s", e)

    return None
