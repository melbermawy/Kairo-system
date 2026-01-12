"""
TikTok Discover Page Adapter.

Per ingestion_spec_v2.md §6: Surface tiktok:discover.

Uses Playwright to scrape the TikTok discover/explore page.
Extracts videos with audio_id, hashtags, and engagement metrics.

FRAGILITY: Medium - TikTok changes DOM frequently.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kairo.ingestion.capture.base import BaseCaptureAdapter, CaptureError, RawCapturedItem

if TYPE_CHECKING:
    from kairo.ingestion.models import Surface

logger = logging.getLogger(__name__)


class TikTokDiscoverAdapter(BaseCaptureAdapter):
    """
    Adapter for TikTok Discover page.

    Scrapes trending videos from https://www.tiktok.com/explore
    """

    def __init__(self, surface: "Surface"):
        """Initialize adapter."""
        super().__init__(surface)
        # TODO: Configure Playwright options

    def capture(self) -> list[RawCapturedItem]:
        """
        Capture trending videos from TikTok Discover page.

        Returns:
            List of RawCapturedItem for each video found.

        Raises:
            CaptureError: If Playwright fails or page structure changed.
        """
        # TODO: Implement Playwright scraping
        # 1. Launch browser
        # 2. Navigate to https://www.tiktok.com/explore
        # 3. Wait for video cards to load
        # 4. Extract video data from each card
        # 5. Return list of RawCapturedItem

        logger.info(
            "TikTok Discover capture not yet implemented",
            extra={"surface": str(self.surface)},
        )

        raise CaptureError("TikTok Discover adapter not yet implemented")


def create_adapter(surface: "Surface") -> TikTokDiscoverAdapter:
    """Factory function for creating adapter instance."""
    return TikTokDiscoverAdapter(surface)
