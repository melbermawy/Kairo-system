"""
Tests for the observability store module.

PR-11: Observability, Classification, and Admin Surfaces.

Tests cover:
- Event appending and reading (with obs enabled/disabled)
- Classification functions (F1 and F2)
- Run listing and detail retrieval
- Edge cases and error handling
"""

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from kairo.hero.observability_store import (
    append_event,
    classify_f1_run,
    classify_f2_run,
    classify_run,
    get_run_detail,
    list_runs,
    log_classification,
    log_llm_call,
    log_run_complete,
    log_run_fail,
    log_run_start,
    obs_dir,
    obs_enabled,
    read_events,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_obs_dir(monkeypatch, tmp_path):
    """Create a temporary observability directory."""
    obs_path = tmp_path / "obs"
    obs_path.mkdir()
    monkeypatch.setenv("KAIRO_OBS_DIR", str(obs_path))
    monkeypatch.setenv("KAIRO_OBS_ENABLED", "true")
    return obs_path


@pytest.fixture
def obs_disabled(monkeypatch):
    """Disable observability."""
    monkeypatch.setenv("KAIRO_OBS_ENABLED", "false")


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestObsConfiguration:
    """Tests for observability configuration functions."""

    def test_obs_enabled_default_false(self, monkeypatch):
        """obs_enabled() returns False by default."""
        monkeypatch.delenv("KAIRO_OBS_ENABLED", raising=False)
        assert obs_enabled() is False

    def test_obs_enabled_true_variants(self, monkeypatch):
        """obs_enabled() returns True for various truthy values."""
        for value in ["true", "True", "TRUE", "1", "yes", "on"]:
            monkeypatch.setenv("KAIRO_OBS_ENABLED", value)
            assert obs_enabled() is True, f"Expected True for {value}"

    def test_obs_enabled_false_variants(self, monkeypatch):
        """obs_enabled() returns False for non-truthy values."""
        for value in ["false", "False", "0", "no", "off", "", "random"]:
            monkeypatch.setenv("KAIRO_OBS_ENABLED", value)
            assert obs_enabled() is False, f"Expected False for {value}"

    def test_obs_dir_default(self, monkeypatch):
        """obs_dir() returns default path."""
        monkeypatch.delenv("KAIRO_OBS_DIR", raising=False)
        assert obs_dir() == Path("var/obs")

    def test_obs_dir_custom(self, monkeypatch):
        """obs_dir() returns custom path from env."""
        monkeypatch.setenv("KAIRO_OBS_DIR", "/custom/path")
        assert obs_dir() == Path("/custom/path")


# =============================================================================
# EVENT APPEND/READ TESTS
# =============================================================================


class TestEventAppendRead:
    """Tests for append_event and read_events functions."""

    def test_append_event_when_enabled(self, temp_obs_dir):
        """append_event() writes event when enabled."""
        run_id = uuid4()
        result = append_event(
            run_id=run_id,
            kind="run_start",
            payload={"brand_id": str(uuid4()), "flow": "F1_today"},
        )

        assert result is True

        # Verify file was created
        file_path = temp_obs_dir / str(run_id) / "run_start.jsonl"
        assert file_path.exists()

        # Verify content
        with open(file_path) as f:
            line = f.readline()
            event = json.loads(line)
            assert event["kind"] == "run_start"
            assert event["flow"] == "F1_today"
            assert "ts" in event

    def test_append_event_when_disabled(self, obs_disabled, monkeypatch, tmp_path):
        """append_event() returns False when disabled."""
        monkeypatch.setenv("KAIRO_OBS_DIR", str(tmp_path))
        run_id = uuid4()

        result = append_event(
            run_id=run_id,
            kind="run_start",
            payload={"test": True},
        )

        assert result is False

        # Verify no file was created
        file_path = tmp_path / str(run_id) / "run_start.jsonl"
        assert not file_path.exists()

    def test_append_multiple_events(self, temp_obs_dir):
        """append_event() appends multiple events to same file."""
        run_id = uuid4()

        for i in range(3):
            append_event(
                run_id=run_id,
                kind="llm_call",
                payload={"call_num": i},
            )

        file_path = temp_obs_dir / str(run_id) / "llm_call.jsonl"
        with open(file_path) as f:
            lines = f.readlines()

        assert len(lines) == 3

        for i, line in enumerate(lines):
            event = json.loads(line)
            assert event["call_num"] == i

    def test_read_events_returns_list(self, temp_obs_dir):
        """read_events() returns list of events."""
        run_id = uuid4()

        for i in range(2):
            append_event(run_id=run_id, kind="engine_step", payload={"step": i})

        events = read_events(run_id, "engine_step")

        assert len(events) == 2
        assert events[0]["step"] == 0
        assert events[1]["step"] == 1

    def test_read_events_missing_file(self, temp_obs_dir):
        """read_events() returns empty list for missing file."""
        run_id = uuid4()
        events = read_events(run_id, "nonexistent")
        assert events == []

    def test_read_events_different_kinds(self, temp_obs_dir):
        """read_events() reads correct kind file."""
        run_id = uuid4()

        append_event(run_id=run_id, kind="run_start", payload={"type": "start"})
        append_event(run_id=run_id, kind="run_complete", payload={"type": "complete"})

        start_events = read_events(run_id, "run_start")
        complete_events = read_events(run_id, "run_complete")

        assert len(start_events) == 1
        assert start_events[0]["type"] == "start"
        assert len(complete_events) == 1
        assert complete_events[0]["type"] == "complete"


# =============================================================================
# CLASSIFICATION TESTS (obs_health labels: ok/degraded/failed)
# =============================================================================


class TestF1Classification:
    """Tests for classify_f1_run function.

    NOTE: These tests verify obs_health labels (ok/degraded/failed),
    which are for operational health monitoring, NOT quality assessment.
    Quality classification uses kairo/hero/eval/quality_classifier.py.
    """

    def test_ok_healthy_count(self):
        """F1 is ok with >= 3 valid opportunities."""
        for count in [3, 6, 8, 10, 12, 15]:
            label, reason = classify_f1_run(
                opportunity_count=count + 2,  # Some may be filtered
                valid_opportunity_count=count,
            )
            assert label == "ok", f"Expected ok for {count} opps"
            assert "healthy_count" in reason

    def test_degraded_low_count(self):
        """F1 is degraded with 1-2 valid opportunities."""
        for count in [1, 2]:
            label, reason = classify_f1_run(
                opportunity_count=count,
                valid_opportunity_count=count,
            )
            assert label == "degraded", f"Expected degraded for {count} opps"
            assert "low_count" in reason

    def test_failed_zero_opportunities(self):
        """F1 is failed with 0 valid opportunities."""
        label, reason = classify_f1_run(
            opportunity_count=5,
            valid_opportunity_count=0,
        )
        assert label == "failed"
        assert "zero_valid" in reason

    def test_failed_taboo_violations(self):
        """F1 is failed with taboo violations."""
        label, reason = classify_f1_run(
            opportunity_count=10,
            valid_opportunity_count=10,
            taboo_violations=1,
        )
        assert label == "failed"
        assert "taboo" in reason

    def test_failed_engine_failure(self):
        """F1 is failed when engine fails."""
        label, reason = classify_f1_run(
            opportunity_count=0,
            valid_opportunity_count=0,
            status="fail",
        )
        assert label == "failed"
        assert "engine_failure" in reason


class TestF2Classification:
    """Tests for classify_f2_run function.

    NOTE: These tests verify obs_health labels (ok/degraded/failed),
    which are for operational health monitoring, NOT quality assessment.
    """

    def test_ok_full_coverage(self):
        """F2 is ok with full variant coverage."""
        label, reason = classify_f2_run(
            package_count=1,
            variant_count=2,
            expected_channels=2,
        )
        assert label == "ok"
        assert "full_coverage" in reason

    def test_ok_more_than_expected(self):
        """F2 is ok with more variants than expected."""
        label, reason = classify_f2_run(
            package_count=1,
            variant_count=3,
            expected_channels=2,
        )
        assert label == "ok"

    def test_degraded_partial_coverage(self):
        """F2 is degraded with some but not all variants."""
        label, reason = classify_f2_run(
            package_count=1,
            variant_count=1,
            expected_channels=2,
        )
        assert label == "degraded"
        assert "partial_coverage" in reason

    def test_failed_no_package(self):
        """F2 is failed when no package created."""
        label, reason = classify_f2_run(
            package_count=0,
            variant_count=0,
        )
        assert label == "failed"
        assert "no_package" in reason

    def test_failed_no_variants(self):
        """F2 is failed when package exists but no variants."""
        label, reason = classify_f2_run(
            package_count=1,
            variant_count=0,
        )
        assert label == "failed"
        assert "no_variants" in reason

    def test_failed_taboo_violations(self):
        """F2 is failed with taboo violations."""
        label, reason = classify_f2_run(
            package_count=1,
            variant_count=2,
            taboo_violations=1,
        )
        assert label == "failed"
        assert "taboo" in reason


class TestRunClassification:
    """Tests for classify_run function (combined F1+F2).

    NOTE: These tests verify obs_health labels (ok/degraded/failed),
    which are for operational health monitoring, NOT quality assessment.
    """

    def test_f1_only_ok(self):
        """Run with ok F1 only is ok."""
        f1_label, f2_label, run_label, reason = classify_run(
            f1_status="ok",
            f2_status=None,
            opportunity_count=10,
            valid_opportunity_count=10,
        )
        assert f1_label == "ok"
        assert f2_label is None
        assert run_label == "ok"

    def test_f1_ok_f2_ok(self):
        """Run with ok F1 and ok F2 is ok."""
        f1_label, f2_label, run_label, reason = classify_run(
            f1_status="ok",
            f2_status="ok",
            opportunity_count=10,
            valid_opportunity_count=10,
            package_count=1,
            variant_count=2,
        )
        assert f1_label == "ok"
        assert f2_label == "ok"
        assert run_label == "ok"

    def test_f1_ok_f2_degraded(self):
        """Run with ok F1 and degraded F2 is degraded."""
        f1_label, f2_label, run_label, reason = classify_run(
            f1_status="ok",
            f2_status="ok",
            opportunity_count=10,
            valid_opportunity_count=10,
            package_count=1,
            variant_count=1,  # Only 1 of 2 expected
        )
        assert f1_label == "ok"
        assert f2_label == "degraded"
        assert run_label == "degraded"

    def test_f1_degraded_f2_ok(self):
        """Run with degraded F1 and ok F2 is degraded."""
        f1_label, f2_label, run_label, reason = classify_run(
            f1_status="ok",
            f2_status="ok",
            opportunity_count=2,
            valid_opportunity_count=2,  # Low count
            package_count=1,
            variant_count=2,
        )
        assert f1_label == "degraded"
        assert f2_label == "ok"
        assert run_label == "degraded"

    def test_any_failed_makes_run_failed(self):
        """Run is failed if either F1 or F2 is failed."""
        # F1 failed
        _, _, run_label, _ = classify_run(
            f1_status="fail",
            f2_status="ok",
            opportunity_count=0,
            valid_opportunity_count=0,
            package_count=1,
            variant_count=2,
        )
        assert run_label == "failed"

        # F2 failed
        _, _, run_label, _ = classify_run(
            f1_status="ok",
            f2_status="ok",
            opportunity_count=10,
            valid_opportunity_count=10,
            package_count=0,  # No package
            variant_count=0,
        )
        assert run_label == "failed"


# =============================================================================
# HIGH-LEVEL LOGGING HELPERS TESTS
# =============================================================================


class TestLoggingHelpers:
    """Tests for high-level logging helper functions."""

    def test_log_run_start(self, temp_obs_dir):
        """log_run_start writes correct event."""
        run_id = uuid4()
        brand_id = uuid4()

        result = log_run_start(
            run_id=run_id,
            brand_id=brand_id,
            flow="F1_today",
            trigger_source="api",
        )

        assert result is True

        events = read_events(run_id, "run_start")
        assert len(events) == 1
        assert events[0]["brand_id"] == str(brand_id)
        assert events[0]["flow"] == "F1_today"

    def test_log_run_complete(self, temp_obs_dir):
        """log_run_complete writes correct event."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_complete(
            run_id=run_id,
            brand_id=brand_id,
            flow="F1_today",
            status="success",
            metrics={"count": 10},
        )

        events = read_events(run_id, "run_complete")
        assert len(events) == 1
        assert events[0]["status"] == "success"
        assert events[0]["metrics"]["count"] == 10

    def test_log_run_fail(self, temp_obs_dir):
        """log_run_fail writes correct event."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_fail(
            run_id=run_id,
            brand_id=brand_id,
            flow="F1_today",
            error="Something went wrong",
            error_type="GraphError",
        )

        events = read_events(run_id, "run_fail")
        assert len(events) == 1
        assert "Something went wrong" in events[0]["error"]
        assert events[0]["error_type"] == "GraphError"

    def test_log_llm_call(self, temp_obs_dir):
        """log_llm_call writes correct event."""
        run_id = uuid4()
        brand_id = uuid4()

        log_llm_call(
            run_id=run_id,
            brand_id=brand_id,
            flow="F1_synthesis",
            model="gpt-5-nano",
            role="fast",
            latency_ms=150,
            tokens_in=100,
            tokens_out=50,
            status="success",
            estimated_cost_usd=0.002,
        )

        events = read_events(run_id, "llm_call")
        assert len(events) == 1
        assert events[0]["model"] == "gpt-5-nano"
        assert events[0]["latency_ms"] == 150
        assert events[0]["estimated_cost_usd"] == 0.002

    def test_log_classification(self, temp_obs_dir):
        """log_classification writes correct event with obs_health labels."""
        run_id = uuid4()
        brand_id = uuid4()

        log_classification(
            run_id=run_id,
            brand_id=brand_id,
            f1_health="ok",
            f2_health="degraded",
            run_health="degraded",
            reason="f2:partial_coverage",
        )

        events = read_events(run_id, "classification")
        assert len(events) == 1
        assert events[0]["f1_health"] == "ok"
        assert events[0]["f2_health"] == "degraded"
        assert events[0]["run_health"] == "degraded"
        assert events[0]["obs_health"] == "degraded"


