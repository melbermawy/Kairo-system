"""
Unit tests for identifier normalization.

PR-1: Tests for normalize_source_identifier() helper.
PR-7: Enhanced normalization - extracts handles from URLs, strips tracking params.
All tests marked @pytest.mark.unit - no DB required.
"""

import pytest

from kairo.brandbrain.identifiers import normalize_source_identifier


@pytest.mark.unit
class TestNormalizeSourceIdentifier:
    """Unit tests for normalize_source_identifier()."""

    # =========================================================================
    # Basic normalization
    # =========================================================================

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        result = normalize_source_identifier("instagram", "posts", "  handle  ")
        assert result == "handle"

    def test_empty_string_unchanged(self):
        """Empty string should remain empty."""
        result = normalize_source_identifier("instagram", "posts", "")
        assert result == ""

    def test_none_returns_none(self):
        """None should return None (falsy passthrough)."""
        result = normalize_source_identifier("instagram", "posts", None)
        assert result is None

    # =========================================================================
    # URL normalization - host lowercasing
    # =========================================================================

    def test_strips_trailing_slash_from_url(self):
        """Should strip trailing slash from URLs.

        PR-7: Instagram URLs are extracted to just the username.
        """
        result = normalize_source_identifier(
            "instagram", "posts", "https://instagram.com/handle/"
        )
        # PR-7: Extracts username from Instagram URL
        assert result == "handle"

    def test_lowercases_url_host_only(self):
        """Should lowercase URL scheme and host, but NOT path.

        PR-7: Instagram URLs are extracted to just the username (lowercased).
        """
        result = normalize_source_identifier(
            "instagram", "posts", "HTTPS://INSTAGRAM.COM/Handle"
        )
        # PR-7: Extracts username from Instagram URL, lowercased
        assert result == "handle"

    def test_preserves_url_path_case(self):
        """Should preserve case in URL path."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/About/Team"
        )
        assert result == "https://example.com/About/Team"

    def test_www_not_stripped_from_general_urls(self):
        """www should NOT be stripped from general URLs (conservative).

        PR-7: Instagram URLs are extracted to just the username.
        """
        result = normalize_source_identifier(
            "instagram", "posts", "https://www.instagram.com/handle"
        )
        # PR-7: Extracts username from Instagram URL regardless of www
        assert result == "handle"

    # =========================================================================
    # URL normalization - query string preservation
    # =========================================================================

    def test_query_string_preserved(self):
        """Query string should be preserved exactly."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/page?foo=Bar&baz=123"
        )
        assert result == "https://example.com/page?foo=Bar&baz=123"

    def test_query_string_case_preserved(self):
        """Query string case should be preserved."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/page?Filter=Active"
        )
        assert "Filter=Active" in result

    def test_fragment_stripped_for_web(self):
        """URL fragment should be stripped (PR-7: fragments don't affect page content)."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/page#Section1"
        )
        # PR-7: Fragments are stripped as they don't change page content
        assert result == "https://example.com/page"

    def test_trailing_slash_stripped_before_query(self):
        """Trailing slash in path should be stripped even with query."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/page/?foo=bar"
        )
        assert result == "https://example.com/page?foo=bar"

    # =========================================================================
    # Handle normalization (non-URL)
    # =========================================================================

    def test_strips_at_sign_from_instagram_handle(self):
        """Should strip @ from Instagram handles."""
        result = normalize_source_identifier("instagram", "posts", "@nogood")
        assert result == "nogood"

    def test_strips_at_sign_from_tiktok_handle(self):
        """Should strip @ from TikTok handles."""
        result = normalize_source_identifier("tiktok", "profile_videos", "@nogood")
        assert result == "nogood"

    def test_does_not_strip_at_from_web_platform(self):
        """Should not strip @ from web platform (no handle rules)."""
        result = normalize_source_identifier("web", "crawl_pages", "@something")
        assert result == "@something"

    def test_does_not_strip_at_from_youtube_platform(self):
        """Should not strip @ from YouTube platform."""
        result = normalize_source_identifier("youtube", "channel_videos", "@channel")
        assert result == "@channel"

    # =========================================================================
    # LinkedIn company normalization
    # =========================================================================

    def test_linkedin_company_url_extracts_slug(self):
        """Should extract company slug from LinkedIn URL."""
        result = normalize_source_identifier(
            "linkedin",
            "company_posts",
            "https://www.linkedin.com/company/nogood-marketing/",
        )
        assert result == "nogood-marketing"

    def test_linkedin_company_url_without_www(self):
        """Should extract company slug from LinkedIn URL without www."""
        result = normalize_source_identifier(
            "linkedin",
            "company_posts",
            "https://linkedin.com/company/acme-corp",
        )
        assert result == "acme-corp"

    def test_linkedin_company_url_slug_lowercased(self):
        """LinkedIn company slug from URL should be lowercased."""
        result = normalize_source_identifier(
            "linkedin",
            "company_posts",
            "https://linkedin.com/company/ACME-Corp/",
        )
        assert result == "acme-corp"

    def test_linkedin_company_slug_not_url_lowercased(self):
        """LinkedIn company slug (not URL) should be lowercased."""
        result = normalize_source_identifier(
            "linkedin", "company_posts", "ACME-Corp"
        )
        assert result == "acme-corp"

    def test_linkedin_company_slug_stays_as_slug(self):
        """LinkedIn company slug (not URL) should stay as slug."""
        result = normalize_source_identifier(
            "linkedin", "company_posts", "my-company"
        )
        assert result == "my-company"

    # =========================================================================
    # YouTube normalization
    # =========================================================================

    def test_youtube_channel_url_extracts_channel_id(self):
        """Should extract channel ID from YouTube URLs (PR-7)."""
        result = normalize_source_identifier(
            "youtube",
            "channel_videos",
            "https://www.youtube.com/channel/UC123abc/",
        )
        # PR-7: Extracts channel ID from YouTube URL
        assert result == "UC123abc"

    def test_youtube_preserves_path_case(self):
        """YouTube channel IDs should preserve case."""
        result = normalize_source_identifier(
            "youtube",
            "channel_videos",
            "https://youtube.com/channel/UCaBcDeFgHi",
        )
        assert "UCaBcDeFgHi" in result

    # =========================================================================
    # Edge cases
    # =========================================================================

    def test_double_slash_protocol_relative_url(self):
        """Protocol-relative URLs should be handled."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "//example.com/page/"
        )
        # Should handle gracefully - scheme defaults to https
        assert "example.com/page" in result

    def test_url_with_port_preserved(self):
        """URL with port should be preserved."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com:8080/page"
        )
        assert result == "https://example.com:8080/page"

    def test_complex_url_all_parts_preserved_except_fragment(self):
        """Complex URL should preserve path case and query, but strip fragment (PR-7)."""
        result = normalize_source_identifier(
            "web",
            "crawl_pages",
            "https://Example.COM/Path/To/Page?key=Value&other=123#Section",
        )
        # Host lowercased, path and query preserved, fragment stripped (PR-7)
        assert result == "https://example.com/Path/To/Page?key=Value&other=123"
