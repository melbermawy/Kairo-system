"""
Tests for F1/F2 Quality Classifier.

Per docs/eval/f1-f2-quality-classifier.md spec.

Test coverage:
- F1 classifier: hard failures, good/partial/bad bands, None handling
- F2 classifier: hard failures, package/variant layer combinations, None handling
- Run-level classifier: structural validity, label combinations
- Harness wiring: labels appear in EvalCaseResult after classification
"""

import pytest

from kairo.hero.eval.quality_classifier import (
    F1Metrics,
    F2Metrics,
    classify_f1_quality,
    classify_f2_quality,
    classify_run,
    extract_f1_metrics_from_case,
    extract_f2_metrics_from_case,
)


# =============================================================================
# F1 CLASSIFIER TESTS
# =============================================================================


class TestClassifyF1Quality:
    """Tests for classify_f1_quality function."""

    # -------------------------------------------------------------------------
    # Hard Failure Tests
    # -------------------------------------------------------------------------

    def test_hard_fail_taboo_violations(self):
        """taboo_violations_count > 0 -> bad"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.8,
            weak_fraction=0.0,
            invalid_fraction=0.0,
            redundancy_rate=0.1,
            taboo_violations_count=1,  # Hard fail
            opportunity_coverage=0.8,
        )
        assert classify_f1_quality(m) == "bad"

    def test_hard_fail_board_too_small(self):
        """board_size < 4 -> bad"""
        m = F1Metrics(
            board_size=3,  # Hard fail
            strong_fraction=1.0,
            weak_fraction=0.0,
            invalid_fraction=0.0,
            redundancy_rate=0.0,
            taboo_violations_count=0,
            opportunity_coverage=1.0,
        )
        assert classify_f1_quality(m) == "bad"

    def test_hard_fail_invalid_fraction_too_high(self):
        """invalid_fraction > 0.05 -> bad"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.8,
            weak_fraction=0.0,
            invalid_fraction=0.06,  # Hard fail
            redundancy_rate=0.1,
            taboo_violations_count=0,
            opportunity_coverage=0.8,
        )
        assert classify_f1_quality(m) == "bad"

    # -------------------------------------------------------------------------
    # Good Band Tests
    # -------------------------------------------------------------------------

    def test_good_all_conditions_met(self):
        """All good band conditions met -> good"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        assert classify_f1_quality(m) == "good"

    def test_good_min_thresholds(self):
        """Exactly at good band thresholds -> good"""
        m = F1Metrics(
            board_size=8,  # >= 8
            strong_fraction=0.5,  # >= 0.5
            weak_fraction=0.2,
            invalid_fraction=0.01,  # <= 0.01
            redundancy_rate=0.3,  # <= 0.3
            taboo_violations_count=0,
            opportunity_coverage=0.6,  # >= 0.6
        )
        assert classify_f1_quality(m) == "good"

    def test_good_coverage_none(self):
        """Coverage None is allowed for good band"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=None,  # Skip constraint
        )
        assert classify_f1_quality(m) == "good"

    def test_good_invalid_fraction_none(self):
        """invalid_fraction None is allowed for good band"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=None,  # Skip constraint
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        assert classify_f1_quality(m) == "good"

    # -------------------------------------------------------------------------
    # Partial Band Tests
    # -------------------------------------------------------------------------

    def test_partial_board_size_between_6_and_8(self):
        """board_size 6-7 with good other metrics -> partial"""
        m = F1Metrics(
            board_size=7,  # < 8, >= 6
            strong_fraction=0.5,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        assert classify_f1_quality(m) == "partial"

    def test_partial_strong_fraction_between_thresholds(self):
        """strong_fraction 0.25-0.5 -> partial"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.4,  # < 0.5, >= 0.25
            weak_fraction=0.2,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        assert classify_f1_quality(m) == "partial"

    def test_partial_redundancy_between_thresholds(self):
        """redundancy_rate 0.3-0.5 -> partial"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.4,  # > 0.3, <= 0.5
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        assert classify_f1_quality(m) == "partial"

    def test_partial_coverage_between_thresholds(self):
        """opportunity_coverage 0.4-0.6 -> partial"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.5,  # < 0.6, >= 0.4
        )
        assert classify_f1_quality(m) == "partial"

    def test_partial_min_thresholds(self):
        """Exactly at partial band thresholds -> partial"""
        m = F1Metrics(
            board_size=6,  # >= 6
            strong_fraction=0.25,  # >= 0.25
            weak_fraction=0.3,
            invalid_fraction=0.05,  # <= 0.05
            redundancy_rate=0.5,  # <= 0.5
            taboo_violations_count=0,
            opportunity_coverage=0.4,  # >= 0.4
        )
        assert classify_f1_quality(m) == "partial"

    # -------------------------------------------------------------------------
    # Bad Band Tests (not hard-failed, but below partial)
    # -------------------------------------------------------------------------

    def test_bad_board_size_5(self):
        """board_size 5 (< 6 but >= 4) -> bad"""
        m = F1Metrics(
            board_size=5,  # < 6
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.8,
        )
        assert classify_f1_quality(m) == "bad"

    def test_bad_low_strong_fraction(self):
        """strong_fraction < 0.25 -> bad"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.2,  # < 0.25
            weak_fraction=0.5,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.8,
        )
        assert classify_f1_quality(m) == "bad"

    def test_bad_high_redundancy(self):
        """redundancy_rate > 0.5 -> bad"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.6,  # > 0.5
            taboo_violations_count=0,
            opportunity_coverage=0.8,
        )
        assert classify_f1_quality(m) == "bad"

    def test_bad_low_coverage(self):
        """opportunity_coverage < 0.4 -> bad"""
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.3,  # < 0.4
        )
        assert classify_f1_quality(m) == "bad"


