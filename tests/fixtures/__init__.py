"""
Test fixtures for Kairo.

PR1: Evidence fixtures for opportunities v2 testing.
"""

from .evidence_fixtures import (
    brand_with_duplicate_evidence,
    brand_with_insufficient_evidence,
    brand_with_low_quality_evidence,
    brand_with_stale_evidence,
    brand_with_sufficient_evidence,
    create_adversarial_duplicates,
    create_adversarial_missing_metrics,
    create_adversarial_missing_thumbnails,
    create_adversarial_no_transcripts,
    create_adversarial_stale_evidence,
    create_adversarial_wrong_platforms,
    create_evidence_item,
    create_insufficient_evidence,
    create_low_quality_evidence,
    create_sufficient_evidence,
)

__all__ = [
    "brand_with_duplicate_evidence",
    "brand_with_insufficient_evidence",
    "brand_with_low_quality_evidence",
    "brand_with_stale_evidence",
    "brand_with_sufficient_evidence",
    "create_adversarial_duplicates",
    "create_adversarial_missing_metrics",
    "create_adversarial_missing_thumbnails",
    "create_adversarial_no_transcripts",
    "create_adversarial_stale_evidence",
    "create_adversarial_wrong_platforms",
    "create_evidence_item",
    "create_insufficient_evidence",
    "create_low_quality_evidence",
    "create_sufficient_evidence",
]
