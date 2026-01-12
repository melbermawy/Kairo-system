"""Django app configuration for Apify integration."""

from django.apps import AppConfig


class ApifyConfig(AppConfig):
    """Configuration for the Apify integration app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "kairo.integrations.apify"
    label = "apify"
    verbose_name = "Apify Integration"
