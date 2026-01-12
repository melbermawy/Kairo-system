"""
Tests for capture adapters.

Per ingestion_spec_v2.md §13: Acceptance Tests.
"""

import pytest
from unittest.mock import patch, MagicMock

from kairo.ingestion.capture.adapters import (
    ADAPTER_REGISTRY,
    RedditRisingAdapter,
    TikTokDiscoverAdapter,
)
from kairo.ingestion.models import Surface


class TestAdapterRegistry:
    """Tests for adapter registry."""

    def test_registry_contains_reddit(self):
        """Registry contains reddit_rising adapter."""
        assert "reddit_rising" in ADAPTER_REGISTRY

    def test_registry_contains_tiktok(self):
        """Registry contains tiktok_discover adapter."""
        assert "tiktok_discover" in ADAPTER_REGISTRY


@pytest.mark.django_db
class TestRedditRisingAdapter:
    """Tests for Reddit rising adapter."""

    def test_adapter_init(self):
        """Adapter can be initialized with surface."""
        surface = Surface.objects.create(
            platform="reddit",
            surface_type="rising",
            surface_key="marketing",
        )
        adapter = RedditRisingAdapter(surface)
        assert adapter.subreddit == "marketing"

    @patch("kairo.ingestion.capture.adapters.reddit_rising.requests.get")
    def test_capture_success(self, mock_get):
        """Adapter parses Reddit API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "abc123",
                            "title": "Test Post",
                            "selftext": "Content",
                            "author": "testuser",
                            "score": 100,
                            "num_comments": 50,
                            "permalink": "/r/marketing/comments/abc123",
                            "created_utc": 1704067200,
                        }
                    }
                ]
            }
        }
        mock_get.return_value = mock_response

        surface = Surface.objects.create(
            platform="reddit",
            surface_type="rising",
            surface_key="marketing",
        )
        adapter = RedditRisingAdapter(surface)
        items = adapter.capture()

        assert len(items) == 1
        assert items[0].platform_item_id == "abc123"


@pytest.mark.django_db
class TestTikTokDiscoverAdapter:
    """Tests for TikTok discover adapter."""

    def test_adapter_init(self):
        """Adapter can be initialized."""
        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
        )
        adapter = TikTokDiscoverAdapter(surface)
        assert adapter is not None

    def test_capture_not_implemented(self):
        """Capture raises CaptureError (requires Playwright)."""
        from kairo.ingestion.capture.base import CaptureError

        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
            surface_key="test",
        )
        adapter = TikTokDiscoverAdapter(surface)
        with pytest.raises(CaptureError):
            adapter.capture()
