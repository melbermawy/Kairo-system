"""
Unit tests for Apify client.

Tests URL building, error handling, and response parsing.
Uses mocked HTTP (no network calls).

PR-0: Tests that call Apify client methods require APIFY_ENABLED=true.
The enable_apify fixture overrides the setting for these tests.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from kairo.integrations.apify.client import (
    ApifyClient,
    ApifyError,
    ApifyTimeoutError,
    RunInfo,
)


# =============================================================================
# PR-0: Fixture to enable Apify for client tests
# =============================================================================


@pytest.fixture
def enable_apify(settings):
    """Enable APIFY_ENABLED for tests that need to call client methods."""
    settings.APIFY_ENABLED = True
    yield
    settings.APIFY_ENABLED = False


class TestApifyClientInit:
    """Tests for ApifyClient initialization."""

    def test_init_with_token(self):
        """Client initializes with token."""
        client = ApifyClient(token="test-token")
        assert client.token == "test-token"
        assert client.base_url == "https://api.apify.com"

    def test_init_with_custom_base_url(self):
        """Client accepts custom base URL."""
        client = ApifyClient(token="test-token", base_url="https://custom.apify.com/")
        assert client.base_url == "https://custom.apify.com"  # Trailing slash stripped

    def test_init_without_token_raises(self):
        """Client raises ValueError without token."""
        with pytest.raises(ValueError, match="token is required"):
            ApifyClient(token="")


@pytest.mark.usefixtures("enable_apify")
class TestApifyClientStartActorRun:
    """Tests for start_actor_run method."""

    @patch("kairo.integrations.apify.client.requests.Session")
    def test_start_actor_run_success(self, mock_session_class):
        """start_actor_run returns RunInfo on success."""
        # Setup mock
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": {
                "id": "run123",
                "status": "RUNNING",
                "defaultDatasetId": "dataset456",
                "startedAt": "2024-01-15T10:00:00.000Z",
            }
        }
        mock_session.post.return_value = mock_response

        client = ApifyClient(token="test-token")
        run_info = client.start_actor_run(
            actor_id="apify/instagram-reel-scraper",
            input_json={"username": ["wendys"]},
        )

        # Verify URL
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://api.apify.com/v2/acts/apify/instagram-reel-scraper/runs"

        # Verify RunInfo
        assert run_info.run_id == "run123"
        assert run_info.status == "RUNNING"
        assert run_info.dataset_id == "dataset456"
        assert run_info.actor_id == "apify/instagram-reel-scraper"

    @patch("kairo.integrations.apify.client.requests.Session")
    def test_start_actor_run_error_response(self, mock_session_class):
        """start_actor_run raises ApifyError on error response."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_session.post.return_value = mock_response

        client = ApifyClient(token="bad-token")
        with pytest.raises(ApifyError) as exc_info:
            client.start_actor_run("actor/test", {})

        assert exc_info.value.status_code == 401

    @patch("kairo.integrations.apify.client.requests.Session")
    def test_start_actor_run_request_exception(self, mock_session_class):
        """start_actor_run raises ApifyError on network error."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.post.side_effect = requests.RequestException("Network error")

        client = ApifyClient(token="test-token")
        with pytest.raises(ApifyError, match="Request failed"):
            client.start_actor_run("actor/test", {})


@pytest.mark.usefixtures("enable_apify")
class TestApifyClientPollRun:
    """Tests for poll_run method."""

    @patch("kairo.integrations.apify.client.time.sleep")
    @patch("kairo.integrations.apify.client.requests.Session")
    def test_poll_run_success(self, mock_session_class, mock_sleep):
        """poll_run returns RunInfo when run succeeds."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # First call: RUNNING, second call: SUCCEEDED
        responses = [
            {"data": {"id": "run123", "status": "RUNNING", "actId": "actor/test"}},
            {
                "data": {
                    "id": "run123",
                    "status": "SUCCEEDED",
                    "actId": "actor/test",
                    "defaultDatasetId": "dataset456",
                    "finishedAt": "2024-01-15T10:05:00.000Z",
                }
            },
        ]
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.side_effect = responses
        mock_session.get.return_value = mock_response

        client = ApifyClient(token="test-token")
        run_info = client.poll_run("run123", timeout_s=60, interval_s=1)

        assert run_info.status == "SUCCEEDED"
        assert run_info.dataset_id == "dataset456"
        assert mock_sleep.call_count == 1

    @patch("kairo.integrations.apify.client.time.monotonic")
    @patch("kairo.integrations.apify.client.requests.Session")
    def test_poll_run_timeout(self, mock_session_class, mock_monotonic):
        """poll_run raises ApifyTimeoutError when timeout exceeded."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "data": {"id": "run123", "status": "RUNNING"}
        }
        mock_session.get.return_value = mock_response

        # Simulate time passing past timeout
        mock_monotonic.side_effect = [0, 10, 20, 35]  # Start, then exceed 30s timeout

        client = ApifyClient(token="test-token")
        with pytest.raises(ApifyTimeoutError, match="timed out"):
            client.poll_run("run123", timeout_s=30, interval_s=1)


@pytest.mark.usefixtures("enable_apify")
class TestApifyClientFetchDatasetItems:
    """Tests for fetch_dataset_items method."""

    @patch("kairo.integrations.apify.client.requests.Session")
    def test_fetch_dataset_items_array_response(self, mock_session_class):
        """fetch_dataset_items handles array response."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        items = [{"id": "item1"}, {"id": "item2"}]
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = items
        mock_session.get.return_value = mock_response

        client = ApifyClient(token="test-token")
        result = client.fetch_dataset_items("dataset456", limit=20, offset=0)

        assert result == items
        # Verify URL and params
        call_args = mock_session.get.call_args
        assert "datasets/dataset456/items" in call_args[0][0]
        assert call_args[1]["params"] == {"limit": 20, "offset": 0}

    @patch("kairo.integrations.apify.client.requests.Session")
    def test_fetch_dataset_items_wrapped_response(self, mock_session_class):
        """fetch_dataset_items handles wrapped response format."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        items = [{"id": "item1"}]
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"items": items, "total": 1}
        mock_session.get.return_value = mock_response

        client = ApifyClient(token="test-token")
        result = client.fetch_dataset_items("dataset456")

        assert result == items


class TestRunInfo:
    """Tests for RunInfo dataclass."""

    def test_is_terminal_succeeded(self):
        """SUCCEEDED is a terminal state."""
        run_info = RunInfo(
            run_id="123",
            actor_id="test",
            status="SUCCEEDED",
            dataset_id="ds",
            started_at=None,
            finished_at=None,
        )
        assert run_info.is_terminal() is True
        assert run_info.is_success() is True

    def test_is_terminal_failed(self):
        """FAILED is a terminal state."""
        run_info = RunInfo(
            run_id="123",
            actor_id="test",
            status="FAILED",
            dataset_id=None,
            started_at=None,
            finished_at=None,
        )
        assert run_info.is_terminal() is True
        assert run_info.is_success() is False

    def test_is_terminal_running(self):
        """RUNNING is not a terminal state."""
        run_info = RunInfo(
            run_id="123",
            actor_id="test",
            status="RUNNING",
            dataset_id=None,
            started_at=None,
            finished_at=None,
        )
        assert run_info.is_terminal() is False
        assert run_info.is_success() is False
