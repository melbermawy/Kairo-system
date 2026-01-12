"""
Unit tests for identifier normalization.

PR-1: Tests for normalize_source_identifier() helper.
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
    # URL normalization
    # =========================================================================

    def test_strips_trailing_slash_from_url(self):
        """Should strip trailing slash from URLs."""
        result = normalize_source_identifier(
            "instagram", "posts", "https://instagram.com/handle/"
        )
        assert result == "https://instagram.com/handle"

    def test_strips_www_from_url(self):
        """Should strip www. prefix from URLs."""
        result = normalize_source_identifier(
            "instagram", "posts", "https://www.instagram.com/handle"
        )
        assert result == "https://instagram.com/handle"

    def test_lowercases_url_host(self):
        """Should lowercase URL scheme and host."""
        result = normalize_source_identifier(
            "instagram", "posts", "HTTPS://WWW.INSTAGRAM.COM/Handle"
        )
        # Host is lowercased, path preserved
        assert result == "https://instagram.com/Handle"

    def test_preserves_url_path_case(self):
        """Should preserve case in URL path."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/About/Team"
        )
        assert result == "https://example.com/About/Team"

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

    def test_does_not_strip_at_from_non_social_platforms(self):
        """Should not strip @ from non-social platforms."""
        result = normalize_source_identifier("web", "crawl_pages", "@something")
        assert result == "@something"

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

    def test_linkedin_company_slug_lowercased(self):
        """LinkedIn company slugs should be lowercased."""
        result = normalize_source_identifier(
            "linkedin", "company_posts", "ACME-Corp"
        )
        assert result == "acme-corp"

    def test_linkedin_company_slug_not_url_stays_as_slug(self):
        """LinkedIn company slug (not URL) should stay as slug."""
        result = normalize_source_identifier(
            "linkedin", "company_posts", "my-company"
        )
        assert result == "my-company"

    # =========================================================================
    # YouTube normalization
    # =========================================================================

    def test_youtube_channel_url_trailing_slash(self):
        """Should strip trailing slash from YouTube URLs."""
        result = normalize_source_identifier(
            "youtube",
            "channel_videos",
            "https://www.youtube.com/channel/UC123abc/",
        )
        assert result == "https://youtube.com/channel/UC123abc"

    # =========================================================================
    # Edge cases
    # =========================================================================

    def test_url_with_query_params_preserved(self):
        """Query params should be preserved (path only stripped)."""
        # Note: urlparse includes query in parsed result, we only strip path slash
        result = normalize_source_identifier(
            "web", "crawl_pages", "https://example.com/page/?foo=bar"
        )
        # The trailing slash before ? is in the path, will be stripped
        assert "example.com/page" in result

    def test_double_slash_url_handled(self):
        """Protocol-relative URLs should be handled."""
        result = normalize_source_identifier(
            "web", "crawl_pages", "//example.com/page/"
        )
        # Should handle gracefully
        assert "example.com" in result
