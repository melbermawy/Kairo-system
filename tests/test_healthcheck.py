"""
Healthcheck tests for PR-0.

These tests verify the basic Django setup is working correctly.
"""

import pytest
from django.test import Client


class TestHealthcheck:
    """Test the healthcheck endpoint."""

    def test_healthcheck_returns_200(self, client: Client):
        """Healthcheck endpoint should return 200 OK."""
        response = client.get("/health/")
        assert response.status_code == 200

    def test_healthcheck_returns_json(self, client: Client):
        """Healthcheck endpoint should return JSON with status."""
        response = client.get("/health/")
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "kairo-backend"


class TestDjangoSetup:
    """Test that Django is configured correctly."""

    def test_django_can_import(self):
        """Django should be importable."""
        import django
        assert django.VERSION >= (5, 0)

    def test_settings_loaded(self):
        """Django settings should be loaded."""
        from django.conf import settings
        assert settings.configured
        assert "kairo.hero" in settings.INSTALLED_APPS

    def test_database_configured(self):
        """Database should be configured."""
        from django.conf import settings
        assert "default" in settings.DATABASES
        # In test mode, we use sqlite in-memory
        assert settings.DATABASES["default"]["ENGINE"] in (
            "django.db.backends.sqlite3",
            "django.db.backends.postgresql",
        )


# PRD-1: out of scope for PR-0 - future tests:
#
# class TestTodayBoard:
#     def test_today_board_requires_auth(self, client):
#         pass
#
# class TestPackageCreation:
#     def test_create_package_from_opportunity(self, client):
#         pass
