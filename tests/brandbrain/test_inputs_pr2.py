"""
Unit tests for actor input builders.

PR-2: Tests for actors/inputs.py.
All tests marked @pytest.mark.unit - no DB required.

These tests verify that input builders produce output matching Appendix C templates.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from kairo.brandbrain.actors.inputs import (
    build_instagram_posts_input,
    build_instagram_reels_input,
    build_linkedin_company_posts_input,
    build_linkedin_profile_posts_input,
    build_tiktok_profile_input,
    build_youtube_channel_input,
    build_web_crawl_input,
)


@dataclass
class MockSourceConnection:
    """Mock SourceConnection for testing input builders."""

    identifier: str
    settings_json: dict[str, Any] | None = None

    def __post_init__(self):
        if self.settings_json is None:
            self.settings_json = {}


@pytest.mark.unit
class TestBuildInstagramPostsInput:
    """Tests for build_instagram_posts_input() - Appendix C1."""

    def test_basic_structure(self):
        """Should match Appendix C1 template structure."""
        source = MockSourceConnection(identifier="https://www.instagram.com/nogood.io/")
        result = build_instagram_posts_input(source, cap=8)

        assert result == {
            "directUrls": ["https://www.instagram.com/nogood.io/"],
            "resultsType": "posts",
            "resultsLimit": 8,
            "addParentData": False,
        }

    def test_respects_cap_value(self):
        """Should use the provided cap value."""
        source = MockSourceConnection(identifier="https://www.instagram.com/handle/")
        result = build_instagram_posts_input(source, cap=12)
        assert result["resultsLimit"] == 12

    def test_identifier_is_used_as_direct_url(self):
        """Identifier should be placed in directUrls array."""
        source = MockSourceConnection(identifier="https://www.instagram.com/test_account/")
        result = build_instagram_posts_input(source, cap=5)
        assert result["directUrls"] == ["https://www.instagram.com/test_account/"]


@pytest.mark.unit
class TestBuildInstagramReelsInput:
    """Tests for build_instagram_reels_input() - Appendix C2."""

    def test_basic_structure(self):
        """Should match Appendix C2 template structure."""
        source = MockSourceConnection(identifier="https://www.instagram.com/nogood.io/")
        result = build_instagram_reels_input(source, cap=6)

        assert result == {
            "username": ["https://www.instagram.com/nogood.io/"],
            "resultsLimit": 6,
            "includeTranscript": True,  # CRITICAL
            "includeSharesCount": False,
            "includeDownloadedVideo": False,
            "skipPinnedPosts": True,
        }

    def test_include_transcript_is_always_true(self):
        """includeTranscript must be True for voice evidence."""
        source = MockSourceConnection(identifier="handle")
        result = build_instagram_reels_input(source, cap=10)
        assert result["includeTranscript"] is True

    def test_respects_cap_value(self):
        """Should use the provided cap value."""
        source = MockSourceConnection(identifier="handle")
        result = build_instagram_reels_input(source, cap=15)
        assert result["resultsLimit"] == 15


@pytest.mark.unit
class TestBuildLinkedinCompanyPostsInput:
    """Tests for build_linkedin_company_posts_input() - Appendix C3."""

    def test_basic_structure(self):
        """Should match Appendix C3 template structure."""
        source = MockSourceConnection(identifier="nogood")  # Already normalized to slug
        result = build_linkedin_company_posts_input(source, cap=6)

        assert result == {
            "sort": "recent",
            "limit": 6,
            "company_name": "nogood",
        }

    def test_respects_cap_value(self):
        """Should use the provided cap value."""
        source = MockSourceConnection(identifier="acme-corp")
        result = build_linkedin_company_posts_input(source, cap=10)
        assert result["limit"] == 10

    def test_uses_identifier_as_company_name(self):
        """Identifier should be used as company_name (already normalized)."""
        source = MockSourceConnection(identifier="my-company-slug")
        result = build_linkedin_company_posts_input(source, cap=6)
        assert result["company_name"] == "my-company-slug"


@pytest.mark.unit
class TestBuildLinkedinProfilePostsInput:
    """Tests for build_linkedin_profile_posts_input() - Appendix C4 (UNVALIDATED)."""

    def test_basic_structure(self):
        """Should match Appendix C4 assumed template structure."""
        source = MockSourceConnection(identifier="https://www.linkedin.com/in/username/")
        result = build_linkedin_profile_posts_input(source, cap=6)

        assert result == {
            "sort": "recent",
            "limit": 6,
            "profile_url": "https://www.linkedin.com/in/username/",
        }

    def test_respects_cap_value(self):
        """Should use the provided cap value."""
        source = MockSourceConnection(identifier="https://www.linkedin.com/in/test/")
        result = build_linkedin_profile_posts_input(source, cap=8)
        assert result["limit"] == 8


@pytest.mark.unit
class TestBuildTiktokProfileInput:
    """Tests for build_tiktok_profile_input() - Appendix C5."""

    def test_basic_structure(self):
        """Should match Appendix C5 template structure."""
        source = MockSourceConnection(identifier="nogood.io")  # Already normalized (no @)
        result = build_tiktok_profile_input(source, cap=6)

        assert result == {
            "profiles": ["nogood.io"],
            "profileSorting": "latest",
            "resultsPerPage": 6,
            "excludePinnedPosts": True,
            "profileScrapeSections": ["videos"],
        }

    def test_strips_at_prefix(self):
        """Should strip @ prefix from handle."""
        source = MockSourceConnection(identifier="@testhandle")
        result = build_tiktok_profile_input(source, cap=6)
        assert result["profiles"] == ["testhandle"]

    def test_respects_cap_value(self):
        """Should use the provided cap value."""
        source = MockSourceConnection(identifier="handle")
        result = build_tiktok_profile_input(source, cap=10)
        assert result["resultsPerPage"] == 10

    def test_handles_already_clean_identifier(self):
        """Should handle identifiers that don't have @ prefix."""
        source = MockSourceConnection(identifier="cleanhandle")
        result = build_tiktok_profile_input(source, cap=6)
        assert result["profiles"] == ["cleanhandle"]


