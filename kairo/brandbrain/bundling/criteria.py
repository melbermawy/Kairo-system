"""
Bundle selection criteria and configuration.

PR-4: Configurable knobs for evidence bundle selection.

All values are deterministic and versioned for reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# =============================================================================
# CONSTANTS
# =============================================================================

# Selection heuristic parameters (Section 7.2)
# Take min(cap, recent_M + top_by_engagement_N)
DEFAULT_RECENT_M = 3  # Most recent items per platform
DEFAULT_TOP_ENGAGEMENT_N = 5  # Top engagement items per platform

# Scoring version for future evolution
SCORING_VERSION = "v1"


@dataclass
class BundleCriteria:
    """
    Configuration for evidence bundle selection.

    All parameters affect selection behavior and are stored in criteria_json
    for reproducibility.

    Attributes:
        recent_m: Number of most recent items per platform (default: 3)
        top_engagement_n: Number of top engagement items per platform (default: 5)
        exclude_collection_pages: Exclude web items with is_collection_page=true (default: True)
        exclude_linkedin_profile_posts: Exclude unvalidated LinkedIn profile posts (default: True)
        include_low_value_key_pages: Include key pages even if is_low_value=true (default: True)
        scoring_version: Version string for engagement scoring logic
    """

    recent_m: int = DEFAULT_RECENT_M
    top_engagement_n: int = DEFAULT_TOP_ENGAGEMENT_N
    exclude_collection_pages: bool = True
    exclude_linkedin_profile_posts: bool = True
    include_low_value_key_pages: bool = True
    scoring_version: str = SCORING_VERSION

    def to_dict(self) -> dict:
        """Convert criteria to dictionary for persistence."""
        return {
            "version": self.scoring_version,
            "recent_m": self.recent_m,
            "top_engagement_n": self.top_engagement_n,
            "exclude_collection_pages": self.exclude_collection_pages,
            "exclude_linkedin_profile_posts": self.exclude_linkedin_profile_posts,
            "include_low_value_key_pages": self.include_low_value_key_pages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BundleCriteria":
        """Create criteria from dictionary."""
        return cls(
            recent_m=data.get("recent_m", DEFAULT_RECENT_M),
            top_engagement_n=data.get("top_engagement_n", DEFAULT_TOP_ENGAGEMENT_N),
            exclude_collection_pages=data.get("exclude_collection_pages", True),
            exclude_linkedin_profile_posts=data.get("exclude_linkedin_profile_posts", True),
            include_low_value_key_pages=data.get("include_low_value_key_pages", True),
            scoring_version=data.get("version", SCORING_VERSION),
        )
