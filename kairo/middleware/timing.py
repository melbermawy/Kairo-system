"""
Request timing middleware for API paths.

PR-7: Backend debug pack - provides request-level timing for API debugging.

Features:
- Logs method, path, status code, total ms, response bytes
- DB query count + total DB time (guarded by KAIRO_LOG_DB_TIMING=1)
- Request storm detection: warns if path exceeds threshold (>20/10s or >120/60s)
- Response size headers: X-Response-Bytes, X-Snapshot-Bytes

Only logs paths starting with /api/ to avoid noise from static files, admin, etc.

Usage:
    Add to MIDDLEWARE in settings.py:
    "kairo.middleware.timing.RequestTimingMiddleware"

    Enable DB timing (optional):
    export KAIRO_LOG_DB_TIMING=1
"""

import json
import logging
import os
import re
import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("kairo.timing")

# Storm detection thresholds
STORM_THRESHOLD_10S = int(os.environ.get("KAIRO_STORM_THRESHOLD_10S", "20"))
STORM_THRESHOLD_60S = int(os.environ.get("KAIRO_STORM_THRESHOLD_60S", "120"))


class RollingCounter:
    """Thread-safe rolling counter for request rate tracking."""

    def __init__(self):
        self._timestamps: list[float] = []
        self._lock = Lock()

    def record(self, now: float) -> tuple[int, int]:
        """Record a request and return (count_10s, count_60s)."""
        with self._lock:
            # Add current timestamp
            self._timestamps.append(now)

            # Prune old entries (older than 60s)
            cutoff_60s = now - 60
            self._timestamps = [t for t in self._timestamps if t > cutoff_60s]

            # Count requests in windows
            cutoff_10s = now - 10
            count_10s = sum(1 for t in self._timestamps if t > cutoff_10s)
            count_60s = len(self._timestamps)

            return count_10s, count_60s


class RequestTimingMiddleware:
    """
    Middleware that logs request timing for /api/ paths.

    Features:
    - Request timing with optional DB query stats
    - Response size tracking (X-Response-Bytes header)
    - Snapshot size tracking for relevant endpoints (X-Snapshot-Bytes header)
    - Request storm detection with per-path rate limiting warnings
    """

    # Normalize path patterns for rate tracking
    # e.g., /api/brands/abc-123/onboarding -> /api/brands/:id/onboarding
    PATH_PATTERNS = [
        (re.compile(r"/api/brands/[^/]+/brandbrain/compile/[^/]+"), "/api/brands/:id/brandbrain/compile/:run_id"),
        (re.compile(r"/api/brands/[^/]+/brandbrain"), "/api/brands/:id/brandbrain"),
        (re.compile(r"/api/brands/[^/]+"), "/api/brands/:id"),
        (re.compile(r"/api/sources/[^/]+"), "/api/sources/:id"),
    ]

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.log_db_timing = os.environ.get("KAIRO_LOG_DB_TIMING", "0") == "1"
        # Per-path rolling counters for storm detection
        self._counters: dict[str, RollingCounter] = defaultdict(RollingCounter)

    def _normalize_path(self, path: str) -> str:
        """Normalize path by replacing UUIDs/IDs with placeholders."""
        for pattern, replacement in self.PATH_PATTERNS:
            if pattern.match(path):
                return replacement
        return path

    def _get_snapshot_size(self, response: HttpResponse, path: str) -> int | None:
        """Extract snapshot_json size for relevant endpoints."""
        # Only for latest snapshot and compile status endpoints
        if "/brandbrain/latest" not in path and "/compile/" not in path:
            return None

        try:
            body = json.loads(response.content)
            # For latest endpoint
            if "snapshot_json" in body:
                return len(json.dumps(body["snapshot_json"]))
            # For compile status with nested snapshot
            if "snapshot" in body and isinstance(body["snapshot"], dict):
                snapshot = body["snapshot"]
                if "snapshot_json" in snapshot:
                    return len(json.dumps(snapshot["snapshot_json"]))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        return None

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Only time /api/ paths
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        start_time = time.perf_counter()
        now = time.time()

        # Optionally track DB queries
        db_queries_before = 0
        if self.log_db_timing:
            from django.db import connection
            db_queries_before = len(connection.queries)

        # Process request
        response = self.get_response(request)

        # Calculate timing
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000

        # Get response size
        response_bytes = len(response.content) if hasattr(response, "content") else 0

        # Get snapshot size for relevant endpoints
        snapshot_bytes = self._get_snapshot_size(response, request.path)

        # Storm detection
        normalized_path = self._normalize_path(request.path)
        count_10s, count_60s = self._counters[normalized_path].record(now)

        # Build log message
        log_parts = [
            f"{request.method} {request.path}",
            f"status={response.status_code}",
            f"ms={duration_ms:.1f}",
            f"bytes={response_bytes}",
        ]

        if snapshot_bytes is not None:
            log_parts.append(f"snapshot_bytes={snapshot_bytes}")

        # Add DB timing if enabled
        if self.log_db_timing:
            from django.db import connection
            db_queries_after = len(connection.queries)
            query_count = db_queries_after - db_queries_before

            # Calculate total DB time from queries
            db_time_ms = 0.0
            for query in connection.queries[db_queries_before:]:
                try:
                    db_time_ms += float(query.get("time", 0)) * 1000
                except (ValueError, TypeError):
                    pass

            log_parts.append(f"queries={query_count}")
            log_parts.append(f"db_ms={db_time_ms:.1f}")

        # Log at INFO level
        logger.info(" | ".join(log_parts))

        # Storm detection warning
        if count_10s > STORM_THRESHOLD_10S:
            logger.warning(
                "STORM path=%s count_10s=%d threshold=%d",
                normalized_path, count_10s, STORM_THRESHOLD_10S
            )
        elif count_60s > STORM_THRESHOLD_60S:
            logger.warning(
                "STORM path=%s count_60s=%d threshold=%d",
                normalized_path, count_60s, STORM_THRESHOLD_60S
            )

        # Add response headers
        response["X-Response-Bytes"] = str(response_bytes)
        response["X-Request-Time-Ms"] = f"{duration_ms:.1f}"

        if snapshot_bytes is not None:
            response["X-Snapshot-Bytes"] = str(snapshot_bytes)

        return response
