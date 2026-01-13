"""
Test settings for Kairo.

PR-5: Dedicated test settings that use SQLite, avoiding external DB dependencies.

This file overrides the main settings to:
1. Skip loading .env file (no external secrets needed for tests)
2. Use SQLite in-memory database (fast, no network)
3. Disable DEBUG to catch production-like issues

Usage:
    pytest uses this automatically via pyproject.toml:
    [tool.pytest.ini_options]
    DJANGO_SETTINGS_MODULE = "kairo.settings_test"
"""

import os

# Prevent dotenv from loading external DATABASE_URL
os.environ["KAIRO_TEST_MODE"] = "true"

# Import everything from base settings AFTER setting test mode
from kairo.settings import *  # noqa: F401, F403, E402

# =============================================================================
# TEST DATABASE CONFIGURATION
# =============================================================================
# Override to use SQLite in-memory for fast, isolated tests

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# =============================================================================
# TEST-SPECIFIC SETTINGS
# =============================================================================

# Disable debug in tests to catch production issues
DEBUG = False

# Use a simple password hasher for faster tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
