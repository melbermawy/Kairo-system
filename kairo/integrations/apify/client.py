"""
Apify API v2 client.

Per brandbrain_spec_skeleton.md §7: Apify Integration Contract.

Implements exactly 3 primitives:
1. start_actor_run(actor_id, input_json) -> RunInfo
2. poll_run(run_id, timeout_s, interval_s) -> RunInfo
3. fetch_dataset_items(dataset_id, limit, offset) -> list[dict]

Endpoints per Apify API v2 docs (https://docs.apify.com/api/v2):
- POST /v2/acts/{actorId}/runs - start actor run
- GET /v2/actor-runs/{runId} - get run status
- GET /v2/datasets/{datasetId}/items - fetch dataset items

PR-0 GUARDRAILS:
All API calls are guarded by require_apify_enabled() from kairo.core.guardrails.
If APIFY_ENABLED=false (default), any API call raises ApifyDisabledError.
This prevents accidental spend during development and testing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import requests

from kairo.core.guardrails import require_apify_enabled

logger = logging.getLogger(__name__)


class ApifyError(Exception):
    """Raised when Apify API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        self.status_code = status_code
        self.body = body[:500] if body else None  # Trim body for logging
        super().__init__(message)


class ApifyTimeoutError(ApifyError):
    """Raised when polling for run completion times out."""

    pass


@dataclass
class RunInfo:
    """
    Information about an Apify actor run.

    Status values per Apify API:
    - READY: Waiting to be allocated on a server
    - RUNNING: Actor is currently executing
    - SUCCEEDED: Actor completed successfully
    - FAILED: Actor run failed
    - TIMED-OUT: Actor run timed out
    - ABORTED: Actor run was aborted
    """

    run_id: str
    actor_id: str
    status: str
    dataset_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None = None

    def is_terminal(self) -> bool:
        """Return True if run is in a terminal state."""
        return self.status in ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED")

    def is_success(self) -> bool:
        """Return True if run succeeded."""
        return self.status == "SUCCEEDED"


