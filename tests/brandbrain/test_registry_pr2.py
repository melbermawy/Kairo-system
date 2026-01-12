"""
Unit tests for actor registry.

PR-2: Tests for actors/registry.py.
All tests marked @pytest.mark.unit - no DB required.
"""

import pytest

from kairo.brandbrain.actors.registry import (
    ACTOR_REGISTRY,
    ActorSpec,
    get_actor_spec,
    is_capability_enabled,
)
from kairo.brandbrain.caps import clear_caps_cache


@pytest.fixture(autouse=True)
def clear_cache_and_env(monkeypatch):
    """Clean up environment variables."""
    clear_caps_cache()
    monkeypatch.delenv("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", raising=False)
    yield
    clear_caps_cache()


@pytest.mark.unit
class TestActorRegistry:
    """Tests for ACTOR_REGISTRY structure."""

    def test_has_all_seven_entries(self):
        """Registry should have all 7 platform/capability combinations."""
        expected_keys = {
            ("instagram", "posts"),
            ("instagram", "reels"),
            ("linkedin", "company_posts"),
            ("linkedin", "profile_posts"),
            ("tiktok", "profile_videos"),
            ("youtube", "channel_videos"),
            ("web", "crawl_pages"),
        }
        assert set(ACTOR_REGISTRY.keys()) == expected_keys

    def test_all_entries_are_actor_specs(self):
        """All registry entries should be ActorSpec instances."""
        for spec in ACTOR_REGISTRY.values():
            assert isinstance(spec, ActorSpec)

    def test_instagram_posts_spec(self):
        """instagram.posts should use apify~instagram-scraper."""
        spec = ACTOR_REGISTRY[("instagram", "posts")]
        assert spec.platform == "instagram"
        assert spec.capability == "posts"
        assert spec.actor_id == "apify~instagram-scraper"
        assert spec.cap_fields == ["resultsLimit"]
        assert spec.validated is True
        assert spec.feature_flag is None

    def test_instagram_reels_spec(self):
        """instagram.reels should use apify~instagram-reel-scraper."""
        spec = ACTOR_REGISTRY[("instagram", "reels")]
        assert spec.platform == "instagram"
        assert spec.capability == "reels"
        assert spec.actor_id == "apify~instagram-reel-scraper"
        assert spec.cap_fields == ["resultsLimit"]
        assert spec.validated is True
        assert spec.feature_flag is None

    def test_linkedin_company_posts_spec(self):
        """linkedin.company_posts should use apimaestro~linkedin-company-posts."""
        spec = ACTOR_REGISTRY[("linkedin", "company_posts")]
        assert spec.platform == "linkedin"
        assert spec.capability == "company_posts"
        assert spec.actor_id == "apimaestro~linkedin-company-posts"
        assert spec.cap_fields == ["limit"]
        assert spec.validated is True
        assert spec.feature_flag is None

    def test_linkedin_profile_posts_spec(self):
        """linkedin.profile_posts should be behind feature flag."""
        spec = ACTOR_REGISTRY[("linkedin", "profile_posts")]
        assert spec.platform == "linkedin"
        assert spec.capability == "profile_posts"
        assert spec.actor_id == "apimaestro~linkedin-profile-posts"
        assert spec.cap_fields == ["limit"]
        assert spec.validated is False  # UNVALIDATED
        assert spec.feature_flag == "BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS"

    def test_tiktok_profile_videos_spec(self):
        """tiktok.profile_videos should use clockworks~tiktok-scraper."""
        spec = ACTOR_REGISTRY[("tiktok", "profile_videos")]
        assert spec.platform == "tiktok"
        assert spec.capability == "profile_videos"
        assert spec.actor_id == "clockworks~tiktok-scraper"
        assert spec.cap_fields == ["resultsPerPage"]
        assert spec.validated is True
        assert spec.feature_flag is None

    def test_youtube_channel_videos_spec(self):
        """youtube.channel_videos should use streamers~youtube-scraper."""
        spec = ACTOR_REGISTRY[("youtube", "channel_videos")]
        assert spec.platform == "youtube"
        assert spec.capability == "channel_videos"
        assert spec.actor_id == "streamers~youtube-scraper"
        assert spec.cap_fields == ["maxResults"]
        assert spec.validated is True
        assert spec.feature_flag is None

    def test_web_crawl_pages_spec(self):
        """web.crawl_pages should use apify~website-content-crawler."""
        spec = ACTOR_REGISTRY[("web", "crawl_pages")]
        assert spec.platform == "web"
        assert spec.capability == "crawl_pages"
        assert spec.actor_id == "apify~website-content-crawler"
        assert spec.cap_fields == ["maxCrawlPages"]
        assert spec.validated is True
        assert spec.feature_flag is None

    def test_all_specs_have_build_input_callable(self):
        """All specs should have a callable build_input."""
        for spec in ACTOR_REGISTRY.values():
            assert callable(spec.build_input)