# =============================================================================
# F2 CLASSIFIER TESTS
# =============================================================================


class TestClassifyF2Quality:
    """Tests for classify_f2_quality function."""

    # -------------------------------------------------------------------------
    # Hard Failure Tests
    # -------------------------------------------------------------------------

    def test_hard_fail_invalid_variant_too_high(self):
        """invalid_variant_fraction > 0.05 -> bad"""
        m = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.06,  # Hard fail
        )
        assert classify_f2_quality(m) == "bad"

    def test_hard_fail_publish_ready_too_low(self):
        """publish_ready_fraction < 0.2 -> bad"""
        m = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.15,  # Hard fail
            invalid_variant_fraction=0.0,
        )
        assert classify_f2_quality(m) == "bad"

    # -------------------------------------------------------------------------
    # Good Band Tests
    # -------------------------------------------------------------------------

    def test_good_all_conditions_met(self):
        """Both package and variant layers good -> good"""
        m = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            execution_clarity_rate=0.8,
            faithful_package_fraction=0.9,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
            voice_alignment_ok_fraction=0.9,
            channel_fit_ok_fraction=0.85,
        )
        assert classify_f2_quality(m) == "good"

    def test_good_min_thresholds(self):
        """Exactly at good band thresholds -> good"""
        m = F2Metrics(
            mean_package_score=11.0,  # >= 11.0
            board_ready_package_fraction=0.7,  # >= 0.7
            execution_clarity_rate=0.7,  # >= 0.7
            faithful_package_fraction=0.8,  # >= 0.8
            publish_ready_fraction=0.6,  # >= 0.6
            invalid_variant_fraction=0.01,  # <= 0.01
            voice_alignment_ok_fraction=0.8,  # >= 0.8
            channel_fit_ok_fraction=0.8,  # >= 0.8
        )
        assert classify_f2_quality(m) == "good"

    def test_good_optional_metrics_none(self):
        """Optional metrics None allowed for good"""
        m = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            execution_clarity_rate=None,  # Skip constraint
            faithful_package_fraction=None,  # Skip constraint
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
            voice_alignment_ok_fraction=None,  # Skip constraint
            channel_fit_ok_fraction=None,  # Skip constraint
        )
        assert classify_f2_quality(m) == "good"

    # -------------------------------------------------------------------------
    # Partial Band Tests
    # -------------------------------------------------------------------------

    def test_partial_package_good_variant_partial(self):
        """Package good, variant partial -> partial"""
        m = F2Metrics(
            mean_package_score=12.0,  # Good package
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.4,  # Partial variant
            invalid_variant_fraction=0.03,
        )
        assert classify_f2_quality(m) == "partial"

    def test_partial_package_partial_variant_good(self):
        """Package partial, variant good -> partial"""
        m = F2Metrics(
            mean_package_score=9.0,  # Partial package
            board_ready_package_fraction=0.5,
            publish_ready_fraction=0.7,  # Good variant
            invalid_variant_fraction=0.0,
        )
        assert classify_f2_quality(m) == "partial"

    def test_partial_both_partial(self):
        """Both layers partial -> partial"""
        m = F2Metrics(
            mean_package_score=9.0,
            board_ready_package_fraction=0.5,
            publish_ready_fraction=0.4,
            invalid_variant_fraction=0.03,
        )
        assert classify_f2_quality(m) == "partial"

    def test_partial_min_thresholds(self):
        """Exactly at partial band thresholds -> partial"""
        m = F2Metrics(
            mean_package_score=8.0,  # >= 8.0
            board_ready_package_fraction=0.4,  # >= 0.4
            execution_clarity_rate=0.5,  # >= 0.5
            faithful_package_fraction=0.6,  # >= 0.6
            publish_ready_fraction=0.3,  # >= 0.3
            invalid_variant_fraction=0.05,  # <= 0.05
            voice_alignment_ok_fraction=0.6,  # >= 0.6
            channel_fit_ok_fraction=0.6,  # >= 0.6
        )
        assert classify_f2_quality(m) == "partial"

    # -------------------------------------------------------------------------
    # Bad Band Tests
    # -------------------------------------------------------------------------

    def test_bad_package_bad_variant_good(self):
        """Package bad, variant good -> bad"""
        m = F2Metrics(
            mean_package_score=6.0,  # Bad package
            board_ready_package_fraction=0.3,
            publish_ready_fraction=0.7,  # Good variant
            invalid_variant_fraction=0.0,
        )
        assert classify_f2_quality(m) == "bad"

    def test_bad_package_good_variant_bad(self):
        """Package good, variant bad -> bad"""
        m = F2Metrics(
            mean_package_score=12.0,  # Good package
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.25,  # Bad variant
            invalid_variant_fraction=0.04,
        )
        assert classify_f2_quality(m) == "bad"

    def test_bad_low_mean_package_score(self):
        """mean_package_score < 8.0 -> bad package layer"""
        m = F2Metrics(
            mean_package_score=7.0,  # < 8.0
            board_ready_package_fraction=0.5,
            publish_ready_fraction=0.4,
            invalid_variant_fraction=0.03,
        )
        assert classify_f2_quality(m) == "bad"

    def test_bad_low_board_ready_fraction(self):
        """board_ready_package_fraction < 0.4 -> bad package layer"""
        m = F2Metrics(
            mean_package_score=9.0,
            board_ready_package_fraction=0.3,  # < 0.4
            publish_ready_fraction=0.4,
            invalid_variant_fraction=0.03,
        )
        assert classify_f2_quality(m) == "bad"


