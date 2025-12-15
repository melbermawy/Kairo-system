"""
Hero Loop (F1/F2) Eval Harness.

PR-10: Offline Eval Harness + Fixtures.

This module provides the main eval harness for running F1 (Today board) and
F2 (Package + Variants) flows against fixture data and computing metrics.

Per docs/eval/evalHarness.md and PR-map-and-standards §PR-10:
- Loads fixtures (brand snapshots + external signals + goldens)
- Calls real hero loop graphs/services (with LLM_DISABLED for CI)
- Computes numeric scores + human-readable reports
- Outputs JSON + markdown artifacts

IMPORTANT: No real LLM calls in tests/CI - use LLM_DISABLED=True.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Paths to fixture files
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "eval"
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "docs" / "eval" / "hero_loop"


# =============================================================================
# RESULT DATACLASSES
# =============================================================================


@dataclass
class HeroEvalStageStatus:
    """
    Stage-level status for hero loop eval.

    10b: Distinguishes between:
    - "ok": Stage completed normally
    - "degraded": Stage completed but with fallback/stub data
    - "failed": Stage could not complete

    This allows the harness to clearly classify runs and avoid
    computing quality metrics on broken/incomplete runs.
    """

    f1_status: str = "ok"  # "ok", "degraded", "failed"
    f2_status: str = "ok"  # "ok", "degraded", "failed"
    failure_reason: str | None = None  # Machine-friendly code if failed/degraded

    def is_structurally_valid(self) -> bool:
        """
        Return True if the run is structurally valid for quality evaluation.

        A run is structurally valid if neither F1 nor F2 failed completely.
        Degraded runs are still structurally valid (just marked as such).
        """
        return self.f1_status != "failed" and self.f2_status != "failed"

    def overall_status(self) -> str:
        """
        Return the overall status of the run.

        - "failed" if either stage failed
        - "degraded" if either stage is degraded (but neither failed)
        - "ok" if both stages are ok
        """
        if self.f1_status == "failed" or self.f2_status == "failed":
            return "failed"
        if self.f1_status == "degraded" or self.f2_status == "degraded":
            return "degraded"
        return "ok"


@dataclass
class EvalCaseResult:
    """Result for a single eval case (one brand)."""

    eval_brand_id: str
    brand_slug: str
    brand_name: str

    # 10b: Stage-level status
    stage_status: HeroEvalStageStatus = field(default_factory=HeroEvalStageStatus)

    # F1 results
    opportunity_count: int = 0
    valid_opportunity_count: int = 0
    opportunity_coverage: float = 0.0  # vs goldens
    avg_opportunity_score: float = 0.0

    # F2 results
    package_count: int = 0
    valid_package_count: int = 0
    variant_count: int = 0
    valid_variant_count: int = 0

    # Quality metrics
    taboo_violations: int = 0
    golden_match_count: int = 0

    # Quality classification labels (per docs/eval/f1-f2-quality-classifier.md)
    f1_label: str | None = None  # "good", "partial", "bad"
    f2_label: str | None = None  # "good", "partial", "bad"
    run_label: str | None = None  # "good", "partial", "bad", "invalid"

    # Raw data for inspection
    opportunities: list[dict] = field(default_factory=list)
    packages: list[dict] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)

    # Warnings/errors
    warnings: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Aggregate result from an eval run."""

    brand_slug: str
    run_id: UUID
    timestamp: datetime
    llm_disabled: bool

    # Aggregate metrics
    metrics: dict[str, float | int | dict[str, float | int]] = field(default_factory=dict)

    # Per-case results
    cases: list[EvalCaseResult] = field(default_factory=list)

    # Overall status
    status: str = "completed"
    errors: list[str] = field(default_factory=list)


# =============================================================================
# FIXTURE LOADING
# =============================================================================


def _load_brands_fixture() -> dict:
    """Load brands fixture."""
    path = FIXTURES_DIR / "brands.json"
    if not path.exists():
        logger.warning(f"Brands fixture not found: {path}")
        return {"brands": []}

    with open(path) as f:
        return json.load(f)


def _load_external_signals_fixture() -> dict:
    """Load external signals fixture."""
    path = FIXTURES_DIR / "external_signals.json"
    if not path.exists():
        logger.warning(f"External signals fixture not found: {path}")
        return {"bundles": {}}

    with open(path) as f:
        return json.load(f)


