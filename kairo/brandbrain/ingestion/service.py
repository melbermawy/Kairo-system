"""
BrandBrain Ingestion Service.

PR-6: Real Apify actor execution, raw item storage, and normalization.

This module provides:
- ingest_source(): End-to-end ingestion for a SourceConnection
  1. Trigger Apify actor run
  2. Poll until terminal status
  3. Fetch raw items with cap enforcement
  4. Store RawApifyItem rows
  5. Call normalization service

Cost controls:
- Actor input caps via build_input()
- Dataset fetch caps via fetch_dataset_items(limit=cap)
- Poll timeout to prevent runaway runs

Dependencies:
- ApifyClient: HTTP client for Apify API
- ActorRegistry: Maps (platform, capability) to actor specs
- NormalizationService: Raw -> Normalized transformation
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from kairo.brandbrain.actors.registry import get_actor_spec, is_capability_enabled
from kairo.brandbrain.caps import cap_for
from kairo.brandbrain.normalization import normalize_apify_run
from kairo.integrations.apify.client import (
    ApifyClient,
    ApifyError,
    ApifyTimeoutError,
)
from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus, RawApifyItem

if TYPE_CHECKING:
    from kairo.brandbrain.models import SourceConnection

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default poll timeout (seconds)
DEFAULT_POLL_TIMEOUT_S = 300  # 5 minutes

# Poll interval (seconds)
DEFAULT_POLL_INTERVAL_S = 5


# =============================================================================
# RESULT TYPES
# =============================================================================


@dataclass
class IngestionResult:
    """
    Result of ingesting a source connection.

    Attributes:
        source_connection_id: UUID of the source
        success: Whether ingestion succeeded
        apify_run_id: UUID of the ApifyRun record
        apify_run_status: Terminal status from Apify
        raw_items_count: Number of raw items stored
        normalized_items_created: New NormalizedEvidenceItem created
        normalized_items_updated: Existing items updated (dedupe)
        error: Error message if failed
    """

    source_connection_id: UUID
    success: bool = False
    apify_run_id: UUID | None = None
    apify_run_status: str | None = None
    raw_items_count: int = 0
    normalized_items_created: int = 0
    normalized_items_updated: int = 0
    error: str | None = None


# =============================================================================
# INGESTION SERVICE
# =============================================================================


def ingest_source(
    source_connection: "SourceConnection",
    *,
    poll_timeout_s: int = DEFAULT_POLL_TIMEOUT_S,
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    apify_client: ApifyClient | None = None,
) -> IngestionResult:
    """
    Ingest evidence from a source connection.

    End-to-end ingestion:
    1. Get actor spec for platform/capability
    2. Build actor input with cap
    3. Start Apify actor run
    4. Poll until terminal status
    5. Fetch raw items with cap
    6. Store RawApifyItem rows
    7. Call normalization service

    Args:
        source_connection: SourceConnection to ingest
        poll_timeout_s: Max seconds to wait for run completion
        poll_interval_s: Polling interval
        apify_client: Optional ApifyClient instance (for testing)

    Returns:
        IngestionResult with success status and counts.
    """
    result = IngestionResult(source_connection_id=source_connection.id)

    platform = source_connection.platform
    capability = source_connection.capability

    # Step 1: Check capability is enabled
    if not is_capability_enabled(platform, capability):
        result.error = f"Capability {platform}.{capability} is disabled"
        logger.warning(
            "Ingestion skipped for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    # Step 2: Get actor spec
    spec = get_actor_spec(platform, capability)
    if not spec:
        result.error = f"No actor spec for {platform}.{capability}"
        logger.error(
            "Ingestion failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    # Step 3: Get cap and build input
    cap = cap_for(platform, capability)
    input_json = spec.build_input(source_connection, cap)

    logger.info(
        "Starting ingestion for %s (actor=%s, cap=%d)",
        source_connection.id,
        spec.actor_id,
        cap,
    )

    # Step 4: Create/get Apify client
    if apify_client is None:
        token = getattr(settings, "APIFY_TOKEN", None) or os.environ.get("APIFY_TOKEN")
        if not token:
            result.error = "APIFY_TOKEN not configured"
            logger.error(
                "Ingestion failed for %s: %s",
                source_connection.id,
                result.error,
            )
            return result
        base_url = getattr(settings, "APIFY_BASE_URL", "https://api.apify.com")
        apify_client = ApifyClient(token=token, base_url=base_url)

    # Step 5: Start actor run
    try:
        run_info = apify_client.start_actor_run(spec.actor_id, input_json)
    except ApifyError as e:
        result.error = f"Failed to start actor run: {e}"
        logger.exception(
            "Ingestion failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    # Create ApifyRun record
    apify_run = ApifyRun.objects.create(
        actor_id=spec.actor_id,
        input_json=input_json,
        apify_run_id=run_info.run_id,
        dataset_id=run_info.dataset_id or "",
        status=ApifyRunStatus.RUNNING,
        started_at=run_info.started_at,
        source_connection_id=source_connection.id,
        brand_id=source_connection.brand_id,
    )
    result.apify_run_id = apify_run.id

    logger.info(
        "Started Apify run %s (apify_run_id=%s) for %s",
        apify_run.id,
        run_info.run_id,
        source_connection.id,
    )

    # Step 6: Poll until terminal status
    try:
        final_run_info = apify_client.poll_run(
            run_info.run_id,
            timeout_s=poll_timeout_s,
            interval_s=poll_interval_s,
        )
    except ApifyTimeoutError as e:
        # Update ApifyRun with timeout status
        apify_run.status = ApifyRunStatus.TIMED_OUT
        apify_run.finished_at = timezone.now()
        apify_run.error_summary = str(e)
        apify_run.save(update_fields=["status", "finished_at", "error_summary"])
        result.apify_run_status = ApifyRunStatus.TIMED_OUT
        result.error = f"Polling timed out: {e}"
        logger.warning(
            "Ingestion timed out for %s: %s",
            source_connection.id,
            result.error,
        )
        return result
    except ApifyError as e:
        apify_run.status = ApifyRunStatus.FAILED
        apify_run.finished_at = timezone.now()
        apify_run.error_summary = str(e)
        apify_run.save(update_fields=["status", "finished_at", "error_summary"])
        result.apify_run_status = ApifyRunStatus.FAILED
        result.error = f"Polling failed: {e}"
        logger.exception(
            "Ingestion failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    # Update ApifyRun with final status
    apify_run.status = final_run_info.status.lower()
    apify_run.finished_at = final_run_info.finished_at
    apify_run.dataset_id = final_run_info.dataset_id or apify_run.dataset_id
    if final_run_info.error_message:
        apify_run.error_summary = final_run_info.error_message
    apify_run.save(update_fields=["status", "finished_at", "dataset_id", "error_summary"])
    result.apify_run_status = final_run_info.status

    # Check if run succeeded
    if not final_run_info.is_success():
        result.error = f"Actor run failed: {final_run_info.status}"
        if final_run_info.error_message:
            result.error += f" - {final_run_info.error_message}"
        logger.warning(
            "Ingestion failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    # Step 7: Fetch raw items with cap enforcement
    dataset_id = final_run_info.dataset_id
    if not dataset_id:
        result.error = "No dataset_id in successful run"
        logger.error(
            "Ingestion failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    try:
        # CRITICAL: Pass cap as limit to enforce dataset-fetch cap
        raw_items = apify_client.fetch_dataset_items(
            dataset_id,
            limit=cap,
            offset=0,
        )
    except ApifyError as e:
        result.error = f"Failed to fetch dataset items: {e}"
        logger.exception(
            "Ingestion failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    logger.info(
        "Fetched %d items from dataset %s (cap=%d)",
        len(raw_items),
        dataset_id,
        cap,
    )

    # Step 8: Store RawApifyItem rows
    with transaction.atomic():
        # Clear existing items for this run (idempotent replace)
        RawApifyItem.objects.filter(apify_run=apify_run).delete()

        # Bulk create new items
        raw_item_objects = [
            RawApifyItem(
                apify_run=apify_run,
                item_index=idx,
                raw_json=item,
            )
            for idx, item in enumerate(raw_items)
        ]
        RawApifyItem.objects.bulk_create(raw_item_objects)

        # Update ApifyRun.raw_item_count
        apify_run.raw_item_count = len(raw_items)
        apify_run.save(update_fields=["raw_item_count"])

    result.raw_items_count = len(raw_items)

    logger.info(
        "Stored %d raw items for ApifyRun %s",
        len(raw_items),
        apify_run.id,
    )

    # Step 9: Call normalization service
    try:
        norm_result = normalize_apify_run(apify_run.id, fetch_limit=cap)
        result.normalized_items_created = norm_result.items_created
        result.normalized_items_updated = norm_result.items_updated
        result.success = True

        logger.info(
            "Normalization complete for ApifyRun %s: created=%d, updated=%d",
            apify_run.id,
            norm_result.items_created,
            norm_result.items_updated,
        )

    except Exception as e:
        result.error = f"Normalization failed: {e}"
        logger.exception(
            "Normalization failed for %s: %s",
            source_connection.id,
            result.error,
        )
        return result

    return result


def reuse_cached_run(
    source_connection: "SourceConnection",
    cached_run: ApifyRun,
) -> IngestionResult:
    """
    Reuse a cached ApifyRun for ingestion.

    If the cached run already has normalized items, skip normalization.
    Otherwise, run normalization on the existing raw items.

    Args:
        source_connection: SourceConnection to ingest
        cached_run: Cached ApifyRun to reuse

    Returns:
        IngestionResult with success status.
    """
    result = IngestionResult(
        source_connection_id=source_connection.id,
        apify_run_id=cached_run.id,
        apify_run_status=cached_run.status,
        raw_items_count=cached_run.raw_item_count,
    )

    # Check if normalization is needed
    if cached_run.normalized_item_count > 0:
        # Already normalized
        result.success = True
        logger.info(
            "Reusing cached run %s with %d normalized items",
            cached_run.id,
            cached_run.normalized_item_count,
        )
        return result

    # Run normalization on existing raw items
    try:
        cap = cap_for(source_connection.platform, source_connection.capability)
        norm_result = normalize_apify_run(cached_run.id, fetch_limit=cap)
        result.normalized_items_created = norm_result.items_created
        result.normalized_items_updated = norm_result.items_updated
        result.success = True

        logger.info(
            "Normalized cached run %s: created=%d, updated=%d",
            cached_run.id,
            norm_result.items_created,
            norm_result.items_updated,
        )

    except Exception as e:
        result.error = f"Normalization failed: {e}"
        logger.exception(
            "Normalization failed for cached run %s: %s",
            cached_run.id,
            result.error,
        )

    return result