# =============================================================================
# RUN-LEVEL CLASSIFIER TESTS
# =============================================================================


class TestClassifyRun:
    """Tests for classify_run function."""

    def test_invalid_when_not_structurally_valid(self):
        """structural_valid = False -> invalid"""
        f1 = F1Metrics(
            board_size=10,
            strong_fraction=0.8,
            weak_fraction=0.0,
            invalid_fraction=0.0,
            redundancy_rate=0.1,
            taboo_violations_count=0,
            opportunity_coverage=0.8,
        )
        f2 = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
        )
        assert classify_run(structural_valid=False, f1_metrics=f1, f2_metrics=f2) == "invalid"

    def test_good_when_both_good(self):
        """F1 good AND F2 good -> good"""
        f1 = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        f2 = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
        )
        assert classify_run(structural_valid=True, f1_metrics=f1, f2_metrics=f2) == "good"

    def test_bad_when_f1_bad(self):
        """F1 bad -> bad (regardless of F2)"""
        f1 = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=1,  # Hard fail
            opportunity_coverage=0.7,
        )
        f2 = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
        )
        assert classify_run(structural_valid=True, f1_metrics=f1, f2_metrics=f2) == "bad"

    def test_bad_when_f2_bad(self):
        """F2 bad -> bad (regardless of F1)"""
        f1 = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        f2 = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.15,  # Hard fail
            invalid_variant_fraction=0.0,
        )
        assert classify_run(structural_valid=True, f1_metrics=f1, f2_metrics=f2) == "bad"

    def test_partial_when_f1_partial_f2_good(self):
        """F1 partial, F2 good -> partial"""
        f1 = F1Metrics(
            board_size=7,  # Partial
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        f2 = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
        )
        assert classify_run(structural_valid=True, f1_metrics=f1, f2_metrics=f2) == "partial"

    def test_partial_when_f1_good_f2_partial(self):
        """F1 good, F2 partial -> partial"""
        f1 = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=0.0,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=0.7,
        )
        f2 = F2Metrics(
            mean_package_score=9.0,  # Partial
            board_ready_package_fraction=0.5,
            publish_ready_fraction=0.4,
            invalid_variant_fraction=0.03,
        )
        assert classify_run(structural_valid=True, f1_metrics=f1, f2_metrics=f2) == "partial"

    def test_partial_when_both_partial(self):
        """F1 partial, F2 partial -> partial"""
        f1 = F1Metrics(
            board_size=7,  # Partial
            strong_fraction=0.4,
            weak_fraction=0.2,
            invalid_fraction=0.0,
            redundancy_rate=0.4,
            taboo_violations_count=0,
            opportunity_coverage=0.5,
        )
        f2 = F2Metrics(
            mean_package_score=9.0,
            board_ready_package_fraction=0.5,
            publish_ready_fraction=0.4,
            invalid_variant_fraction=0.03,
        )
        assert classify_run(structural_valid=True, f1_metrics=f1, f2_metrics=f2) == "partial"