def _load_goldens_fixture(fixture_type: str) -> dict:
    """Load goldens fixture (opportunities, packages, or variants)."""
    path = FIXTURES_DIR / "goldens" / f"{fixture_type}.json"
    if not path.exists():
        logger.warning(f"Goldens fixture not found: {path}")
        return {"goldens": {}}

    with open(path) as f:
        return json.load(f)


def _get_brand_fixture(brand_slug: str) -> dict | None:
    """Get brand fixture by slug."""
    brands_data = _load_brands_fixture()
    for brand in brands_data.get("brands", []):
        if brand.get("brand_slug") == brand_slug:
            return brand
    return None


def _get_signals_for_brand(eval_brand_id: str) -> dict:
    """Get external signals for a brand."""
    signals_data = _load_external_signals_fixture()
    return signals_data.get("bundles", {}).get(eval_brand_id, {})


def _get_opportunity_goldens(eval_brand_id: str) -> list[dict]:
    """Get golden opportunities for a brand."""
    goldens = _load_goldens_fixture("opportunities")
    return goldens.get("goldens", {}).get(eval_brand_id, [])


def _get_package_goldens(eval_brand_id: str) -> list[dict]:
    """Get golden packages for a brand."""
    goldens = _load_goldens_fixture("packages")
    return goldens.get("goldens", {}).get(eval_brand_id, [])


def _get_variant_goldens(eval_brand_id: str) -> list[dict]:
    """Get golden variants for a brand."""
    goldens = _load_goldens_fixture("variants")
    return goldens.get("goldens", {}).get(eval_brand_id, [])


# =============================================================================
# METRICS COMPUTATION
# =============================================================================


def _compute_opportunity_coverage(
    generated_opps: list[dict],
    golden_opps: list[dict],
) -> tuple[float, int]:
    """
    Compute opportunity coverage vs goldens.

    Uses simple Jaccard similarity on title words.
    Returns (coverage_rate, match_count).
    """
    if not golden_opps:
        return 0.0, 0

    matched = 0
    for golden in golden_opps:
        golden_words = set(golden.get("title", "").lower().split())
        for gen in generated_opps:
            gen_words = set(gen.get("title", "").lower().split())
            if golden_words and gen_words:
                jaccard = len(golden_words & gen_words) / len(golden_words | gen_words)
                if jaccard > 0.3:  # Threshold for "match"
                    matched += 1
                    break

    coverage = matched / len(golden_opps) if golden_opps else 0.0
    return coverage, matched


