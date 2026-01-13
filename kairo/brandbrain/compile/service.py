"""
BrandBrain Compile Orchestration Service.

PR-5: Compile lifecycle management with stub LLM output.
PR-6: Durable job queue + real ingestion wiring.

Per spec Section 7.1, compile orchestration handles:
- Step 0: Validate gating requirements (Tier0 required fields + ≥1 enabled source)
- Step 1-2: Load onboarding + ensure freshness
- Step 3: Normalize (idempotent)
- Step 4: Bundle
- Step 5: FeatureReport
- Step 6-11: LLM compile + QA + merge (STUB for PR-6)

Async Mechanism (PR-6):
Durable job queue with DB-backed persistence.
- POST /compile enqueues job and returns immediately
- Worker process claims and executes jobs
- Jobs survive restarts
- Retry with exponential backoff

Sync Mode (for tests):
- sync=True bypasses job queue and runs inline
- Required for SQLite in-memory tests (no thread sharing)
"""

from __future__ import annotations

import logging
import os
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

    PR-6: Production uses durable job queue (enqueues job, worker executes).
    Tests use sync=True for inline execution (SQLite in-memory).

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

    # Execute work
    if sync:
        # Synchronous execution for tests (SQLite in-memory doesn't share between threads)
        # Uses the new worker module with real ingestion
        from kairo.brandbrain.compile.worker import execute_compile_job
        execute_compile_job(compile_run.id, force_refresh)
        compile_run.refresh_from_db()
        return CompileResult(
            compile_run_id=compile_run.id,
            status=compile_run.status,
            poll_url=f"/api/brands/{brand_id}/brandbrain/compile/{compile_run.id}/status",
        )
    else:
        # Production: Enqueue job to durable job queue
        # Worker process will claim and execute
        from kairo.brandbrain.jobs import enqueue_compile_job
        enqueue_compile_job(
            brand_id=brand_id,
            compile_run_id=compile_run.id,
            force_refresh=force_refresh,
            prompt_version=prompt_version,
            model=model,
        )
        return CompileResult(
            compile_run_id=compile_run.id,
            status="PENDING",
            poll_url=f"/api/brands/{brand_id}/brandbrain/compile/{compile_run.id}/status",
        )


# =============================================================================
# LEGACY WORKER (PR-5 compatibility - deprecated)
# =============================================================================
# These functions are kept for backward compatibility but are deprecated.
# PR-6 moved worker logic to kairo.brandbrain.compile.worker module.


def _run_compile_worker(compile_run_id: UUID, force_refresh: bool = False) -> None:
    """
    DEPRECATED: Use kairo.brandbrain.compile.worker.execute_compile_job instead.

    This is kept for backward compatibility. PR-6 moved worker logic to
    the worker module with real ingestion support.
    """
    from kairo.brandbrain.compile.worker import execute_compile_job
    execute_compile_job(compile_run_id, force_refresh)


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
