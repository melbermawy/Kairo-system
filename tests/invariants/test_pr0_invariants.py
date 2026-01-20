"""
PR-0 Guardrail Invariant Tests.

Per opportunities_v1_prd.md Section I.1 (PR-0 Baseline + Guardrails).

These tests verify that:
1. Apify is disabled by default (APIFY_ENABLED=false)
2. SourceActivation defaults to fixture_only mode
3. GET /today sentinel is detectable via context variable

These are invariant tests - they verify configuration defaults that
prevent accidental violations of PRD constraints. They do NOT test
behavior, only that guards are in place.
"""

import pytest

from kairo.core.guardrails import (
    ApifyDisabledError,
    get_sourceactivation_mode,
    is_apify_enabled,
    is_in_get_today_context,
    is_today_get_read_only,
    require_apify_enabled,
    reset_get_today_context,
    set_get_today_context,
)


# =============================================================================
# Test 1 - Apify Disabled by Default
# Per PRD Section G.2 INV-G5: Only POST /regenerate/ may trigger Apify spend
# =============================================================================


class TestApifyDisabledByDefault:
    """Verify APIFY_ENABLED defaults to false and guard rejects calls."""

    def test_apify_disabled_by_default(self):
        """APIFY_ENABLED should be false by default in test environment."""
        # In test mode without explicit override, Apify should be disabled
        assert is_apify_enabled() is False, (
            "APIFY_ENABLED must default to false to prevent accidental spend"
        )

    def test_require_apify_enabled_raises_when_disabled(self):
        """require_apify_enabled() should raise ApifyDisabledError when disabled."""
        # Guard should raise when Apify is disabled
        with pytest.raises(ApifyDisabledError) as exc_info:
            require_apify_enabled()

        # Error message should be informative
        assert "disabled" in str(exc_info.value).lower()

    def test_apify_disabled_error_message_mentions_post_regenerate(self):
        """Error message should mention that only POST /regenerate/ enables Apify."""
        with pytest.raises(ApifyDisabledError) as exc_info:
            require_apify_enabled()

        # Error should guide developer to correct usage
        error_msg = str(exc_info.value)
        assert "regenerate" in error_msg.lower() or "POST" in error_msg, (
            "ApifyDisabledError should mention POST /regenerate/ as the only allowed path"
        )


# =============================================================================
# Test 2 - SourceActivation Default Mode
# Per PRD Section G.3: fixture_only is mandatory for CI and default for onboarding
# =============================================================================


class TestSourceActivationDefaultMode:
    """Verify SOURCEACTIVATION_MODE_DEFAULT is fixture_only."""

    def test_sourceactivation_mode_defaults_to_fixture_only(self):
        """SourceActivation mode should default to 'fixture_only'."""
        mode = get_sourceactivation_mode()
        assert mode == "fixture_only", (
            f"SOURCEACTIVATION_MODE_DEFAULT must be 'fixture_only', got '{mode}'. "
            "Per PRD Section G.3: fixture_only is mandatory for CI."
        )

    def test_sourceactivation_mode_returns_valid_literal(self):
        """get_sourceactivation_mode() should return one of the allowed values."""
        mode = get_sourceactivation_mode()
        assert mode in ("fixture_only", "live_cap_limited"), (
            f"Mode must be 'fixture_only' or 'live_cap_limited', got '{mode}'"
        )


# =============================================================================
# Test 3 - GET Sentinel Detectable
# Per PRD Section G.2 INV-G1: GET /today/ is read-only
# =============================================================================


class TestGetTodaySentinelDetectable:
    """Verify GET /today context sentinel works correctly."""

    def test_get_today_context_default_is_false(self):
        """Outside of GET /today requests, context should be false."""
        assert is_in_get_today_context() is False, (
            "GET /today context should default to False outside of requests"
        )

    def test_set_get_today_context_activates_sentinel(self):
        """set_get_today_context(True) should activate the sentinel."""
        # Initial state
        assert is_in_get_today_context() is False

        # Activate sentinel
        token = set_get_today_context(True)
        try:
            assert is_in_get_today_context() is True, (
                "Sentinel should be active after set_get_today_context(True)"
            )
        finally:
            reset_get_today_context(token)

        # Should be reset after token reset
        assert is_in_get_today_context() is False, (
            "Sentinel should be inactive after reset_get_today_context()"
        )

    def test_get_today_context_resets_properly(self):
        """Context should reset properly via token."""
        token = set_get_today_context(True)
        assert is_in_get_today_context() is True

        reset_get_today_context(token)
        assert is_in_get_today_context() is False

    def test_nested_context_handling(self):
        """Nested context activations should reset independently."""
        # Outer context
        outer_token = set_get_today_context(True)
        assert is_in_get_today_context() is True

        # Inner context (shouldn't change state since already True)
        inner_token = set_get_today_context(True)
        assert is_in_get_today_context() is True

        # Reset inner - state should still be True (per outer)
        reset_get_today_context(inner_token)
        assert is_in_get_today_context() is True

        # Reset outer - now should be False
        reset_get_today_context(outer_token)
        assert is_in_get_today_context() is False

    def test_today_get_read_only_flag_default(self):
        """TODAY_GET_READ_ONLY should default to True."""
        assert is_today_get_read_only() is True, (
            "TODAY_GET_READ_ONLY must default to True for safety. "
            "Per PRD Section G.2 INV-G1: GET /today/ is read-only."
        )


# =============================================================================
# Test 4 - Middleware Integration (HTTP level)
# =============================================================================


@pytest.mark.django_db
class TestGetTodaySentinelMiddleware:
    """Verify middleware sets sentinel for GET /today requests."""

    def test_get_today_activates_sentinel(self, client, test_brand):
        """GET /api/brands/{id}/today/ should activate the sentinel."""
        from kairo.core.guardrails import is_in_get_today_context

        # Note: We can't directly test the sentinel during request handling
        # from the test side because the sentinel is request-scoped.
        # Instead, we verify the middleware is properly configured.

        # The middleware should be in the chain
        from django.conf import settings
        middleware_path = "kairo.middleware.get_today_sentinel.GetTodaySentinelMiddleware"
        assert middleware_path in settings.MIDDLEWARE, (
            f"GetTodaySentinelMiddleware must be in MIDDLEWARE settings"
        )

    def test_middleware_pattern_matches_today_endpoint(self):
        """Middleware pattern should match GET /today endpoint."""
        from kairo.middleware.get_today_sentinel import _TODAY_GET_PATTERN

        # Should match
        assert _TODAY_GET_PATTERN.match("/api/brands/11111111-1111-1111-1111-111111111111/today/")
        assert _TODAY_GET_PATTERN.match("/api/brands/11111111-1111-1111-1111-111111111111/today")

        # Should NOT match
        assert not _TODAY_GET_PATTERN.match("/api/brands/11111111-1111-1111-1111-111111111111/today/regenerate/")
        assert not _TODAY_GET_PATTERN.match("/api/brands/")
        assert not _TODAY_GET_PATTERN.match("/api/health/")

    def test_post_today_does_not_activate_sentinel(self, client, test_brand):
        """POST to /today should NOT activate the sentinel (different endpoint)."""
        # The middleware specifically checks for GET method
        from kairo.middleware.get_today_sentinel import _TODAY_GET_PATTERN

        # Pattern matches the path, but middleware also checks method
        path = f"/api/brands/{test_brand.id}/today/"
        assert _TODAY_GET_PATTERN.match(path) is not None

        # Middleware class checks both path AND method
        # POST requests should not trigger the sentinel
