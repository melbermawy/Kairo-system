"""
Fixture Loader for SourceActivation.

PR-4: Fixture-only SourceActivation.
Per PR-4 requirements: Deterministic fixture behavior.

Loads fixture datasets from repo JSON files and normalizes them
into EvidenceItemData instances.

CRITICAL: EvidenceItem IDs must be stable across runs.
Uses uuid5 with deterministic input: f"{brand_id}:{platform}:{canonical_url}"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from kairo.sourceactivation.types import EvidenceItemData, SeedPack

logger = logging.getLogger(__name__)

# Namespace UUID for deterministic evidence ID generation
# PR-4: Same brand+platform+url = same ID across runs
EVIDENCE_NAMESPACE = UUID("b2c3d4e5-f6a7-8901-bcde-f23456789012")

# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent


def generate_evidence_id(brand_id: UUID, platform: str, canonical_url: str) -> UUID:
    """
    Generate deterministic UUID for an evidence item.

    PR-4 requirement: Same fixtures + same seed_pack = same EvidenceItem IDs.
    Uses uuid5 to ensure reproducibility.

    Args:
        brand_id: Brand UUID
        platform: Platform name (instagram, tiktok, etc.)
        canonical_url: Canonical URL of the content

    Returns:
        Deterministic UUID5
    """
    seed = f"{brand_id}:{platform}:{canonical_url}"
    return uuid5(EVIDENCE_NAMESPACE, seed)


def load_fixtures_for_brand(
    brand_id: UUID,
    seed_pack: SeedPack,
) -> list[EvidenceItemData]:
    """
    Load fixture evidence items for a brand.

    Loads from JSON fixture files based on brand_id.
    If no brand-specific fixture exists, uses default fixtures.

    Args:
        brand_id: UUID of the brand
        seed_pack: SeedPack for context (used for filtering in future)

    Returns:
        List of EvidenceItemData instances
    """
    now = datetime.now(timezone.utc)

    # Try brand-specific fixture first
    brand_fixture_path = FIXTURES_DIR / f"{brand_id}.json"
    default_fixture_path = FIXTURES_DIR / "default.json"

    fixture_path = None
    if brand_fixture_path.exists():
        fixture_path = brand_fixture_path
        logger.debug("Loading brand-specific fixture: %s", fixture_path)
    elif default_fixture_path.exists():
        fixture_path = default_fixture_path
        logger.debug("Loading default fixture: %s", fixture_path)
    else:
        logger.info(
            "No fixtures found for brand %s, returning empty list",
            brand_id,
        )
        return []

    try:
        with open(fixture_path, "r") as f:
            data = json.load(f)

        items = []
        for raw_item in data.get("items", []):
            item = _parse_fixture_item(raw_item, brand_id, now)
            if item:
                items.append(item)

        logger.info(
            "Loaded %d fixture items for brand %s",
            len(items),
            brand_id,
        )
        return items

    except json.JSONDecodeError as e:
        logger.warning(
            "Malformed fixture file: %s - %s",
            fixture_path,
            str(e),
        )
        return []
    except Exception as e:
        logger.warning(
            "Error loading fixtures for brand %s: %s",
            brand_id,
            str(e),
        )
        return []


def _parse_fixture_item(
    raw: dict,
    brand_id: UUID,
    fetched_at: datetime,
) -> EvidenceItemData | None:
    """
    Parse a raw fixture dict into EvidenceItemData.

    Args:
        raw: Raw fixture data dict
        brand_id: Brand UUID
        fetched_at: Timestamp for fetched_at

    Returns:
        EvidenceItemData or None if parsing fails
    """
    try:
        # Required fields
        platform = raw.get("platform", "")
        canonical_url = raw.get("canonical_url", "")

        if not platform or not canonical_url:
            logger.warning(
                "Fixture item missing required fields: platform=%s, canonical_url=%s",
                platform,
                canonical_url,
            )
            return None

        # Parse published_at if present
        published_at = None
        if raw.get("published_at"):
            try:
                published_at = datetime.fromisoformat(
                    raw["published_at"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        return EvidenceItemData(
            platform=platform,
            actor_id=raw.get("actor_id", "FIXTURE"),
            acquisition_stage=raw.get("acquisition_stage", 1),
            recipe_id=raw.get("recipe_id", "FIXTURE"),
            canonical_url=canonical_url,
            external_id=raw.get("external_id", ""),
            author_ref=raw.get("author_ref", ""),
            title=raw.get("title", ""),
            text_primary=raw.get("text_primary", ""),
            text_secondary=raw.get("text_secondary", ""),
            hashtags=raw.get("hashtags", []),
            view_count=raw.get("view_count"),
            like_count=raw.get("like_count"),
            comment_count=raw.get("comment_count"),
            share_count=raw.get("share_count"),
            published_at=published_at,
            fetched_at=fetched_at,
            has_transcript=raw.get("has_transcript", False),
            raw_json=raw,
        )

    except Exception as e:
        logger.warning("Error parsing fixture item: %s", str(e))
        return None