def _compute_text_similarity(text1: str, text2: str) -> float:
    """
    Simple word-level Jaccard similarity.

    Returns similarity in [0, 1].
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def _check_taboo_violations(text: str, taboos: list[str]) -> list[str]:
    """Check for taboo violations in text."""
    violations = []
    text_lower = text.lower()
    for taboo in taboos:
        if taboo.lower() in text_lower:
            violations.append(taboo)
    return violations


def _compute_quality_labels(case_result: EvalCaseResult) -> None:
    """
    Compute quality classification labels for a case result.

    Mutates case_result to set f1_label, f2_label, and run_label.

    Per docs/eval/f1-f2-quality-classifier.md spec.
    """
    from kairo.hero.eval.quality_classifier import (
        classify_f1_quality,
        classify_f2_quality,
        classify_run,
        extract_f1_metrics_from_case,
        extract_f2_metrics_from_case,
    )

    # Check structural validity
    structural_valid = case_result.stage_status.is_structurally_valid()

    if not structural_valid:
        # Cannot compute F1/F2 labels for structurally invalid runs
        case_result.f1_label = None
        case_result.f2_label = None
        case_result.run_label = "invalid"
        return

    # Extract F1 metrics and classify
    f1_metrics = extract_f1_metrics_from_case(case_result)
    case_result.f1_label = classify_f1_quality(f1_metrics)

    # Extract F2 metrics and classify
    f2_metrics = extract_f2_metrics_from_case(case_result)
    case_result.f2_label = classify_f2_quality(f2_metrics)

    # Classify the run
    case_result.run_label = classify_run(structural_valid, f1_metrics, f2_metrics)


# =============================================================================
# BRAND SEEDING
# =============================================================================


def _ensure_eval_brand_exists(brand_fixture: dict) -> UUID:
    """
    Ensure eval brand exists in DB, create if needed.

    Returns the brand UUID.
    """
    from kairo.core.models import Brand, Tenant

    tenant_slug = brand_fixture.get("tenant_slug", "eval-tenant")
    brand_slug = brand_fixture.get("brand_slug")
    brand_name = brand_fixture.get("brand_name", "Eval Brand")

    # Get or create tenant
    tenant, _ = Tenant.objects.get_or_create(
        slug=tenant_slug,
        defaults={"name": "Eval Tenant"},
    )

    # Get or create brand
    snapshot = brand_fixture.get("snapshot", {})
    brand, created = Brand.objects.get_or_create(
        slug=brand_slug,
        tenant=tenant,
        defaults={
            "name": brand_name,
            "positioning": snapshot.get("positioning", ""),
            "tone_tags": snapshot.get("voice_tone_tags", []),
            "taboos": snapshot.get("taboos", []),
        },
    )

    if created:
        logger.info(f"Created eval brand: {brand_slug}")
    else:
        # Update existing brand to match fixture
        brand.name = brand_name
        brand.positioning = snapshot.get("positioning", "")
        brand.tone_tags = snapshot.get("voice_tone_tags", [])
        brand.taboos = snapshot.get("taboos", [])
        brand.save()
        logger.info(f"Updated eval brand: {brand_slug}")

    return brand.id


def _build_brand_snapshot_dto(brand_fixture: dict, brand_id: UUID):
    """Build BrandSnapshotDTO from fixture data."""
    from kairo.hero.dto import BrandSnapshotDTO, PersonaDTO, PillarDTO

    snapshot = brand_fixture.get("snapshot", {})

    pillars = []
    for p in snapshot.get("pillars", []):
        pillars.append(
            PillarDTO(
                id=uuid4(),  # Eval-only ID
                name=p.get("name", ""),
                description=p.get("description", ""),
            )
        )

    personas = []
    for p in snapshot.get("personas", []):
        personas.append(
            PersonaDTO(
                id=uuid4(),  # Eval-only ID
                name=p.get("name", ""),
                role=p.get("role", ""),
                summary=p.get("summary", ""),
            )
        )

    return BrandSnapshotDTO(
        brand_id=brand_id,
        brand_name=brand_fixture.get("brand_name", ""),
        positioning=snapshot.get("positioning"),
        pillars=pillars,
        personas=personas,
        voice_tone_tags=snapshot.get("voice_tone_tags", []),
        taboos=snapshot.get("taboos", []),
    )


def _build_external_signals_dto(brand_id: UUID, signals_fixture: dict):
    """Build ExternalSignalBundleDTO from fixture data."""
    from kairo.hero.dto import (
        CompetitorPostSignalDTO,
        ExternalSignalBundleDTO,
        SocialMomentSignalDTO,
        TrendSignalDTO,
        WebMentionSignalDTO,
    )

    trends = []
    for t in signals_fixture.get("trends", []):
        trends.append(TrendSignalDTO(**t))

    web_mentions = []
    for w in signals_fixture.get("web_mentions", []):
        web_mentions.append(WebMentionSignalDTO(**w))

    competitor_posts = []
    for c in signals_fixture.get("competitor_posts", []):
        competitor_posts.append(CompetitorPostSignalDTO(**c))

    social_moments = []
    for s in signals_fixture.get("social_moments", []):
        social_moments.append(SocialMomentSignalDTO(**s))

    return ExternalSignalBundleDTO(
        brand_id=brand_id,
        fetched_at=datetime.now(timezone.utc),
        trends=trends,
        web_mentions=web_mentions,
        competitor_posts=competitor_posts,
        social_moments=social_moments,
    )


# =============================================================================
# MAIN EVAL FUNCTION
# =============================================================================


def run_hero_loop_eval(
    brand_slug: str,
    *,
    llm_disabled: bool = True,
    max_opportunities: int | None = None,
    output_dir: Path | None = None,
) -> EvalResult:
    """
    Run the hero loop eval for a specific brand.

    This is the main entrypoint for the eval harness.

    Args:
        brand_slug: Slug of the brand to evaluate
        llm_disabled: If True, use stub LLM outputs (default for CI)
        max_opportunities: Max opportunities to process for F2 (default: 3)
        output_dir: Directory for output artifacts (default: docs/eval/hero_loop/)

    Returns:
        EvalResult with metrics and case results
    """
    from kairo.hero.engines import content_engine, opportunities_engine

    run_id = uuid4()
    timestamp = datetime.now(timezone.utc)
    output_path = output_dir or OUTPUT_DIR

    # Set LLM_DISABLED environment variable
    if llm_disabled:
        os.environ["LLM_DISABLED"] = "true"
    else:
        os.environ.pop("LLM_DISABLED", None)

    logger.info(
        f"Starting hero loop eval",
        extra={
            "run_id": str(run_id),
            "brand_slug": brand_slug,
            "llm_disabled": llm_disabled,
        },
    )

    # Initialize result
    result = EvalResult(
        brand_slug=brand_slug,
        run_id=run_id,
        timestamp=timestamp,
        llm_disabled=llm_disabled,
    )

    # Load brand fixture
    brand_fixture = _get_brand_fixture(brand_slug)
    if not brand_fixture:
        result.status = "error"
        result.errors.append(f"Brand fixture not found: {brand_slug}")
        return result

    eval_brand_id = brand_fixture.get("eval_brand_id", brand_slug)

    try:
        # Ensure brand exists in DB
        brand_id = _ensure_eval_brand_exists(brand_fixture)

        # Load goldens
        opp_goldens = _get_opportunity_goldens(eval_brand_id)
        pkg_goldens = _get_package_goldens(eval_brand_id)
        var_goldens = _get_variant_goldens(eval_brand_id)

        # Initialize case result
        case_result = EvalCaseResult(
            eval_brand_id=eval_brand_id,
            brand_slug=brand_slug,
            brand_name=brand_fixture.get("brand_name", ""),
        )

        # =====================================================================
        # F1: Run Today Board (Opportunities)
        # =====================================================================
        logger.info(f"Running F1 (Today board) for {brand_slug}")

        # 10b: Track F1 stage status
        f1_failed = False
        f1_degraded = False
        f1_failure_reason = None

        try:
            # Call opportunities engine - it fetches snapshot and signals internally
            today_board = opportunities_engine.generate_today_board(
                brand_id=brand_id,
                run_id=run_id,
                trigger_source="eval",
            )

            # 10b: Check if F1 ran in degraded mode
            if today_board.meta.degraded:
                f1_degraded = True
                f1_failure_reason = today_board.meta.reason or "degraded_unknown"
                logger.warning(
                    f"F1 ran in degraded mode: {f1_failure_reason}",
                    extra={"run_id": str(run_id), "brand_slug": brand_slug},
                )

            # Check for empty opportunities (structural failure)
            if not today_board.opportunities:
                f1_failed = True
                f1_failure_reason = "no_opportunities"
                logger.error(
                    "F1 failed: No opportunities generated",
                    extra={"run_id": str(run_id), "brand_slug": brand_slug},
                )

        except Exception as e:
            f1_failed = True
            f1_failure_reason = f"f1_exception:{type(e).__name__}"
            logger.exception(f"F1 failed with exception: {e}")
            today_board = None

        # Set F1 stage status
        if f1_failed:
            case_result.stage_status.f1_status = "failed"
            case_result.stage_status.failure_reason = f1_failure_reason
        elif f1_degraded:
            case_result.stage_status.f1_status = "degraded"
            case_result.stage_status.failure_reason = f1_failure_reason

        # Extract opportunities if F1 didn't completely fail
        generated_opps = []
        if today_board and today_board.opportunities:
            for opp in today_board.opportunities:
                opp_dict = {
                    "id": str(opp.id),
                    "title": opp.title,
                    "angle": opp.angle,
                    "type": opp.type.value if hasattr(opp.type, "value") else str(opp.type),
                    "primary_channel": opp.primary_channel.value if hasattr(opp.primary_channel, "value") else str(opp.primary_channel),
                    "score": opp.score,
                    "is_valid": getattr(opp, "is_valid", True),
                }
                generated_opps.append(opp_dict)

        case_result.opportunity_count = len(generated_opps)
        case_result.valid_opportunity_count = sum(1 for o in generated_opps if o.get("is_valid", True))
        case_result.opportunities = generated_opps

        # Compute F1 metrics (only if F1 didn't fail)
        if generated_opps and not f1_failed:
            case_result.avg_opportunity_score = sum(o.get("score", 0) for o in generated_opps) / len(generated_opps)

            coverage, match_count = _compute_opportunity_coverage(generated_opps, opp_goldens)
            case_result.opportunity_coverage = coverage
            case_result.golden_match_count = match_count

            # Check for taboo violations in opportunities
            taboos = brand_fixture.get("snapshot", {}).get("taboos", [])
            for opp in generated_opps:
                violations = _check_taboo_violations(
                    f"{opp.get('title', '')} {opp.get('angle', '')}",
                    taboos,
                )
                if violations:
                    case_result.taboo_violations += 1
                    case_result.warnings.append(f"Taboo violation in opp: {violations}")

        # =====================================================================
        # F2: Run Package + Variants for top opportunities
        # =====================================================================

        # 10b: Track F2 stage status
        f2_failed = False
        f2_error_count = 0
        f2_success_count = 0

        # 10b: Skip F2 if F1 failed completely
        if f1_failed:
            case_result.stage_status.f2_status = "failed"
            if not case_result.stage_status.failure_reason:
                case_result.stage_status.failure_reason = "f1_failed_skipped_f2"
            logger.warning(
                "Skipping F2 because F1 failed",
                extra={"run_id": str(run_id), "brand_slug": brand_slug},
            )
        else:
            max_opps = max_opportunities or 3
            top_opps = sorted(generated_opps, key=lambda x: x.get("score", 0), reverse=True)[:max_opps]

            logger.info(f"Running F2 (Packages + Variants) for top {len(top_opps)} opportunities")

            # Get taboos for checking
            taboos = brand_fixture.get("snapshot", {}).get("taboos", [])

            for opp in top_opps:
                opp_id = UUID(opp["id"])

                try:
                    # Create package
                    package = content_engine.create_package_from_opportunity(
                        brand_id=brand_id,
                        opportunity_id=opp_id,
                    )

                    pkg_dict = {
                        "id": str(package.id),
                        "title": package.title,
                        "status": str(package.status),
                        "channels": package.channels,
                        "origin_opportunity_id": str(opp_id),
                    }
                    case_result.packages.append(pkg_dict)
                    case_result.package_count += 1
                    case_result.valid_package_count += 1

                    # Generate variants
                    variants = content_engine.generate_variants_for_package(package.id)

                    for variant in variants:
                        var_dict = {
                            "id": str(variant.id),
                            "channel": variant.channel,
                            "status": str(variant.status),
                            "package_id": str(package.id),
                            "body_preview": variant.draft_text[:100] if variant.draft_text else "",
                        }
                        case_result.variants.append(var_dict)
                        case_result.variant_count += 1
                        case_result.valid_variant_count += 1

                        # Check taboos in variant body
                        if variant.draft_text:
                            violations = _check_taboo_violations(variant.draft_text, taboos)
                            if violations:
                                case_result.taboo_violations += 1
                                case_result.warnings.append(f"Taboo violation in variant: {violations}")

                    f2_success_count += 1

                except Exception as e:
                    f2_error_count += 1
                    case_result.warnings.append(f"Error processing opportunity {opp_id}: {str(e)}")
                    logger.warning(f"Error in F2 for opp {opp_id}: {e}")

            # 10b: Determine F2 status based on success/error counts
            if f2_success_count == 0 and len(top_opps) > 0:
                # All F2 attempts failed
                f2_failed = True
                case_result.stage_status.f2_status = "failed"
                case_result.stage_status.failure_reason = case_result.stage_status.failure_reason or "all_f2_failed"
            elif f2_error_count > 0:
                # Some F2 attempts failed (partial success = degraded)
                case_result.stage_status.f2_status = "degraded"
                case_result.stage_status.failure_reason = case_result.stage_status.failure_reason or "partial_f2_failure"
            else:
                # All F2 attempts succeeded
                case_result.stage_status.f2_status = "ok"

        # Add case to results
        result.cases.append(case_result)

        # 10b: Set overall result status based on stage status
        overall_status = case_result.stage_status.overall_status()
        if overall_status == "failed":
            result.status = "failed"
            result.errors.append(f"Stage failure: {case_result.stage_status.failure_reason}")
        elif overall_status == "degraded":
            result.status = "degraded"
        else:
            result.status = "completed"

        # Compute aggregate metrics (only compute quality metrics if structurally valid)
        result.metrics = {
            "opportunity_count": case_result.opportunity_count,
            "valid_opportunity_count": case_result.valid_opportunity_count,
            "package_count": case_result.package_count,
            "variant_count": case_result.variant_count,
            "taboo_violations": case_result.taboo_violations,
            # 10b: Stage status info
            "f1_status": case_result.stage_status.f1_status,
            "f2_status": case_result.stage_status.f2_status,
        }

        # Only add quality metrics if the run is structurally valid
        if case_result.stage_status.is_structurally_valid():
            result.metrics.update({
                "opportunity_coverage": case_result.opportunity_coverage,
                "avg_opportunity_score": case_result.avg_opportunity_score,
                "golden_match_count": case_result.golden_match_count,
            })

        # Compute quality classification labels (per docs/eval/f1-f2-quality-classifier.md)
        _compute_quality_labels(case_result)

        # Write output artifacts
        _write_eval_artifacts(result, case_result, output_path)

        logger.info(
            f"Eval completed",
            extra={
                "run_id": str(run_id),
                "brand_slug": brand_slug,
                "status": result.status,
                "f1_status": case_result.stage_status.f1_status,
                "f2_status": case_result.stage_status.f2_status,
                "metrics": result.metrics,
            },
        )

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))
        logger.exception(f"Eval failed: {e}")

    return result


# =============================================================================
# OUTPUT ARTIFACTS
# =============================================================================


def _write_eval_artifacts(
    result: EvalResult,
    case_result: EvalCaseResult,
    output_dir: Path,
) -> None:
    """Write JSON and Markdown output artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = result.timestamp.strftime("%Y%m%d_%H%M%S")
    base_name = f"{result.brand_slug}_{timestamp_str}"

    # Write JSON
    json_path = output_dir / f"{base_name}.json"
    json_data = {
        "run_id": str(result.run_id),
        "brand_slug": result.brand_slug,
        "timestamp": result.timestamp.isoformat(),
        "llm_disabled": result.llm_disabled,
        "status": result.status,
        # 10b: Include stage status prominently
        "stage_status": {
            "f1_status": case_result.stage_status.f1_status,
            "f2_status": case_result.stage_status.f2_status,
            "failure_reason": case_result.stage_status.failure_reason,
            "is_structurally_valid": case_result.stage_status.is_structurally_valid(),
        },
        # Quality classification labels (per docs/eval/f1-f2-quality-classifier.md)
        "quality_labels": {
            "f1_label": case_result.f1_label,
            "f2_label": case_result.f2_label,
            "run_label": case_result.run_label,
        },
        "metrics": result.metrics,
        "case": {
            "eval_brand_id": case_result.eval_brand_id,
            "brand_name": case_result.brand_name,
            "opportunities": case_result.opportunities,
            "packages": case_result.packages,
            "variants": case_result.variants,
            "warnings": case_result.warnings,
        },
        "errors": result.errors,
    }

    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2, default=str)

    logger.info(f"Wrote eval JSON: {json_path}")

    # Write Markdown summary
    md_path = output_dir / f"{base_name}.md"
    md_content = _generate_markdown_report(result, case_result)

    with open(md_path, "w") as f:
        f.write(md_content)

    logger.info(f"Wrote eval Markdown: {md_path}")


