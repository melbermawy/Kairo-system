"""
BrandBrain Compile Worker.

PR-6: Refactored compile pipeline with real ingestion.

This module contains the actual compile execution logic,
separated from the async/job scheduling concerns.

The compile pipeline:
1. Set compile_run status RUNNING
2. Load onboarding answers
3. For each enabled source:
   - Check capability enabled
   - Freshness decision (refresh vs reuse)
   - If refresh: run Apify actor -> fetch raw -> normalize
   - If reuse: ensure normalization exists
4. Create EvidenceBundle
5. Create FeatureReport
6. LLM compile (STUB for PR-6)
7. Create BrandBrainSnapshot
8. Mark SUCCEEDED or FAILED

Evidence status tracking:
- reused: Sources with fresh cached runs
- refreshed: Sources that triggered new actor runs
- skipped: Sources with disabled capabilities
- failed: Sources that failed during ingestion
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import connection
from django.utils import timezone

from kairo.brandbrain.actors.registry import is_capability_enabled
from kairo.brandbrain.bundling import create_evidence_bundle, create_feature_report
from kairo.brandbrain.freshness import check_source_freshness
from kairo.brandbrain.ingestion import ingest_source
from kairo.brandbrain.ingestion.service import reuse_cached_run

if TYPE_CHECKING:
    from kairo.brandbrain.models import (
        BrandBrainCompileRun,
        BrandBrainSnapshot,
        SourceConnection,
    )

logger = logging.getLogger(__name__)


def execute_compile_job(
    compile_run_id: UUID,
    force_refresh: bool = False,
) -> None:
    """
    Execute the compile pipeline for a compile run.

    This is the main entry point called by:
    - BrandBrain worker (job queue execution)
    - compile_brandbrain() with sync=True (testing)

    Args:
        compile_run_id: UUID of the BrandBrainCompileRun
        force_refresh: If True, refresh all sources regardless of TTL
    """
    import django
    django.setup()  # Ensure Django is ready in worker thread

    from kairo.brandbrain.models import (
        BrandBrainCompileRun,
        BrandBrainSnapshot,
        BrandOnboarding,
        SourceConnection,
    )

    # Close any stale connections in this thread
    connection.close()

    try:
        compile_run = BrandBrainCompileRun.objects.get(id=compile_run_id)
    except BrandBrainCompileRun.DoesNotExist:
        logger.error("Compile run %s not found", compile_run_id)
        raise ValueError(f"Compile run not found: {compile_run_id}")

    brand_id = compile_run.brand_id

    try:
        # Step 1: Update status to RUNNING
        compile_run.status = "RUNNING"
        compile_run.save(update_fields=["status"])

        # Initialize evidence status tracking
        evidence_status = {
            "reused": [],
            "refreshed": [],
            "skipped": [],
            "failed": [],
        }

        # Step 2: Load onboarding
        try:
            onboarding = BrandOnboarding.objects.get(brand_id=brand_id)
            answers = onboarding.answers_json or {}
        except BrandOnboarding.DoesNotExist:
            answers = {}

        # Update onboarding snapshot
        compile_run.onboarding_snapshot_json["answers"] = answers
        compile_run.save(update_fields=["onboarding_snapshot_json"])

        # Step 3: Process each enabled source
        sources = SourceConnection.objects.filter(
            brand_id=brand_id,
            is_enabled=True,
        )

        for source in sources:
            source_key = f"{source.platform}.{source.capability}"

            # Check if capability is enabled (feature flag)
            if not is_capability_enabled(source.platform, source.capability):
                evidence_status["skipped"].append({
                    "source": source_key,
                    "reason": "Capability disabled (feature flag)",
                })
                continue

            # Check freshness
            freshness = check_source_freshness(source.id, force_refresh=force_refresh)

            if freshness.should_refresh:
                # Trigger real ingestion
                logger.info(
                    "Refreshing source %s for compile run %s: %s",
                    source_key,
                    compile_run_id,
                    freshness.reason,
                )

                result = ingest_source(source)

                if result.success:
                    evidence_status["refreshed"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
                        "apify_run_status": result.apify_run_status,
                        "raw_items_count": result.raw_items_count,
                        "normalized_created": result.normalized_items_created,
                        "normalized_updated": result.normalized_items_updated,
                    })
                else:
                    evidence_status["failed"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "error": result.error,
                        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
                        "apify_run_status": result.apify_run_status,
                    })
            else:
                # Reuse cached run
                if freshness.cached_run:
                    # Ensure normalization exists
                    result = reuse_cached_run(source, freshness.cached_run)

                    evidence_status["reused"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "run_age_hours": freshness.run_age_hours,
                        "apify_run_id": str(freshness.cached_run.id),
                        "normalized_created": result.normalized_items_created,
                        "normalized_updated": result.normalized_items_updated,
                    })
                else:
                    evidence_status["reused"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "run_age_hours": freshness.run_age_hours,
                    })

        # Update evidence status
        compile_run.evidence_status_json = evidence_status
        compile_run.save(update_fields=["evidence_status_json"])

        # Check if any required sources failed
        # For now, we continue even if some sources fail
        # (could be changed to fail-fast if needed)
        failed_count = len(evidence_status["failed"])
        if failed_count > 0:
            logger.warning(
                "Compile run %s has %d failed source(s)",
                compile_run_id,
                failed_count,
            )

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

        # Steps 6-7: LLM compile (STUB for PR-6)
        stub_draft = _create_stub_draft(answers, bundle, feature_report)
        compile_run.draft_json = stub_draft

        # Step 8: QA checks (STUB for PR-6)
        compile_run.qa_report_json = {
            "status": "STUB",
            "note": "PR-6 stub - QA not implemented",
            "checks": [],
        }

        # Steps 9-11: Merge overrides, compute diff, create snapshot
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
        raise


def _create_stub_draft(
    answers: dict,
    bundle: Any | None,
    feature_report: Any | None,
) -> dict:
    """
    Create a stub draft_json for PR-6.

    This is NOT a real LLM compile. It's a placeholder that proves
    the pipeline works end-to-end with real evidence.
    """
    return {
        "_stub": True,
        "_note": "PR-6 stub - LLM compile not implemented",
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

    PR-6: Minimal snapshot with stub draft but real evidence provenance.
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    snapshot = BrandBrainSnapshot.objects.create(
        brand_id=compile_run.brand_id,
        compile_run=compile_run,
        snapshot_json=draft_json,
        diff_from_previous_json={
            "_note": "PR-6 stub - diff not computed",
        },
    )

    return snapshot
