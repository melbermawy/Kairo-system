"""
BrandBrain Compile Orchestration Service.

PR-5: Compile lifecycle management with stub LLM output.

Per spec Section 7.1, compile orchestration handles:
- Step 0: Validate gating requirements (Tier0 required fields + ≥1 enabled source)
- Step 1-2: Load onboarding + ensure freshness
- Step 3: Normalize (idempotent)
- Step 4: Bundle
- Step 5: FeatureReport
- Step 6-11: LLM compile + QA + merge (STUB for PR-5)

Async Mechanism (PR-5 Decision):
No existing job framework (Celery/Django-Q/RQ) in codebase.
Using ThreadPoolExecutor for minimal async - documented tradeoff:
- Pros: No new dependencies, works in any deployment
- Cons: No persistence across restarts, limited scalability
- Future: Migrate to proper job queue when added (PR-6+)
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from kairo.brandbrain.compile.hashing import compute_compile_input_hash
from kairo.brandbrain.freshness import any_source_stale, check_source_freshness

if TYPE_CHECKING:
    from kairo.brandbrain.models import BrandBrainCompileRun, BrandBrainSnapshot


logger = logging.getLogger(__name__)

# Thread pool for async compile work
# Max workers = 4 to limit concurrent compiles
# This is a minimal async mechanism for PR-5
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="brandbrain_compile_")


# =============================================================================
# GATING ERRORS
# =============================================================================


@dataclass
class GatingError:
    """A single gating validation error."""
    code: str
    message: str


@dataclass
class GatingResult:
    """Result of compile gating validation."""
    allowed: bool
    errors: list[GatingError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "errors": [{"code": e.code, "message": e.message} for e in self.errors],
        }


# Required Tier0 fields per spec Section 7.0
TIER0_REQUIRED_FIELDS = [
    "tier0.what_we_do",
    "tier0.who_for",
    "tier0.primary_goal",
    "tier0.cta_posture",
]


def check_compile_gating(brand_id: UUID) -> GatingResult:
    """
    Check if compile is allowed for a brand.

    Per spec Section 7.0, compile requires:
    1. Tier0 required fields present
    2. At least one enabled SourceConnection

    Returns:
        GatingResult with allowed=True or errors list.
    """
    from kairo.brandbrain.models import BrandOnboarding, SourceConnection

    errors = []

    # Check 1: Tier0 required fields
    try:
        onboarding = BrandOnboarding.objects.get(brand_id=brand_id)
        answers = onboarding.answers_json or {}
    except BrandOnboarding.DoesNotExist:
        answers = {}

    missing_fields = []
    for field_name in TIER0_REQUIRED_FIELDS:
        value = answers.get(field_name)
        # Check for non-empty value (None, "", [], {} all fail)
        if not value:
            missing_fields.append(field_name)

    if missing_fields:
        errors.append(GatingError(
            code="MISSING_TIER0_FIELDS",
            message=f"Missing required Tier0 fields: {', '.join(missing_fields)}",
        ))

    # Check 2: At least one enabled source
    has_enabled_source = SourceConnection.objects.filter(
        brand_id=brand_id,
        is_enabled=True,
    ).exists()

    if not has_enabled_source:
        errors.append(GatingError(
            code="NO_ENABLED_SOURCES",
            message="At least one enabled SourceConnection is required",
        ))

    return GatingResult(
        allowed=len(errors) == 0,
        errors=errors,
    )


# =============================================================================
# SHORT-CIRCUIT DETECTION
# =============================================================================


@dataclass
class ShortCircuitResult:
    """Result of short-circuit check."""
    is_noop: bool
    snapshot: "BrandBrainSnapshot | None" = None
    reason: str = ""


def should_short_circuit_compile(
    brand_id: UUID,
    prompt_version: str = "v1",
    model: str = "gpt-4",
) -> ShortCircuitResult:
    """
    Check if compile would be a no-op.

    Per spec Section 1.1, no-op conditions (all must be true):
    1. Latest snapshot exists for brand
    2. All enabled source connections have successful ApifyRuns within TTL
    3. hash(onboarding_answers_json) matches snapshot's hash
    4. hash(overrides_json + pinned_paths) matches
    5. prompt_version and model match current config

    Must complete in <20ms to stay within compile kickoff budget.

    Returns:
        ShortCircuitResult with is_noop=True if no-op, else False.
    """
    from kairo.brandbrain.models import BrandBrainSnapshot, BrandBrainCompileRun

    # Check 1: Latest snapshot exists
    latest_snapshot = (
        BrandBrainSnapshot.objects
        .filter(brand_id=brand_id)
        .order_by("-created_at")
        .first()
    )

    if not latest_snapshot:
        return ShortCircuitResult(
            is_noop=False,
            reason="No existing snapshot",
        )

    # Check 2: No stale sources
    if any_source_stale(brand_id):
        return ShortCircuitResult(
            is_noop=False,
            reason="One or more sources need refresh",
        )

    # Check 3-5: Compare input hashes
    # The compile run should have stored the input hash
    compile_run = latest_snapshot.compile_run
    if not compile_run:
        return ShortCircuitResult(
            is_noop=False,
            reason="Snapshot has no associated compile run",
        )

    # Check prompt_version and model match
    if compile_run.prompt_version != prompt_version or compile_run.model != model:
        return ShortCircuitResult(
            is_noop=False,
            reason="Prompt version or model changed",
        )

    # Compute current input hash
    current_hash = compute_compile_input_hash(brand_id, prompt_version, model)

    # Get stored hash from compile run (stored in onboarding_snapshot_json)
    stored_hash = compile_run.onboarding_snapshot_json.get("input_hash")

    if stored_hash != current_hash:
        return ShortCircuitResult(
            is_noop=False,
            reason="Input hash changed",
        )

    return ShortCircuitResult(
        is_noop=True,
        snapshot=latest_snapshot,
        reason="All inputs unchanged",
    )


# =============================================================================
# COMPILE RESULT
# =============================================================================


@dataclass
class CompileResult:
    """Result of compile kickoff."""
    compile_run_id: UUID
    status: str  # PENDING, RUNNING, SUCCEEDED, FAILED, UNCHANGED
    poll_url: str | None = None
    snapshot: "BrandBrainSnapshot | None" = None
    error: str | None = None


# =============================================================================
# COMPILE ORCHESTRATION
# =============================================================================


def compile_brandbrain(
    brand_id: UUID,
    force_refresh: bool = False,
    prompt_version: str = "v1",
    model: str = "gpt-4",
    sync: bool = False,
) -> CompileResult:
    """
    Kick off a BrandBrain compile.

    Per spec Section 7.1, this creates a BrandBrainCompileRun and schedules
    async work. Returns immediately with compile_run_id (within 200ms).

    Short-circuit: If inputs unchanged, returns existing snapshot immediately.

    Args:
        brand_id: UUID of the brand to compile
        force_refresh: If True, skip short-circuit check
        prompt_version: Compile prompt version
        model: LLM model identifier
        sync: If True, run compile synchronously (for tests with in-memory SQLite)

    Returns:
        CompileResult with compile_run_id and status.
    """
    from kairo.brandbrain.models import BrandBrainCompileRun

    # Step 0: Check gating
    gating = check_compile_gating(brand_id)
    if not gating.allowed:
        # Don't create a compile run for gating failures
        # Return error result (caller should return 4xx)
        error_msg = "; ".join(e.message for e in gating.errors)
        return CompileResult(
            compile_run_id=UUID(int=0),  # Placeholder - won't be used
            status="FAILED",
            error=error_msg,
        )

    # Short-circuit check (unless force_refresh)
    if not force_refresh:
        short_circuit = should_short_circuit_compile(brand_id, prompt_version, model)
        if short_circuit.is_noop:
            logger.info(
                "Short-circuit compile for brand %s: %s",
                brand_id,
                short_circuit.reason,
            )
            return CompileResult(
                compile_run_id=short_circuit.snapshot.compile_run.id if short_circuit.snapshot and short_circuit.snapshot.compile_run else UUID(int=0),
                status="UNCHANGED",
                snapshot=short_circuit.snapshot,
            )

    # Create compile run
    input_hash = compute_compile_input_hash(brand_id, prompt_version, model)

    compile_run = BrandBrainCompileRun.objects.create(
        brand_id=brand_id,
        prompt_version=prompt_version,
        model=model,
        status="PENDING",
        onboarding_snapshot_json={
            "input_hash": input_hash,
            "captured_at": timezone.now().isoformat(),
        },
        evidence_status_json={
            "reused": [],
            "refreshed": [],
            "skipped": [],
            "failed": [],
        },
    )

    logger.info(
        "Created compile run %s for brand %s",
        compile_run.id,
        brand_id,
    )

    # Execute work (sync for tests, async for production)
    if sync:
        # Synchronous execution for tests (SQLite in-memory doesn't share between threads)
        _run_compile_worker(compile_run.id, force_refresh)
        compile_run.refresh_from_db()
        return CompileResult(
            compile_run_id=compile_run.id,
            status=compile_run.status,
            poll_url=f"/api/brands/{brand_id}/brandbrain/compile/{compile_run.id}/status",
        )
    else:
        # Async execution for production
        _executor.submit(_run_compile_worker, compile_run.id, force_refresh)
        return CompileResult(
            compile_run_id=compile_run.id,
            status="PENDING",
            poll_url=f"/api/brands/{brand_id}/brandbrain/compile/{compile_run.id}/status",
        )


def _run_compile_worker(compile_run_id: UUID, force_refresh: bool = False) -> None:
    """
    Background worker that executes the compile pipeline.

    Per spec Section 7.1 steps 1-11:
    - Steps 1-5: Load, freshen, normalize, bundle, feature report
    - Steps 6-11: LLM compile (STUB), QA, merge, diff, snapshot

    PR-5 stubs the LLM compile (step 7) with placeholder output.
    """
    import django
    django.setup()  # Ensure Django is ready in worker thread

    from django.db import connection
    from kairo.brandbrain.models import (
        BrandBrainCompileRun,
        BrandBrainSnapshot,
        BrandOnboarding,
        SourceConnection,
    )
    from kairo.brandbrain.bundling import create_evidence_bundle, create_feature_report
    from kairo.brandbrain.actors.registry import is_capability_enabled

    # Close any stale connections in this thread
    connection.close()

    try:
        compile_run = BrandBrainCompileRun.objects.get(id=compile_run_id)
    except BrandBrainCompileRun.DoesNotExist:
        logger.error("Compile run %s not found", compile_run_id)
        return

    brand_id = compile_run.brand_id

    try:
        # Update status to RUNNING
        compile_run.status = "RUNNING"
        compile_run.save(update_fields=["status"])

        # Initialize evidence status tracking
        evidence_status = {
            "reused": [],
            "refreshed": [],
            "skipped": [],
            "failed": [],
        }

        # Step 1: Load onboarding
        try:
            onboarding = BrandOnboarding.objects.get(brand_id=brand_id)
            answers = onboarding.answers_json or {}
        except BrandOnboarding.DoesNotExist:
            answers = {}

        # Update onboarding snapshot
        compile_run.onboarding_snapshot_json["answers"] = answers
        compile_run.save(update_fields=["onboarding_snapshot_json"])

        # Step 2: Check source freshness and populate evidence_status
        sources = SourceConnection.objects.filter(
            brand_id=brand_id,
            is_enabled=True,
        )

        for source in sources:
            source_key = f"{source.platform}.{source.capability}"

            # Check if capability is enabled (feature flag for linkedin.profile_posts)
            if not is_capability_enabled(source.platform, source.capability):
                evidence_status["skipped"].append({
                    "source": source_key,
                    "reason": "Capability disabled (feature flag)",
                })
                continue

            # Check freshness
            freshness = check_source_freshness(source.id, force_refresh=force_refresh)

            if freshness.should_refresh:
                # PR-5: Mark as "would refresh" but don't actually trigger ingestion
                # Actual ingestion integration is PR-6+
                evidence_status["refreshed"].append({
                    "source": source_key,
                    "reason": freshness.reason,
                    "note": "PR-5 stub - ingestion not triggered",
                })
            else:
                evidence_status["reused"].append({
                    "source": source_key,
                    "reason": freshness.reason,
                    "run_age_hours": freshness.run_age_hours,
                })

        compile_run.evidence_status_json = evidence_status
        compile_run.save(update_fields=["evidence_status_json"])

        # Step 3: Normalize (idempotent)
        # PR-5: Skip actual normalization, rely on existing data

        # Step 4: Create EvidenceBundle
        try:
            bundle = create_evidence_bundle(brand_id)
            compile_run.bundle = bundle
            compile_run.save(update_fields=["bundle"])
            logger.info(
                "Created bundle %s with %d items for compile run %s",
                bundle.id,
                len(bundle.item_ids),
                compile_run_id,
            )
        except Exception as e:
            logger.warning(
                "Bundle creation failed for compile run %s: %s",
                compile_run_id,
                str(e),
            )
            bundle = None

        # Step 5: Create FeatureReport
        feature_report = None
        if bundle:
            try:
                feature_report = create_feature_report(bundle)
                logger.info(
                    "Created feature report %s for compile run %s",
                    feature_report.id,
                    compile_run_id,
                )
            except Exception as e:
                logger.warning(
                    "Feature report creation failed for compile run %s: %s",
                    compile_run_id,
                    str(e),
                )

        # Steps 6-7: LLM compile (STUB for PR-5)
        # Per spec, we stub with placeholder draft_json
        stub_draft = _create_stub_draft(answers, bundle, feature_report)
        compile_run.draft_json = stub_draft

        # Step 8: QA checks (STUB for PR-5)
        compile_run.qa_report_json = {
            "status": "STUB",
            "note": "PR-5 stub - QA not implemented",
            "checks": [],
        }

        # Steps 9-11: Merge overrides, compute diff, create snapshot
        # PR-5: Create minimal snapshot
        snapshot = _create_stub_snapshot(compile_run, stub_draft)

        # Mark as SUCCEEDED
        compile_run.status = "SUCCEEDED"
        compile_run.save(update_fields=["status", "draft_json", "qa_report_json"])

        logger.info(
            "Compile run %s succeeded with snapshot %s",
            compile_run_id,
            snapshot.id,
        )

    except Exception as e:
        logger.exception("Compile run %s failed", compile_run_id)
        compile_run.status = "FAILED"
        compile_run.error = str(e)
        compile_run.save(update_fields=["status", "error"])


def _create_stub_draft(
    answers: dict,
    bundle: Any | None,
    feature_report: Any | None,
) -> dict:
    """
    Create a stub draft_json for PR-5.

    This is NOT a real LLM compile. It's a placeholder that proves
    the pipeline works end-to-end.
    """
    return {
        "_stub": True,
        "_note": "PR-5 stub - LLM compile not implemented",
        "positioning": {
            "what_we_do": {
                "value": answers.get("tier0.what_we_do", ""),
                "confidence": 0.9 if answers.get("tier0.what_we_do") else 0.0,
                "sources": [{"type": "answer", "id": "tier0.what_we_do"}],
                "locked": False,
                "override_value": None,
            },
            "who_for": {
                "value": answers.get("tier0.who_for", ""),
                "confidence": 0.9 if answers.get("tier0.who_for") else 0.0,
                "sources": [{"type": "answer", "id": "tier0.who_for"}],
                "locked": False,
                "override_value": None,
            },
        },
        "voice": {
            "cta_policy": {
                "value": answers.get("tier0.cta_posture", "soft"),
                "confidence": 0.9 if answers.get("tier0.cta_posture") else 0.0,
                "sources": [{"type": "answer", "id": "tier0.cta_posture"}],
                "locked": False,
                "override_value": None,
            },
        },
        "meta": {
            "content_goal": {
                "value": answers.get("tier0.primary_goal", ""),
                "confidence": 0.9 if answers.get("tier0.primary_goal") else 0.0,
                "sources": [{"type": "answer", "id": "tier0.primary_goal"}],
                "locked": False,
                "override_value": None,
            },
            "evidence_summary": {
                "bundle_id": str(bundle.id) if bundle else None,
                "item_count": len(bundle.item_ids) if bundle else 0,
            },
            "feature_report_id": str(feature_report.id) if feature_report else None,
        },
    }


def _create_stub_snapshot(
    compile_run: "BrandBrainCompileRun",
    draft_json: dict,
) -> "BrandBrainSnapshot":
    """
    Create a BrandBrainSnapshot from the compile run.

    PR-5: Minimal snapshot with stub draft.
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    snapshot = BrandBrainSnapshot.objects.create(
        brand_id=compile_run.brand_id,
        compile_run=compile_run,
        snapshot_json=draft_json,
        diff_from_previous_json={
            "_note": "PR-5 stub - diff not computed",
        },
    )

    return snapshot


