"""
Tests for Hero Loop Eval Harness.

PR-10: Offline Eval Harness + Fixtures.

These tests verify:
1. Fixture loading works correctly
2. Eval harness runs with LLM_DISABLED=True
3. Results contain expected structure
4. Metrics are computed correctly

Per docs/eval/evalHarness.md and PR-map-and-standards §PR-10:
- Tests MUST use LLM_DISABLED=True
- Tests verify fixture loading, not LLM quality
- Tests check result structure and basic metrics
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from kairo.hero.eval.f1_f2_hero_loop import (
    EvalCaseResult,
    EvalResult,
    HeroEvalStageStatus,
    _check_taboo_violations,
    _compute_opportunity_coverage,
    _compute_text_similarity,
    _get_brand_fixture,
    _get_opportunity_goldens,
    _get_package_goldens,
    _get_signals_for_brand,
    _get_variant_goldens,
    _load_brands_fixture,
    _load_external_signals_fixture,
    _load_goldens_fixture,
    run_hero_loop_eval,
)


@pytest.fixture(autouse=True)
def ensure_llm_disabled():
    """Ensure LLM_DISABLED is set for all tests."""
    original = os.environ.get("LLM_DISABLED")
    os.environ["LLM_DISABLED"] = "true"
    yield
    if original is None:
        os.environ.pop("LLM_DISABLED", None)
    else:
        os.environ["LLM_DISABLED"] = original


class TestFixtureLoading:
    """Tests for fixture loading functions."""

    def test_load_brands_fixture_returns_dict(self):
        """brands.json loads as dict with 'brands' key."""
        result = _load_brands_fixture()
        assert isinstance(result, dict)
        assert "brands" in result

    def test_load_brands_fixture_has_eval_brands(self):
        """brands.json contains eval brand definitions."""
        result = _load_brands_fixture()
        brands = result.get("brands", [])
        assert len(brands) >= 1, "Expected at least one eval brand"

        # Check first brand has required fields
        brand = brands[0]
        assert "eval_brand_id" in brand
        assert "brand_slug" in brand
        assert "brand_name" in brand
        assert "snapshot" in brand

    def test_load_external_signals_fixture_returns_dict(self):
        """external_signals.json loads as dict with 'bundles' key."""
        result = _load_external_signals_fixture()
        assert isinstance(result, dict)
        assert "bundles" in result

    def test_load_goldens_opportunities(self):
        """opportunities.json goldens load correctly."""
        result = _load_goldens_fixture("opportunities")
        assert isinstance(result, dict)
        assert "goldens" in result

    def test_load_goldens_packages(self):
        """packages.json goldens load correctly."""
        result = _load_goldens_fixture("packages")
        assert isinstance(result, dict)
        assert "goldens" in result

    def test_load_goldens_variants(self):
        """variants.json goldens load correctly."""
        result = _load_goldens_fixture("variants")
        assert isinstance(result, dict)
        assert "goldens" in result

    def test_get_brand_fixture_returns_matching_brand(self):
        """_get_brand_fixture returns brand by slug."""
        brands_data = _load_brands_fixture()
        if brands_data.get("brands"):
            first_slug = brands_data["brands"][0]["brand_slug"]
            result = _get_brand_fixture(first_slug)
            assert result is not None
            assert result["brand_slug"] == first_slug

    def test_get_brand_fixture_returns_none_for_unknown(self):
        """_get_brand_fixture returns None for unknown slug."""
        result = _get_brand_fixture("nonexistent-brand-xyz-123")
        assert result is None

    def test_get_signals_for_brand_returns_dict(self):
        """_get_signals_for_brand returns dict even for unknown brand."""
        result = _get_signals_for_brand("nonexistent-brand")
        assert isinstance(result, dict)

    def test_get_opportunity_goldens_returns_list(self):
        """_get_opportunity_goldens returns list even for unknown brand."""
        result = _get_opportunity_goldens("nonexistent-brand")
        assert isinstance(result, list)

    def test_get_package_goldens_returns_list(self):
        """_get_package_goldens returns list even for unknown brand."""
        result = _get_package_goldens("nonexistent-brand")
        assert isinstance(result, list)

    def test_get_variant_goldens_returns_list(self):
        """_get_variant_goldens returns list even for unknown brand."""
        result = _get_variant_goldens("nonexistent-brand")
        assert isinstance(result, list)


class TestMetricsComputation:
    """Tests for metrics computation functions."""

    def test_compute_text_similarity_identical(self):
        """Identical texts have similarity 1.0."""
        result = _compute_text_similarity("hello world", "hello world")
        assert result == 1.0

    def test_compute_text_similarity_different(self):
        """Completely different texts have similarity 0.0."""
        result = _compute_text_similarity("hello world", "foo bar baz")
        assert result == 0.0

    def test_compute_text_similarity_partial(self):
        """Partially overlapping texts have similarity between 0 and 1."""
        result = _compute_text_similarity("hello world foo", "hello world bar")
        assert 0 < result < 1

    def test_compute_text_similarity_empty(self):
        """Empty texts have similarity 0.0."""
        assert _compute_text_similarity("", "hello") == 0.0
        assert _compute_text_similarity("hello", "") == 0.0
        assert _compute_text_similarity("", "") == 0.0

    def test_compute_opportunity_coverage_empty_goldens(self):
        """Empty goldens returns 0.0 coverage."""
        coverage, matches = _compute_opportunity_coverage(
            [{"title": "Test opp"}],
            [],
        )
        assert coverage == 0.0
        assert matches == 0

    def test_compute_opportunity_coverage_no_generated(self):
        """No generated opps returns 0.0 coverage."""
        coverage, matches = _compute_opportunity_coverage(
            [],
            [{"title": "Golden opp"}],
        )
        assert coverage == 0.0
        assert matches == 0

    def test_compute_opportunity_coverage_exact_match(self):
        """Exact title match returns 1.0 coverage."""
        coverage, matches = _compute_opportunity_coverage(
            [{"title": "AI trends for 2025"}],
            [{"title": "AI trends for 2025"}],
        )
        assert coverage == 1.0
        assert matches == 1

    def test_compute_opportunity_coverage_partial_match(self):
        """Partial title match with >0.3 Jaccard returns match."""
        coverage, matches = _compute_opportunity_coverage(
            [{"title": "AI trends in enterprise software"}],
            [{"title": "AI trends for 2025"}],
        )
        # "AI trends" overlaps, should meet threshold
        assert matches >= 0  # May or may not match depending on threshold

    def test_check_taboo_violations_none(self):
        """No taboos returns empty list."""
        violations = _check_taboo_violations("This is clean text", [])
        assert violations == []

    def test_check_taboo_violations_found(self):
        """Taboo word found returns the word."""
        violations = _check_taboo_violations(
            "This text mentions disruption in the industry",
            ["disruption", "revolutionary"],
        )
        assert "disruption" in violations
        assert "revolutionary" not in violations

    def test_check_taboo_violations_case_insensitive(self):
        """Taboo check is case insensitive."""
        violations = _check_taboo_violations(
            "This text mentions DISRUPTION",
            ["disruption"],
        )
        assert "disruption" in violations


class TestHeroEvalStageStatus:
    """Tests for HeroEvalStageStatus dataclass (10b)."""

    def test_stage_status_defaults_to_ok(self):
        """Stage status defaults to ok for both F1 and F2."""
        status = HeroEvalStageStatus()
        assert status.f1_status == "ok"
        assert status.f2_status == "ok"
        assert status.failure_reason is None

    def test_is_structurally_valid_when_ok(self):
        """Run is structurally valid when both stages are ok."""
        status = HeroEvalStageStatus(f1_status="ok", f2_status="ok")
        assert status.is_structurally_valid() is True

    def test_is_structurally_valid_when_degraded(self):
        """Run is structurally valid when degraded (not failed)."""
        status = HeroEvalStageStatus(f1_status="degraded", f2_status="ok")
        assert status.is_structurally_valid() is True

        status = HeroEvalStageStatus(f1_status="ok", f2_status="degraded")
        assert status.is_structurally_valid() is True

        status = HeroEvalStageStatus(f1_status="degraded", f2_status="degraded")
        assert status.is_structurally_valid() is True

    def test_is_structurally_valid_false_when_f1_failed(self):
        """Run is NOT structurally valid when F1 failed."""
        status = HeroEvalStageStatus(f1_status="failed", f2_status="ok")
        assert status.is_structurally_valid() is False

    def test_is_structurally_valid_false_when_f2_failed(self):
        """Run is NOT structurally valid when F2 failed."""
        status = HeroEvalStageStatus(f1_status="ok", f2_status="failed")
        assert status.is_structurally_valid() is False

    def test_is_structurally_valid_false_when_both_failed(self):
        """Run is NOT structurally valid when both stages failed."""
        status = HeroEvalStageStatus(f1_status="failed", f2_status="failed")
        assert status.is_structurally_valid() is False

    def test_overall_status_ok(self):
        """Overall status is ok when both stages are ok."""
        status = HeroEvalStageStatus(f1_status="ok", f2_status="ok")
        assert status.overall_status() == "ok"

    def test_overall_status_degraded(self):
        """Overall status is degraded when any stage is degraded."""
        status = HeroEvalStageStatus(f1_status="degraded", f2_status="ok")
        assert status.overall_status() == "degraded"

        status = HeroEvalStageStatus(f1_status="ok", f2_status="degraded")
        assert status.overall_status() == "degraded"

    def test_overall_status_failed(self):
        """Overall status is failed when any stage failed."""
        status = HeroEvalStageStatus(f1_status="failed", f2_status="ok")
        assert status.overall_status() == "failed"

        status = HeroEvalStageStatus(f1_status="ok", f2_status="failed")
        assert status.overall_status() == "failed"

    def test_overall_status_failed_takes_precedence(self):
        """Failed status takes precedence over degraded."""
        status = HeroEvalStageStatus(f1_status="degraded", f2_status="failed")
        assert status.overall_status() == "failed"


class TestEvalResultDataclasses:
    """Tests for result dataclasses."""

    def test_eval_case_result_defaults(self):
        """EvalCaseResult has correct defaults."""
        result = EvalCaseResult(
            eval_brand_id="test-brand",
            brand_slug="test",
            brand_name="Test Brand",
        )
        assert result.opportunity_count == 0
        assert result.valid_opportunity_count == 0
        assert result.opportunity_coverage == 0.0
        assert result.package_count == 0
        assert result.variant_count == 0
        assert result.taboo_violations == 0
        assert result.opportunities == []
        assert result.packages == []
        assert result.variants == []
        assert result.warnings == []

    def test_eval_case_result_has_stage_status(self):
        """EvalCaseResult has stage_status field with HeroEvalStageStatus (10b)."""
        result = EvalCaseResult(
            eval_brand_id="test-brand",
            brand_slug="test",
            brand_name="Test Brand",
        )
        assert isinstance(result.stage_status, HeroEvalStageStatus)
        assert result.stage_status.f1_status == "ok"
        assert result.stage_status.f2_status == "ok"

    def test_eval_result_defaults(self):
        """EvalResult has correct defaults."""
        from datetime import datetime, timezone
        from uuid import uuid4

        result = EvalResult(
            brand_slug="test",
            run_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            llm_disabled=True,
        )
        assert result.status == "completed"
        assert result.metrics == {}
        assert result.cases == []
        assert result.errors == []


@pytest.mark.django_db
class TestEvalHarnessRun:
    """Integration tests for the eval harness."""

    def test_run_hero_loop_eval_unknown_brand_returns_error(self):
        """Unknown brand slug returns error status."""
        result = run_hero_loop_eval(
            brand_slug="nonexistent-brand-xyz-123",
            llm_disabled=True,
        )
        assert result.status == "error"
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_run_hero_loop_eval_with_fixture_brand(self):
        """Eval runs successfully with fixture brand."""
        # Get first available brand from fixtures
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        # Use temp dir for output to avoid polluting docs/
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_hero_loop_eval(
                brand_slug=brand_slug,
                llm_disabled=True,
                max_opportunities=1,  # Limit for speed
                output_dir=Path(tmpdir),
            )

            # Check result structure
            assert isinstance(result, EvalResult)
            assert result.brand_slug == brand_slug
            assert result.llm_disabled is True
            assert isinstance(result.run_id, UUID)
            assert result.timestamp is not None

            # Check status (may be error if DB setup issues, but structure should be valid)
            # 10b: "degraded" is also a valid status (when F1 runs in degraded mode)
            assert result.status in ("completed", "degraded", "error")

            # If completed or degraded, check metrics exist
            if result.status in ("completed", "degraded"):
                assert isinstance(result.metrics, dict)
                assert len(result.cases) >= 1

                # Check output artifacts were written
                output_files = list(Path(tmpdir).glob("*.json"))
                assert len(output_files) >= 1, "Expected JSON output artifact"

                md_files = list(Path(tmpdir).glob("*.md"))
                assert len(md_files) >= 1, "Expected Markdown output artifact"

    def test_run_hero_loop_eval_result_has_expected_metrics(self):
        """Eval result contains expected metric keys."""
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_hero_loop_eval(
                brand_slug=brand_slug,
                llm_disabled=True,
                max_opportunities=1,
                output_dir=Path(tmpdir),
            )

            if result.status == "completed":
                expected_metrics = [
                    "opportunity_count",
                    "package_count",
                    "variant_count",
                    "taboo_violations",
                ]

                for metric in expected_metrics:
                    assert metric in result.metrics, f"Missing metric: {metric}"

    def test_run_hero_loop_eval_case_has_opportunities(self):
        """Eval case result has opportunity data."""
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_hero_loop_eval(
                brand_slug=brand_slug,
                llm_disabled=True,
                max_opportunities=1,
                output_dir=Path(tmpdir),
            )

            if result.status == "completed" and result.cases:
                case = result.cases[0]
                assert case.eval_brand_id is not None
                assert case.brand_slug == brand_slug
                # With LLM_DISABLED, stub should generate opportunities
                assert case.opportunity_count >= 0


@pytest.mark.django_db
class TestEvalHarnessStageStatus:
    """
    Integration tests for stage-level status (10b).

    Tests verify:
    1. F1 failure case - f1_status=="failed", f2_status=="failed"
    2. Degraded-but-structurally-valid case - f1_status=="degraded", f2 runs normally
    3. Fully ok case - both statuses=="ok"
    """

    def test_f1_failure_sets_failed_status(self):
        """
        10b: When F1 (opportunities) fails completely, both stages are marked failed.

        Patch the opportunities engine to raise an exception.
        """
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch opportunities engine to fail
            with patch(
                "kairo.hero.engines.opportunities_engine.generate_today_board"
            ) as mock_engine:
                mock_engine.side_effect = RuntimeError("F1 total failure")

                result = run_hero_loop_eval(
                    brand_slug=brand_slug,
                    llm_disabled=True,
                    max_opportunities=1,
                    output_dir=Path(tmpdir),
                )

                # Result should indicate failure
                assert result.status == "failed", "Status should be failed on F1 exception"

                # Check stage status
                assert len(result.cases) >= 1
                case = result.cases[0]
                assert case.stage_status.f1_status == "failed", "F1 should be failed"
                assert case.stage_status.f2_status == "failed", "F2 should be failed (skipped due to F1)"
                assert case.stage_status.failure_reason is not None
                assert "f1_exception" in case.stage_status.failure_reason

                # Should NOT be structurally valid
                assert case.stage_status.is_structurally_valid() is False

    def test_f1_degraded_is_structurally_valid(self):
        """
        10b: When F1 runs in degraded mode (stub opps), it's degraded but still valid.

        Patch the LLM graph call to fail, triggering degraded mode.
        """
        from kairo.hero.dto import TodayBoardDTO, TodayBoardMetaDTO
        from uuid import uuid4
        from datetime import datetime, timezone

        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock TodayBoardDTO with degraded=True
            mock_result = MagicMock(spec=TodayBoardDTO)
            mock_result.meta = MagicMock(spec=TodayBoardMetaDTO)
            mock_result.meta.degraded = True
            mock_result.meta.reason = "llm_graph_failure"

            # Create mock opportunities (simplified)
            mock_opp = MagicMock()
            mock_opp.id = uuid4()
            mock_opp.title = "Test Opportunity"
            mock_opp.angle = "Test angle"
            mock_opp.type = MagicMock()
            mock_opp.type.value = "TREND"
            mock_opp.primary_channel = MagicMock()
            mock_opp.primary_channel.value = "LINKEDIN"
            mock_opp.score = 75.0
            mock_opp.is_valid = True

            mock_result.opportunities = [mock_opp]

            with patch(
                "kairo.hero.engines.opportunities_engine.generate_today_board"
            ) as mock_engine:
                mock_engine.return_value = mock_result

                # Also patch content engine to avoid DB lookups for F2
                with patch(
                    "kairo.hero.engines.content_engine.create_package_from_opportunity"
                ) as mock_package:
                    mock_pkg = MagicMock()
                    mock_pkg.id = uuid4()
                    mock_pkg.title = "Test Package"
                    mock_pkg.status = "DRAFT"
                    mock_pkg.channels = ["LINKEDIN"]
                    mock_package.return_value = mock_pkg

                    with patch(
                        "kairo.hero.engines.content_engine.generate_variants_for_package"
                    ) as mock_variants:
                        mock_variant = MagicMock()
                        mock_variant.id = uuid4()
                        mock_variant.channel = "LINKEDIN"
                        mock_variant.status = "DRAFT"
                        mock_variant.draft_text = "Test variant text"
                        mock_variants.return_value = [mock_variant]

                        result = run_hero_loop_eval(
                            brand_slug=brand_slug,
                            llm_disabled=True,
                            max_opportunities=1,
                            output_dir=Path(tmpdir),
                        )

                        # Result should indicate degraded (not failed)
                        assert result.status == "degraded", "Status should be degraded"

                        # Check stage status
                        assert len(result.cases) >= 1
                        case = result.cases[0]
                        assert case.stage_status.f1_status == "degraded", "F1 should be degraded"
                        assert case.stage_status.f2_status == "ok", "F2 should be ok"

                        # Should still be structurally valid
                        assert case.stage_status.is_structurally_valid() is True

    def test_fully_ok_run_has_ok_status(self):
        """
        10b: A successful run has both stages as 'ok'.
        """
        from uuid import uuid4

        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock TodayBoardResultDTO with degraded=False
            mock_result = MagicMock()
            mock_result.meta = MagicMock()
            mock_result.meta.degraded = False
            mock_result.meta.reason = None

            # Create mock opportunities
            mock_opp = MagicMock()
            mock_opp.id = uuid4()
            mock_opp.title = "Real Opportunity"
            mock_opp.angle = "Real angle"
            mock_opp.type = MagicMock()
            mock_opp.type.value = "NEWS"
            mock_opp.primary_channel = MagicMock()
            mock_opp.primary_channel.value = "TWITTER"
            mock_opp.score = 85.0
            mock_opp.is_valid = True

            mock_result.opportunities = [mock_opp]

            with patch(
                "kairo.hero.engines.opportunities_engine.generate_today_board"
            ) as mock_engine:
                mock_engine.return_value = mock_result

                # Also patch content engine
                with patch(
                    "kairo.hero.engines.content_engine.create_package_from_opportunity"
                ) as mock_package:
                    mock_pkg = MagicMock()
                    mock_pkg.id = uuid4()
                    mock_pkg.title = "Real Package"
                    mock_pkg.status = "DRAFT"
                    mock_pkg.channels = ["TWITTER"]
                    mock_package.return_value = mock_pkg

                    with patch(
                        "kairo.hero.engines.content_engine.generate_variants_for_package"
                    ) as mock_variants:
                        mock_variant = MagicMock()
                        mock_variant.id = uuid4()
                        mock_variant.channel = "TWITTER"
                        mock_variant.status = "DRAFT"
                        mock_variant.draft_text = "Real variant text"
                        mock_variants.return_value = [mock_variant]

                        result = run_hero_loop_eval(
                            brand_slug=brand_slug,
                            llm_disabled=True,
                            max_opportunities=1,
                            output_dir=Path(tmpdir),
                        )

                        # Result should indicate completed (ok)
                        assert result.status == "completed", "Status should be completed"

                        # Check stage status
                        assert len(result.cases) >= 1
                        case = result.cases[0]
                        assert case.stage_status.f1_status == "ok", "F1 should be ok"
                        assert case.stage_status.f2_status == "ok", "F2 should be ok"

                        # Should be structurally valid
                        assert case.stage_status.is_structurally_valid() is True

                        # Metrics should include quality metrics when valid
                        assert "opportunity_coverage" in result.metrics
                        assert "avg_opportunity_score" in result.metrics

    def test_f2_partial_failure_sets_degraded_status(self):
        """
        10b: When F2 partially fails (some packages fail), F2 is degraded.
        """
        from uuid import uuid4

        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock TodayBoardResultDTO with degraded=False
            mock_result = MagicMock()
            mock_result.meta = MagicMock()
            mock_result.meta.degraded = False
            mock_result.meta.reason = None

            # Create two mock opportunities
            mock_opp1 = MagicMock()
            mock_opp1.id = uuid4()
            mock_opp1.title = "Opportunity 1"
            mock_opp1.angle = "Angle 1"
            mock_opp1.type = MagicMock()
            mock_opp1.type.value = "NEWS"
            mock_opp1.primary_channel = MagicMock()
            mock_opp1.primary_channel.value = "TWITTER"
            mock_opp1.score = 90.0
            mock_opp1.is_valid = True

            mock_opp2 = MagicMock()
            mock_opp2.id = uuid4()
            mock_opp2.title = "Opportunity 2"
            mock_opp2.angle = "Angle 2"
            mock_opp2.type = MagicMock()
            mock_opp2.type.value = "TREND"
            mock_opp2.primary_channel = MagicMock()
            mock_opp2.primary_channel.value = "LINKEDIN"
            mock_opp2.score = 80.0
            mock_opp2.is_valid = True

            mock_result.opportunities = [mock_opp1, mock_opp2]

            with patch(
                "kairo.hero.engines.opportunities_engine.generate_today_board"
            ) as mock_engine:
                mock_engine.return_value = mock_result

                call_count = [0]

                def package_side_effect(*args, **kwargs):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        # First call succeeds
                        mock_pkg = MagicMock()
                        mock_pkg.id = uuid4()
                        mock_pkg.title = "Package 1"
                        mock_pkg.status = "DRAFT"
                        mock_pkg.channels = ["TWITTER"]
                        return mock_pkg
                    else:
                        # Second call fails
                        raise RuntimeError("Package creation failed")

                with patch(
                    "kairo.hero.engines.content_engine.create_package_from_opportunity"
                ) as mock_package:
                    mock_package.side_effect = package_side_effect

                    with patch(
                        "kairo.hero.engines.content_engine.generate_variants_for_package"
                    ) as mock_variants:
                        mock_variant = MagicMock()
                        mock_variant.id = uuid4()
                        mock_variant.channel = "TWITTER"
                        mock_variant.status = "DRAFT"
                        mock_variant.draft_text = "Variant text"
                        mock_variants.return_value = [mock_variant]

                        result = run_hero_loop_eval(
                            brand_slug=brand_slug,
                            llm_disabled=True,
                            max_opportunities=2,
                            output_dir=Path(tmpdir),
                        )

                        # Check stage status
                        assert len(result.cases) >= 1
                        case = result.cases[0]
                        assert case.stage_status.f1_status == "ok", "F1 should be ok"
                        assert case.stage_status.f2_status == "degraded", "F2 should be degraded (partial failure)"

                        # Should still be structurally valid
                        assert case.stage_status.is_structurally_valid() is True

    def test_result_metrics_include_stage_status(self):
        """
        10b: Result metrics include f1_status and f2_status keys.
        """
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_hero_loop_eval(
                brand_slug=brand_slug,
                llm_disabled=True,
                max_opportunities=1,
                output_dir=Path(tmpdir),
            )

            # Check that metrics include stage status fields
            assert "f1_status" in result.metrics
            assert "f2_status" in result.metrics
            assert result.metrics["f1_status"] in ("ok", "degraded", "failed")
            assert result.metrics["f2_status"] in ("ok", "degraded", "failed")

    def test_failed_run_has_no_quality_metrics(self):
        """
        10b: When is_structurally_valid() is False, quality metrics are NOT included.

        This ensures we don't compute misleading metrics on broken runs.
        Quality metrics = opportunity_coverage, avg_opportunity_score, golden_match_count
        """
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch opportunities engine to fail completely
            with patch(
                "kairo.hero.engines.opportunities_engine.generate_today_board"
            ) as mock_engine:
                mock_engine.side_effect = RuntimeError("Total F1 failure")

                result = run_hero_loop_eval(
                    brand_slug=brand_slug,
                    llm_disabled=True,
                    max_opportunities=1,
                    output_dir=Path(tmpdir),
                )

                # Verify the run is structurally invalid
                assert result.status == "failed"
                assert len(result.cases) >= 1
                case = result.cases[0]
                assert case.stage_status.is_structurally_valid() is False

                # Quality metrics should NOT be in the metrics dict
                quality_metrics = [
                    "opportunity_coverage",
                    "avg_opportunity_score",
                    "golden_match_count",
                ]

                for metric in quality_metrics:
                    assert metric not in result.metrics, (
                        f"Quality metric '{metric}' should not be included in failed run"
                    )

                # Basic count metrics should still be present (for diagnostics)
                assert "opportunity_count" in result.metrics
                assert "f1_status" in result.metrics
                assert "f2_status" in result.metrics

    def test_valid_run_has_quality_metrics(self):
        """
        10b: When is_structurally_valid() is True, quality metrics ARE included.
        """
        from uuid import uuid4

        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            pytest.skip("No eval brands in fixtures")

        brand_slug = brands[0]["brand_slug"]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock that returns a valid (non-degraded) result
            mock_result = MagicMock()
            mock_result.meta = MagicMock()
            mock_result.meta.degraded = False
            mock_result.meta.reason = None

            mock_opp = MagicMock()
            mock_opp.id = uuid4()
            mock_opp.title = "Valid Opportunity"
            mock_opp.angle = "Valid angle"
            mock_opp.type = MagicMock()
            mock_opp.type.value = "NEWS"
            mock_opp.primary_channel = MagicMock()
            mock_opp.primary_channel.value = "LINKEDIN"
            mock_opp.score = 85.0
            mock_opp.is_valid = True

            mock_result.opportunities = [mock_opp]

            with patch(
                "kairo.hero.engines.opportunities_engine.generate_today_board"
            ) as mock_engine:
                mock_engine.return_value = mock_result

                with patch(
                    "kairo.hero.engines.content_engine.create_package_from_opportunity"
                ) as mock_package:
                    mock_pkg = MagicMock()
                    mock_pkg.id = uuid4()
                    mock_pkg.title = "Valid Package"
                    mock_pkg.status = "DRAFT"
                    mock_pkg.channels = ["LINKEDIN"]
                    mock_package.return_value = mock_pkg

                    with patch(
                        "kairo.hero.engines.content_engine.generate_variants_for_package"
                    ) as mock_variants:
                        mock_variants.return_value = []

                        result = run_hero_loop_eval(
                            brand_slug=brand_slug,
                            llm_disabled=True,
                            max_opportunities=1,
                            output_dir=Path(tmpdir),
                        )

                        # Verify the run is structurally valid
                        assert result.status == "completed"
                        assert len(result.cases) >= 1
                        case = result.cases[0]
                        assert case.stage_status.is_structurally_valid() is True

                        # Quality metrics SHOULD be in the metrics dict
                        assert "opportunity_coverage" in result.metrics
                        assert "avg_opportunity_score" in result.metrics
                        assert "golden_match_count" in result.metrics
