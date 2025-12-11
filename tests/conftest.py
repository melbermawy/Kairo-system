"""
Pytest configuration for Kairo tests.

PR-0: Basic setup for Django test environment.
"""

import os

import django
import pytest


def pytest_configure():
    """Configure Django settings before tests run."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairo.settings")
    # Use sqlite for tests by default (faster, no docker needed)
    os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
    django.setup()


@pytest.fixture
def client():
    """Django test client fixture."""
    from django.test import Client
    return Client()