# =============================================================================
# STATUS RETRIEVAL
# =============================================================================


@dataclass
class CompileStatus:
    """Status of a compile run."""
    compile_run_id: UUID
    status: str
    error: str | None = None
    evidence_status: dict | None = None
    snapshot: "BrandBrainSnapshot | None" = None
    progress: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "compile_run_id": str(self.compile_run_id),
            "status": self.status,
        }

        if self.status == "RUNNING" and self.progress:
            result["progress"] = self.progress

        if self.status == "SUCCEEDED":
            result["evidence_status"] = self.evidence_status
            if self.snapshot:
                result["snapshot"] = {
                    "snapshot_id": str(self.snapshot.id),
                    "created_at": self.snapshot.created_at.isoformat(),
                    "snapshot_json": self.snapshot.snapshot_json,
                }

        if self.status == "FAILED":
            result["error"] = self.error
            result["evidence_status"] = self.evidence_status

        return result


def get_compile_status(compile_run_id: UUID, brand_id: UUID) -> CompileStatus | None:
    """
    Get the status of a compile run.

    Pure DB read. No side effects. Target <30ms P95.

    SECURITY: Enforces brand ownership - compile run must belong to the
    specified brand. Prevents cross-brand data leakage.

    Args:
        compile_run_id: UUID of the compile run
        brand_id: UUID of the brand (enforced for security)

    Returns:
        CompileStatus or None if not found OR if brand_id doesn't match.
    """
    from kairo.brandbrain.models import BrandBrainCompileRun, BrandBrainSnapshot

    try:
        # SECURITY: Filter by BOTH compile_run_id AND brand_id
        compile_run = BrandBrainCompileRun.objects.get(
            id=compile_run_id,
            brand_id=brand_id,
        )
    except BrandBrainCompileRun.DoesNotExist:
        return None

    # Get snapshot if succeeded
    snapshot = None
    if compile_run.status == "SUCCEEDED":
        snapshot = (
            BrandBrainSnapshot.objects
            .filter(compile_run_id=compile_run_id)
            .first()
        )

    return CompileStatus(
        compile_run_id=compile_run.id,
        status=compile_run.status,
        error=compile_run.error,
        evidence_status=compile_run.evidence_status_json,
        snapshot=snapshot,
        progress={"stage": "compiling", "sources_completed": 0, "sources_total": 0}
        if compile_run.status == "RUNNING" else None,
    )
