"""
TTL freshness decision logic for BrandBrain.

PR-2: TTL Decision Logic.

Per spec Section 3.2:
- Reuse last successful ApifyRun if within TTL
- Default TTL: 24 hours (BRANDBRAIN_APIFY_RUN_TTL_HOURS)
- A compile may trigger ingestion only when:
  1. No successful ApifyRun linked to that SourceConnection exists, OR
  2. The latest successful ApifyRun is older than TTL, OR
  3. force_refresh=true (internal/dev flag)

This module provides:
- FreshnessResult dataclass with decision outcome
- check_source_freshness() function for TTL decision
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from kairo.brandbrain.caps import apify_run_ttl_hours
from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus

if TYPE_CHECKING:
    from uuid import UUID


@dataclass
class FreshnessResult:
    """
    Result of a freshness check for a SourceConnection.

    Attributes:
        should_refresh: True if a new actor run should be triggered
        cached_run: The cached ApifyRun to reuse (None if should_refresh)
        reason: Human-readable explanation of the decision
        run_age_hours: Age of the cached run in hours (None if no cached run)
    """

    should_refresh: bool
    cached_run: ApifyRun | None
    reason: str
    run_age_hours: float | None


def check_source_freshness(
    source_connection_id: "UUID",
    force_refresh: bool = False,
) -> FreshnessResult:
    """
    Check if a SourceConnection needs a fresh actor run.

    Decision matrix:
    1. force_refresh=True → always refresh
    2. No cached run with status='succeeded' → refresh
    3. Cached run older than TTL → refresh
    4. Cached run within TTL → reuse

    The cached run is the most recent ApifyRun linked to this SourceConnection
    with status='succeeded'.

    Args:
        source_connection_id: UUID of the SourceConnection to check
        force_refresh: If True, always trigger refresh (ignores cache)

    Returns:
        FreshnessResult with decision and metadata.
    """
    # Force refresh bypasses all cache checks
    if force_refresh:
        return FreshnessResult(
            should_refresh=True,
            cached_run=None,
            reason="force_refresh=True",
            run_age_hours=None,
        )

    # Find the most recent successful run for this source
    # Uses partial index idx_apifyrun_source_success for efficiency
    # Note: ApifyRunStatus.SUCCEEDED must match the index predicate exactly
    latest_run = (
        ApifyRun.objects.filter(
            source_connection_id=source_connection_id,
            status=ApifyRunStatus.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )

    # No cached run → refresh
    if latest_run is None:
        return FreshnessResult(
            should_refresh=True,
            cached_run=None,
            reason="No successful run exists for this source",
            run_age_hours=None,
        )

    # Calculate run age
    now = timezone.now()
    age = now - latest_run.created_at
    age_hours = age.total_seconds() / 3600

    # Get TTL from config
    ttl_hours = apify_run_ttl_hours()

    # Check if within TTL
    if age_hours <= ttl_hours:
        return FreshnessResult(
            should_refresh=False,
            cached_run=latest_run,
            reason=f"Cached run is fresh ({age_hours:.1f}h old, TTL={ttl_hours}h)",
            run_age_hours=age_hours,
        )
    else:
        return FreshnessResult(
            should_refresh=True,
            cached_run=None,
            reason=f"Cached run is stale ({age_hours:.1f}h old, TTL={ttl_hours}h)",
            run_age_hours=age_hours,
        )


def any_source_stale(brand_id: "UUID") -> bool:
    """
    Check if any enabled SourceConnection for a brand needs refresh.

    Used by compile short-circuit logic to determine if a compile
    would be a no-op.

    Args:
        brand_id: UUID of the brand to check

    Returns:
        True if any source needs refresh, False if all are fresh.
    """
    from kairo.brandbrain.models import SourceConnection

    # Get all enabled source connections for this brand
    sources = SourceConnection.objects.filter(brand_id=brand_id, is_enabled=True)

    for source in sources:
        result = check_source_freshness(source.id)
        if result.should_refresh:
            return True

    return False
