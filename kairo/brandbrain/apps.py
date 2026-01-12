"""
BrandBrain app configuration.

PR-1: Data Model + Migrations + Indexes.
"""

from django.apps import AppConfig


class BrandBrainConfig(AppConfig):
    """Configuration for the BrandBrain app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "kairo.brandbrain"
    label = "brandbrain"
    verbose_name = "BrandBrain"
