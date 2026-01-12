"""
Django settings for Kairo backend.

PR-0: repo + env spine
- Loads secrets from environment variables
- Database via DATABASE_URL (postgres/supabase)
- No business logic, no domain models
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# Load .env file if present (for local dev)
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# SECURITY SETTINGS (env-driven)
# =============================================================================

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-insecure-key-do-not-use-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


# =============================================================================
# APPLICATION DEFINITION
# =============================================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "corsheaders",
    # Kairo apps
    "kairo.core",
    "kairo.hero",
    "kairo.ingestion",
    # Integrations
    "kairo.integrations.apify.apps.ApifyConfig",
    # PRD-1: out of scope for PR-0 - future apps:
    # "kairo.engines.brand_brain",
    # "kairo.engines.opportunities",
    # "kairo.engines.patterns",
    # "kairo.engines.content",
    # "kairo.engines.learning",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kairo.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "kairo.wsgi.application"


# =============================================================================
# DATABASE (via DATABASE_URL)
# =============================================================================

# Default to sqlite for initial setup, but real usage requires postgres
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
)

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}


# =============================================================================
# DEV SAFETY CHECK: Detect rogue DATABASE_URL override
# =============================================================================
# Only runs in DEBUG mode. Warns if DATABASE_URL points to localhost but .env
# contains a non-localhost URL (indicating shell env is overriding .env).
# See docs/notes/dev_env_database_url_fix.md for resolution steps.

def _check_database_url_override():
    """Warn if DATABASE_URL appears to be overridden by shell environment."""
    if not DEBUG:
        return

    # Check if DATABASE_URL points to localhost
    if "localhost" not in DATABASE_URL and "127.0.0.1" not in DATABASE_URL:
        return

    # Read .env to see what it contains
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    env_value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    # If .env has non-localhost but we're using localhost, warn
                    if "localhost" not in env_value and "127.0.0.1" not in env_value:
                        import sys
                        print(
                            "\n"
                            "\033[93m" + "=" * 70 + "\033[0m\n"
                            "\033[93m⚠️  WARNING: DATABASE_URL overridden by shell environment!\033[0m\n"
                            "\033[93m" + "=" * 70 + "\033[0m\n"
                            f"  Current:  {DATABASE_URL[:60]}...\n"
                            f"  .env has: {env_value[:60]}...\n"
                            "\n"
                            "  Your shell has a rogue DATABASE_URL export.\n"
                            "  See: docs/notes/dev_env_database_url_fix.md\n"
                            "\n"
                            "  Quick fix: unset DATABASE_URL\n"
                            "  Or use:    python scripts/run_manage.py <command>\n"
                            "\033[93m" + "=" * 70 + "\033[0m\n",
                            file=sys.stderr,
                        )
                    break
    except Exception:
        pass  # Don't crash on check failure


_check_database_url_override()


# =============================================================================
# PASSWORD VALIDATION
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# =============================================================================
# STATIC FILES
# =============================================================================

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# =============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# CORS SETTINGS
# =============================================================================

CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000",
).split(",")

CORS_ALLOW_CREDENTIALS = True


# =============================================================================
# LOGGING
# =============================================================================

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "kairo": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}


# =============================================================================
# EXTERNAL SIGNALS MODE
# =============================================================================
# Controls whether external signals come from fixtures or ingestion pipeline.
# - "fixtures": Use fixture-based loader (default, for tests)
# - "ingestion": Use real ingested TrendCandidates only (NO FALLBACK)
EXTERNAL_SIGNALS_MODE = os.environ.get("EXTERNAL_SIGNALS_MODE", "fixtures")


# =============================================================================
# APIFY INTEGRATION
# =============================================================================
# Per brandbrain_spec_skeleton.md §7: Apify Integration Contract
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_BASE_URL = os.environ.get("APIFY_BASE_URL", "https://api.apify.com")


# =============================================================================
# PRD-1: OUT OF SCOPE FOR PR-0
# =============================================================================
# The following will be added in later PRs:
#
# PR-7: LLM Client + Model Policy
# - LLM_DISABLED = os.environ.get("LLM_DISABLED", "True").lower() in ("true", "1")
# - OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# - OPENAI_MODEL_M1 = os.environ.get("OPENAI_MODEL_M1", "gpt-4")
# - OPENAI_MODEL_M2 = os.environ.get("OPENAI_MODEL_M2", "gpt-4")
#
# PR-6: Observability + Run IDs
# - INCLUDE_RUN_ID_IN_LOGS = os.environ.get("INCLUDE_RUN_ID_IN_LOGS", "True")
# - SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