@pytest.mark.unit
class TestBuildYoutubeChannelInput:
    """Tests for build_youtube_channel_input() - Appendix C6."""

    def test_basic_structure(self):
        """Should match Appendix C6 template structure."""
        source = MockSourceConnection(
            identifier="https://www.youtube.com/channel/UCZ4qs1SgV7wTkM2VjHByuRQ"
        )
        result = build_youtube_channel_input(source, cap=6)

        assert result == {
            "startUrls": [{"url": "https://www.youtube.com/channel/UCZ4qs1SgV7wTkM2VjHByuRQ"}],
            "maxResults": 6,
            "maxResultsShorts": 0,
            "maxResultsStreams": 0,
        }

    def test_respects_cap_value(self):
        """Should use the provided cap value."""
        source = MockSourceConnection(identifier="https://www.youtube.com/channel/xyz")
        result = build_youtube_channel_input(source, cap=12)
        assert result["maxResults"] == 12

    def test_shorts_and_streams_excluded(self):
        """Shorts and streams should be excluded (set to 0)."""
        source = MockSourceConnection(identifier="https://www.youtube.com/channel/xyz")
        result = build_youtube_channel_input(source, cap=6)
        assert result["maxResultsShorts"] == 0
        assert result["maxResultsStreams"] == 0


@pytest.mark.unit
class TestBuildWebCrawlInput:
    """Tests for build_web_crawl_input() - Appendix C7."""

    def test_basic_structure_homepage_only(self):
        """Should match Appendix C7 template with homepage only."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={},
        )
        result = build_web_crawl_input(source, cap=3)

        assert result == {
            "startUrls": [{"url": "https://example.com"}],
            "maxCrawlDepth": 1,
            "maxCrawlPages": 1,  # min(3, 1) = 1
        }

    def test_includes_extra_start_urls(self):
        """Should include extra_start_urls from settings_json."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={
                "extra_start_urls": [
                    "https://example.com/about",
                    "https://example.com/contact",
                ],
            },
        )
        result = build_web_crawl_input(source, cap=3)

        assert result == {
            "startUrls": [
                {"url": "https://example.com"},
                {"url": "https://example.com/about"},
                {"url": "https://example.com/contact"},
            ],
            "maxCrawlDepth": 1,
            "maxCrawlPages": 3,  # min(3, 3) = 3
        }

    def test_clamps_extra_urls_to_two(self):
        """Should only include up to 2 extra URLs."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={
                "extra_start_urls": [
                    "https://example.com/page1",
                    "https://example.com/page2",
                    "https://example.com/page3",  # Should be dropped
                    "https://example.com/page4",  # Should be dropped
                ],
            },
        )
        result = build_web_crawl_input(source, cap=5)

        # Should only have homepage + 2 extra = 3 total
        assert len(result["startUrls"]) == 3
        assert result["startUrls"][0]["url"] == "https://example.com"
        assert result["startUrls"][1]["url"] == "https://example.com/page1"
        assert result["startUrls"][2]["url"] == "https://example.com/page2"

    def test_filters_empty_and_non_string_urls(self):
        """Should filter out empty strings and non-string values."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={
                "extra_start_urls": [
                    "",  # Empty string - should be filtered
                    "  ",  # Whitespace only - should be filtered
                    None,  # Non-string - should be filtered (though type hint says list)
                    123,  # Non-string - should be filtered
                    "https://example.com/valid",  # Valid
                ],
            },
        )
        result = build_web_crawl_input(source, cap=3)

        # Should only have homepage + 1 valid extra
        assert len(result["startUrls"]) == 2
        assert result["startUrls"][1]["url"] == "https://example.com/valid"

    def test_max_crawl_pages_capped_to_url_count(self):
        """maxCrawlPages should be min(cap, len(startUrls))."""
        # Cap is 10, but only 2 URLs
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={
                "extra_start_urls": ["https://example.com/about"],
            },
        )
        result = build_web_crawl_input(source, cap=10)
        assert result["maxCrawlPages"] == 2  # min(10, 2) = 2

    def test_max_crawl_pages_uses_cap_when_urls_exceed_cap(self):
        """maxCrawlPages should use cap when there are more URLs than cap."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={
                "extra_start_urls": [
                    "https://example.com/about",
                    "https://example.com/contact",
                ],
            },
        )
        result = build_web_crawl_input(source, cap=2)
        assert result["maxCrawlPages"] == 2  # min(2, 3) = 2

    def test_handles_none_settings_json(self):
        """Should handle None settings_json gracefully."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json=None,
        )
        result = build_web_crawl_input(source, cap=3)
        assert len(result["startUrls"]) == 1

    def test_handles_missing_extra_start_urls(self):
        """Should handle missing extra_start_urls key."""
        source = MockSourceConnection(
            identifier="https://example.com",
            settings_json={"other_key": "value"},
        )
        result = build_web_crawl_input(source, cap=3)
        assert len(result["startUrls"]) == 1
