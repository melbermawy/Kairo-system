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
