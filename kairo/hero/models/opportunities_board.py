"""
OpportunitiesBoard: Persisted TodayBoard state.

PR1: Background execution infrastructure for opportunities v2.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

The OpportunitiesBoard persists the result of opportunity generation:
- state: The terminal state (ready, insufficient_evidence, error)
- opportunities_json: Serialized list of opportunity IDs
- evidence_summary_json: Summary of evidence used
- diagnostics_json: Generation diagnostics for observability

CRITICAL INVARIANTS:
- Only background jobs write to this table
- GET /today reads from this table (via cache first)
- State transitions are explicit and auditable
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.db import models

from kairo.core.enums import TodayBoardState
from kairo.core.models import Brand

if TYPE_CHECKING:
    from kairo.hero.dto import TodayBoardDTO


class OpportunitiesBoard(models.Model):
    """
    Persisted TodayBoard for a brand.

    Each row represents a generation result. Only the latest board
    for a brand is used for GET /today responses.

    PR1: Created by background jobs, never by GET requests.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="opportunities_boards",
    )

    # State machine state (terminal states only in DB)
    state = models.CharField(
        max_length=30,
        choices=TodayBoardState.choices,
        default=TodayBoardState.NOT_GENERATED_YET,
        db_index=True,
    )

    # PR1.1: Machine-parseable reason for ready state
    # REQUIRED when state=ready AND opportunity_ids is empty
    # Values: "generated", "gates_only_no_synthesis", "no_valid_candidates", "empty_brand_context"
    ready_reason = models.CharField(max_length=50, null=True, blank=True)

    # Opportunity IDs (list of UUIDs for this board)
    # Actual Opportunity records are in core.Opportunity
    opportunity_ids = models.JSONField(default=list)

    # Evidence summary for diagnostics/UI
    evidence_summary_json = models.JSONField(default=dict)

    # Evidence shortfall details (if state is insufficient_evidence)
    evidence_shortfall_json = models.JSONField(default=dict)

    # Remediation message for degraded states
    remediation = models.TextField(null=True, blank=True)

    # Generation diagnostics (timing, counts, etc.)
    diagnostics_json = models.JSONField(default=dict)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hero"
        db_table = "hero_opportunities_board"
        indexes = [
            # Latest board lookup for a brand
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_oppboard_brand_latest",
            ),
            models.Index(
                fields=["brand", "state"],
                name="idx_oppboard_brand_state",
            ),
        ]

    def __str__(self) -> str:
        return f"OpportunitiesBoard {self.id} for {self.brand_id} [{self.state}]"

    def validate_referential_integrity(self) -> tuple[bool, list[str]]:
        """
        PR1.1: Validate that all opportunity_ids reference existing Opportunity records.

        PERSISTENCE TRUTH DECISION (PR1.1):
        - OpportunitiesBoard is the authoritative persisted snapshot for GET /today
        - opportunity_ids references REAL Opportunity records in core.Opportunity
        - This method validates that all referenced IDs exist

        Returns:
            Tuple of (is_valid, list of missing IDs as strings)
        """
        from uuid import UUID

        from kairo.core.models import Opportunity

        if not self.opportunity_ids:
            return True, []

        # Parse UUIDs
        try:
            ids = [UUID(str(oid)) for oid in self.opportunity_ids]
        except (ValueError, TypeError) as e:
            return False, [f"Invalid UUID format: {e}"]

        # Check which IDs exist
        existing_ids = set(
            Opportunity.objects.filter(id__in=ids).values_list("id", flat=True)
        )
        missing_ids = [str(oid) for oid in ids if oid not in existing_ids]

        return len(missing_ids) == 0, missing_ids

    def to_dto(self) -> "TodayBoardDTO":
        """
        Convert to TodayBoardDTO for API responses.

        PR-5: Implements read-time join for evidence_preview.
        Uses a single batched query to fetch all evidence previews.

        MUST be called with opportunities loaded separately.
        """
        from datetime import timezone
        from uuid import UUID as UUIDType

        from kairo.core.models import Opportunity
        from kairo.hero.dto import (
            BrandSnapshotDTO,
            EvidencePreviewDTO,
            EvidenceShortfallDTO,
            OpportunityDTO,
            TodayBoardDTO,
            TodayBoardMetaDTO,
        )
        from kairo.hero.services.evidence_query_service import fetch_evidence_previews

        # Load opportunities by IDs
        opp_data_list = []  # Temporary storage for opportunity data before DTO creation
        all_evidence_ids = []  # Collect all evidence IDs for batched fetch
        evidence_ids_by_opp: dict[UUIDType, list[UUIDType]] = {}  # Track per-opportunity

        if self.opportunity_ids:
            opp_records = Opportunity.objects.filter(id__in=self.opportunity_ids)
            for opp in opp_records:
                # PR-2: Read why_now and evidence_ids from metadata
                metadata = opp.metadata or {}
                why_now = metadata.get("why_now", "")

                # PR-2: Invalid why_now in DB is an INVARIANT VIOLATION
                # This should never happen if _persist_opportunities is working correctly.
                # If it does, raise an error - do NOT silently return partial results.
                if not why_now or len(why_now.strip()) < 10:
                    raise ValueError(
                        f"PR-2 invariant violation: Opportunity {opp.id} has invalid why_now "
                        f"(length={len(why_now.strip()) if why_now else 0}). "
                        "This indicates a persistence bug - opportunities without valid why_now "
                        "should not be in the database."
                    )

                # PR-2/5: Parse evidence_ids from metadata
                evidence_ids_raw = metadata.get("evidence_ids", [])
                evidence_ids = []
                for eid in evidence_ids_raw:
                    try:
                        evidence_ids.append(UUIDType(str(eid)))
                    except (ValueError, TypeError):
                        pass  # Skip invalid UUIDs (not critical)

                # Collect evidence IDs for batched fetch (PR-5)
                evidence_ids_by_opp[opp.id] = evidence_ids
                all_evidence_ids.extend(evidence_ids)

                opp_data_list.append({
                    "record": opp,
                    "why_now": why_now.strip(),
                    "evidence_ids": evidence_ids,
                })

        # PR-5: Batch fetch all evidence previews in a SINGLE query
        # Deduplicate but preserve ordering information
        unique_evidence_ids = list(dict.fromkeys(all_evidence_ids))
        evidence_previews_list = fetch_evidence_previews(
            unique_evidence_ids,
            strict=True,  # PR-5: Raise ValueError on missing IDs
        )

        # Build preview lookup dict
        preview_by_id: dict[UUIDType, EvidencePreviewDTO] = {}
        for preview in evidence_previews_list:
            preview_by_id[preview.id] = EvidencePreviewDTO(
                id=preview.id,
                platform=preview.platform,
                canonical_url=preview.canonical_url,
                author_ref=preview.author_ref,
                text_snippet=preview.text_snippet,
                has_transcript=preview.has_transcript,
            )

        # Build opportunity DTOs with evidence previews
        opportunities = []
        for opp_data in opp_data_list:
            opp = opp_data["record"]
            evidence_ids = opp_data["evidence_ids"]

            # Map evidence_ids to previews in order (PR-5: stable ordering)
            evidence_preview = [
                preview_by_id[eid]
                for eid in evidence_ids
                if eid in preview_by_id
            ]

            opportunities.append(
                OpportunityDTO(
                    id=opp.id,
                    brand_id=opp.brand_id,
                    title=opp.title,
                    angle=opp.angle,
                    why_now=opp_data["why_now"],  # PR-2: Required field
                    type=opp.type,
                    primary_channel=opp.primary_channel,
                    score=opp.score or 0.0,
                    score_explanation=opp.score_explanation,
                    source=opp.source or "",
                    source_url=opp.source_url,
                    persona_id=opp.persona_id,
                    pillar_id=opp.pillar_id,
                    suggested_channels=opp.suggested_channels or [],
                    evidence_ids=evidence_ids,  # PR-2: Forward-compat field
                    evidence_preview=evidence_preview,  # PR-5: Read-time join
                    is_pinned=opp.is_pinned,
                    is_snoozed=opp.is_snoozed,
                    snoozed_until=opp.snoozed_until,
                    created_via=opp.created_via,
                    created_at=opp.created_at,
                    updated_at=opp.updated_at,
                )
            )

        # Build minimal snapshot
        brand = self.brand
        snapshot = BrandSnapshotDTO(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or None,
            pillars=[],
            personas=[],
            voice_tone_tags=brand.tone_tags or [],
            taboos=brand.taboos or [],
        )

        # Build evidence shortfall if applicable
        evidence_shortfall = None
        if self.evidence_shortfall_json:
            evidence_shortfall = EvidenceShortfallDTO(
                required_items=self.evidence_shortfall_json.get("required_items", 8),
                found_items=self.evidence_shortfall_json.get("found_items", 0),
                required_platforms=self.evidence_shortfall_json.get("required_platforms", []),
                found_platforms=self.evidence_shortfall_json.get("found_platforms", []),
                missing_platforms=self.evidence_shortfall_json.get("missing_platforms", []),
                transcript_coverage=self.evidence_shortfall_json.get("transcript_coverage", 0.0),
                min_transcript_coverage=self.evidence_shortfall_json.get("min_transcript_coverage", 0.3),
            )

        # Build metadata
        diagnostics = self.diagnostics_json or {}
        meta = TodayBoardMetaDTO(
            generated_at=self.created_at.replace(tzinfo=timezone.utc) if self.created_at.tzinfo is None else self.created_at,
            source="hero_f1_v2",
            state=TodayBoardState(self.state),
            ready_reason=self.ready_reason,  # PR1.1: machine-parseable reason
            job_id=None,  # Board is complete, no job running
            cache_hit=False,  # Caller sets this
            cache_key=None,  # Caller sets this
            degraded=self.state in (TodayBoardState.INSUFFICIENT_EVIDENCE, TodayBoardState.ERROR),
            reason=self.state if self.state != TodayBoardState.READY else None,
            remediation=self.remediation,
            evidence_shortfall=evidence_shortfall,
            total_candidates=diagnostics.get("total_candidates"),
            opportunity_count=len(opportunities),
            notes=diagnostics.get("notes", []),
            wall_time_ms=diagnostics.get("wall_time_ms"),
            evidence_fetch_ms=diagnostics.get("evidence_fetch_ms"),
        )

        return TodayBoardDTO(
            brand_id=self.brand_id,
            snapshot=snapshot,
            opportunities=opportunities,
            meta=meta,
        )
