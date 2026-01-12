"""
Reddit Rising Posts Adapter.

Per ingestion_spec_v2.md §6: Surface reddit:rising.

Uses requests to fetch JSON from Reddit's public endpoint.
No authentication required for public subreddits.

FRAGILITY: Low - Reddit JSON endpoints are stable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import requests

from kairo.ingestion.capture.base import BaseCaptureAdapter, CaptureError, RawCapturedItem

if TYPE_CHECKING:
    from kairo.ingestion.models import Surface

logger = logging.getLogger(__name__)

# Reddit requires a User-Agent header
USER_AGENT = "kairo-ingestion/1.0 (trend detection research)"


class RedditRisingAdapter(BaseCaptureAdapter):
    """
    Adapter for Reddit Rising posts.

    Fetches rising posts from a subreddit using Reddit's JSON API.
    """

    def __init__(self, surface: "Surface"):
        """Initialize adapter."""
        super().__init__(surface)
        self.subreddit = surface.surface_key or "marketing"

    def capture(self) -> list[RawCapturedItem]:
        """
        Capture rising posts from Reddit subreddit.

        Returns:
            List of RawCapturedItem for each post found.

        Raises:
            CaptureError: If request fails.
        """
        url = f"https://www.reddit.com/r/{self.subreddit}/rising.json"

        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(
                "Reddit API request failed",
                extra={"subreddit": self.subreddit, "error": str(e)},
            )
            raise CaptureError(f"Reddit request failed: {e}", original_error=e) from e

        items = []
        posts = data.get("data", {}).get("children", [])

        for post_data in posts:
            post = post_data.get("data", {})
            if not post:
                continue

            item = RawCapturedItem(
                platform_item_id=post.get("id", ""),
                item_type="post",
                author_id=post.get("author_fullname", ""),
                author_handle=post.get("author", ""),
                text_content=post.get("title", ""),
                hashtags=[],  # Reddit uses flair instead
                view_count=None,  # Reddit doesn't expose views
                like_count=post.get("score"),
                comment_count=post.get("num_comments"),
                share_count=None,
                item_created_at=datetime.fromtimestamp(
                    post.get("created_utc", 0), tz=timezone.utc
                ) if post.get("created_utc") else None,
                canonical_url=f"https://reddit.com{post.get('permalink', '')}",
                raw_json=post,
            )
            items.append(item)

        logger.info(
            "Reddit capture completed",
            extra={
                "subreddit": self.subreddit,
                "item_count": len(items),
            },
        )

        return items


def create_adapter(surface: "Surface") -> RedditRisingAdapter:
    """Factory function for creating adapter instance."""
    return RedditRisingAdapter(surface)
