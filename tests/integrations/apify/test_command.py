"""
Tests for brandbrain_apify_explore management command.

Uses mocked Apify client returning canned dataset items.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from kairo.integrations.apify.models import ApifyRun, RawApifyItem
from kairo.integrations.apify.client import RunInfo


@pytest.fixture
def mock_apify_client():
    """Create a mock ApifyClient with successful run."""
    with patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient") as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client

        # start_actor_run returns initial RunInfo
        mock_client.start_actor_run.return_value = RunInfo(
            run_id="apify-run-123",
            actor_id="apify/instagram-scraper",
            status="RUNNING",
            dataset_id="dataset-456",
            started_at=datetime.now(timezone.utc),
            finished_at=None,
        )

        # poll_run returns completed RunInfo
        mock_client.poll_run.return_value = RunInfo(
            run_id="apify-run-123",
            actor_id="apify/instagram-scraper",
            status="SUCCEEDED",
            dataset_id="dataset-456",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        # fetch_dataset_items returns canned items
        mock_client.fetch_dataset_items.return_value = [
            {"id": "item1", "caption": "Hello world", "likesCount": 100},
            {"id": "item2", "caption": "Testing", "likesCount": 50},
            {"id": "item3", "caption": "Sample post", "likesCount": 200},
        ]

        yield mock_client


@pytest.mark.django_db
class TestBrandbrainApifyExploreCommand:
    """Tests for the management command."""

    def test_command_creates_apify_run(self, mock_apify_client, settings, tmp_path):
        """Command creates ApifyRun row."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        call_command(
            "brandbrain_apify_explore",
            actor_id="apify/instagram-scraper",
            input_json='{"username": ["wendys"]}',
            limit=3,
        )

        # Verify ApifyRun created
        assert ApifyRun.objects.count() == 1
        run = ApifyRun.objects.first()
        assert run.actor_id == "apify/instagram-scraper"
        assert run.apify_run_id == "apify-run-123"
        assert run.dataset_id == "dataset-456"
        assert run.status == "succeeded"
        assert run.item_count == 3

    def test_command_creates_raw_items(self, mock_apify_client, settings, tmp_path):
        """Command creates RawApifyItem rows."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        call_command(
            "brandbrain_apify_explore",
            actor_id="apify/instagram-scraper",
            input_json='{"username": ["wendys"]}',
            limit=3,
        )

        # Verify RawApifyItem created
        assert RawApifyItem.objects.count() == 3
        items = list(RawApifyItem.objects.order_by("item_index"))
        assert items[0].item_index == 0
        assert items[0].raw_json["caption"] == "Hello world"
        assert items[1].item_index == 1
        assert items[2].item_index == 2

    def test_command_saves_sample_files(self, mock_apify_client, settings, tmp_path):
        """Command saves sample JSON files under var/."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        call_command(
            "brandbrain_apify_explore",
            actor_id="apify/instagram-scraper",
            input_json='{"username": ["wendys"]}',
            limit=3,
            save_samples=2,  # Only save first 2
        )

        # Find the sample directory (actor_id "/" becomes "_")
        run = ApifyRun.objects.first()
        sample_dir = tmp_path / "var" / "apify_samples" / "apify_instagram-scraper" / str(run.id)
        assert sample_dir.exists()

        # Check sample files
        sample_files = list(sample_dir.glob("*.json"))
        assert len(sample_files) == 2

        # Verify content
        item_0 = json.loads((sample_dir / "item_0.json").read_text())
        assert item_0["caption"] == "Hello world"

    def test_command_requires_token(self, settings):
        """Command raises error if APIFY_TOKEN not set."""
        settings.APIFY_TOKEN = ""

        with pytest.raises(CommandError, match="APIFY_TOKEN not set"):
            call_command(
                "brandbrain_apify_explore",
                actor_id="test/actor",
                input_json="{}",
            )

    def test_command_limit_hard_cap(self, settings):
        """Command rejects --limit > 50."""
        settings.APIFY_TOKEN = "test-token"

        with pytest.raises(CommandError, match="cannot exceed 50"):
            call_command(
                "brandbrain_apify_explore",
                actor_id="test/actor",
                input_json="{}",
                limit=51,
            )

    def test_command_input_file(self, mock_apify_client, settings, tmp_path):
        """Command accepts --input-file."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        # Create input file
        input_file = tmp_path / "input.json"
        input_file.write_text('{"username": ["wendys"], "resultsLimit": 10}')

        call_command(
            "brandbrain_apify_explore",
            actor_id="apify/instagram-scraper",
            input_file=str(input_file),
        )

        # Verify input was passed
        call_args = mock_apify_client.start_actor_run.call_args
        assert call_args[0][1] == {"username": ["wendys"], "resultsLimit": 10}

    def test_command_invalid_json(self, settings):
        """Command raises error on invalid JSON."""
        settings.APIFY_TOKEN = "test-token"

        with pytest.raises(CommandError, match="Invalid JSON"):
            call_command(
                "brandbrain_apify_explore",
                actor_id="test/actor",
                input_json="not valid json",
            )

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_command_handles_failed_run(self, mock_class, settings, tmp_path):
        """Command handles failed actor run."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        mock_client.start_actor_run.return_value = RunInfo(
            run_id="apify-run-fail",
            actor_id="test/actor",
            status="RUNNING",
            dataset_id=None,
            started_at=datetime.now(timezone.utc),
            finished_at=None,
        )

        mock_client.poll_run.return_value = RunInfo(
            run_id="apify-run-fail",
            actor_id="test/actor",
            status="FAILED",
            dataset_id=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            error_message="Actor crashed",
        )

        call_command(
            "brandbrain_apify_explore",
            actor_id="test/actor",
            input_json="{}",
        )

        # Verify ApifyRun created with failed status
        run = ApifyRun.objects.first()
        assert run.status == "failed"
        assert run.error_summary == "Actor crashed"
        assert run.item_count == 0
        assert RawApifyItem.objects.count() == 0


