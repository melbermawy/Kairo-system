"""
F1 / F2 Quality Classifier for Hero Loop Eval.

Per docs/eval/f1-f2-quality-classifier.md spec.

This module provides classification of hero loop eval runs as:
- "good": Output you'd happily work from with light edits
- "partial": Salvageable but inconsistent
- "bad": You'd rather start from scratch
- "invalid": Structural bug, quality metrics not interpretable

IMPORTANT: This is eval-harness only logic. Nothing here gates real-time behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# =============================================================================
# METRICS DATACLASSES
# =============================================================================


@dataclass
class F1Metrics:
    """
    F1 (Opportunities Board) metrics for quality classification.

    All metrics are computed from the eval harness output.
    Fields marked as optional (| None) may be absent in early PRD-1.
    """

    board_size: int
    """Number of opportunities on the board."""

    strong_fraction: float
    """Fraction of opportunities with score >= 80."""

    weak_fraction: float
    """Fraction of opportunities with score < 60."""

    invalid_fraction: float | None
    """Fraction with is_valid == False (after graph, before engine filtering)."""

    redundancy_rate: float
    """Fraction of pairs deemed redundant (high Jaccard similarity)."""

    taboo_violations_count: int
    """Count of opportunities with taboo violations."""

    opportunity_coverage: float | None = None
    """Fraction of golden opportunities represented on the board (if goldens exist)."""


@dataclass
class F2Metrics:
    """
    F2 (Packages + Variants) metrics for quality classification.

    All metrics are computed from the eval harness output.
    Fields marked as optional (| None) may be absent in early PRD-1.
    """

    # Package-level metrics (required)
    mean_package_score: float
    """Average package score (0-15)."""

    board_ready_package_fraction: float
    """Fraction of packages with quality_band == 'board_ready'."""

    # Variant-level metrics (required)
    publish_ready_fraction: float
    """Fraction of variants with quality_band == 'publish_ready'."""

    invalid_variant_fraction: float
    """Fraction with quality_band == 'invalid'."""

    # Package-level metrics (optional)
    execution_clarity_rate: float | None = None
    """Fraction of packages that satisfy execution clarity heuristic."""

    faithful_package_fraction: float | None = None
    """Fraction of packages where thesis is 'faithful' to source opportunity."""

    # Variant-level metrics (optional)
    voice_alignment_ok_fraction: float | None = None
    """Fraction where brand voice is {strong, ok}."""

    channel_fit_ok_fraction: float | None = None
    """Fraction where channel fit is {strong, ok}."""


# =============================================================================
# F1 QUALITY CLASSIFIER
# =============================================================================


QualityLabel = Literal["good", "partial", "bad"]
RunLabel = Literal["good", "partial", "bad", "invalid"]


def classify_f1_quality(m: F1Metrics) -> QualityLabel:
    """
    Classify F1 (Opportunities Board) quality.

    Returns "good", "partial", or "bad" based on spec §3.

    Hard Failure Gates (-> "bad"):
    - taboo_violations_count > 0
    - board_size < 4
    - invalid_fraction > 0.05

    "good" Band (ALL must be true):
    - board_size >= 8
    - strong_fraction >= 0.5
    - invalid_fraction <= 0.01 (or None)
    - redundancy_rate <= 0.3
    - opportunity_coverage >= 0.6 (or None)

    "partial" Band (ALL must be true, if not "good"):
    - board_size >= 6
    - strong_fraction >= 0.25
    - invalid_fraction <= 0.05 (or None)
    - redundancy_rate <= 0.5
    - opportunity_coverage >= 0.4 (or None)

    Otherwise -> "bad"
    """
    # Hard failures
    if m.taboo_violations_count > 0:
        return "bad"
    if m.board_size < 4:
        return "bad"
    if m.invalid_fraction is not None and m.invalid_fraction > 0.05:
        return "bad"

    coverage = m.opportunity_coverage  # may be None

    # Good band
    if (
        m.board_size >= 8
        and m.strong_fraction >= 0.5
        and (m.invalid_fraction is None or m.invalid_fraction <= 0.01)
        and m.redundancy_rate <= 0.3
        and (coverage is None or coverage >= 0.6)
    ):
        return "good"

    # Partial band
    if (
        m.board_size >= 6
        and m.strong_fraction >= 0.25
        and (m.invalid_fraction is None or m.invalid_fraction <= 0.05)
        and m.redundancy_rate <= 0.5
        and (coverage is None or coverage >= 0.4)
    ):
        return "partial"

    return "bad"


# =============================================================================
# F2 QUALITY CLASSIFIER
# =============================================================================


def _classify_package_layer(m: F2Metrics) -> QualityLabel:
    """
    Classify F2 package layer quality.

    "good" Package Layer (ALL must be true):
    - board_ready_package_fraction >= 0.7
    - mean_package_score >= 11.0
    - execution_clarity_rate >= 0.7 (if available)
    - faithful_package_fraction >= 0.8 (if available)

    "partial" Package Layer (ALL must be true, if not "good"):
    - board_ready_package_fraction >= 0.4
    - mean_package_score >= 8.0
    - execution_clarity_rate >= 0.5 (if available)
    - faithful_package_fraction >= 0.6 (if available)

    Otherwise -> "bad"
    """
    # Good package layer
    if (
        m.board_ready_package_fraction >= 0.7
        and m.mean_package_score >= 11.0
        and (m.execution_clarity_rate is None or m.execution_clarity_rate >= 0.7)
        and (m.faithful_package_fraction is None or m.faithful_package_fraction >= 0.8)
    ):
        return "good"

    # Partial package layer
    if (
        m.board_ready_package_fraction >= 0.4
        and m.mean_package_score >= 8.0
        and (m.execution_clarity_rate is None or m.execution_clarity_rate >= 0.5)
        and (m.faithful_package_fraction is None or m.faithful_package_fraction >= 0.6)
    ):
        return "partial"

    return "bad"


def _classify_variant_layer(m: F2Metrics) -> QualityLabel:
    """
    Classify F2 variant layer quality.

    "good" Variant Layer (ALL must be true):
    - publish_ready_fraction >= 0.6
    - invalid_variant_fraction <= 0.01 (or == 0)
    - voice_alignment_ok_fraction >= 0.8 (if available)
    - channel_fit_ok_fraction >= 0.8 (if available)

    "partial" Variant Layer (ALL must be true, if not "good"):
    - publish_ready_fraction >= 0.3
    - invalid_variant_fraction <= 0.05
    - voice_alignment_ok_fraction >= 0.6 (if available)
    - channel_fit_ok_fraction >= 0.6 (if available)

    Otherwise -> "bad"
    """
    # Good variant layer
    if (
        m.publish_ready_fraction >= 0.6
        and m.invalid_variant_fraction <= 0.01
        and (m.voice_alignment_ok_fraction is None or m.voice_alignment_ok_fraction >= 0.8)
        and (m.channel_fit_ok_fraction is None or m.channel_fit_ok_fraction >= 0.8)
    ):
        return "good"

    # Partial variant layer
    if (
        m.publish_ready_fraction >= 0.3
        and m.invalid_variant_fraction <= 0.05
        and (m.voice_alignment_ok_fraction is None or m.voice_alignment_ok_fraction >= 0.6)
        and (m.channel_fit_ok_fraction is None or m.channel_fit_ok_fraction >= 0.6)
    ):
        return "partial"

    return "bad"


def classify_f2_quality(m: F2Metrics) -> QualityLabel:
    """
    Classify F2 (Packages + Variants) quality.

    Returns "good", "partial", or "bad" based on spec §4.

    Hard Failure Gates (-> "bad"):
    - invalid_variant_fraction > 0.05
    - publish_ready_fraction < 0.2

    Combines package layer and variant layer classifications:
    - "good" if BOTH package and variant layers are "good"
    - "bad" if EITHER package or variant layer is "bad"
    - "partial" otherwise
    """
    # Hard failures
    if m.invalid_variant_fraction > 0.05:
        return "bad"
    if m.publish_ready_fraction < 0.2:
        return "bad"

    package_label = _classify_package_layer(m)
    variant_label = _classify_variant_layer(m)

    if package_label == "good" and variant_label == "good":
        return "good"

    if package_label == "bad" or variant_label == "bad":
        return "bad"

    return "partial"


# =============================================================================
# RUN-LEVEL CLASSIFIER
# =============================================================================


def classify_run(
    structural_valid: bool,
    f1_metrics: F1Metrics,
    f2_metrics: F2Metrics,
) -> RunLabel:
    """
    Classify an entire eval run.

    Returns "good", "partial", "bad", or "invalid" based on spec §5.

    - "invalid" if structural_valid is False (F1 or F2 failed completely)
    - "good" if both F1 and F2 are "good"
    - "bad" if either F1 or F2 is "bad"
    - "partial" otherwise
    """
    if not structural_valid:
        return "invalid"

    f1_label = classify_f1_quality(f1_metrics)
    f2_label = classify_f2_quality(f2_metrics)

    if f1_label == "good" and f2_label == "good":
        return "good"

    if "bad" in {f1_label, f2_label}:
        return "bad"

    return "partial"


# =============================================================================
# METRICS EXTRACTION HELPERS
# =============================================================================


def extract_f1_metrics_from_case(
    case_result,
    *,
    redundancy_rate: float = 0.0,
    invalid_fraction: float | None = None,
) -> F1Metrics:
    """
    Extract F1Metrics from an EvalCaseResult.

    Some metrics (redundancy_rate, invalid_fraction) aren't computed by the
    current harness and must be passed in or default to sensible values.

    Args:
        case_result: EvalCaseResult from the eval harness
        redundancy_rate: Fraction of redundant opportunity pairs (default 0.0)
        invalid_fraction: Fraction of invalid opportunities (default None)

    Returns:
        F1Metrics for classification
    """
    opportunities = case_result.opportunities
    board_size = len(opportunities)

    # Compute strong/weak fractions
    if board_size > 0:
        strong_count = sum(1 for o in opportunities if o.get("score", 0) >= 80)
        weak_count = sum(1 for o in opportunities if o.get("score", 0) < 60)
        strong_fraction = strong_count / board_size
        weak_fraction = weak_count / board_size
    else:
        strong_fraction = 0.0
        weak_fraction = 0.0

    # Get opportunity coverage (may be None if no goldens)
    opportunity_coverage = case_result.opportunity_coverage if case_result.opportunity_coverage > 0 else None

    return F1Metrics(
        board_size=board_size,
        strong_fraction=strong_fraction,
        weak_fraction=weak_fraction,
        invalid_fraction=invalid_fraction,
        redundancy_rate=redundancy_rate,
        taboo_violations_count=case_result.taboo_violations,
        opportunity_coverage=opportunity_coverage,
    )


def extract_f2_metrics_from_case(
    case_result,
    *,
    mean_package_score: float = 10.0,
    board_ready_package_fraction: float | None = None,
    publish_ready_fraction: float | None = None,
    invalid_variant_fraction: float | None = None,
) -> F2Metrics:
    """
    Extract F2Metrics from an EvalCaseResult.

    Many F2 quality metrics aren't computed by the current harness and must
    be passed in or default to sensible values for early PRD-1.

    Args:
        case_result: EvalCaseResult from the eval harness
        mean_package_score: Average package score (default 10.0)
        board_ready_package_fraction: Fraction of board-ready packages (default computed from valid count)
        publish_ready_fraction: Fraction of publish-ready variants (default computed from valid count)
        invalid_variant_fraction: Fraction of invalid variants (default computed from counts)

    Returns:
        F2Metrics for classification
    """
    package_count = case_result.package_count
    variant_count = case_result.variant_count
    valid_package_count = case_result.valid_package_count
    valid_variant_count = case_result.valid_variant_count

    # Compute board_ready_package_fraction if not provided
    if board_ready_package_fraction is None:
        if package_count > 0:
            board_ready_package_fraction = valid_package_count / package_count
        else:
            board_ready_package_fraction = 0.0

    # Compute publish_ready_fraction if not provided
    if publish_ready_fraction is None:
        if variant_count > 0:
            publish_ready_fraction = valid_variant_count / variant_count
        else:
            publish_ready_fraction = 0.0

    # Compute invalid_variant_fraction if not provided
    if invalid_variant_fraction is None:
        if variant_count > 0:
            invalid_variant_fraction = (variant_count - valid_variant_count) / variant_count
        else:
            invalid_variant_fraction = 0.0

    return F2Metrics(
        mean_package_score=mean_package_score,
        board_ready_package_fraction=board_ready_package_fraction,
        publish_ready_fraction=publish_ready_fraction,
        invalid_variant_fraction=invalid_variant_fraction,
        # Optional metrics not yet computed by harness
        execution_clarity_rate=None,
        faithful_package_fraction=None,
        voice_alignment_ok_fraction=None,
        channel_fit_ok_fraction=None,
    )
