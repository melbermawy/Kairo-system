"""
GET /today Sentinel Middleware.

PR-0: Request context tracking per opportunities_v1_prd.md Section I.1.

This middleware sets a context variable when processing GET requests to
/api/brands/{brand_id}/today/ endpoints. This allows guard functions
to detect if they're being called from a GET /today context.

The sentinel is used by tests to verify that generation logic is not
invoked during GET /today requests. Actual enforcement is in PR-1.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from django.http import HttpRequest, HttpResponse

from kairo.core.guardrails import reset_get_today_context, set_get_today_context

logger = logging.getLogger("kairo.middleware.get_today_sentinel")

# Pattern to match GET /api/brands/{uuid}/today/ or GET /api/brands/{uuid}/today
# Does NOT match /today/regenerate/
_TODAY_GET_PATTERN = re.compile(
    r"^/api/brands/[0-9a-f-]+/today/?$",
    re.IGNORECASE,
)


class GetTodaySentinelMiddleware:
    """
    Middleware that sets context sentinel for GET /today requests.

    This middleware:
    1. Detects GET requests to /api/brands/{brand_id}/today/
    2. Sets the get_today_context sentinel for the duration of the request
    3. Resets the sentinel after the request completes

    Usage in tests:
        from kairo.core.guardrails import is_in_get_today_context

        # During a GET /today request, this returns True
        assert is_in_get_today_context() == True

    Note: This middleware does not change any behavior. It only sets context
    for detection by guards and tests. Actual enforcement is in PR-1.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Check if this is a GET request to /today endpoint
        is_get_today = (
            request.method == "GET"
            and _TODAY_GET_PATTERN.match(request.path) is not None
        )

        if is_get_today:
            # Set the sentinel for this request context
            token = set_get_today_context(True)
            logger.debug("GET /today sentinel activated: path=%s", request.path)
            try:
                response = self.get_response(request)
            finally:
                reset_get_today_context(token)
                logger.debug("GET /today sentinel deactivated: path=%s", request.path)
            return response
        else:
            # Not a GET /today request, proceed normally
            return self.get_response(request)