def _generate_markdown_report(result: EvalResult, case_result: EvalCaseResult) -> str:
    """Generate human-readable Markdown report."""
    # 10b: Determine status emoji
    status_emoji = {
        "completed": "✅",
        "degraded": "⚠️",
        "failed": "❌",
        "error": "❌",
    }.get(result.status, "❓")

    lines = [
        f"# Hero Loop Eval: {result.brand_slug}",
        "",
        f"**Run ID:** `{result.run_id}`",
        f"**Timestamp:** {result.timestamp.isoformat()}",
        f"**LLM Disabled:** {result.llm_disabled}",
        f"**Status:** {status_emoji} {result.status}",
        "",
    ]

    # 10b: Stage status section
    stage = case_result.stage_status
    lines.extend([
        "## Stage Status",
        "",
        "| Stage | Status | Structurally Valid |",
        "|-------|--------|-------------------|",
        f"| F1 (Opportunities) | {stage.f1_status} | {'✅' if stage.f1_status != 'failed' else '❌'} |",
        f"| F2 (Packages/Variants) | {stage.f2_status} | {'✅' if stage.f2_status != 'failed' else '❌'} |",
        "",
    ])

    if stage.failure_reason:
        lines.append(f"**Failure Reason:** `{stage.failure_reason}`")
        lines.append("")

    if not stage.is_structurally_valid():
        lines.extend([
            "> ⚠️ **This run is NOT structurally valid.** Quality metrics should not be trusted.",
            "",
        ])

    # Quality Classification section (per docs/eval/f1-f2-quality-classifier.md)
    lines.extend([
        "---",
        "",
        "## Quality Classification",
        "",
    ])

    # Helper function for label emoji
    def _label_emoji(label: str | None) -> str:
        if label is None:
            return "❓"
        return {
            "good": "✅",
            "partial": "⚠️",
            "bad": "❌",
            "invalid": "🚫",
        }.get(label, "❓")

    lines.extend([
        "| Stage | Label |",
        "|-------|-------|",
        f"| F1 (Opportunities) | {_label_emoji(case_result.f1_label)} {case_result.f1_label or 'N/A'} |",
        f"| F2 (Packages/Variants) | {_label_emoji(case_result.f2_label)} {case_result.f2_label or 'N/A'} |",
        f"| **Run** | {_label_emoji(case_result.run_label)} **{case_result.run_label or 'N/A'}** |",
        "",
    ])

    # Add interpretation guidance
    if case_result.run_label == "good":
        lines.append("> ✅ **Good:** Output you'd happily work from with light edits.")
    elif case_result.run_label == "partial":
        lines.append("> ⚠️ **Partial:** Salvageable but inconsistent.")
    elif case_result.run_label == "bad":
        lines.append("> ❌ **Bad:** You'd rather start from scratch.")
    elif case_result.run_label == "invalid":
        lines.append("> 🚫 **Invalid:** Structural bug; quality metrics not interpretable.")
    lines.append("")

    lines.extend([
        "---",
        "",
        "## Metrics Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ])

    for key, value in result.metrics.items():
        if isinstance(value, float):
            lines.append(f"| {key} | {value:.2f} |")
        else:
            lines.append(f"| {key} | {value} |")

    lines.extend([
        "",
        "---",
        "",
        "## F1: Today Board (Opportunities)",
        "",
        f"Generated **{case_result.opportunity_count}** opportunities "
        f"({case_result.valid_opportunity_count} valid).",
        "",
    ])

    if case_result.opportunities:
        lines.extend([
            "### Top Opportunities",
            "",
            "| Title | Score | Type | Channel |",
            "|-------|-------|------|---------|",
        ])
        for opp in sorted(case_result.opportunities, key=lambda x: x.get("score", 0), reverse=True)[:5]:
            lines.append(
                f"| {opp.get('title', '')[:50]}... | {opp.get('score', 0):.1f} | "
                f"{opp.get('type', '')} | {opp.get('primary_channel', '')} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## F2: Packages & Variants",
        "",
        f"Generated **{case_result.package_count}** packages and "
        f"**{case_result.variant_count}** variants.",
        "",
    ])

    if case_result.packages:
        lines.extend([
            "### Packages",
            "",
        ])
        for pkg in case_result.packages:
            lines.append(f"- **{pkg.get('title', 'Untitled')}** ({pkg.get('status', '')})")

    lines.extend([
        "",
        "---",
        "",
        "## Warnings",
        "",
    ])

    if case_result.warnings:
        for warning in case_result.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("_No warnings._")

    if result.errors:
        lines.extend([
            "",
            "---",
            "",
            "## Errors",
            "",
        ])
        for error in result.errors:
            lines.append(f"- {error}")

    lines.extend([
        "",
        "---",
        "",
        "_Generated with [Claude Code](https://claude.com/claude-code)_",
    ])

    return "\n".join(lines)
