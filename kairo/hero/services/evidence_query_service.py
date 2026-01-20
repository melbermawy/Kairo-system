"""
Evidence Query Service.

PR-3: Query helpers for EvidenceItem.
PR-5: Strict mode for read-time join (raises on missing IDs).
Per opportunities_v1_prd.md Section F.1 (EvidencePreviewDTO requirements).

This service provides:
- Batch fetch of EvidenceItems by IDs
- Stable ordering matching input ID order
- Efficient single-query retrieval
- Strict mode for invariant enforcement

IMPORTANT: This is query-only for PR-3. No creation/mutation logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from kairo.hero.models import EvidenceItem

logger = logging.getLogger(__name__)


@dataclass
class EvidencePreview:
    """
    Lightweight preview of evidence for UI display.

    Per PRD F.1: EvidencePreviewDTO fields.
    This is the minimal data needed for opportunity card previews.
    """

    id: UUID
    platform: str
    canonical_url: str
    author_ref: str
    text_snippet: str  # First 200 chars of text_primary
    has_transcript: bool


def fetch_evidence_by_ids(
    evidence_ids: list[UUID],
) -> list["EvidenceItem"]:
    """
    Fetch EvidenceItems by ID list in a single query.

    Args:
        evidence_ids: List of UUIDs to fetch

    Returns:
        List of EvidenceItem instances, ordered to match input IDs.
        Missing IDs are silently skipped (no error).

    Query efficiency:
        - Single query regardless of list size
        - Uses IN clause with indexed PK
    """
    from kairo.hero.models import EvidenceItem

    if not evidence_ids:
        return []

    # Fetch all in one query
    items_by_id = {
        item.id: item
        for item in EvidenceItem.objects.filter(id__in=evidence_ids)
    }

    # Return in input order, skipping any missing
    ordered_items = []
    for eid in evidence_ids:
        if eid in items_by_id:
            ordered_items.append(items_by_id[eid])
        else:
            logger.warning(
                "EvidenceItem not found",
                extra={"evidence_id": str(eid)},
            )

    return ordered_items


def fetch_evidence_previews(
    evidence_ids: list[UUID],
    *,
    strict: bool = False,
) -> list[EvidencePreview]:
    """
    Fetch evidence previews for UI display.

    Args:
        evidence_ids: List of UUIDs to fetch
        strict: If True, raises ValueError if any evidence_id is missing in DB.
                PR-5: Use strict=True for read-time join in OpportunitiesBoard.to_dto().

    Returns:
        List of EvidencePreview instances, ordered to match input IDs.
        If strict=False, missing IDs are silently skipped (no error).
        If strict=True, raises ValueError for missing IDs (invariant violation).

    Raises:
        ValueError: If strict=True and any evidence_id is not found in DB.

    Per PRD F.1: Returns enough fields for EvidencePreviewDTO:
        - id, platform, canonical_url, author_ref, text_snippet, has_transcript
    """
    from kairo.hero.models import EvidenceItem

    if not evidence_ids:
        return []

    # Fetch all in one query
    items_by_id = {
        item.id: item
        for item in EvidenceItem.objects.filter(id__in=evidence_ids)
    }

    # PR-5: Check for missing IDs in strict mode
    if strict:
        missing_ids = [eid for eid in evidence_ids if eid not in items_by_id]
        if missing_ids:
            raise ValueError(
                f"PR-5 invariant violation: Evidence IDs not found in database: "
                f"{[str(eid) for eid in missing_ids]}. "
                "This indicates a data integrity issue - evidence_ids in Opportunity "
                "must reference existing EvidenceItem records."
            )

    previews = []
    for eid in evidence_ids:
        item = items_by_id.get(eid)
        if item is None:
            # Non-strict mode: skip missing
            logger.warning(
                "EvidenceItem not found",
                extra={"evidence_id": str(eid)},
            )
            continue

        # Truncate text to 200 chars for snippet
        text_snippet = (item.text_primary or "")[:200].strip()
        if len(item.text_primary or "") > 200:
            text_snippet = text_snippet + "..."

        previews.append(
            EvidencePreview(
                id=item.id,
                platform=item.platform,
                canonical_url=item.canonical_url,
                author_ref=item.author_ref,
                text_snippet=text_snippet,
                has_transcript=item.has_transcript,
            )
        )

    return previews
