"""
Tests for the Apify sample loader helper.

PR-0: Verify sample loader behavior and path safety.

All tests here are marked @pytest.mark.unit for fast CI runs.
"""

import pytest

from tests.helpers.apify_samples import (
    InvalidPathError,
    SampleNotFoundError,
    list_sample_dirs,
    list_run_dirs,
    load_sample,
    get_sample_path,
    SAMPLES_ROOT,
)


@pytest.mark.unit
class TestListSampleDirs:
    """Tests for list_sample_dirs()."""

    def test_returns_list_of_directories(self):
        """Should return a list of actor directory names."""
        dirs = list_sample_dirs()

        assert isinstance(dirs, list)
        assert len(dirs) > 0, "Expected at least one sample directory"

    def test_returns_sorted_list(self):
        """Should return directories in sorted order."""
        dirs = list_sample_dirs()

        assert dirs == sorted(dirs)

    def test_contains_known_actors(self):
        """Should contain known actor directories from the spec."""
        dirs = list_sample_dirs()

        # At minimum, we expect these actors to exist per the spec validation
        expected_actors = [
            "apify_instagram-scraper",
            "apify_instagram-reel-scraper",
            "apimaestro_linkedin-company-posts",
            "clockworks_tiktok-scraper",
            "streamers_youtube-scraper",
            "apify_website-content-crawler",
        ]

        for actor in expected_actors:
            assert actor in dirs, f"Expected actor '{actor}' not found in samples"


@pytest.mark.unit
class TestListRunDirs:
    """Tests for list_run_dirs()."""

    def test_returns_uuid_directories(self):
        """Should return run UUIDs for a valid actor."""
        # Use a known actor
        runs = list_run_dirs("apify_instagram-scraper")

        assert isinstance(runs, list)
        assert len(runs) > 0, "Expected at least one run directory"

        # Verify UUIDs are valid format
        import re
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        for run_uuid in runs:
            assert uuid_pattern.match(run_uuid), f"Invalid UUID format: {run_uuid}"

    def test_raises_on_invalid_actor(self):
        """Should raise InvalidPathError for invalid actor names."""
        with pytest.raises(InvalidPathError):
            list_run_dirs("../../../etc/passwd")

    def test_raises_on_nonexistent_actor(self):
        """Should raise SampleNotFoundError for nonexistent actors."""
        with pytest.raises(SampleNotFoundError):
            list_run_dirs("nonexistent_actor_12345")


@pytest.mark.unit
class TestLoadSample:
    """Tests for load_sample()."""

    def test_loads_instagram_sample(self):
        """Should load an Instagram post sample correctly."""
        sample = load_sample("apify_instagram-scraper", item_index=0)

        assert isinstance(sample, dict)
        # Instagram samples should have these fields per Appendix B1
        assert "id" in sample
        assert "url" in sample
        assert "ownerUsername" in sample

    def test_loads_different_item_indices(self):
        """Should load different items by index."""
        sample_0 = load_sample("apify_instagram-scraper", item_index=0)
        sample_1 = load_sample("apify_instagram-scraper", item_index=1)

        # Different items should have different IDs
        assert sample_0["id"] != sample_1["id"]

    def test_raises_on_negative_index(self):
        """Should raise ValueError for negative item indices."""
        with pytest.raises(ValueError, match="non-negative"):
            load_sample("apify_instagram-scraper", item_index=-1)

    def test_raises_on_path_traversal(self):
        """Should raise InvalidPathError for path traversal attempts."""
        with pytest.raises(InvalidPathError):
            load_sample("../secret", item_index=0)

        with pytest.raises(InvalidPathError):
            load_sample("actor/../../../etc/passwd", item_index=0)

    def test_raises_on_nonexistent_item(self):
        """Should raise SampleNotFoundError for nonexistent item indices."""
        with pytest.raises(SampleNotFoundError):
            load_sample("apify_instagram-scraper", item_index=9999)

    def test_loads_with_specific_run_uuid(self):
        """Should load from a specific run UUID when provided."""
        # Get the first run UUID
        runs = list_run_dirs("apify_instagram-scraper")
        assert len(runs) > 0

        # Load with explicit run UUID
        sample = load_sample(
            "apify_instagram-scraper",
            item_index=0,
            run_uuid=runs[0],
        )

        assert isinstance(sample, dict)
        assert "id" in sample


@pytest.mark.unit
class TestGetSamplePath:
    """Tests for get_sample_path()."""

    def test_returns_valid_path(self):
        """Should return a valid Path object."""
        path = get_sample_path("apify_instagram-scraper", item_index=0)

        assert path.exists()
        assert path.suffix == ".json"
        assert "item_0.json" in str(path)

    def test_path_is_within_samples_root(self):
        """Should return paths within the samples root (security check)."""
        path = get_sample_path("apify_instagram-scraper", item_index=0)

        # Resolve both to handle symlinks
        resolved_path = path.resolve()
        resolved_root = SAMPLES_ROOT.resolve()

        # Path should be a child of SAMPLES_ROOT
        assert str(resolved_path).startswith(str(resolved_root))


@pytest.mark.unit
class TestPathSafety:
    """Security-focused tests for path handling."""

    def test_empty_actor_name_rejected(self):
        """Should reject empty actor names."""
        with pytest.raises(InvalidPathError):
            load_sample("", item_index=0)

    def test_dot_dot_in_actor_rejected(self):
        """Should reject '..' sequences in actor names."""
        with pytest.raises(InvalidPathError):
            load_sample("actor..name", item_index=0)

    def test_slash_in_actor_rejected(self):
        """Should reject forward slashes in actor names."""
        with pytest.raises(InvalidPathError):
            load_sample("actor/name", item_index=0)

    def test_backslash_in_actor_rejected(self):
        """Should reject backslashes in actor names."""
        with pytest.raises(InvalidPathError):
            load_sample("actor\\name", item_index=0)
