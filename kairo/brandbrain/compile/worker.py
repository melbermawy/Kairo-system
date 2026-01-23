"""
BrandBrain Compile Worker.

PR-6: Refactored compile pipeline with real ingestion.
PR-7: Added real LLM synthesis (replaced stub).

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
6. LLM synthesis (generates BrandBrain snapshot)
7. Create BrandBrainSnapshot
8. Mark SUCCEEDED or FAILED

Evidence status tracking:
- reused: Sources with fresh cached runs
- refreshed: Sources that triggered new actor runs
- skipped: Sources with disabled capabilities
- failed: Sources that failed during ingestion
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
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


def _log_llm_config(context: str = "compile_execution") -> dict:
    """
    Log LLM configuration at key points (worker startup, compile execution).
    Returns config dict for diagnostics.
    """
    llm_disabled = os.environ.get("LLM_DISABLED", "").lower() in ("true", "1", "yes", "on")
    openai_key_present = bool(os.environ.get("OPENAI_API_KEY"))

    # Get model config
    heavy_model = os.environ.get("KAIRO_LLM_MODEL_HEAVY", "gpt-4")
    fast_model = os.environ.get("KAIRO_LLM_MODEL_FAST", "gpt-4")

    config = {
        "llm_disabled": llm_disabled,
        "openai_key_present": openai_key_present,
        "heavy_model": heavy_model,
        "fast_model": fast_model,
        "provider": "openai" if openai_key_present else None,
    }

    # Log with clear visibility
    logger.info(
        "LLM_CONFIG [%s] | llm_disabled=%s | openai_key_present=%s | provider=%s | heavy_model=%s | fast_model=%s",
        context,
        llm_disabled,
        openai_key_present,
        config["provider"],
        heavy_model,
        fast_model,
    )

    return config


def execute_compile_job(
    compile_run_id: UUID,
    force_refresh: bool = False,
    user_id: UUID | None = None,
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

        # Log LLM config at compile start (critical for debugging stub issues)
        _llm_config = _log_llm_config(f"compile_run={compile_run_id}")

        # Timing instrumentation (stored in draft_json._diagnostics when DEBUG)
        _timings = {"started_at": timezone.now().isoformat()}
        _t_start = time.perf_counter()

        # Source diagnostics tracking
        _source_diagnostics = {
            "sources_considered": [],
            "sources_with_evidence": [],
            "sources_without_evidence": [],
        }

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
        _timings["gating_ms"] = int((time.perf_counter() - _t_start) * 1000)
        _t_ingestion_start = time.perf_counter()
        _source_timings = {}

        sources = SourceConnection.objects.filter(
            brand_id=brand_id,
            is_enabled=True,
        )

        for source in sources:
            _t_source_start = time.perf_counter()
            source_key = f"{source.platform}.{source.capability}"

            # Track source consideration
            source_diag = {
                "source": source_key,
                "enabled": True,
                "freshness_action": None,
                "has_evidence": False,
                "normalized_count": 0,
                "exclusion_reason": None,
            }

            # Check if capability is enabled (feature flag)
            if not is_capability_enabled(source.platform, source.capability):
                logger.info(
                    "EVIDENCE_DECISION source=%s action=skip reason=capability_disabled apify_run=none cost_risk=none",
                    source_key,
                )
                evidence_status["skipped"].append({
                    "source": source_key,
                    "reason": "Capability disabled (feature flag)",
                })
                source_diag["freshness_action"] = "skip"
                source_diag["exclusion_reason"] = "capability_disabled"
                _source_diagnostics["sources_considered"].append(source_diag)
                _source_timings[source_key] = int((time.perf_counter() - _t_source_start) * 1000)
                continue

            # Check freshness
            freshness = check_source_freshness(source.id, force_refresh=force_refresh)

            # Determine action and cost risk
            action = "refresh" if freshness.should_refresh else "reuse"
            cost_risk = "high" if freshness.should_refresh else "low"
            cached_run_id = str(freshness.cached_run.id) if freshness.cached_run else "none"

            # Log evidence decision (single line per source)
            logger.info(
                "EVIDENCE_DECISION source=%s action=%s reason=%s apify_run=%s cost_risk=%s age_hours=%s",
                source_key,
                action,
                freshness.reason.replace(" ", "_"),
                cached_run_id,
                cost_risk,
                f"{freshness.run_age_hours:.1f}" if freshness.run_age_hours else "none",
            )

            source_diag["freshness_action"] = action

            if freshness.should_refresh:
                # Trigger real ingestion (with user's BYOK token if available)
                result = ingest_source(source, user_id=user_id)

                if result.success:
                    normalized_count = result.normalized_items_created + result.normalized_items_updated
                    evidence_status["refreshed"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
                        "apify_run_status": result.apify_run_status,
                        "raw_items_count": result.raw_items_count,
                        "normalized_created": result.normalized_items_created,
                        "normalized_updated": result.normalized_items_updated,
                    })
                    source_diag["normalized_count"] = normalized_count
                    source_diag["has_evidence"] = normalized_count > 0
                    if normalized_count == 0:
                        source_diag["exclusion_reason"] = "no_normalized_items_from_refresh"
                else:
                    evidence_status["failed"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "error": result.error,
                        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
                        "apify_run_status": result.apify_run_status,
                    })
                    source_diag["exclusion_reason"] = f"ingestion_failed: {result.error}"
            else:
                # Reuse cached run
                if freshness.cached_run:
                    # Ensure normalization exists
                    result = reuse_cached_run(source, freshness.cached_run)
                    normalized_count = freshness.cached_run.normalized_item_count

                    evidence_status["reused"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "run_age_hours": freshness.run_age_hours,
                        "apify_run_id": str(freshness.cached_run.id),
                        "normalized_created": result.normalized_items_created,
                        "normalized_updated": result.normalized_items_updated,
                    })
                    source_diag["normalized_count"] = normalized_count
                    source_diag["has_evidence"] = normalized_count > 0
                    if normalized_count == 0:
                        source_diag["exclusion_reason"] = "cached_run_has_zero_normalized_items"
                else:
                    evidence_status["reused"].append({
                        "source": source_key,
                        "reason": freshness.reason,
                        "run_age_hours": freshness.run_age_hours,
                    })
                    source_diag["exclusion_reason"] = "no_cached_run"

            # Track source diagnostics
            _source_diagnostics["sources_considered"].append(source_diag)
            if source_diag["has_evidence"]:
                _source_diagnostics["sources_with_evidence"].append(source_key)
            else:
                _source_diagnostics["sources_without_evidence"].append({
                    "source": source_key,
                    "reason": source_diag["exclusion_reason"],
                })

            _source_timings[source_key] = int((time.perf_counter() - _t_source_start) * 1000)

        _timings["ingestion_total_ms"] = int((time.perf_counter() - _t_ingestion_start) * 1000)
        _timings["ingestion_per_source_ms"] = _source_timings

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
        _t_bundling_start = time.perf_counter()
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
        _timings["bundling_ms"] = int((time.perf_counter() - _t_bundling_start) * 1000)

        # Step 5: Create FeatureReport
        _t_feature_start = time.perf_counter()
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
        _timings["feature_report_ms"] = int((time.perf_counter() - _t_feature_start) * 1000)

        # Steps 6-7: LLM synthesis
        _t_llm_start = time.perf_counter()
        llm_meta = {"provider": None, "model": None, "used": False, "tokens_in": 0, "tokens_out": 0, "error": None}
        _llm_prompts = {}  # Store prompts for DEBUG diagnostics

        # Check if LLM is enabled (default: enabled if OPENAI_API_KEY is set)
        llm_disabled = os.environ.get("LLM_DISABLED", "").lower() in ("true", "1", "yes", "on")
        openai_key_present = bool(os.environ.get("OPENAI_API_KEY"))

        logger.info(
            "LLM synthesis config | compile_run=%s | llm_disabled=%s | openai_key_present=%s | bundle_items=%d | feature_report=%s",
            compile_run_id,
            llm_disabled,
            openai_key_present,
            len(bundle.item_ids) if bundle else 0,
            feature_report.id if feature_report else None,
        )

        if llm_disabled or not openai_key_present:
            # Fall back to stub if LLM disabled or no API key
            logger.warning(
                "LLM synthesis skipped | compile_run=%s | reason=%s",
                compile_run_id,
                "LLM_DISABLED=true" if llm_disabled else "OPENAI_API_KEY not set",
            )
            draft_json = _create_stub_draft(answers, bundle, feature_report)
            llm_meta["error"] = "LLM_DISABLED" if llm_disabled else "OPENAI_API_KEY not set"
        else:
            # Real LLM synthesis
            try:
                draft_json, llm_meta, _llm_prompts = _synthesize_brandbrain(
                    brand_id=brand_id,
                    compile_run_id=compile_run_id,
                    answers=answers,
                    bundle=bundle,
                    feature_report=feature_report,
                )
                logger.info(
                    "LLM synthesis completed | compile_run=%s | tokens_in=%d | tokens_out=%d | model=%s",
                    compile_run_id,
                    llm_meta.get("tokens_in", 0),
                    llm_meta.get("tokens_out", 0),
                    llm_meta.get("model"),
                )
            except Exception as e:
                logger.exception("LLM synthesis failed | compile_run=%s | error=%s", compile_run_id, str(e))
                # Fall back to stub on LLM failure
                draft_json = _create_stub_draft(answers, bundle, feature_report)
                llm_meta["error"] = str(e)

        _timings["llm_ms"] = int((time.perf_counter() - _t_llm_start) * 1000)

        # Add LLM metadata to draft
        draft_json["_llm_meta"] = llm_meta
        compile_run.draft_json = draft_json

        # Step 8: QA checks (STUB for PR-6)
        compile_run.qa_report_json = {
            "status": "STUB",
            "note": "PR-6 stub - QA not implemented",
            "checks": [],
        }

        # Steps 9-11: Merge overrides, compute diff, create snapshot
        _t_snapshot_start = time.perf_counter()
        snapshot = _create_stub_snapshot(compile_run, draft_json)
        _timings["snapshot_insert_ms"] = int((time.perf_counter() - _t_snapshot_start) * 1000)

        # Finalize timings
        _timings["finished_at"] = timezone.now().isoformat()
        _timings["total_ms"] = int((time.perf_counter() - _t_start) * 1000)

        # Add diagnostics to draft_json when DEBUG enabled
        if getattr(settings, "DEBUG", False):
            draft_json["_diagnostics"] = {
                "timings": _timings,
                "llm_config": _llm_config,
                "sources": _source_diagnostics,
                "prompts": _llm_prompts,  # system_prompt, user_prompt, raw_response (if LLM was called)
            }
            compile_run.draft_json = draft_json

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
    Create a stub draft_json for fallback (LLM disabled or failed).

    This is NOT a real LLM compile. It echoes onboarding answers
    and is marked with _stub=True.
    """
    return {
        "_stub": True,
        "_note": "Fallback stub - LLM not called",
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


def _synthesize_brandbrain(
    brand_id: UUID,
    compile_run_id: UUID,
    answers: dict,
    bundle: Any | None,
    feature_report: Any | None,
) -> tuple[dict, dict, dict]:
    """
    Synthesize BrandBrain snapshot using LLM.

    PR-7: Real LLM synthesis that generates:
    - differentiators
    - proof_types
    - tone_tags
    - taboos
    - risk_boundaries
    - content_pillars

    Returns:
        tuple[dict, dict, dict]: (draft_json, llm_meta, prompts_dict)
        prompts_dict contains system_prompt, user_prompt, raw_response for diagnostics
    """
    from kairo.hero.llm_client import LLMClient, LLMCallError

    client = LLMClient()
    llm_meta = {
        "provider": "openai",
        "model": client.config.heavy_model_name,
        "used": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "error": None,
    }

    # Build context from onboarding answers
    what_we_do = answers.get("tier0.what_we_do", "")
    who_for = answers.get("tier0.who_for", "")
    primary_goal = answers.get("tier0.primary_goal", "")
    cta_posture = answers.get("tier0.cta_posture", "soft")

    # Build evidence snippets from bundle (top N)
    evidence_snippets = []
    if bundle:
        from kairo.brandbrain.models import NormalizedEvidenceItem
        items = NormalizedEvidenceItem.objects.filter(id__in=bundle.item_ids[:20])
        for item in items:
            snippet = {
                "platform": item.platform,
                "type": item.content_type,
                "text": (item.text_primary or "")[:500],  # Truncate long content
            }
            evidence_snippets.append(snippet)

    # Build the synthesis prompt
    system_prompt = """You are a brand strategist AI. Given a company's onboarding answers and evidence from their social media presence, synthesize a BrandBrain snapshot.

Output valid JSON with this exact structure:
{
  "positioning": {
    "what_we_do": {"value": "string", "confidence": 0.0-1.0},
    "who_for": {"value": "string", "confidence": 0.0-1.0},
    "differentiators": [{"value": "string", "confidence": 0.0-1.0}, ...]
  },
  "voice": {
    "tone_tags": ["tag1", "tag2", ...],
    "cta_policy": {"value": "soft|moderate|aggressive", "confidence": 0.0-1.0},
    "taboos": ["thing to avoid 1", "thing to avoid 2", ...],
    "risk_boundaries": ["boundary 1", "boundary 2", ...]
  },
  "content": {
    "content_pillars": [{"name": "string", "description": "string"}, ...],
    "proof_types": ["case_study", "testimonial", "data", ...]
  },
  "meta": {
    "content_goal": {"value": "string", "confidence": 0.0-1.0}
  }
}

Guidelines:
- differentiators: 3-5 unique selling points based on evidence
- tone_tags: 3-5 adjectives describing brand voice (e.g., "professional", "friendly", "bold")
- taboos: 2-3 things the brand should never say/do
- risk_boundaries: 2-3 limits on controversial topics
- content_pillars: 3-5 main content themes with descriptions
- proof_types: types of social proof that work for this brand
- confidence: 0.9 for strong evidence, 0.7 for inferred, 0.5 for assumed"""

    user_prompt = f"""## Onboarding Answers

**What we do:** {what_we_do or "Not provided"}
**Who for:** {who_for or "Not provided"}
**Primary goal:** {primary_goal or "Not provided"}
**CTA posture:** {cta_posture}

## Evidence from Social Media ({len(evidence_snippets)} items)

"""
    for i, snippet in enumerate(evidence_snippets[:10], 1):
        user_prompt += f"{i}. [{snippet['platform']}/{snippet['type']}] {snippet['text'][:200]}...\n\n"

    user_prompt += "\nSynthesize a BrandBrain snapshot based on this information. Output only valid JSON."

    # Make the LLM call
    try:
        response = client.call(
            brand_id=brand_id,
            flow="brandbrain_synthesis",
            prompt=user_prompt,
            role="heavy",
            system_prompt=system_prompt,
            run_id=compile_run_id,
        )

        llm_meta["used"] = True
        llm_meta["tokens_in"] = response.usage_tokens_in
        llm_meta["tokens_out"] = response.usage_tokens_out
        llm_meta["model"] = response.model

        # Parse the response
        raw_text = response.raw_text.strip()

        # Try to extract JSON from markdown fence if present
        import re
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        if fence_match:
            raw_text = fence_match.group(1).strip()

        llm_output = json.loads(raw_text)

        # Build the draft_json with proper structure
        draft_json = {
            "_stub": False,
            "_note": "LLM synthesized",
            "positioning": {
                "what_we_do": _make_field(
                    llm_output.get("positioning", {}).get("what_we_do", {}),
                    fallback=what_we_do,
                    source_id="tier0.what_we_do",
                ),
                "who_for": _make_field(
                    llm_output.get("positioning", {}).get("who_for", {}),
                    fallback=who_for,
                    source_id="tier0.who_for",
                ),
                "differentiators": llm_output.get("positioning", {}).get("differentiators", []),
            },
            "voice": {
                "cta_policy": _make_field(
                    llm_output.get("voice", {}).get("cta_policy", {}),
                    fallback=cta_posture,
                    source_id="tier0.cta_posture",
                ),
                "tone_tags": llm_output.get("voice", {}).get("tone_tags", []),
                "taboos": llm_output.get("voice", {}).get("taboos", []),
                "risk_boundaries": llm_output.get("voice", {}).get("risk_boundaries", []),
            },
            "content": {
                "content_pillars": llm_output.get("content", {}).get("content_pillars", []),
                "proof_types": llm_output.get("content", {}).get("proof_types", []),
            },
            "meta": {
                "content_goal": _make_field(
                    llm_output.get("meta", {}).get("content_goal", {}),
                    fallback=primary_goal,
                    source_id="tier0.primary_goal",
                ),
                "evidence_summary": {
                    "bundle_id": str(bundle.id) if bundle else None,
                    "item_count": len(bundle.item_ids) if bundle else 0,
                },
                "feature_report_id": str(feature_report.id) if feature_report else None,
            },
        }

        # Return prompts for diagnostics
        prompts_dict = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": response.raw_text,
        }

        return draft_json, llm_meta, prompts_dict

    except LLMCallError as e:
        llm_meta["error"] = str(e)
        raise
    except json.JSONDecodeError as e:
        llm_meta["error"] = f"Invalid JSON from LLM: {str(e)}"
        raise


def _make_field(llm_field: dict | Any, fallback: str, source_id: str) -> dict:
    """Convert LLM output field to standard field structure."""
    if isinstance(llm_field, dict) and "value" in llm_field:
        return {
            "value": llm_field.get("value", fallback) or fallback,
            "confidence": llm_field.get("confidence", 0.7),
            "sources": [{"type": "llm", "id": source_id}],
            "locked": False,
            "override_value": None,
        }
    elif isinstance(llm_field, str):
        return {
            "value": llm_field or fallback,
            "confidence": 0.7,
            "sources": [{"type": "llm", "id": source_id}],
            "locked": False,
            "override_value": None,
        }
    else:
        return {
            "value": fallback,
            "confidence": 0.5,
            "sources": [{"type": "answer", "id": source_id}],
            "locked": False,
            "override_value": None,
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
