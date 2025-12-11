"""
Django app configuration for Kairo core.

PR-1: Canonical schema + migrations.
"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kairo.core"
    verbose_name = "Kairo Core"