# =============================================================================
# LIST AND DETAIL TESTS
# =============================================================================


class TestListAndDetail:
    """Tests for list_runs and get_run_detail functions."""

    def test_list_runs_empty(self, temp_obs_dir):
        """list_runs returns empty list when no runs."""
        runs = list_runs()
        assert runs == []

    def test_list_runs_with_data(self, temp_obs_dir):
        """list_runs returns run summaries with obs_health."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_run_complete(run_id, brand_id, "F1_today", "success")
        # Use obs_health labels (ok/degraded/failed), NOT quality labels
        log_classification(run_id, brand_id, "ok", None, "ok", "healthy_count:8")

        runs = list_runs()

        assert len(runs) == 1
        assert runs[0]["run_id"] == str(run_id)
        assert runs[0]["status"] == "complete"
        assert runs[0]["obs_health"] == "ok"

    def test_list_runs_limit(self, temp_obs_dir):
        """list_runs respects limit."""
        for _ in range(5):
            run_id = uuid4()
            brand_id = uuid4()
            log_run_start(run_id, brand_id, "F1_today", "api")

        runs = list_runs(limit=3)
        assert len(runs) == 3

    def test_get_run_detail_exists(self, temp_obs_dir):
        """get_run_detail returns full run info."""
        run_id = uuid4()
        brand_id = uuid4()

        log_run_start(run_id, brand_id, "F1_today", "api")
        log_llm_call(
            run_id, brand_id, "F1_synthesis", "gpt-5", "heavy",
            100, 50, 25, "success"
        )
        log_llm_call(
            run_id, brand_id, "F1_scoring", "gpt-5-nano", "fast",
            50, 30, 10, "success"
        )
        log_run_complete(run_id, brand_id, "F1_today", "success")

        detail = get_run_detail(run_id)

        assert detail["exists"] is True
        assert "run_start" in detail["events"]
        assert "llm_call" in detail["events"]
        assert len(detail["events"]["llm_call"]) == 2
        assert detail["stats"]["llm_calls"] == 2
        assert detail["stats"]["total_latency_ms"] == 150

    def test_get_run_detail_not_exists(self, temp_obs_dir):
        """get_run_detail returns exists=False for missing run."""
        detail = get_run_detail(uuid4())
        assert detail["exists"] is False