class ApifyClient:
    """
    HTTP client for Apify API v2.

    Authentication via Bearer token (recommended by Apify docs).
    """

    def __init__(self, token: str, base_url: str = "https://api.apify.com"):
        """
        Initialize Apify client.

        Args:
            token: Apify API token
            base_url: Base URL for Apify API (default: https://api.apify.com)
        """
        if not token:
            raise ValueError("Apify token is required")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    def start_actor_run(self, actor_id: str, input_json: dict[str, Any]) -> RunInfo:
        """
        Start an actor run.

        Args:
            actor_id: Actor ID (e.g., "apify/instagram-reel-scraper")
            input_json: Input configuration for the actor

        Returns:
            RunInfo with initial run status

        Raises:
            ApifyDisabledError: If APIFY_ENABLED=false (PR-0 guardrail)
            ApifyError: If API returns an error
        """
        # PR-0: Global kill switch - fail fast if Apify is disabled
        require_apify_enabled()

        # TASK-2 FIX: URL-encode actor_id to handle slashes (e.g., apify/instagram-scraper → apify%2Finstagram-scraper)
        # Without encoding, "apify/instagram-scraper" becomes path segments instead of actor ID
        encoded_actor_id = quote(actor_id, safe="")
        url = f"{self.base_url}/v2/acts/{encoded_actor_id}/runs"

        # TASK-2: Hard observability - log APIFY_CALL_START
        call_start_ms = time.monotonic() * 1000
        logger.info(
            "APIFY_CALL_START actor_id=%s url=%s",
            actor_id,
            url,
        )

        try:
            response = self._session.post(url, json=input_json, timeout=30)
            duration_ms = int(time.monotonic() * 1000 - call_start_ms)
        except requests.exceptions.SSLError as e:
            duration_ms = int(time.monotonic() * 1000 - call_start_ms)
            logger.error(
                "APIFY_CALL_END actor_id=%s status=SSL_ERROR duration_ms=%d error=%s",
                actor_id,
                duration_ms,
                str(e),
            )
            raise ApifyError(
                "SSL/TLS connection error to Apify. This may be a network issue or "
                "firewall blocking HTTPS connections. Please check your network settings."
            ) from e
        except requests.exceptions.ConnectionError as e:
            duration_ms = int(time.monotonic() * 1000 - call_start_ms)
            logger.error(
                "APIFY_CALL_END actor_id=%s status=CONNECTION_ERROR duration_ms=%d error=%s",
                actor_id,
                duration_ms,
                str(e),
            )
            raise ApifyError(
                "Could not connect to Apify API. Please check your network connection."
            ) from e
        except requests.exceptions.Timeout as e:
            duration_ms = int(time.monotonic() * 1000 - call_start_ms)
            logger.error(
                "APIFY_CALL_END actor_id=%s status=TIMEOUT duration_ms=%d error=%s",
                actor_id,
                duration_ms,
                str(e),
            )
            raise ApifyError(
                "Connection to Apify API timed out. The service may be slow or overloaded."
            ) from e
        except requests.RequestException as e:
            duration_ms = int(time.monotonic() * 1000 - call_start_ms)
            # TASK-2: Log APIFY_CALL_END with error
            logger.error(
                "APIFY_CALL_END actor_id=%s status=ERROR duration_ms=%d error=%s",
                actor_id,
                duration_ms,
                str(e),
            )
            raise ApifyError(f"Request failed: {e}") from e

        if not response.ok:
            # TASK-2: Log APIFY_CALL_END with HTTP error
            logger.error(
                "APIFY_CALL_END actor_id=%s status=HTTP_ERROR duration_ms=%d http_status=%d error=%s",
                actor_id,
                duration_ms,
                response.status_code,
                response.text[:200],
            )
            # Provide more helpful error messages for common status codes
            if response.status_code == 401:
                error_msg = (
                    "Apify authentication failed (401). Your Apify token may be invalid, "
                    "expired, or you may have run out of credits. Please check your token "
                    "in Settings or visit apify.com to verify your account status."
                )
            elif response.status_code == 403:
                error_msg = (
                    "Apify access denied (403). Your account may not have permission to run "
                    "this actor, or your subscription tier may not support it."
                )
            elif response.status_code == 402:
                error_msg = (
                    "Apify payment required (402). Your Apify credits are exhausted. "
                    "Please add credits at apify.com or update your subscription."
                )
            else:
                error_msg = f"Failed to start actor run: HTTP {response.status_code}"

            raise ApifyError(
                error_msg,
                status_code=response.status_code,
                body=response.text,
            )

        data = response.json().get("data", {})
        run_info = self._parse_run_info(data, actor_id)

        # TASK-2: Log APIFY_CALL_END with success
        logger.info(
            "APIFY_CALL_END actor_id=%s run_id=%s status=STARTED duration_ms=%d apify_status=%s",
            actor_id,
            run_info.run_id,
            duration_ms,
            run_info.status,
        )
        return run_info

    def poll_run(
        self,
        run_id: str,
        timeout_s: int = 180,
        interval_s: int = 3,
    ) -> RunInfo:
        """
        Poll run status until terminal state or timeout.

        Args:
            run_id: Apify run ID
            timeout_s: Maximum time to wait (seconds)
            interval_s: Polling interval (seconds)

        Returns:
            RunInfo with final status

        Raises:
            ApifyDisabledError: If APIFY_ENABLED=false (PR-0 guardrail)
            ApifyTimeoutError: If polling times out
            ApifyError: If API returns an error
        """
        # PR-0: Global kill switch - fail fast if Apify is disabled
        require_apify_enabled()

        url = f"{self.base_url}/v2/actor-runs/{run_id}"
        start_time = time.monotonic()
        logger.info("Polling run: run_id=%s, timeout_s=%d", run_id, timeout_s)

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout_s:
                raise ApifyTimeoutError(
                    f"Polling timed out after {timeout_s}s for run_id={run_id}"
                )

            try:
                response = self._session.get(url, timeout=30)
            except requests.RequestException as e:
                raise ApifyError(f"Request failed: {e}") from e

            if not response.ok:
                raise ApifyError(
                    f"Failed to get run status: {response.status_code}",
                    status_code=response.status_code,
                    body=response.text,
                )

            data = response.json().get("data", {})
            # Extract actor_id from response or use empty string
            actor_id = data.get("actId", data.get("actorId", ""))
            run_info = self._parse_run_info(data, actor_id)

            if run_info.is_terminal():
                logger.info(
                    "Run completed: run_id=%s, status=%s",
                    run_info.run_id,
                    run_info.status,
                )
                return run_info

            logger.debug(
                "Run still in progress: run_id=%s, status=%s, elapsed=%.1fs",
                run_id,
                run_info.status,
                elapsed,
            )
            time.sleep(interval_s)

    def fetch_dataset_items(
        self,
        dataset_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Fetch items from a dataset.

        Args:
            dataset_id: Dataset ID
            limit: Maximum items to fetch
            offset: Number of items to skip

        Returns:
            List of raw item dictionaries

        Raises:
            ApifyDisabledError: If APIFY_ENABLED=false (PR-0 guardrail)
            ApifyError: If API returns an error
        """
        # PR-0: Global kill switch - fail fast if Apify is disabled
        require_apify_enabled()

        url = f"{self.base_url}/v2/datasets/{dataset_id}/items"
        params = {"limit": limit, "offset": offset}
        logger.info(
            "Fetching dataset items: dataset_id=%s, limit=%d, offset=%d",
            dataset_id,
            limit,
            offset,
        )

        try:
            response = self._session.get(url, params=params, timeout=60)
        except requests.RequestException as e:
            raise ApifyError(f"Request failed: {e}") from e

        if not response.ok:
            raise ApifyError(
                f"Failed to fetch dataset items: {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )

        # Dataset items endpoint returns array directly, not wrapped in "data"
        items = response.json()
        if isinstance(items, dict) and "items" in items:
            # Handle wrapped response format
            items = items["items"]

        logger.info("Fetched %d items from dataset", len(items))
        return items

    def _parse_run_info(self, data: dict[str, Any], actor_id: str) -> RunInfo:
        """Parse API response into RunInfo."""
        started_at = None
        finished_at = None

        if data.get("startedAt"):
            try:
                started_at = datetime.fromisoformat(
                    data["startedAt"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        if data.get("finishedAt"):
            try:
                finished_at = datetime.fromisoformat(
                    data["finishedAt"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return RunInfo(
            run_id=data.get("id", ""),
            actor_id=actor_id or data.get("actId", ""),
            status=data.get("status", "UNKNOWN"),
            dataset_id=data.get("defaultDatasetId"),
            started_at=started_at,
            finished_at=finished_at,
            error_message=data.get("statusMessage") if data.get("status") == "FAILED" else None,
        )
