"""
External Signals Service.

PR-5: External Signals Bundler (Stubbed, No HTTP).

This service provides external signal bundles for brands using local fixtures only.
No HTTP calls, no LLM calls, no deepagents - just local JSON files.

Per PRD-1 §6.2 and PR-map-and-standards §PR-5:
- Returns ExternalSignalBundleDTO for a given brand_id
- Rich bundles for demo brands with fixtures
- Empty bundles for unknown brands (graceful degradation)
- Malformed fixtures log warnings and return empty bundles

IMPORTANT: This module must NOT import requests, httpx, aiohttp, urllib.request,
or any other HTTP library. All external data comes from local fixtures.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from kairo.core.models import Brand
from kairo.hero.dto import (
    CompetitorPostSignalDTO,
    ExternalSignalBundleDTO,
    SocialMomentSignalDTO,
    TrendSignalDTO,
    WebMentionSignalDTO,
)

logger = logging.getLogger(__name__)

# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "external_signals"


def get_bundle_for_brand(brand_id: UUID) -> ExternalSignalBundleDTO:
    """
    Get external signals bundle for a brand.

    PR-5 implementation (stubbed, fixture-based):
    - Looks up brand by ID to get its slug
    - Loads fixture data from local JSON file based on slug
    - Returns empty bundle if brand not found or no fixture exists
    - Returns empty bundle on malformed fixture (with warning log)

    Args:
        brand_id: UUID of the brand

    Returns:
        ExternalSignalBundleDTO with signals data (or empty if not available)
    """
    now = datetime.now(timezone.utc)

    # Try to get brand slug for fixture lookup
    try:
        brand = Brand.objects.get(id=brand_id)
        brand_slug = brand.slug
    except Brand.DoesNotExist:
        logger.info(
            "Brand not found for external signals lookup",
            extra={"brand_id": str(brand_id)},
        )
        return _empty_bundle(brand_id, now)

    # Load index to find fixture file for this brand
    fixture_filename = _get_fixture_filename_for_slug(brand_slug)
    if not fixture_filename:
        logger.debug(
            "No fixture mapping for brand",
            extra={"brand_id": str(brand_id), "brand_slug": brand_slug},
        )
        return _empty_bundle(brand_id, now)

    # Load and parse fixture file
    return _load_fixture(brand_id, fixture_filename, now)


def _get_fixture_filename_for_slug(slug: str) -> str | None:
    """
    Look up fixture filename for a brand slug from the index.

    Args:
        slug: Brand slug to look up

    Returns:
        Fixture filename if found, None otherwise
    """
    index_path = FIXTURES_DIR / "_index.json"

    if not index_path.exists():
        logger.warning(
            "External signals index file not found",
            extra={"expected_path": str(index_path)},
        )
        return None

    try:
        with open(index_path, "r") as f:
            index_data = json.load(f)

        slug_to_fixture = index_data.get("brand_slug_to_fixture", {})
        return slug_to_fixture.get(slug)

    except json.JSONDecodeError as e:
        logger.warning(
            "Malformed external signals index file",
            extra={"path": str(index_path), "error": str(e)},
        )
        return None


def _load_fixture(
    brand_id: UUID,
    filename: str,
    fetched_at: datetime,
) -> ExternalSignalBundleDTO:
    """
    Load fixture file and parse into ExternalSignalBundleDTO.

    Args:
        brand_id: UUID of the brand
        filename: Name of the fixture file
        fetched_at: Timestamp for the bundle

    Returns:
        ExternalSignalBundleDTO with parsed data or empty bundle on error
    """
    fixture_path = FIXTURES_DIR / filename

    if not fixture_path.exists():
        logger.warning(
            "External signals fixture file not found",
            extra={"brand_id": str(brand_id), "path": str(fixture_path)},
        )
        return _empty_bundle(brand_id, fetched_at)

    try:
        with open(fixture_path, "r") as f:
            data = json.load(f)

        return _parse_fixture_data(brand_id, data, fetched_at)

    except json.JSONDecodeError as e:
        logger.warning(
            "Malformed external signals fixture file",
            extra={"brand_id": str(brand_id), "path": str(fixture_path), "error": str(e)},
        )
        return _empty_bundle(brand_id, fetched_at)

    except Exception as e:
        logger.warning(
            "Error loading external signals fixture",
            extra={"brand_id": str(brand_id), "path": str(fixture_path), "error": str(e)},
        )
        return _empty_bundle(brand_id, fetched_at)


def _parse_fixture_data(
    brand_id: UUID,
    data: dict,
    fetched_at: datetime,
) -> ExternalSignalBundleDTO:
    """
    Parse raw fixture data into ExternalSignalBundleDTO.

    Gracefully handles missing or malformed nested data.

    Args:
        brand_id: UUID of the brand
        data: Raw fixture data dict
        fetched_at: Timestamp for the bundle

    Returns:
        ExternalSignalBundleDTO with parsed signals
    """
    trends = []
    for item in data.get("trends", []):
        try:
            trends.append(TrendSignalDTO(**item))
        except Exception as e:
            logger.warning(
                "Skipping malformed trend signal",
                extra={"brand_id": str(brand_id), "item": item, "error": str(e)},
            )

    web_mentions = []
    for item in data.get("web_mentions", []):
        try:
            web_mentions.append(WebMentionSignalDTO(**item))
        except Exception as e:
            logger.warning(
                "Skipping malformed web mention signal",
                extra={"brand_id": str(brand_id), "item": item, "error": str(e)},
            )

    competitor_posts = []
    for item in data.get("competitor_posts", []):
        try:
            competitor_posts.append(CompetitorPostSignalDTO(**item))
        except Exception as e:
            logger.warning(
                "Skipping malformed competitor post signal",
                extra={"brand_id": str(brand_id), "item": item, "error": str(e)},
            )

    social_moments = []
    for item in data.get("social_moments", []):
        try:
            social_moments.append(SocialMomentSignalDTO(**item))
        except Exception as e:
            logger.warning(
                "Skipping malformed social moment signal",
                extra={"brand_id": str(brand_id), "item": item, "error": str(e)},
            )

    return ExternalSignalBundleDTO(
        brand_id=brand_id,
        fetched_at=fetched_at,
        trends=trends,
        web_mentions=web_mentions,
        competitor_posts=competitor_posts,
        social_moments=social_moments,
    )


def _empty_bundle(brand_id: UUID, fetched_at: datetime) -> ExternalSignalBundleDTO:
    """
    Create an empty external signals bundle.

    Args:
        brand_id: UUID of the brand
        fetched_at: Timestamp for the bundle

    Returns:
        ExternalSignalBundleDTO with empty lists
    """
    return ExternalSignalBundleDTO(
        brand_id=brand_id,
        fetched_at=fetched_at,
        trends=[],
        web_mentions=[],
        competitor_posts=[],
        social_moments=[],
    )