@pytest.mark.django_db
class TestBrandbrainApifyExploreResumeMode:
    """Tests for resume mode with --existing-run-id."""

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_resume_with_polling(self, mock_class, settings, tmp_path):
        """Resume mode polls run until complete then fetches items."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        # poll_run returns completed RunInfo
        mock_client.poll_run.return_value = RunInfo(
            run_id="existing-run-789",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="dataset-abc",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        mock_client.fetch_dataset_items.return_value = [
            {"id": "resume1", "caption": "Resumed item"},
        ]

        call_command(
            "brandbrain_apify_explore",
            existing_run_id="existing-run-789",
            actor_id="apify~instagram-scraper",
            limit=10,
        )

        # Verify poll_run was called with the run_id
        mock_client.poll_run.assert_called_once()
        call_args = mock_client.poll_run.call_args
        assert call_args[0][0] == "existing-run-789"
        # Verify start_actor_run was NOT called
        mock_client.start_actor_run.assert_not_called()

        # Verify ApifyRun created
        assert ApifyRun.objects.count() == 1
        run = ApifyRun.objects.first()
        assert run.apify_run_id == "existing-run-789"
        assert run.status == "succeeded"

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_resume_with_dataset_id_skips_polling(self, mock_class, settings, tmp_path):
        """When --dataset-id provided, skip polling entirely."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        mock_client.fetch_dataset_items.return_value = [
            {"id": "direct1", "caption": "Direct fetch"},
        ]

        call_command(
            "brandbrain_apify_explore",
            existing_run_id="existing-run-xyz",
            dataset_id="known-dataset-id",
            actor_id="apify~instagram-scraper",
            limit=5,
        )

        # Verify poll_run was NOT called
        mock_client.poll_run.assert_not_called()
        # Verify fetch_dataset_items was called with provided dataset_id
        mock_client.fetch_dataset_items.assert_called_once()
        call_args = mock_client.fetch_dataset_items.call_args
        assert call_args[0][0] == "known-dataset-id"
        assert call_args[1]["limit"] == 5

        # Verify ApifyRun created with provided IDs
        run = ApifyRun.objects.first()
        assert run.apify_run_id == "existing-run-xyz"
        assert run.dataset_id == "known-dataset-id"

    def test_resume_rejects_input_flags(self, settings):
        """Resume mode rejects --input-json and --input-file."""
        settings.APIFY_TOKEN = "test-token"

        with pytest.raises(CommandError, match="not allowed with --existing-run-id"):
            call_command(
                "brandbrain_apify_explore",
                existing_run_id="some-run-id",
                input_json='{"username": ["test"]}',
            )

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_resume_works_without_actor_id(self, mock_class, settings, tmp_path):
        """Resume mode doesn't require --actor-id."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        mock_client.poll_run.return_value = RunInfo(
            run_id="no-actor-run",
            actor_id="",
            status="SUCCEEDED",
            dataset_id="ds-123",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        mock_client.fetch_dataset_items.return_value = []

        # Should not raise - actor_id is optional in resume mode
        call_command(
            "brandbrain_apify_explore",
            existing_run_id="no-actor-run",
            limit=5,
        )

        run = ApifyRun.objects.first()
        assert run.actor_id == ""

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_resume_failed_run_stores_failure_and_raises(self, mock_class, settings, tmp_path):
        """Resume mode with failed run stores failure info then raises error."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        mock_client.poll_run.return_value = RunInfo(
            run_id="failed-resume",
            actor_id="test/actor",
            status="FAILED",
            dataset_id=None,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            error_message="Run failed",
        )

        # Should raise CommandError for failed run
        with pytest.raises(CommandError, match="Run failed"):
            call_command(
                "brandbrain_apify_explore",
                existing_run_id="failed-resume",
                actor_id="test/actor",
            )

        # But ApifyRun should still be stored with failure info
        run = ApifyRun.objects.first()
        assert run is not None
        assert run.status == "failed"
        assert run.error_summary == "Run failed"


