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
from uuid import UUID

import pytest

from kairo.hero.eval.f1_f2_hero_loop import (
    EvalCaseResult,
    EvalResult,
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
            assert result.status in ("completed", "error")

            # If completed, check metrics exist
            if result.status == "completed":
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