# =============================================================================
# NONE HANDLING TESTS
# =============================================================================


class TestNoneHandling:
    """Tests for proper None handling per spec §5.3."""

    def test_f1_none_never_treated_as_zero(self):
        """
        None metrics should skip constraint, not fail.

        Per spec: "We must never silently treat None as 0.0"
        """
        # With None for invalid_fraction and coverage, this should be good
        m = F1Metrics(
            board_size=10,
            strong_fraction=0.6,
            weak_fraction=0.1,
            invalid_fraction=None,
            redundancy_rate=0.2,
            taboo_violations_count=0,
            opportunity_coverage=None,
        )
        assert classify_f1_quality(m) == "good"

    def test_f2_none_metrics_skip_constraints(self):
        """None optional metrics should skip constraints."""
        m = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            execution_clarity_rate=None,
            faithful_package_fraction=None,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
            voice_alignment_ok_fraction=None,
            channel_fit_ok_fraction=None,
        )
        assert classify_f2_quality(m) == "good"

    def test_f2_low_optional_metric_fails_constraint(self):
        """Optional metric present but low should fail constraint."""
        m = F2Metrics(
            mean_package_score=12.0,
            board_ready_package_fraction=0.8,
            execution_clarity_rate=0.3,  # Below 0.5 partial threshold
            faithful_package_fraction=None,
            publish_ready_fraction=0.7,
            invalid_variant_fraction=0.0,
            voice_alignment_ok_fraction=None,
            channel_fit_ok_fraction=None,
        )
        # Package layer becomes bad due to execution_clarity_rate < 0.5
        assert classify_f2_quality(m) == "bad"


# =============================================================================
# METRICS EXTRACTION TESTS
# =============================================================================


