"""
Observability Store Module.

PR-11: Observability, Classification, and Admin Surfaces.

Provides a filesystem-based observability sink for:
- Run events (start, complete, fail)
- LLM call events
- Engine step events
- Operational health events (ok/degraded/failed)

Storage format:
- JSONL files organized by run_id
- {KAIRO_OBS_DIR}/{run_id}/{kind}.jsonl
- Each line is a JSON object with timestamp + payload

Environment variables:
- KAIRO_OBS_ENABLED: Enable observability (default: false in dev, true in prod)
- KAIRO_OBS_DIR: Output directory (default: var/obs)

Per PR-map-and-standards §PR-11:
- Classification rules must be deterministic
- No business logic in admin; read-only views only

IMPORTANT: This module provides obs_health labels (ok/degraded/failed) for operational
health monitoring. These are DISTINCT from quality labels (good/partial/bad) in
kairo/hero/eval/quality_classifier.py which is the single source of truth for quality.
The two systems have different inputs/thresholds and are NOT equivalent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger("kairo.hero.observability")


# =============================================================================
# CONFIGURATION
# =============================================================================


def obs_enabled() -> bool:
    """
    Check if observability is enabled.

    Returns True if KAIRO_OBS_ENABLED is set to "true", "1", "yes", or "on".
    Default: false (to avoid noise in dev).
    """
    enabled_str = os.getenv("KAIRO_OBS_ENABLED", "").lower().strip()
    return enabled_str in ("true", "1", "yes", "on")


def obs_dir() -> Path:
    """
    Get the observability output directory.

    Default: var/obs (relative to working directory)
    """
    return Path(os.getenv("KAIRO_OBS_DIR", "var/obs"))


# =============================================================================
# EVENT KINDS
# =============================================================================

# Valid event kinds for type safety
EventKind = Literal[
    "run_start",
    "run_complete",
    "run_fail",
    "llm_call",
    "engine_step",
    "classification",
    "opportunity",
    "package",
    "variant",
]


# =============================================================================
# CORE FUNCTIONS
# =============================================================================


def append_event(
    run_id: "UUID",
    kind: EventKind,
    payload: dict[str, Any],
) -> bool:
    """
    Append an event to the observability store.

    Creates the directory structure if it doesn't exist.
    Appends a single line of JSON to {obs_dir}/{run_id}/{kind}.jsonl

    Args:
        run_id: UUID of the run (used for directory structure)
        kind: Event type (run_start, llm_call, etc.)
        payload: Event payload (will be serialized to JSON)

    Returns:
        True if event was written, False if observability is disabled or error

    Note:
        Failures are logged but do not raise exceptions.
        Observability should never break the main code path.
    """
    if not obs_enabled():
        return False

    try:
        # Build the event record with timestamp
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": str(run_id),
            "kind": kind,
            **payload,
        }

        # Build path
        run_dir = obs_dir() / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        file_path = run_dir / f"{kind}.jsonl"

        # Append to file (one JSON object per line)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

        return True

    except Exception as e:
        # Log but don't raise - observability should never break main path
        logger.warning(
            "Failed to append observability event",
            extra={
                "run_id": str(run_id),
                "kind": kind,
                "error": str(e),
            },
        )
        return False


def read_events(
    run_id: "UUID",
    kind: EventKind,
) -> list[dict[str, Any]]:
    """
    Read all events of a given kind for a run.

    Args:
        run_id: UUID of the run
        kind: Event type to read

    Returns:
        List of event dictionaries, empty list if file doesn't exist
    """
    file_path = obs_dir() / str(run_id) / f"{kind}.jsonl"

    if not file_path.exists():
        return []

    events = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception as e:
        logger.warning(
            "Failed to read observability events",
            extra={
                "run_id": str(run_id),
                "kind": kind,
                "error": str(e),
            },
        )

    return events


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    """
    List recent runs from the observability store.

    Scans the obs_dir for run directories and extracts metadata.

    Args:
        limit: Maximum number of runs to return

    Returns:
        List of run info dicts, sorted by timestamp (most recent first)
    """
    base_dir = obs_dir()

    if not base_dir.exists():
        return []

    runs = []

    try:
        for run_dir in base_dir.iterdir():
            if not run_dir.is_dir():
                continue

            # Try to get run metadata from run_start event
            run_info = {
                "run_id": run_dir.name,
                "path": str(run_dir),
                "timestamp": None,
                "brand_id": None,
                "flow": None,
                "status": None,
                "obs_health": None,
            }

            # Read run_start for metadata
            start_events = read_events_from_path(run_dir / "run_start.jsonl")
            if start_events:
                first = start_events[0]
                run_info["timestamp"] = first.get("ts")
                run_info["brand_id"] = first.get("brand_id")
                run_info["flow"] = first.get("flow")

            # Read run_complete or run_fail for status
            complete_events = read_events_from_path(run_dir / "run_complete.jsonl")
            if complete_events:
                run_info["status"] = "complete"
            else:
                fail_events = read_events_from_path(run_dir / "run_fail.jsonl")
                if fail_events:
                    run_info["status"] = "fail"
                else:
                    run_info["status"] = "running"

            # Read classification if exists
            class_events = read_events_from_path(run_dir / "classification.jsonl")
            if class_events:
                last = class_events[-1]
                run_info["obs_health"] = last.get("obs_health")

            runs.append(run_info)

    except Exception as e:
        logger.warning(
            "Failed to list observability runs",
            extra={"error": str(e)},
        )

    # Sort by timestamp (most recent first)
    runs.sort(key=lambda r: r.get("timestamp") or "", reverse=True)

    return runs[:limit]


def read_events_from_path(file_path: Path) -> list[dict[str, Any]]:
    """
    Read events from a specific file path.

    Helper for list_runs.
    """
    if not file_path.exists():
        return []

    events = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception:
        pass

    return events


def get_run_detail(run_id: "UUID") -> dict[str, Any]:
    """
    Get detailed information about a specific run.

    Returns all events grouped by kind.

    Args:
        run_id: UUID of the run

    Returns:
        Dict with run_id, events by kind, and computed stats
    """
    run_dir = obs_dir() / str(run_id)

    if not run_dir.exists():
        return {"run_id": str(run_id), "exists": False}

    result = {
        "run_id": str(run_id),
        "exists": True,
        "events": {},
        "stats": {},
    }

    # Read all event files
    event_kinds: list[EventKind] = [
        "run_start",
        "run_complete",
        "run_fail",
        "llm_call",
        "engine_step",
        "classification",
        "opportunity",
        "package",
        "variant",
    ]

    for kind in event_kinds:
        events = read_events(run_id, kind)
        if events:
            result["events"][kind] = events

    # Compute stats
    llm_events = result["events"].get("llm_call", [])
    if llm_events:
        total_latency = sum(e.get("latency_ms", 0) for e in llm_events)
        total_tokens_in = sum(e.get("tokens_in", 0) for e in llm_events)
        total_tokens_out = sum(e.get("tokens_out", 0) for e in llm_events)
        result["stats"]["llm_calls"] = len(llm_events)
        result["stats"]["total_latency_ms"] = total_latency
        result["stats"]["total_tokens_in"] = total_tokens_in
        result["stats"]["total_tokens_out"] = total_tokens_out

    return result


# =============================================================================
# CLASSIFICATION
# =============================================================================

# Observability health labels - distinct from eval quality labels!
#
# IMPORTANT: These are "obs_health" labels (ok/degraded/failed) NOT the
# eval quality labels (good/partial/bad) from kairo/hero/eval/quality_classifier.py.
#
# The single source of truth for quality classification is eval/quality_classifier.py.
# This module only provides lightweight operational health signals for observability.
# The two systems have different inputs and thresholds and are NOT equivalent.
ObsHealthLabel = Literal["ok", "degraded", "failed"]


def classify_f1_run(
    opportunity_count: int,
    valid_opportunity_count: int,
    taboo_violations: int = 0,
    status: str = "ok",
) -> tuple[ObsHealthLabel, str]:
    """
    Classify F1 (opportunity generation) run health as ok/degraded/failed.

    NOTE: This is an operational health check, NOT a quality assessment.
    For quality classification, use kairo/hero/eval/quality_classifier.py.

    Operational health thresholds:
    - ok: Engine succeeded and produced >= 3 valid opportunities, no taboo violations
    - degraded: Low output (1-2) or too many opportunities (>24) but engine didn't fail
    - failed: Engine failure, OR taboo violations, OR zero valid opportunities

    Args:
        opportunity_count: Total opportunities generated
        valid_opportunity_count: Opportunities passing validation
        taboo_violations: Number of taboo violations detected
        status: Engine status (ok, partial, degraded, fail)

    Returns:
        Tuple of (obs_health_label, reason)
    """
    # Failed: engine failure or taboo violations
    if status == "fail":
        return ("failed", "engine_failure")

    if taboo_violations > 0:
        return ("failed", f"taboo_violations:{taboo_violations}")

    if valid_opportunity_count == 0:
        return ("failed", "zero_valid_opportunities")

    # Ok: healthy operation
    if valid_opportunity_count >= 3:
        return ("ok", f"healthy_count:{valid_opportunity_count}")

    # Degraded: suboptimal but not failed
    return ("degraded", f"low_count:{valid_opportunity_count}")


def classify_f2_run(
    package_count: int,
    variant_count: int,
    expected_channels: int = 2,
    taboo_violations: int = 0,
    status: str = "ok",
) -> tuple[ObsHealthLabel, str]:
    """
    Classify F2 (package/variant generation) run health as ok/degraded/failed.

    NOTE: This is an operational health check, NOT a quality assessment.
    For quality classification, use kairo/hero/eval/quality_classifier.py.

    Operational health thresholds:
    - ok: Package created, variants for all expected channels, no taboo violations
    - degraded: Package created but missing some variants
    - failed: No package, OR taboo violations, OR engine failure

    Args:
        package_count: Number of packages created
        variant_count: Number of variants created
        expected_channels: Number of channels expected (default 2: linkedin, x)
        taboo_violations: Number of taboo violations detected
        status: Engine status

    Returns:
        Tuple of (obs_health_label, reason)
    """
    # Failed: engine failure or taboo violations
    if status == "fail":
        return ("failed", "engine_failure")

    if taboo_violations > 0:
        return ("failed", f"taboo_violations:{taboo_violations}")

    if package_count == 0:
        return ("failed", "no_package_created")

    # Ok: full coverage
    if variant_count >= expected_channels:
        return ("ok", f"full_coverage:{variant_count}_variants")

    # Degraded: some variants but not all channels
    if variant_count > 0:
        return ("degraded", f"partial_coverage:{variant_count}/{expected_channels}_variants")

    # Failed: no variants
    return ("failed", "no_variants_created")


def classify_run(
    f1_status: str,
    f2_status: str | None,
    opportunity_count: int = 0,
    valid_opportunity_count: int = 0,
    package_count: int = 0,
    variant_count: int = 0,
    taboo_violations: int = 0,
) -> tuple[ObsHealthLabel, ObsHealthLabel | None, ObsHealthLabel, str]:
    """
    Classify a full hero loop run (F1 + optional F2) for operational health.

    NOTE: This is an operational health check, NOT a quality assessment.
    For quality classification, use kairo/hero/eval/quality_classifier.py.

    Returns:
        Tuple of (f1_health, f2_health, run_health, reason)

    The run_health is the worst of f1_health and f2_health.
    """
    # Classify F1
    f1_label, f1_reason = classify_f1_run(
        opportunity_count=opportunity_count,
        valid_opportunity_count=valid_opportunity_count,
        taboo_violations=taboo_violations,
        status=f1_status,
    )

    # Classify F2 if it ran
    f2_label: ObsHealthLabel | None = None
    f2_reason = None
    if f2_status is not None:
        f2_label, f2_reason = classify_f2_run(
            package_count=package_count,
            variant_count=variant_count,
            taboo_violations=taboo_violations,
            status=f2_status,
        )

    # Overall run health is the worst of the two
    if f2_label is None:
        run_label = f1_label
        reason = f"f1:{f1_reason}"
    else:
        # Priority: failed > degraded > ok
        priority = {"failed": 0, "degraded": 1, "ok": 2}
        if priority[f1_label] <= priority[f2_label]:
            run_label = f1_label
            reason = f"f1:{f1_reason}"
        else:
            run_label = f2_label
            reason = f"f2:{f2_reason}"

    return (f1_label, f2_label, run_label, reason)


# =============================================================================
# HIGH-LEVEL LOGGING HELPERS
# =============================================================================


def log_run_start(
    run_id: "UUID",
    brand_id: "UUID",
    flow: str,
    trigger_source: str = "api",
) -> bool:
    """Log the start of a run."""
    return append_event(
        run_id=run_id,
        kind="run_start",
        payload={
            "brand_id": str(brand_id),
            "flow": flow,
            "trigger_source": trigger_source,
        },
    )


def log_run_complete(
    run_id: "UUID",
    brand_id: "UUID",
    flow: str,
    status: str,
    metrics: dict[str, Any] | None = None,
) -> bool:
    """Log the completion of a run."""
    return append_event(
        run_id=run_id,
        kind="run_complete",
        payload={
            "brand_id": str(brand_id),
            "flow": flow,
            "status": status,
            "metrics": metrics or {},
        },
    )


def log_run_fail(
    run_id: "UUID",
    brand_id: "UUID",
    flow: str,
    error: str,
    error_type: str | None = None,
) -> bool:
    """Log a run failure."""
    return append_event(
        run_id=run_id,
        kind="run_fail",
        payload={
            "brand_id": str(brand_id),
            "flow": flow,
            "error": error[:500],  # Truncate long errors
            "error_type": error_type,
        },
    )


def log_llm_call(
    run_id: "UUID",
    brand_id: "UUID",
    flow: str,
    model: str,
    role: str,
    latency_ms: int,
    tokens_in: int,
    tokens_out: int,
    status: str,
    estimated_cost_usd: float | None = None,
    error_summary: str | None = None,
) -> bool:
    """Log an LLM call."""
    payload = {
        "brand_id": str(brand_id),
        "flow": flow,
        "model": model,
        "role": role,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "status": status,
    }

    if estimated_cost_usd is not None:
        payload["estimated_cost_usd"] = estimated_cost_usd

    if error_summary:
        payload["error_summary"] = error_summary

    return append_event(run_id=run_id, kind="llm_call", payload=payload)


def log_classification(
    run_id: "UUID",
    brand_id: "UUID",
    f1_health: ObsHealthLabel,
    f2_health: ObsHealthLabel | None,
    run_health: ObsHealthLabel,
    reason: str,
) -> bool:
    """
    Log run operational health classification.

    NOTE: This logs obs_health (ok/degraded/failed), NOT quality labels.
    For quality classification, see kairo/hero/eval/quality_classifier.py.
    """
    return append_event(
        run_id=run_id,
        kind="classification",
        payload={
            "brand_id": str(brand_id),
            "f1_health": f1_health,
            "f2_health": f2_health,
            "run_health": run_health,
            "reason": reason,
            "obs_health": run_health,  # For easy filtering
        },
    )
