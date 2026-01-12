"""
Base adapter interface for capture adapters.

Per ingestion_spec_v2.md §5: Capture stage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kairo.ingestion.models import Surface


@dataclass
class RawCapturedItem:
    """
    Raw item captured from a platform.

    Adapters return a list of these, which are then
    persisted as EvidenceItem rows.
    """

    platform_item_id: str
    item_type: str  # video, post, audio, comment
    author_id: str = ""
    author_handle: str = ""
    text_content: str = ""
    audio_id: str = ""
    audio_title: str = ""
    hashtags: list[str] | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    item_created_at: datetime | None = None
    canonical_url: str = ""
    raw_json: dict | None = None


class BaseCaptureAdapter(ABC):
    """
    Abstract base class for capture adapters.

    Each platform/surface type has its own adapter implementation.
    """

    def __init__(self, surface: "Surface"):
        """
        Initialize adapter with surface configuration.

        Args:
            surface: Surface model instance with platform/type/key
        """
        self.surface = surface

    @abstractmethod
    def capture(self) -> list[RawCapturedItem]:
        """
        Execute capture for this surface.

        Returns:
            List of raw captured items.

        Raises:
            CaptureError: If capture fails.
        """
        pass

    @property
    def platform(self) -> str:
        """Platform identifier."""
        return self.surface.platform

    @property
    def surface_type(self) -> str:
        """Surface type identifier."""
        return self.surface.surface_type

    @property
    def surface_key(self) -> str:
        """Optional surface key (e.g., hashtag value)."""
        return self.surface.surface_key


class CaptureError(Exception):
    """Exception raised when capture fails."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error
