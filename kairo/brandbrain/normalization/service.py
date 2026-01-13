"""
Normalization service for BrandBrain.

PR-3: Raw → Normalized transformation with idempotent dedupe.

Main entrypoint: normalize_apify_run(apify_run_id)

Responsibilities:
1. Fetch raw items from ApifyRun (with dataset-fetch cap)
2. Transform using per-actor adapters
3. Create/update NormalizedEvidenceItem with idempotent dedupe
4. Merge raw_refs on update (don't drop old refs)
5. Update ApifyRun.normalized_item_count

Dedupe Strategy:
- Non-web: UNIQUE(brand_id, platform, content_type, external_id)
- Web: UNIQUE(brand_id, platform, content_type, canonical_url)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from kairo.brandbrain.caps import cap_for
from kairo.brandbrain.normalization.adapters import get_adapter
from kairo.integrations.apify.models import ApifyRun, RawApifyItem

if TYPE_CHECKING:
    from kairo.brandbrain.models import NormalizedEvidenceItem, SourceConnection

logger = logging.getLogger(__name__)


@dataclass
class NormalizationResult:
    """
    Result of a normalization operation.

    Attributes:
        apify_run_id: The ApifyRun that was normalized
        items_processed: Number of raw items processed
        items_created: Number of new NormalizedEvidenceItem created
        items_updated: Number of existing items updated (dedupe)
        items_skipped: Number of items skipped (adapter error, missing data)
        errors: List of error messages for skipped items
    """

    apify_run_id: UUID
    items_processed: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def normalize_apify_run(
    apify_run_id: UUID,
    *,
    fetch_limit: int | None = None,
) -> NormalizationResult:
    """
    Normalize all raw items from an ApifyRun.

    This is the main entrypoint for PR-3 normalization.

    Process:
    1. Load ApifyRun and linked SourceConnection
    2. Fetch raw items with cap enforcement
    3. Transform each item using the appropriate adapter
    4. Upsert into NormalizedEvidenceItem with dedupe
    5. Update ApifyRun.normalized_item_count

    Args:
        apify_run_id: UUID of the ApifyRun to normalize
        fetch_limit: Optional override for fetch limit (for testing)

    Returns:
        NormalizationResult with counts and errors.

    Raises:
        ValueError: If ApifyRun not found or missing required fields.
    """
    result = NormalizationResult(apify_run_id=apify_run_id)

    # Load ApifyRun
    try:
        apify_run = ApifyRun.objects.get(id=apify_run_id)
    except ApifyRun.DoesNotExist:
        raise ValueError(f"ApifyRun not found: {apify_run_id}")

    # Validate required fields
    if not apify_run.source_connection_id:
        raise ValueError(f"ApifyRun {apify_run_id} has no source_connection_id")
    if not apify_run.brand_id:
        raise ValueError(f"ApifyRun {apify_run_id} has no brand_id")

    # Get source connection for platform/capability
    source_connection = _get_source_connection(apify_run.source_connection_id)
    if not source_connection:
        raise ValueError(f"SourceConnection not found: {apify_run.source_connection_id}")

    # Get adapter for this actor
    adapter = get_adapter(apify_run.actor_id)
    if not adapter:
        raise ValueError(f"No adapter for actor_id: {apify_run.actor_id}")

    # Determine fetch limit (PR-3 cap enforcement)
    if fetch_limit is None:
        fetch_limit = cap_for(source_connection.platform, source_connection.capability)

    # Fetch raw items (from database, not Apify API)
    raw_items = _fetch_raw_items(apify_run, limit=fetch_limit)
    logger.info(
        "Normalizing %d raw items for ApifyRun %s (actor=%s, cap=%d)",
        len(raw_items),
        apify_run_id,
        apify_run.actor_id,
        fetch_limit,
    )

    # Process each raw item
    for raw_item in raw_items:
        result.items_processed += 1

        try:
            # Transform using adapter
            normalized_data = adapter(raw_item.raw_json)

            # Build raw_ref for this item
            raw_ref = {
                "apify_run_id": str(apify_run.id),
                "raw_item_id": str(raw_item.id),
            }

            # Upsert with dedupe
            created = _upsert_normalized_item(
                brand_id=apify_run.brand_id,
                normalized_data=normalized_data,
                raw_ref=raw_ref,
            )

            if created:
                result.items_created += 1
            else:
                result.items_updated += 1

        except Exception as e:
            result.items_skipped += 1
            result.errors.append(f"Item {raw_item.id}: {str(e)}")
            logger.warning(
                "Failed to normalize item %s: %s",
                raw_item.id,
                str(e),
                exc_info=True,
            )

    # Update ApifyRun.normalized_item_count
    total_normalized = result.items_created + result.items_updated
    ApifyRun.objects.filter(id=apify_run_id).update(
        normalized_item_count=total_normalized
    )

    logger.info(
        "Normalization complete for ApifyRun %s: "
        "processed=%d, created=%d, updated=%d, skipped=%d",
        apify_run_id,
        result.items_processed,
        result.items_created,
        result.items_updated,
        result.items_skipped,
    )

    return result


def _get_source_connection(source_connection_id: UUID) -> "SourceConnection | None":
    """Get SourceConnection by ID."""
    from kairo.brandbrain.models import SourceConnection

    try:
        return SourceConnection.objects.get(id=source_connection_id)
    except SourceConnection.DoesNotExist:
        return None


def _fetch_raw_items(apify_run: ApifyRun, limit: int) -> list[RawApifyItem]:
    """
    Fetch raw items for an ApifyRun with cap enforcement.

    PR-3 requirement: dataset-fetch cap must be enforced.
    """
    return list(
        RawApifyItem.objects.filter(apify_run=apify_run)
        .order_by("item_index")[:limit]
    )


def _upsert_normalized_item(
    brand_id: UUID,
    normalized_data: dict,
    raw_ref: dict,
) -> bool:
    """
    Upsert a NormalizedEvidenceItem with idempotent dedupe.

    Dedupe strategy per spec:
    - Non-web: UNIQUE(brand_id, platform, content_type, external_id)
    - Web: UNIQUE(brand_id, platform, content_type, canonical_url)

    On update:
    - Merge raw_refs (append new ref if not already present)
    - Update other fields

    Args:
        brand_id: Brand UUID
        normalized_data: Dict from adapter
        raw_ref: Dict with apify_run_id and raw_item_id

    Returns:
        True if created, False if updated (dedupe).
    """
    from kairo.brandbrain.models import NormalizedEvidenceItem

    platform = normalized_data["platform"]
    content_type = normalized_data["content_type"]
    external_id = normalized_data.get("external_id")
    canonical_url = normalized_data.get("canonical_url", "")

    with transaction.atomic():
        # Build lookup query based on dedupe strategy
        if platform == "web":
            # Web: dedupe by canonical_url
            # DB constraint: UNIQUE(brand_id, platform, content_type, canonical_url) WHERE platform='web'
            lookup = Q(
                brand_id=brand_id,
                platform=platform,
                content_type=content_type,
                canonical_url=canonical_url,
            )
        elif external_id:
            # Non-web with external_id
            # DB constraint: UNIQUE(brand_id, platform, content_type, external_id) WHERE external_id IS NOT NULL
            lookup = Q(
                brand_id=brand_id,
                platform=platform,
                content_type=content_type,
                external_id=external_id,
            )
        else:
            # Non-web items MUST have external_id - no fallback to avoid silent collisions
            # The DB only has partial unique constraints for:
            #   - external_id when NOT NULL (non-web)
            #   - canonical_url when platform='web'
            # A non-web item without external_id would bypass dedupe entirely.
            raise ValueError(
                f"Non-web item (platform={platform}) must have external_id for dedupe. "
                f"Received external_id=None, canonical_url={canonical_url}"
            )

        # Try to find existing item
        existing = NormalizedEvidenceItem.objects.filter(lookup).first()

        if existing:
            # Update existing item
            _update_normalized_item(existing, normalized_data, raw_ref)
            return False
        else:
            # Create new item
            _create_normalized_item(brand_id, normalized_data, raw_ref)
            return True


def _update_normalized_item(
    item: "NormalizedEvidenceItem",
    normalized_data: dict,
    raw_ref: dict,
) -> None:
    """
    Update an existing NormalizedEvidenceItem.

    Merges raw_refs (appends new ref if not present).
    """
    # Merge raw_refs
    existing_refs = item.raw_refs or []
    if raw_ref not in existing_refs:
        existing_refs.append(raw_ref)

    # Update fields
    item.canonical_url = normalized_data.get("canonical_url", item.canonical_url)
    item.published_at = normalized_data.get("published_at") or item.published_at
    item.author_ref = normalized_data.get("author_ref", item.author_ref)
    item.title = normalized_data.get("title") or item.title
    item.text_primary = normalized_data.get("text_primary", item.text_primary)
    item.text_secondary = normalized_data.get("text_secondary") or item.text_secondary
    item.hashtags = normalized_data.get("hashtags", item.hashtags)
    item.metrics_json = normalized_data.get("metrics_json", item.metrics_json)
    item.media_json = normalized_data.get("media_json", item.media_json)
    item.flags_json = normalized_data.get("flags_json", item.flags_json)
    item.raw_refs = existing_refs

    item.save()


def _create_normalized_item(
    brand_id: UUID,
    normalized_data: dict,
    raw_ref: dict,
) -> "NormalizedEvidenceItem":
    """Create a new NormalizedEvidenceItem."""
    from kairo.brandbrain.models import NormalizedEvidenceItem

    return NormalizedEvidenceItem.objects.create(
        brand_id=brand_id,
        platform=normalized_data["platform"],
        content_type=normalized_data["content_type"],
        external_id=normalized_data.get("external_id"),
        canonical_url=normalized_data.get("canonical_url", ""),
        published_at=normalized_data.get("published_at"),
        author_ref=normalized_data.get("author_ref", ""),
        title=normalized_data.get("title"),
        text_primary=normalized_data.get("text_primary", ""),
        text_secondary=normalized_data.get("text_secondary"),
        hashtags=normalized_data.get("hashtags", []),
        metrics_json=normalized_data.get("metrics_json", {}),
        media_json=normalized_data.get("media_json", {}),
        flags_json=normalized_data.get("flags_json", {}),
        raw_refs=[raw_ref],
    )


# =============================================================================
# BATCH NORMALIZATION (for compile orchestration)
# =============================================================================


def normalize_source_connection(
    source_connection_id: UUID,
    apify_run_id: UUID | None = None,
) -> NormalizationResult | None:
    """
    Normalize items for a SourceConnection.

    If apify_run_id is provided, uses that run.
    Otherwise, finds the latest successful run for the source.

    This is a convenience wrapper for compile orchestration (PR-5).

    Args:
        source_connection_id: UUID of the SourceConnection
        apify_run_id: Optional specific ApifyRun to normalize

    Returns:
        NormalizationResult or None if no run to normalize.
    """
    from kairo.integrations.apify.models import ApifyRunStatus

    if apify_run_id:
        return normalize_apify_run(apify_run_id)

    # Find latest successful run for this source
    latest_run = (
        ApifyRun.objects.filter(
            source_connection_id=source_connection_id,
            status=ApifyRunStatus.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )

    if not latest_run:
        logger.warning(
            "No successful ApifyRun found for SourceConnection %s",
            source_connection_id,
        )
        return None

    return normalize_apify_run(latest_run.id)