class TestMetricsExtraction:
    """Tests for extract_f1_metrics_from_case and extract_f2_metrics_from_case."""

    def test_extract_f1_computes_strong_fraction(self):
        """F1 extraction should compute strong_fraction from opportunities."""
        from kairo.hero.eval.f1_f2_hero_loop import EvalCaseResult

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
            opportunities=[
                {"title": "Opp1", "score": 85},  # Strong
                {"title": "Opp2", "score": 75},  # Not strong
                {"title": "Opp3", "score": 90},  # Strong
                {"title": "Opp4", "score": 50},  # Weak
            ],
            taboo_violations=0,
            opportunity_coverage=0.6,
        )

        m = extract_f1_metrics_from_case(case)

        assert m.board_size == 4
        assert m.strong_fraction == 0.5  # 2/4
        assert m.weak_fraction == 0.25  # 1/4 (score < 60)
        assert m.taboo_violations_count == 0

    def test_extract_f2_computes_fractions(self):
        """F2 extraction should compute fractions from counts."""
        from kairo.hero.eval.f1_f2_hero_loop import EvalCaseResult

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
            package_count=5,
            valid_package_count=4,
            variant_count=10,
            valid_variant_count=8,
        )

        m = extract_f2_metrics_from_case(case)

        assert m.board_ready_package_fraction == 0.8  # 4/5
        assert m.publish_ready_fraction == 0.8  # 8/10
        assert m.invalid_variant_fraction == 0.2  # 2/10

    def test_extract_f1_empty_board(self):
        """F1 extraction handles empty board gracefully."""
        from kairo.hero.eval.f1_f2_hero_loop import EvalCaseResult

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
            opportunities=[],
            taboo_violations=0,
            opportunity_coverage=0.0,
        )

        m = extract_f1_metrics_from_case(case)

        assert m.board_size == 0
        assert m.strong_fraction == 0.0
        assert m.weak_fraction == 0.0

    def test_extract_f2_zero_counts(self):
        """F2 extraction handles zero counts gracefully."""
        from kairo.hero.eval.f1_f2_hero_loop import EvalCaseResult

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
            package_count=0,
            valid_package_count=0,
            variant_count=0,
            valid_variant_count=0,
        )

        m = extract_f2_metrics_from_case(case)

        assert m.board_ready_package_fraction == 0.0
        assert m.publish_ready_fraction == 0.0
        assert m.invalid_variant_fraction == 0.0


# =============================================================================
# HARNESS WIRING TESTS
# =============================================================================


class TestHarnessWiring:
    """Tests for quality classifier integration with eval harness."""

    def test_compute_quality_labels_sets_labels(self):
        """_compute_quality_labels should set all three labels."""
        from kairo.hero.eval.f1_f2_hero_loop import EvalCaseResult, _compute_quality_labels

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
            opportunities=[
                {"title": f"Opp{i}", "score": 85} for i in range(10)
            ],
            package_count=5,
            valid_package_count=5,
            variant_count=10,
            valid_variant_count=10,
            taboo_violations=0,
            opportunity_coverage=0.7,
        )

        _compute_quality_labels(case)

        assert case.f1_label is not None
        assert case.f2_label is not None
        assert case.run_label is not None

    def test_compute_quality_labels_invalid_run(self):
        """Invalid structural status -> run_label = 'invalid', others None."""
        from kairo.hero.eval.f1_f2_hero_loop import (
            EvalCaseResult,
            HeroEvalStageStatus,
            _compute_quality_labels,
        )

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
            stage_status=HeroEvalStageStatus(f1_status="failed", f2_status="ok"),
        )

        _compute_quality_labels(case)

        assert case.f1_label is None
        assert case.f2_label is None
        assert case.run_label == "invalid"

    def test_case_result_has_label_fields(self):
        """EvalCaseResult should have f1_label, f2_label, run_label fields."""
        from kairo.hero.eval.f1_f2_hero_loop import EvalCaseResult

        case = EvalCaseResult(
            eval_brand_id="test",
            brand_slug="test",
            brand_name="Test Brand",
        )

        assert hasattr(case, "f1_label")
        assert hasattr(case, "f2_label")
        assert hasattr(case, "run_label")
        assert case.f1_label is None
        assert case.f2_label is None
        assert case.run_label is None
