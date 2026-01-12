"""Django app configuration for ingestion module."""

from django.apps import AppConfig


class IngestionConfig(AppConfig):
    """Configuration for the ingestion app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "kairo.ingestion"
    verbose_name = "Ingestion Pipeline"
