"""
Unit tests for caps configuration.

PR-2: Tests for caps.py.
All tests marked @pytest.mark.unit - no DB required.
"""

import os

import pytest

from kairo.brandbrain.caps import (
    DEFAULT_CAPS,
    cap_for,
    global_max_normalized_items,
    apify_run_ttl_hours,
    clear_caps_cache,
)


@pytest.fixture(autouse=True)
def clear_cache_and_env(monkeypatch):
    """Clear caps cache before each test and clean env vars."""
    clear_caps_cache()
    # Remove any existing env vars that might interfere
    for key in [
        "BRANDBRAIN_CAP_IG_POSTS",
        "BRANDBRAIN_CAP_IG_REELS",
        "BRANDBRAIN_CAP_LI",
        "BRANDBRAIN_CAP_TT",
        "BRANDBRAIN_CAP_YT",
        "BRANDBRAIN_CAP_WEB",
        "BRANDBRAIN_MAX_NORMALIZED_ITEMS",
        "BRANDBRAIN_APIFY_RUN_TTL_HOURS",
    ]:
        monkeypatch.delenv(key, raising=False)
    yield
    clear_caps_cache()


@pytest.mark.unit
class TestCapFor:
    """Tests for cap_for() function."""

    def test_returns_default_for_instagram_posts(self):
        """Should return default cap for instagram.posts."""
        assert cap_for("instagram", "posts") == 8

    def test_returns_default_for_instagram_reels(self):
        """Should return default cap for instagram.reels."""
        assert cap_for("instagram", "reels") == 6

    def test_returns_default_for_linkedin_company_posts(self):
        """Should return default cap for linkedin.company_posts."""
        assert cap_for("linkedin", "company_posts") == 6

    def test_returns_default_for_linkedin_profile_posts(self):
        """Should return default cap for linkedin.profile_posts."""
        assert cap_for("linkedin", "profile_posts") == 6

    def test_returns_default_for_tiktok_profile_videos(self):
        """Should return default cap for tiktok.profile_videos."""
        assert cap_for("tiktok", "profile_videos") == 6

    def test_returns_default_for_youtube_channel_videos(self):
        """Should return default cap for youtube.channel_videos."""
        assert cap_for("youtube", "channel_videos") == 6

    def test_returns_default_for_web_crawl_pages(self):
        """Should return default cap for web.crawl_pages."""
        assert cap_for("web", "crawl_pages") == 3

    def test_returns_conservative_default_for_unknown(self):
        """Should return conservative default (6) for unknown platform/capability."""
        assert cap_for("unknown_platform", "unknown_capability") == 6

    def test_env_override_instagram_posts(self, monkeypatch):
        """Should respect BRANDBRAIN_CAP_IG_POSTS env var."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_IG_POSTS", "12")
        assert cap_for("instagram", "posts") == 12

    def test_env_override_instagram_reels(self, monkeypatch):
        """Should respect BRANDBRAIN_CAP_IG_REELS env var."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_IG_REELS", "10")
        assert cap_for("instagram", "reels") == 10

    def test_env_override_linkedin(self, monkeypatch):
        """Should respect BRANDBRAIN_CAP_LI env var for both linkedin capabilities."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_LI", "15")
        assert cap_for("linkedin", "company_posts") == 15
        assert cap_for("linkedin", "profile_posts") == 15

    def test_env_override_tiktok(self, monkeypatch):
        """Should respect BRANDBRAIN_CAP_TT env var."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_TT", "20")
        assert cap_for("tiktok", "profile_videos") == 20

    def test_env_override_youtube(self, monkeypatch):
        """Should respect BRANDBRAIN_CAP_YT env var."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_YT", "8")
        assert cap_for("youtube", "channel_videos") == 8

    def test_env_override_web(self, monkeypatch):
        """Should respect BRANDBRAIN_CAP_WEB env var."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_WEB", "5")
        assert cap_for("web", "crawl_pages") == 5

    def test_invalid_env_value_uses_default(self, monkeypatch):
        """Should use default when env var is not a valid integer."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_IG_POSTS", "invalid")
        assert cap_for("instagram", "posts") == 8

    def test_zero_env_value_uses_default(self, monkeypatch):
        """Should use default when env var is zero (caps must be positive)."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_IG_POSTS", "0")
        assert cap_for("instagram", "posts") == 8

    def test_negative_env_value_uses_default(self, monkeypatch):
        """Should use default when env var is negative."""
        clear_caps_cache()
        monkeypatch.setenv("BRANDBRAIN_CAP_IG_POSTS", "-5")
        assert cap_for("instagram", "posts") == 8


@pytest.mark.unit
class TestGlobalMaxNormalizedItems:
    """Tests for global_max_normalized_items() function."""

    def test_returns_default(self):
        """Should return default of 40."""
        assert global_max_normalized_items() == 40

    def test_env_override(self, monkeypatch):
        """Should respect BRANDBRAIN_MAX_NORMALIZED_ITEMS env var."""
        monkeypatch.setenv("BRANDBRAIN_MAX_NORMALIZED_ITEMS", "100")
        assert global_max_normalized_items() == 100

    def test_invalid_env_uses_default(self, monkeypatch):
        """Should use default when env var is invalid."""
        monkeypatch.setenv("BRANDBRAIN_MAX_NORMALIZED_ITEMS", "not_a_number")
        assert global_max_normalized_items() == 40


@pytest.mark.unit
class TestApifyRunTtlHours:
    """Tests for apify_run_ttl_hours() function."""

    def test_returns_default(self):
        """Should return default of 24 hours."""
        assert apify_run_ttl_hours() == 24

    def test_env_override(self, monkeypatch):
        """Should respect BRANDBRAIN_APIFY_RUN_TTL_HOURS env var."""
        monkeypatch.setenv("BRANDBRAIN_APIFY_RUN_TTL_HOURS", "48")
        assert apify_run_ttl_hours() == 48

    def test_invalid_env_uses_default(self, monkeypatch):
        """Should use default when env var is invalid."""
        monkeypatch.setenv("BRANDBRAIN_APIFY_RUN_TTL_HOURS", "invalid")
        assert apify_run_ttl_hours() == 24


@pytest.mark.unit
class TestDefaultCapsMatch:
    """Verify DEFAULT_CAPS matches spec Section 3.1."""

    def test_all_expected_keys_present(self):
        """All platform/capability combinations from spec should be present."""
        expected_keys = {
            ("instagram", "posts"),
            ("instagram", "reels"),
            ("linkedin", "company_posts"),
            ("linkedin", "profile_posts"),
            ("tiktok", "profile_videos"),
            ("youtube", "channel_videos"),
            ("web", "crawl_pages"),
        }
        assert set(DEFAULT_CAPS.keys()) == expected_keys

    def test_default_values_match_spec(self):
        """Default values should match spec Section 3.1."""
        assert DEFAULT_CAPS[("instagram", "posts")] == 8
        assert DEFAULT_CAPS[("instagram", "reels")] == 6
        assert DEFAULT_CAPS[("linkedin", "company_posts")] == 6
        assert DEFAULT_CAPS[("linkedin", "profile_posts")] == 6
        assert DEFAULT_CAPS[("tiktok", "profile_videos")] == 6
        assert DEFAULT_CAPS[("youtube", "channel_videos")] == 6
        assert DEFAULT_CAPS[("web", "crawl_pages")] == 3
