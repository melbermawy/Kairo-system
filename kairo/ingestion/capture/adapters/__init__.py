"""
Capture adapters for various platforms.

Each adapter implements BaseCaptureAdapter for a specific
platform/surface_type combination.
"""

from kairo.ingestion.capture.base import BaseCaptureAdapter, CaptureError, RawCapturedItem
from kairo.ingestion.capture.adapters.reddit_rising import RedditRisingAdapter
from kairo.ingestion.capture.adapters.tiktok_discover import TikTokDiscoverAdapter

# Registry of available adapters by surface type
ADAPTER_REGISTRY: dict[str, type[BaseCaptureAdapter]] = {
    "reddit_rising": RedditRisingAdapter,
    "tiktok_discover": TikTokDiscoverAdapter,
}

__all__ = [
    "BaseCaptureAdapter",
    "CaptureError",
    "RawCapturedItem",
    "ADAPTER_REGISTRY",
    "RedditRisingAdapter",
    "TikTokDiscoverAdapter",
]
