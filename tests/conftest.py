"""
Pytest configuration for Kairo tests.

PR-0: Basic setup for Django test environment.
PR-0: BrandBrain test fixtures and helpers.
PR-5: Fixed test DB configuration to use SQLite (no external dependencies).

Database configuration is handled by kairo.settings_test (set in pyproject.toml).
"""

import uuid

import pytest


@pytest.fixture
def client():
    """Django test client fixture."""
    from django.test import Client
    return Client()


# =============================================================================
# BRANDBRAIN FIXTURES
# =============================================================================


@pytest.fixture
def sample_brand_id() -> str:
    """Return a stable UUID for test brands."""
    return "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def sample_tenant_id() -> str:
    """Return a stable UUID for test tenants."""
    return "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def sample_compile_run_id() -> str:
    """Return a stable UUID for test compile runs."""
    return "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def test_tenant(db):
    """
    Create a test Tenant in the database.

    Note: The `db` fixture dependency grants DB access; @pytest.mark.django_db
    on fixtures is deprecated (PytestRemovedIn9Warning).
    """
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        name="Test Tenant",
        slug="test-tenant",
    )


@pytest.fixture
def test_brand(db, test_tenant):
    """
    Create a test Brand in the database.

    Note: The `db` fixture dependency grants DB access; @pytest.mark.django_db
    on fixtures is deprecated (PytestRemovedIn9Warning).
    """
    from kairo.core.models import Brand

    return Brand.objects.create(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        tenant=test_tenant,
        name="Test Brand",
        slug="test-brand",
        positioning="We help developers build better software.",
    )


# =============================================================================
# BRANDBRAIN DICT BUILDERS (for tests that don't need DB)
# =============================================================================


@pytest.fixture
def brand_dict():
    """Return a brand dict using the builder."""
    from tests.brandbrain.builders import build_brand
    return build_brand()


@pytest.fixture
def onboarding_answers_tier0():
    """Return Tier 0 onboarding answers using the builder."""
    from tests.brandbrain.builders import build_onboarding_answers_tier0
    return build_onboarding_answers_tier0()


@pytest.fixture
def normalized_evidence_item():
    """Return a NormalizedEvidenceItem stub using the builder."""
    from tests.brandbrain.builders import build_normalized_evidence_item_stub
    return build_normalized_evidence_item_stub()


@pytest.fixture
def brandbrain_snapshot():
    """Return a BrandBrainSnapshot stub using the builder."""
    from tests.brandbrain.builders import build_snapshot_stub
    return build_snapshot_stub()
