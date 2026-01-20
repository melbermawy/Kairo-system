"""
Opportunities v2 Guardrails.

PR-0: Baseline guardrails per opportunities_v1_prd.md Section I.1.

This module provides:
1. Flag readers for guardrail configuration
2. Guard functions that fail fast on invariant violations
3. Context sentinels for detecting request context

These guardrails are scaffolding only - they detect and fail on violations,
but do not change existing behavior. Actual enforcement happens in PR-1+.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Literal

from django.conf import settings

logger = logging.getLogger("kairo.core.guardrails")


# =============================================================================
# EXCEPTIONS
# =============================================================================


class ApifyDisabledError(Exception):
    """
    Raised when Apify API call is attempted but APIFY_ENABLED=false.

    Per PRD Section G.2 INV-G5: Only POST /regenerate/ may trigger Apify spend.
    This exception prevents accidental spend during development and testing.
    """

    def __init__(self, message: str = "Apify is disabled (APIFY_ENABLED=false)"):
        super().__init__(message)


class GuardrailViolationError(Exception):
    """
    Raised when a PRD guardrail invariant is violated.

    This is a programming error - the code path should not be reachable
    under normal operation with correct flag configuration.
    """

    pass


# =============================================================================
# CONTEXT SENTINELS (Thread/Request-local state)
# =============================================================================

# Context variable to track if we're in a GET /today request
# Used by tests to detect if generation logic is invoked during GET
_get_today_context: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "get_today_context", default=False
)


def set_get_today_context(active: bool) -> contextvars.Token[bool]:
    """
    Set the GET /today context sentinel.

    Args:
        active: True if entering GET /today request context

    Returns:
        Token to restore previous state (use with reset_get_today_context)

    Usage (in middleware or view):
        token = set_get_today_context(True)
        try:
            # ... handle request ...
        finally:
            reset_get_today_context(token)
    """
    return _get_today_context.set(active)


def reset_get_today_context(token: contextvars.Token[bool]) -> None:
    """
    Reset the GET /today context sentinel to previous state.

    Args:
        token: Token from set_get_today_context
    """
    _get_today_context.reset(token)


def is_in_get_today_context() -> bool:
    """
    Check if currently in a GET /today request context.

    Returns:
        True if in GET /today context, False otherwise

    Usage (in guard functions):
        if is_in_get_today_context():
            raise GuardrailViolationError("Cannot call LLM during GET /today")
    """
    return _get_today_context.get()


# =============================================================================
# FLAG READERS
# =============================================================================


def is_apify_enabled() -> bool:
    """
    Check if Apify API calls are enabled.

    Returns:
        True if APIFY_ENABLED=true, False otherwise

    Default is False (safe). Must be explicitly enabled for live calls.
    """
    return getattr(settings, "APIFY_ENABLED", False)


def get_sourceactivation_mode() -> Literal["fixture_only", "live_cap_limited"]:
    """
    Get the default SourceActivation execution mode.

    Returns:
        "fixture_only" - Load pre-recorded fixtures, no Apify calls (default)
        "live_cap_limited" - Execute real Apify calls with budget caps

    Per PRD Section G.3:
    - fixture_only is mandatory for CI
    - fixture_only is default for onboarding/first visit
    - live_cap_limited only for POST /regenerate/
    """
    mode = getattr(settings, "SOURCEACTIVATION_MODE_DEFAULT", "fixture_only")
    if mode not in ("fixture_only", "live_cap_limited"):
        logger.warning(
            "Invalid SOURCEACTIVATION_MODE_DEFAULT=%r, defaulting to fixture_only",
            mode,
        )
        return "fixture_only"
    return mode


def is_today_get_read_only() -> bool:
    """
    Check if GET /today/ should be strictly read-only.

    Returns:
        True if TODAY_GET_READ_ONLY=true (default), False otherwise

    Per PRD Section G.2 INV-G1:
    GET /today/ never directly executes Apify actors or inline LLM synthesis.
    """
    return getattr(settings, "TODAY_GET_READ_ONLY", True)


def is_fixture_fallback_allowed() -> bool:
    """
    Check if fixture fallback is allowed when live mode fails.

    Returns:
        True if ALLOW_FIXTURE_FALLBACK=true (default for dev), False otherwise

    When False and mode=live_cap_limited:
    - If Apify returns 0 items → insufficient_evidence (no fixture rescue)
    - If gates fail → insufficient_evidence with real shortfall data

    Set to False for live testing to get real feedback about evidence quality.
    """
    return getattr(settings, "ALLOW_FIXTURE_FALLBACK", True)


# =============================================================================
# GUARD FUNCTIONS
# =============================================================================


def require_apify_enabled() -> None:
    """
    Guard: Raise if Apify is not enabled.

    Call this at the start of any function that makes Apify API calls.
    This ensures no accidental spend when APIFY_ENABLED=false.

    Raises:
        ApifyDisabledError: If APIFY_ENABLED is not true

    Usage:
        def call_apify_actor(...):
            require_apify_enabled()  # Fail fast
            # ... actual API call ...
    """
    if not is_apify_enabled():
        raise ApifyDisabledError(
            "Apify API calls are disabled. Set APIFY_ENABLED=true to enable. "
            "Per PRD Section G.2: Only POST /regenerate/ should enable Apify calls."
        )


def assert_not_in_get_today() -> None:
    """
    Guard: Raise if called from GET /today context.

    Call this in functions that should never run during GET /today,
    such as LLM synthesis or Apify calls.

    Raises:
        GuardrailViolationError: If called from GET /today context

    Usage:
        def run_llm_synthesis(...):
            assert_not_in_get_today()  # Fail fast
            # ... actual synthesis ...
    """
    if is_in_get_today_context():
        raise GuardrailViolationError(
            "This operation is not allowed during GET /today. "
            "Per PRD Section G.2 INV-G1: GET is read-only, no LLM or Apify calls."
        )


# =============================================================================
# COMPOSITE GUARDS
# =============================================================================


def require_live_apify_allowed() -> None:
    """
    Guard: Raise if live Apify calls are not allowed.

    This combines multiple checks:
    1. APIFY_ENABLED must be true
    2. Must not be in GET /today context

    Call this before any live Apify API call.

    Raises:
        ApifyDisabledError: If APIFY_ENABLED is not true
        GuardrailViolationError: If called from GET /today context
    """
    require_apify_enabled()
    assert_not_in_get_today()
