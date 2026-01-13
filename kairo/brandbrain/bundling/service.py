"""
Evidence bundling service for BrandBrain.

PR-4: Bundle creation and deterministic FeatureReport.

Main entrypoints:
- create_evidence_bundle(brand_id): Create an EvidenceBundle with deterministic selection
- create_feature_report(bundle): Create a FeatureReport from a bundle

Selection heuristics per spec Section 7.2:
- Take min(cap, recent_M + top_by_engagement_N) per platform
- Respect global max (40 items)
- Exclude collection pages unless web is the only evidence
- Exclude unvalidated LinkedIn profile posts by default
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import F, Q
from django.db.models.functions import Coalesce

from kairo.brandbrain.bundling.criteria import BundleCriteria
from kairo.brandbrain.bundling.features import extract_all_features
from kairo.brandbrain.bundling.scoring import compute_engagement_score
from kairo.brandbrain.caps import cap_for, global_max_normalized_items

if TYPE_CHECKING:
    from kairo.brandbrain.models import EvidenceBundle, FeatureReport, NormalizedEvidenceItem

logger = logging.getLogger(__name__)


# =============================================================================
# FEATURE FLAG
# =============================================================================

LINKEDIN_PROFILE_POSTS_FLAG = "BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS"


def _is_linkedin_profile_posts_enabled() -> bool:
    """Check if LinkedIn profile posts feature flag is enabled."""
    value = os.environ.get(LINKEDIN_PROFILE_POSTS_FLAG, "").lower()
    return value in ("true", "1", "yes", "on")


# =============================================================================
# PLATFORM/CONTENT_TYPE TO CAPABILITY MAPPING
# =============================================================================

# NormalizedEvidenceItem has platform + content_type, not capability.
# This maps to the capability for cap lookup.
CONTENT_TYPE_TO_CAPABILITY = {
    ("instagram", "post"): ("instagram", "posts"),
    ("instagram", "reel"): ("instagram", "reels"),
    ("linkedin", "text_post"): ("linkedin", "company_posts"),  # Default to company_posts
    ("tiktok", "short_video"): ("tiktok", "profile_videos"),
    ("youtube", "video"): ("youtube", "channel_videos"),
    ("web", "web_page"): ("web", "crawl_pages"),
}


class UnknownContentTypeError(ValueError):
    """Raised when an unknown (platform, content_type) pair is encountered."""

    def __init__(self, platform: str, content_type: str):
        self.platform = platform
        self.content_type = content_type
        super().__init__(
            f"Unknown (platform, content_type) pair: ({platform!r}, {content_type!r}). "
            f"Add mapping to CONTENT_TYPE_TO_CAPABILITY."
        )


def _get_cap_for_item(platform: str, content_type: str) -> int:
    """
    Get the cap for a platform/content_type combination.

    Raises:
        UnknownContentTypeError: If the (platform, content_type) pair is not in
            CONTENT_TYPE_TO_CAPABILITY mapping.
    """
    key = (platform, content_type)
    if key in CONTENT_TYPE_TO_CAPABILITY:
        mapped_platform, capability = CONTENT_TYPE_TO_CAPABILITY[key]
        return cap_for(mapped_platform, capability)
    raise UnknownContentTypeError(platform, content_type)


# =============================================================================
# BUNDLE CREATION
# =============================================================================


def create_evidence_bundle(
    brand_id: UUID,
    *,
    criteria: BundleCriteria | None = None,
) -> "EvidenceBundle":
    """
    Create an EvidenceBundle with deterministic selection.

    This is the main entrypoint for PR-4 bundling.

    Selection algorithm:
    1. Get all enabled source connections for brand
    2. For each platform/content_type:
       a. Filter eligible items (exclude collection pages, LinkedIn profile posts)
       b. Select recent_M most recent + top_engagement_N by engagement score
       c. Respect per-platform cap
    3. Merge across platforms respecting global max
    4. Create EvidenceBundle with criteria_json and summary_json

    Args:
        brand_id: UUID of the brand to bundle evidence for
        criteria: Optional BundleCriteria override (for testing)

    Returns:
        Created EvidenceBundle instance
    """
    from kairo.brandbrain.models import (
        EvidenceBundle,
        NormalizedEvidenceItem,
        SourceConnection,
    )

    if criteria is None:
        criteria = BundleCriteria()

    # Get enabled source connections
    enabled_sources = SourceConnection.objects.filter(
        brand_id=brand_id,
        is_enabled=True,
    ).values_list("platform", "capability", flat=False)

    enabled_platforms = set()
    enabled_capabilities = {}
    for platform, capability in enabled_sources:
        enabled_platforms.add(platform)
        if platform not in enabled_capabilities:
            enabled_capabilities[platform] = set()
        enabled_capabilities[platform].add(capability)

    logger.info(
        "Creating bundle for brand %s with %d enabled platforms",
        brand_id,
        len(enabled_platforms),
    )

    # Determine global max
    global_max = global_max_normalized_items()

    # Track selection stats
    summary = {
        "by_platform": {},
        "total_selected": 0,
        "total_eligible": 0,
        "excluded_collection_pages": 0,
        "excluded_linkedin_profile_posts": 0,
        "web_only_exception_applied": False,
    }

    # ==========================================================================
    # CANDIDATE QUERYSET
    # ==========================================================================
    # This is the base candidate set we bundle from: brand_id + enabled platforms.
    # All predicates (like web-only) and per-platform slices must be derived from
    # this queryset to ensure consistency. If we later add more filters (content_type
    # gating, etc.), they should be applied here so has_non_web_evidence and all
    # downstream queries stay accurate.
    candidate_qs = NormalizedEvidenceItem.objects.filter(
        brand_id=brand_id,
        platform__in=enabled_platforms,
    )

    # Check if we have non-web evidence in the candidate set.
    # "Web-only" means: in the candidate set we're bundling from, there are zero
    # non-web items. This determines whether collection pages should be included
    # (web-only exception) or excluded.
    # IMPORTANT: This predicate is derived from candidate_qs to ensure it cannot
    # drift from the actual bundling logic. Any filters added to candidate_qs
    # above will automatically be reflected here.
    has_non_web_evidence = candidate_qs.exclude(platform="web").exists()

    # Collect items per platform/content_type
    all_selected_items: list["NormalizedEvidenceItem"] = []
    items_by_platform: dict[str, list["NormalizedEvidenceItem"]] = {}

    # Get unique platform/content_type combinations from candidate set
    platform_content_types = (
        candidate_qs
        .values_list("platform", "content_type")
        .distinct()
    )

    for platform, content_type in platform_content_types:
        # Build base query from candidate_qs (already filtered by brand_id + enabled platforms)
        base_query = candidate_qs.filter(
            platform=platform,
            content_type=content_type,
        )

        # Apply exclusions
        excluded_count = 0

        # LinkedIn profile posts exclusion note:
        # NormalizedEvidenceItem does NOT have capability or source_connection_id,
        # so the bundler CANNOT distinguish linkedin.company_posts vs linkedin.profile_posts
        # at the NEI level. Containment of unvalidated profile_posts is enforced upstream:
        # - Ingestion gating: profile_posts capability is disabled by default
        # - Normalization adapter gating: only creates NEI for enabled capabilities
        # The criteria.exclude_linkedin_profile_posts flag exists for documentation and
        # future-proofing, but no filtering happens here.
        if platform == "linkedin" and content_type == "text_post":
            if criteria.exclude_linkedin_profile_posts and not _is_linkedin_profile_posts_enabled():
                logger.debug(
                    "LinkedIn profile posts exclusion requested but bundler cannot distinguish "
                    "company_posts vs profile_posts at NEI level for brand %s. "
                    "Containment enforced upstream via ingestion/normalization gating.",
                    brand_id,
                )

        # Exclude collection pages for web (unless web-only)
        if platform == "web" and criteria.exclude_collection_pages:
            collection_page_query = base_query.filter(
                flags_json__is_collection_page=True
            )
            collection_count = collection_page_query.count()

            if has_non_web_evidence:
                # Exclude collection pages
                base_query = base_query.exclude(
                    flags_json__is_collection_page=True
                )
                summary["excluded_collection_pages"] += collection_count
            else:
                # Web-only exception: include collection pages
                summary["web_only_exception_applied"] = True
                logger.info(
                    "Web-only exception: allowing %d collection pages for brand %s",
                    collection_count,
                    brand_id,
                )

        # Get cap for this platform/content_type
        platform_cap = _get_cap_for_item(platform, content_type)

        # Get total eligible count
        total_eligible = base_query.count()
        summary["total_eligible"] += total_eligible

        if total_eligible == 0:
            continue

        # Selection: recent_M + top_engagement_N, capped at platform_cap
        selection_limit = min(
            platform_cap,
            criteria.recent_m + criteria.top_engagement_n,
        )

        # Get recent items (ordered by published_at DESC, then canonical_url for determinism)
        recent_items = list(
            base_query.order_by(
                F("published_at").desc(nulls_last=True),
                "canonical_url",
            )[:criteria.recent_m]
        )

        recent_ids = {item.id for item in recent_items}

        # Get remaining items for engagement scoring (exclude already selected)
        remaining_query = base_query.exclude(id__in=recent_ids)

        # Score and sort by engagement
        remaining_items = list(remaining_query)
        scored_items = [
            (item, compute_engagement_score(item))
            for item in remaining_items
        ]

        # Sort by score DESC, then published_at DESC, then canonical_url for determinism
        # Uses numeric timestamp to avoid TypeError when comparing datetime vs None
        scored_items.sort(
            key=lambda x: (
                -x[1],  # score DESC
                -(x[0].published_at.timestamp() if x[0].published_at else 0),  # published_at DESC
                x[0].canonical_url,  # tie-breaker
            ),
        )

        # Take top_engagement_n from scored
        top_engagement_items = [item for item, score in scored_items[:criteria.top_engagement_n]]

        # Combine and cap
        combined = recent_items + top_engagement_items

        # Remove duplicates while preserving order (in case of overlap)
        seen = set()
        selected = []
        for item in combined:
            if item.id not in seen and len(selected) < selection_limit:
                seen.add(item.id)
                selected.append(item)

        if platform not in items_by_platform:
            items_by_platform[platform] = []
        items_by_platform[platform].extend(selected)
        all_selected_items.extend(selected)

        summary["by_platform"][platform] = summary["by_platform"].get(platform, {})
        summary["by_platform"][platform][content_type] = {
            "eligible": total_eligible,
            "selected": len(selected),
            "cap": platform_cap,
        }

    # Apply global max cap
    if len(all_selected_items) > global_max:
        logger.info(
            "Applying global max cap: %d items -> %d",
            len(all_selected_items),
            global_max,
        )

        # Sort all items by engagement score DESC for global selection
        all_scored = [
            (item, compute_engagement_score(item))
            for item in all_selected_items
        ]
        all_scored.sort(
            key=lambda x: (
                -x[1],
                -(x[0].published_at.timestamp() if x[0].published_at else 0),
                x[0].canonical_url,
            ),
        )

        all_selected_items = [item for item, score in all_scored[:global_max]]

    summary["total_selected"] = len(all_selected_items)

    # Extract item IDs in deterministic order
    # Sort by platform, then by score, then by published_at, then canonical_url
    all_selected_items.sort(
        key=lambda x: (
            x.platform,
            -compute_engagement_score(x),
            -(x.published_at.timestamp() if x.published_at else 0),
            x.canonical_url,
        ),
    )

    item_ids = [str(item.id) for item in all_selected_items]

    # Add transcript coverage to summary
    transcript_count = sum(
        1 for item in all_selected_items
        if (item.flags_json or {}).get("has_transcript", False)
    )
    summary["transcript_coverage"] = {
        "items_with_transcript": transcript_count,
        "total_items": len(all_selected_items),
        "coverage": transcript_count / len(all_selected_items) if all_selected_items else 0.0,
    }

    # Add caps used to criteria
    criteria_json = criteria.to_dict()
    criteria_json["global_max"] = global_max
    criteria_json["caps_used"] = {
        f"{p}/{ct}": _get_cap_for_item(p, ct)
        for p, ct in platform_content_types
        if p in enabled_platforms
    }

    # Create bundle
    bundle = EvidenceBundle.objects.create(
        brand_id=brand_id,
        criteria_json=criteria_json,
        item_ids=item_ids,
        summary_json=summary,
    )

    logger.info(
        "Created bundle %s for brand %s: %d items selected",
        bundle.id,
        brand_id,
        len(item_ids),
    )

    return bundle


# =============================================================================
# FEATURE REPORT CREATION
# =============================================================================


def create_feature_report(bundle: "EvidenceBundle") -> "FeatureReport":
    """
    Create a deterministic FeatureReport from an EvidenceBundle.

    This extracts statistics from the bundle items with no ML or randomness.

    Stats included:
    - Average text_primary length by platform
    - Emoji density (emojis / chars)
    - CTA frequency (keyword matching)
    - Hashtag usage stats
    - Hook markers frequency

    Args:
        bundle: EvidenceBundle to analyze

    Returns:
        Created FeatureReport instance
    """
    from kairo.brandbrain.models import FeatureReport, NormalizedEvidenceItem

    # Load bundle items
    item_ids = [UUID(id_str) for id_str in bundle.item_ids]
    items = list(
        NormalizedEvidenceItem.objects.filter(id__in=item_ids)
    )

    # Sort items deterministically for consistent processing
    items.sort(key=lambda x: (x.platform, x.canonical_url))

    # Extract all features
    stats_json = extract_all_features(items)

    # Add metadata
    stats_json["bundle_id"] = str(bundle.id)
    stats_json["item_count"] = len(items)

    # Create report
    report = FeatureReport.objects.create(
        brand_id=bundle.brand_id,
        bundle=bundle,
        stats_json=stats_json,
    )

    logger.info(
        "Created feature report %s for bundle %s: %d items analyzed",
        report.id,
        bundle.id,
        len(items),
    )

    return report