@pytest.mark.django_db
class TestBrandbrainApifyExploreIdempotency:
    """Tests for idempotent behavior on re-runs."""

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_no_duplicate_items_on_rerun(self, mock_class, settings, tmp_path):
        """Running twice with same existing-run-id creates no duplicate items."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        mock_client.poll_run.return_value = RunInfo(
            run_id="idempotent-run",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="ds-idem",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        mock_client.fetch_dataset_items.return_value = [
            {"id": "idem1", "caption": "First"},
            {"id": "idem2", "caption": "Second"},
        ]

        # Run once
        call_command(
            "brandbrain_apify_explore",
            existing_run_id="idempotent-run",
            actor_id="apify~instagram-scraper",
        )

        assert ApifyRun.objects.count() == 1
        assert RawApifyItem.objects.count() == 2

        # Run again with same existing-run-id
        call_command(
            "brandbrain_apify_explore",
            existing_run_id="idempotent-run",
            actor_id="apify~instagram-scraper",
        )

        # Should still have only 1 ApifyRun and 2 items
        assert ApifyRun.objects.count() == 1
        assert RawApifyItem.objects.count() == 2

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_upsert_updates_existing_run(self, mock_class, settings, tmp_path):
        """Re-running updates existing ApifyRun rather than creating duplicate."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        # First run - SUCCEEDED with initial data
        mock_client.poll_run.return_value = RunInfo(
            run_id="upsert-run",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="ds-initial",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        mock_client.fetch_dataset_items.return_value = [
            {"id": "initial1", "caption": "Initial item"},
        ]

        call_command(
            "brandbrain_apify_explore",
            existing_run_id="upsert-run",
            actor_id="apify~instagram-scraper",
        )

        run = ApifyRun.objects.first()
        original_id = run.id
        original_dataset_id = run.dataset_id
        assert run.status == "succeeded"
        assert run.dataset_id == "ds-initial"

        # Second run - same run_id but we update dataset_id (simulating re-fetch)
        mock_client.poll_run.return_value = RunInfo(
            run_id="upsert-run",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="ds-updated",  # Different dataset ID
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        mock_client.fetch_dataset_items.return_value = [
            {"id": "updated1", "caption": "Updated item"},
        ]

        call_command(
            "brandbrain_apify_explore",
            existing_run_id="upsert-run",
            actor_id="apify~instagram-scraper",
        )

        # Should still have only 1 ApifyRun (same PK)
        assert ApifyRun.objects.count() == 1
        run = ApifyRun.objects.first()
        assert run.id == original_id
        assert run.status == "succeeded"
        # Dataset ID should be updated
        assert run.dataset_id == "ds-updated"
        assert run.dataset_id != original_dataset_id

    @patch("kairo.integrations.apify.management.commands.brandbrain_apify_explore.ApifyClient")
    def test_sample_files_overwritten(self, mock_class, settings, tmp_path):
        """Sample files are overwritten on re-run (not duplicated)."""
        settings.APIFY_TOKEN = "test-token"
        settings.BASE_DIR = tmp_path

        mock_client = MagicMock()
        mock_class.return_value = mock_client

        mock_client.poll_run.return_value = RunInfo(
            run_id="sample-run",
            actor_id="apify~instagram-scraper",
            status="SUCCEEDED",
            dataset_id="ds-sample",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

        # First run with initial data
        mock_client.fetch_dataset_items.return_value = [
            {"id": "v1", "caption": "Version 1"},
        ]

        call_command(
            "brandbrain_apify_explore",
            existing_run_id="sample-run",
            actor_id="apify~instagram-scraper",
            save_samples=1,
        )

        run = ApifyRun.objects.first()
        sample_dir = tmp_path / "var" / "apify_samples" / "apify_instagram-scraper" / str(run.id)
        sample_file = sample_dir / "item_0.json"

        assert sample_file.exists()
        content_v1 = json.loads(sample_file.read_text())
        assert content_v1["caption"] == "Version 1"

        # Second run with updated data
        mock_client.fetch_dataset_items.return_value = [
            {"id": "v2", "caption": "Version 2"},
        ]

        call_command(
            "brandbrain_apify_explore",
            existing_run_id="sample-run",
            actor_id="apify~instagram-scraper",
            save_samples=1,
        )

        # Sample file should be overwritten with new content
        content_v2 = json.loads(sample_file.read_text())
        assert content_v2["caption"] == "Version 2"

        # Should only have 1 sample file, not 2
        sample_files = list(sample_dir.glob("*.json"))
        assert len(sample_files) == 1