@pytest.mark.unit
class TestGetActorSpec:
    """Tests for get_actor_spec() function."""

    def test_returns_spec_for_validated_actor(self):
        """Should return ActorSpec for validated actors."""
        spec = get_actor_spec("instagram", "posts")
        assert spec is not None
        assert spec.actor_id == "apify~instagram-scraper"

    def test_returns_none_for_unknown_actor(self):
        """Should return None for unknown platform/capability."""
        spec = get_actor_spec("unknown", "capability")
        assert spec is None

    def test_returns_none_for_feature_flagged_actor_when_disabled(self):
        """linkedin.profile_posts should return None when feature flag is off."""
        spec = get_actor_spec("linkedin", "profile_posts")
        assert spec is None

    def test_returns_spec_for_feature_flagged_actor_when_enabled(self, monkeypatch):
        """linkedin.profile_posts should return spec when feature flag is on."""
        monkeypatch.setenv("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", "true")
        spec = get_actor_spec("linkedin", "profile_posts")
        assert spec is not None
        assert spec.actor_id == "apimaestro~linkedin-profile-posts"

    def test_feature_flag_accepts_various_truthy_values(self, monkeypatch):
        """Feature flag should accept various truthy values."""
        for value in ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"]:
            monkeypatch.setenv("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", value)
            spec = get_actor_spec("linkedin", "profile_posts")
            assert spec is not None, f"Should be enabled for '{value}'"


@pytest.mark.unit
class TestIsCapabilityEnabled:
    """Tests for is_capability_enabled() function."""

    def test_validated_actors_always_enabled(self):
        """Validated actors should always be enabled."""
        assert is_capability_enabled("instagram", "posts") is True
        assert is_capability_enabled("instagram", "reels") is True
        assert is_capability_enabled("linkedin", "company_posts") is True
        assert is_capability_enabled("tiktok", "profile_videos") is True
        assert is_capability_enabled("youtube", "channel_videos") is True
        assert is_capability_enabled("web", "crawl_pages") is True

    def test_unknown_capability_not_enabled(self):
        """Unknown capabilities should not be enabled."""
        assert is_capability_enabled("unknown", "capability") is False

    def test_linkedin_profile_posts_disabled_by_default(self):
        """linkedin.profile_posts should be disabled by default."""
        assert is_capability_enabled("linkedin", "profile_posts") is False

    def test_linkedin_profile_posts_enabled_with_flag(self, monkeypatch):
        """linkedin.profile_posts should be enabled when flag is set."""
        monkeypatch.setenv("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", "true")
        assert is_capability_enabled("linkedin", "profile_posts") is True

    def test_feature_flag_rejects_falsy_values(self, monkeypatch):
        """Feature flag should remain disabled for falsy values."""
        for value in ["false", "False", "0", "no", "off", "", "anything_else"]:
            monkeypatch.setenv("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", value)
            assert is_capability_enabled("linkedin", "profile_posts") is False, \
                f"Should be disabled for '{value}'"
