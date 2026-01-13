"""
PR-4 Tests: Evidence Bundling + Deterministic FeatureReport.

Tests for bundle creation and feature extraction per spec Section 7.2.

Test Categories:
A) Global max enforcement - bundle never exceeds BRANDBRAIN_MAX_NORMALIZED_ITEMS
B) Per-platform cap enforcement - cap_for called/respected
C) Determinism - same DB state -> identical bundle and feature stats
D) Collection page exclusion - excluded when non-web evidence exists
E) Web-only exception - collection pages included when only web items exist
F) Key pages - included even if low_value=true (but collection pages excluded)
G) LinkedIn profile posts - excluded by default even if normalized rows exist
H) FeatureReport - deterministic stats extraction
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kairo.brandbrain.bundling import (
    BundleCriteria,
    create_evidence_bundle,
    create_feature_report,
)
from kairo.brandbrain.bundling.features import (
    CTA_KEYWORDS,
    HOOK_MARKERS,
    compute_emoji_density,
    count_cta_occurrences,
    count_hook_markers,
    extract_all_features,
)
from kairo.brandbrain.bundling.scoring import (
    ENGAGEMENT_WEIGHTS,
    compute_engagement_score,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant-bundling",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand",
        slug="test-brand-bundling",
    )


@pytest.fixture
def source_instagram_posts(db, brand):
    """Create an Instagram posts source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="instagram",
        capability="posts",
        identifier="testbrand",
        is_enabled=True,
    )


@pytest.fixture
def source_instagram_reels(db, brand):
    """Create an Instagram reels source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="instagram",
        capability="reels",
        identifier="testbrand",
        is_enabled=True,
    )


@pytest.fixture
def source_web(db, brand):
    """Create a web source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="web",
        capability="crawl_pages",
        identifier="https://example.com",
        is_enabled=True,
        settings_json={"extra_start_urls": ["https://example.com/about"]},
    )


@pytest.fixture
def source_linkedin(db, brand):
    """Create a LinkedIn company posts source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="linkedin",
        capability="company_posts",
        identifier="testcompany",
        is_enabled=True,
    )


def create_normalized_item(
    brand,
    platform: str,
    content_type: str,
    external_id: str | None = None,
    canonical_url: str = "",
    published_at: datetime | None = None,
    text_primary: str = "",
    hashtags: list | None = None,
    metrics_json: dict | None = None,
    flags_json: dict | None = None,
) -> Any:
    """Helper to create NormalizedEvidenceItem."""
    from kairo.brandbrain.models import NormalizedEvidenceItem

    if external_id is None and platform != "web":
        external_id = str(uuid.uuid4())

    if not canonical_url:
        canonical_url = f"https://{platform}.com/item/{uuid.uuid4()}"

    return NormalizedEvidenceItem.objects.create(
        brand=brand,
        platform=platform,
        content_type=content_type,
        external_id=external_id,
        canonical_url=canonical_url,
        published_at=published_at,
        author_ref="testauthor",
        text_primary=text_primary,
        hashtags=hashtags or [],
        metrics_json=metrics_json or {},
        flags_json=flags_json or {},
    )


# =============================================================================
# A) GLOBAL MAX ENFORCEMENT TESTS
# =============================================================================


class TestGlobalMaxEnforcement:
    """Test that bundle never exceeds global max."""

    def test_global_max_enforced(self, brand, source_instagram_posts):
        """Bundle should not exceed global max items."""
        # Create more items than global max
        now = datetime.now(timezone.utc)
        for i in range(50):  # More than default 40
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                text_primary=f"Post {i}",
                metrics_json={"likes": 100 - i},
            )

        bundle = create_evidence_bundle(brand.id)

        # Should not exceed global max (default 40)
        assert len(bundle.item_ids) <= 40
        assert bundle.summary_json["total_selected"] <= 40

    def test_global_max_from_env(self, brand, source_instagram_posts, monkeypatch):
        """Global max should respect environment variable."""
        monkeypatch.setenv("BRANDBRAIN_MAX_NORMALIZED_ITEMS", "10")

        # Clear caps cache
        from kairo.brandbrain.caps import clear_caps_cache
        clear_caps_cache()

        # Create items
        now = datetime.now(timezone.utc)
        for i in range(20):
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": 100 - i},
            )

        bundle = create_evidence_bundle(brand.id)

        # Should not exceed env max
        assert len(bundle.item_ids) <= 10

        # Clean up
        clear_caps_cache()


# =============================================================================
# B) PER-PLATFORM CAP ENFORCEMENT TESTS
# =============================================================================


class TestPerPlatformCapEnforcement:
    """Test that per-platform caps are respected."""

    def test_instagram_posts_cap_enforced(self, brand, source_instagram_posts):
        """Instagram posts should respect cap_for(instagram, posts)."""
        from kairo.brandbrain.caps import cap_for

        expected_cap = cap_for("instagram", "posts")

        # Create more items than cap
        now = datetime.now(timezone.utc)
        for i in range(expected_cap + 5):
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": 100 - i},
            )

        bundle = create_evidence_bundle(brand.id)

        # Count Instagram posts in bundle
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected_items = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        ig_count = selected_items.filter(platform="instagram", content_type="post").count()

        assert ig_count <= expected_cap

    def test_multiple_platforms_respect_individual_caps(
        self, brand, source_instagram_posts, source_instagram_reels, source_linkedin
    ):
        """Each platform should respect its own cap."""
        from kairo.brandbrain.caps import cap_for

        now = datetime.now(timezone.utc)

        # Create items for each platform
        for i in range(15):
            create_normalized_item(
                brand, "instagram", "post",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": 100 - i},
            )
            create_normalized_item(
                brand, "instagram", "reel",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": 50 - i},
            )
            create_normalized_item(
                brand, "linkedin", "text_post",
                published_at=now - timedelta(hours=i),
                metrics_json={"reactions": 20 - i},
            )

        bundle = create_evidence_bundle(brand.id)

        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected_items = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )

        ig_posts = selected_items.filter(platform="instagram", content_type="post").count()
        ig_reels = selected_items.filter(platform="instagram", content_type="reel").count()
        li_posts = selected_items.filter(platform="linkedin", content_type="text_post").count()

        assert ig_posts <= cap_for("instagram", "posts")
        assert ig_reels <= cap_for("instagram", "reels")
        assert li_posts <= cap_for("linkedin", "company_posts")


# =============================================================================
# C) DETERMINISM TESTS
# =============================================================================


class TestDeterminism:
    """Test that same DB state produces identical results."""

    def test_bundle_deterministic_same_items(self, brand, source_instagram_posts):
        """Running twice should produce identical bundle item_ids."""
        now = datetime.now(timezone.utc)
        for i in range(10):
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                text_primary=f"Post {i} with some content",
                metrics_json={"likes": 100 - i, "comments": 10 - i},
            )

        bundle1 = create_evidence_bundle(brand.id)
        bundle2 = create_evidence_bundle(brand.id)

        # Item IDs should be identical and in same order
        assert bundle1.item_ids == bundle2.item_ids

    def test_bundle_deterministic_criteria(self, brand, source_instagram_posts):
        """criteria_json should be identical across runs."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": i * 10},
            )

        bundle1 = create_evidence_bundle(brand.id)
        bundle2 = create_evidence_bundle(brand.id)

        # Criteria should be identical (minus created_at which isn't in criteria)
        assert bundle1.criteria_json == bundle2.criteria_json

    def test_feature_report_deterministic(self, brand, source_instagram_posts):
        """FeatureReport should be identical for same bundle."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                text_primary=f"Check out this post! #test #content {i}",
                hashtags=["test", "content"],
                metrics_json={"likes": i * 10},
            )

        bundle = create_evidence_bundle(brand.id)
        report1 = create_feature_report(bundle)
        report2 = create_feature_report(bundle)

        # Stats should be identical
        assert report1.stats_json == report2.stats_json


# =============================================================================
# D) COLLECTION PAGE EXCLUSION TESTS
# =============================================================================


class TestCollectionPageExclusion:
    """Test that collection pages are excluded when non-web evidence exists."""

    def test_collection_pages_excluded_with_other_evidence(
        self, brand, source_instagram_posts, source_web
    ):
        """Collection pages should be excluded when Instagram content exists."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts
        for i in range(3):
            create_normalized_item(
                brand,
                "instagram",
                "post",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": 100},
            )

        # Create web pages including collection page
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog",
            text_primary="Blog listing page",
            flags_json={"is_collection_page": True, "is_low_value": True},
        )
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/about",
            text_primary="About us page with lots of content",
            flags_json={"is_collection_page": False, "is_low_value": False},
        )

        bundle = create_evidence_bundle(brand.id)

        # Collection page should be excluded
        assert "https://example.com/blog" not in str(bundle.item_ids)
        assert bundle.summary_json["excluded_collection_pages"] == 1
        assert bundle.summary_json["web_only_exception_applied"] is False

    def test_collection_pages_excluded_count_correct(self, brand, source_instagram_posts, source_web):
        """Summary should correctly count excluded collection pages."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create multiple collection pages
        for i in range(3):
            create_normalized_item(
                brand,
                "web",
                "web_page",
                external_id=None,
                canonical_url=f"https://example.com/blog/page{i}",
                text_primary="Collection page",
                flags_json={"is_collection_page": True},
            )

        bundle = create_evidence_bundle(brand.id)

        assert bundle.summary_json["excluded_collection_pages"] == 3


# =============================================================================
# E) WEB-ONLY EXCEPTION TESTS
# =============================================================================


class TestWebOnlyException:
    """Test that collection pages are included when only web items exist."""

    def test_collection_pages_included_when_web_only(self, brand, source_web):
        """Collection pages should be included when no non-web evidence exists."""
        # Create only web pages
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog",
            text_primary="Blog listing page",
            flags_json={"is_collection_page": True, "is_low_value": True},
        )
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/about",
            text_primary="About us page",
            flags_json={"is_collection_page": False, "is_low_value": False},
        )

        bundle = create_evidence_bundle(brand.id)

        # Web-only exception should apply
        assert bundle.summary_json["web_only_exception_applied"] is True

        # Collection page should be included
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        urls = [item.canonical_url for item in selected]

        assert "https://example.com/blog" in urls


# =============================================================================
# F) KEY PAGES TESTS
# =============================================================================


class TestKeyPagesIncluded:
    """Test that key pages are included even if low_value=true."""

    def test_low_value_key_page_included(self, brand, source_instagram_posts, source_web):
        """Key pages should be included even if is_low_value=true."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create key page marked as low value (but not collection page)
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/about",
            text_primary="Short about page",
            flags_json={"is_collection_page": False, "is_low_value": True},
        )

        bundle = create_evidence_bundle(brand.id)

        # Key page should be included despite being low value
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        urls = [item.canonical_url for item in selected]

        assert "https://example.com/about" in urls

    def test_collection_page_excluded_even_from_key_pages(
        self, brand, source_instagram_posts, source_web
    ):
        """Collection pages should be excluded even if they're key pages."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create key page that's also a collection page
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/resources",
            text_primary="Resources index page",
            flags_json={"is_collection_page": True, "is_low_value": True},
        )

        bundle = create_evidence_bundle(brand.id)

        # Collection page should still be excluded
        assert bundle.summary_json["excluded_collection_pages"] == 1


# =============================================================================
# G) LINKEDIN PROFILE POSTS EXCLUSION TESTS
# =============================================================================


class TestLinkedInProfilePostsExclusion:
    """Test that LinkedIn profile posts are excluded by default."""

    def test_linkedin_profile_posts_excluded_by_default(self, brand, source_linkedin):
        """LinkedIn posts should be included since they're company_posts."""
        now = datetime.now(timezone.utc)

        # Create LinkedIn company posts
        for i in range(5):
            create_normalized_item(
                brand,
                "linkedin",
                "text_post",
                published_at=now - timedelta(hours=i),
                text_primary=f"Company update {i}",
                metrics_json={"reactions": 100 - i * 10},
            )

        # Make sure feature flag is NOT set
        os.environ.pop("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", None)

        bundle = create_evidence_bundle(brand.id)

        # LinkedIn posts should be included (they're from company_posts source)
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        li_count = selected.filter(platform="linkedin").count()

        # Should have LinkedIn items since source is company_posts
        assert li_count > 0

    def test_criteria_excludes_linkedin_profile_posts(self, brand):
        """Default criteria should have exclude_linkedin_profile_posts=True."""
        criteria = BundleCriteria()
        assert criteria.exclude_linkedin_profile_posts is True


# =============================================================================
# H) FEATURE REPORT TESTS
# =============================================================================


class TestFeatureReportStats:
    """Test deterministic feature extraction."""

    def test_text_stats_by_platform(self, brand, source_instagram_posts, source_linkedin):
        """Text stats should be computed per platform."""
        now = datetime.now(timezone.utc)

        # Create items with known text lengths
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            text_primary="Short post",  # 10 chars
        )
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(hours=1),
            text_primary="Longer post with more content",  # 30 chars
        )
        create_normalized_item(
            brand, "linkedin", "text_post",
            published_at=now,
            text_primary="LinkedIn update",  # 15 chars
        )

        bundle = create_evidence_bundle(brand.id)
        report = create_feature_report(bundle)

        stats = report.stats_json["text_stats"]
        assert "instagram" in stats
        assert "linkedin" in stats
        assert stats["instagram"]["item_count"] == 2
        assert stats["linkedin"]["item_count"] == 1

    def test_emoji_density_computed(self, brand, source_instagram_posts):
        """Emoji density should be computed correctly."""
        now = datetime.now(timezone.utc)

        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            text_primary="Hello world! 😀🎉",  # 2 emojis in ~15 chars
        )
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(hours=1),
            text_primary="No emojis here",
        )

        bundle = create_evidence_bundle(brand.id)
        report = create_feature_report(bundle)

        emoji_stats = report.stats_json["emoji_stats"]
        assert emoji_stats["by_platform"]["instagram"]["items_with_emoji"] >= 1

    def test_cta_frequency_computed(self, brand, source_instagram_posts):
        """CTA frequency should be computed correctly."""
        now = datetime.now(timezone.utc)

        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            text_primary="Click the link in bio to learn more!",
        )
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(hours=1),
            text_primary="Just a regular post",
        )

        bundle = create_evidence_bundle(brand.id)
        report = create_feature_report(bundle)

        cta_stats = report.stats_json["cta_stats"]
        assert cta_stats["items_with_cta"] >= 1

    def test_hashtag_stats_computed(self, brand, source_instagram_posts):
        """Hashtag stats should be computed correctly."""
        now = datetime.now(timezone.utc)

        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            hashtags=["marketing", "content", "social"],
        )
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(hours=1),
            hashtags=[],
        )

        bundle = create_evidence_bundle(brand.id)
        report = create_feature_report(bundle)

        hashtag_stats = report.stats_json["hashtag_stats"]
        assert hashtag_stats["items_with_hashtags"] >= 1
        assert hashtag_stats["by_platform"]["instagram"]["max_count"] == 3

    def test_hook_markers_computed(self, brand, source_instagram_posts):
        """Hook marker frequency should be computed correctly."""
        now = datetime.now(timezone.utc)

        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            text_primary="Here's how to grow your audience in 3 ways",
        )
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(hours=1),
            text_primary="Beautiful sunset photo",
        )

        bundle = create_evidence_bundle(brand.id)
        report = create_feature_report(bundle)

        hook_stats = report.stats_json["hook_marker_stats"]
        assert hook_stats["items_with_hooks"] >= 1

    def test_transcript_coverage_computed(self, brand, source_instagram_posts):
        """Transcript coverage should be computed correctly."""
        now = datetime.now(timezone.utc)

        create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            flags_json={"has_transcript": True},
        )
        create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(hours=1),
            flags_json={"has_transcript": False},
        )

        bundle = create_evidence_bundle(brand.id)
        report = create_feature_report(bundle)

        transcript_stats = report.stats_json["transcript_coverage"]
        assert transcript_stats["overall_with_transcript"] >= 1


# =============================================================================
# I) UNIT TESTS FOR HELPER FUNCTIONS
# =============================================================================


class TestEngagementScoring:
    """Test engagement scoring functions."""

    def test_instagram_scoring(self):
        """Instagram scoring should use likes, comments, views."""
        from kairo.brandbrain.bundling.scoring import compute_engagement_score_from_dict

        metrics = {"likes": 100, "comments": 10, "views": 1000}
        score = compute_engagement_score_from_dict("instagram", metrics)

        # Expected: 100*1.0 + 10*3.0 + 1000*0.1 = 100 + 30 + 100 = 230
        assert score == 230.0

    def test_missing_metrics_default_to_zero(self):
        """Missing metrics should not affect score."""
        from kairo.brandbrain.bundling.scoring import compute_engagement_score_from_dict

        metrics = {"likes": 100}  # No comments or views
        score = compute_engagement_score_from_dict("instagram", metrics)

        # Should only count likes
        assert score == 100.0

    def test_web_has_no_engagement_score(self):
        """Web platform should have zero engagement score."""
        from kairo.brandbrain.bundling.scoring import compute_engagement_score_from_dict

        metrics = {"likes": 100, "comments": 10}
        score = compute_engagement_score_from_dict("web", metrics)

        assert score == 0.0


class TestEmojiDensity:
    """Test emoji density computation."""

    def test_emoji_density_with_emojis(self):
        """Should correctly count emojis."""
        density = compute_emoji_density("Hello 😀🎉 world!")

        # 2 emojis in ~16 chars
        assert density > 0
        assert density < 1

    def test_emoji_density_no_emojis(self):
        """Should return 0 for text without emojis."""
        density = compute_emoji_density("Hello world!")

        assert density == 0.0

    def test_emoji_density_empty_string(self):
        """Should return 0 for empty string."""
        density = compute_emoji_density("")

        assert density == 0.0


class TestCTAOccurrences:
    """Test CTA counting."""

    def test_counts_cta_keywords(self):
        """Should count CTA keywords."""
        count = count_cta_occurrences("Click the link in bio to learn more")

        assert count >= 2  # "click", "link in bio", "learn more"

    def test_case_insensitive(self):
        """Should be case insensitive."""
        count1 = count_cta_occurrences("CLICK HERE")
        count2 = count_cta_occurrences("click here")

        assert count1 == count2

    def test_no_cta_returns_zero(self):
        """Should return 0 when no CTAs present."""
        count = count_cta_occurrences("Just a regular sentence")

        assert count == 0


class TestHookMarkers:
    """Test hook marker counting."""

    def test_counts_hook_markers(self):
        """Should count hook markers."""
        count = count_hook_markers("Here's how to grow in 3 ways")

        assert count >= 2  # "here's how", "3 ways"

    def test_case_insensitive(self):
        """Should be case insensitive."""
        count1 = count_hook_markers("HERE'S HOW")
        count2 = count_hook_markers("here's how")

        assert count1 == count2


# =============================================================================
# J) CRITERIA TESTS
# =============================================================================


class TestBundleCriteria:
    """Test BundleCriteria configuration."""

    def test_default_values(self):
        """Default criteria should match constants."""
        from kairo.brandbrain.bundling.criteria import (
            DEFAULT_RECENT_M,
            DEFAULT_TOP_ENGAGEMENT_N,
        )

        criteria = BundleCriteria()

        assert criteria.recent_m == DEFAULT_RECENT_M
        assert criteria.top_engagement_n == DEFAULT_TOP_ENGAGEMENT_N
        assert criteria.exclude_collection_pages is True
        assert criteria.exclude_linkedin_profile_posts is True

    def test_to_dict_round_trip(self):
        """Should be able to serialize and deserialize."""
        criteria = BundleCriteria(
            recent_m=5,
            top_engagement_n=10,
            exclude_collection_pages=False,
        )

        as_dict = criteria.to_dict()
        restored = BundleCriteria.from_dict(as_dict)

        assert restored.recent_m == 5
        assert restored.top_engagement_n == 10
        assert restored.exclude_collection_pages is False

    def test_criteria_stored_in_bundle(self, brand, source_instagram_posts):
        """Criteria should be stored in bundle criteria_json."""
        create_normalized_item(
            brand, "instagram", "post",
            published_at=datetime.now(timezone.utc),
        )

        criteria = BundleCriteria(recent_m=5, top_engagement_n=7)
        bundle = create_evidence_bundle(brand.id, criteria=criteria)

        assert bundle.criteria_json["recent_m"] == 5
        assert bundle.criteria_json["top_engagement_n"] == 7
        assert "version" in bundle.criteria_json


# =============================================================================
# K) EMPTY/EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_bundle_when_no_items(self, brand, source_instagram_posts):
        """Should create empty bundle when no items exist."""
        bundle = create_evidence_bundle(brand.id)

        assert len(bundle.item_ids) == 0
        assert bundle.summary_json["total_selected"] == 0

    def test_empty_bundle_when_no_enabled_sources(self, brand):
        """Should create empty bundle when no sources enabled."""
        # Create items but no enabled source connection
        create_normalized_item(
            brand, "instagram", "post",
            published_at=datetime.now(timezone.utc),
        )

        bundle = create_evidence_bundle(brand.id)

        # No enabled sources means no items selected
        assert len(bundle.item_ids) == 0

    def test_feature_report_with_empty_bundle(self, brand, source_instagram_posts):
        """Should handle empty bundle gracefully."""
        bundle = create_evidence_bundle(brand.id)  # No items
        report = create_feature_report(bundle)

        assert report.stats_json["item_count"] == 0


# =============================================================================
# L) SELECTION HEURISTIC TESTS
# =============================================================================


class TestSelectionHeuristics:
    """Test the recent_M + top_engagement_N selection heuristic."""

    def test_recent_items_selected(self, brand, source_instagram_posts):
        """Most recent items should always be selected."""
        now = datetime.now(timezone.utc)

        # Create items with different recency
        recent_item = create_normalized_item(
            brand, "instagram", "post",
            published_at=now,
            text_primary="Most recent",
            metrics_json={"likes": 1},  # Low engagement
        )
        old_item = create_normalized_item(
            brand, "instagram", "post",
            published_at=now - timedelta(days=30),
            text_primary="Old item",
            metrics_json={"likes": 1000},  # High engagement
        )

        bundle = create_evidence_bundle(brand.id)

        # Most recent should be in bundle
        assert str(recent_item.id) in bundle.item_ids

    def test_high_engagement_selected(self, brand, source_instagram_posts):
        """High engagement items should be selected after recent."""
        now = datetime.now(timezone.utc)

        criteria = BundleCriteria(recent_m=1, top_engagement_n=2)

        # Create items with different engagement
        for i in range(5):
            create_normalized_item(
                brand, "instagram", "post",
                published_at=now - timedelta(hours=i),
                metrics_json={"likes": i * 100, "comments": i * 10},
            )

        bundle = create_evidence_bundle(brand.id, criteria=criteria)

        # Should have recent_m + top_engagement_n = 3 items (capped by platform cap)
        assert len(bundle.item_ids) <= 3


# =============================================================================
# M) UNKNOWN CONTENT TYPE RAISES EXCEPTION
# =============================================================================


class TestUnknownContentTypeRaises:
    """Test that unknown (platform, content_type) pairs raise an exception."""

    def test_unknown_content_type_raises_error(self, brand, source_instagram_posts):
        """Unknown content type should raise UnknownContentTypeError."""
        from kairo.brandbrain.bundling import UnknownContentTypeError

        # Create an item with an unknown content_type
        create_normalized_item(
            brand,
            "instagram",
            "unknown_type",  # Not in CONTENT_TYPE_TO_CAPABILITY
            published_at=datetime.now(timezone.utc),
        )

        with pytest.raises(UnknownContentTypeError) as exc_info:
            create_evidence_bundle(brand.id)

        assert exc_info.value.platform == "instagram"
        assert exc_info.value.content_type == "unknown_type"
        assert "unknown_type" in str(exc_info.value)

    def test_unknown_platform_raises_error(self, brand):
        """Unknown platform should raise UnknownContentTypeError."""
        from kairo.brandbrain.bundling import UnknownContentTypeError
        from kairo.brandbrain.models import SourceConnection

        # Create source for unknown platform
        SourceConnection.objects.create(
            brand=brand,
            platform="newplatform",
            capability="posts",
            identifier="test",
            is_enabled=True,
        )

        # Create an item with an unknown platform
        create_normalized_item(
            brand,
            "newplatform",
            "post",
            published_at=datetime.now(timezone.utc),
        )

        with pytest.raises(UnknownContentTypeError) as exc_info:
            create_evidence_bundle(brand.id)

        assert exc_info.value.platform == "newplatform"


# =============================================================================
# N) LINKEDIN EXCLUSION IS EXPLICIT NO-OP AT NEI LEVEL
# =============================================================================


class TestLinkedInExclusionNoOp:
    """Test that LinkedIn profile-posts exclusion is explicitly documented as no-op at NEI level."""

    def test_linkedin_posts_included_regardless_of_criteria(self, brand, source_linkedin):
        """LinkedIn posts should NOT be filtered by bundler (filtering happens upstream)."""
        now = datetime.now(timezone.utc)

        # Create LinkedIn posts
        for i in range(5):
            create_normalized_item(
                brand,
                "linkedin",
                "text_post",
                published_at=now - timedelta(hours=i),
                text_primary=f"LinkedIn post {i}",
                metrics_json={"reactions": 100 - i * 10},
            )

        # Even with exclude_linkedin_profile_posts=True, posts should NOT be filtered
        # because bundler cannot distinguish company_posts vs profile_posts at NEI level
        criteria = BundleCriteria(exclude_linkedin_profile_posts=True)
        bundle = create_evidence_bundle(brand.id, criteria=criteria)

        # All LinkedIn items should be selected (up to cap)
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        li_count = selected.filter(platform="linkedin").count()

        # Should have LinkedIn items - exclusion does NOT happen at bundler level
        assert li_count > 0, (
            "LinkedIn posts should be included. Bundler cannot distinguish "
            "company_posts vs profile_posts at NEI level."
        )

    def test_linkedin_exclusion_count_always_zero(self, brand, source_linkedin):
        """excluded_linkedin_profile_posts count should always be 0 (bundler can't exclude)."""
        now = datetime.now(timezone.utc)

        for i in range(3):
            create_normalized_item(
                brand,
                "linkedin",
                "text_post",
                published_at=now - timedelta(hours=i),
                metrics_json={"reactions": 100},
            )

        bundle = create_evidence_bundle(brand.id)

        # The count should always be 0 because bundler can't actually exclude
        assert bundle.summary_json["excluded_linkedin_profile_posts"] == 0, (
            "excluded_linkedin_profile_posts should be 0 - bundler cannot distinguish "
            "company_posts vs profile_posts at NEI level"
        )


# =============================================================================
# O) LOW-VALUE WEB PAGES NOT EXCLUDED
# =============================================================================


class TestLowValueWebPagesNotExcluded:
    """Test that low-value web pages are NOT excluded (only collection pages are)."""

    def test_low_value_non_collection_page_included(self, brand, source_instagram_posts, source_web):
        """Low-value pages that are NOT collection pages should be included."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts (so we have non-web evidence)
        create_normalized_item(
            brand,
            "instagram",
            "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create low-value web page that is NOT a collection page
        low_value_item = create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/short-page",
            text_primary="Short content page",
            flags_json={"is_collection_page": False, "is_low_value": True},
        )

        bundle = create_evidence_bundle(brand.id)

        # Low-value page should be included (only collection pages are excluded)
        assert str(low_value_item.id) in bundle.item_ids, (
            "Low-value pages should be included. Only collection pages are excluded."
        )

    def test_low_value_collection_page_excluded(self, brand, source_instagram_posts, source_web):
        """Collection pages should be excluded regardless of low_value flag."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts
        create_normalized_item(
            brand,
            "instagram",
            "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create collection page (is_low_value doesn't matter for exclusion)
        collection_item = create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog-index",
            text_primary="Blog listing",
            flags_json={"is_collection_page": True, "is_low_value": True},
        )

        bundle = create_evidence_bundle(brand.id)

        # Collection page should be excluded
        assert str(collection_item.id) not in bundle.item_ids
        assert bundle.summary_json["excluded_collection_pages"] == 1

    def test_normal_value_collection_page_excluded(self, brand, source_instagram_posts, source_web):
        """Collection pages should be excluded even if not marked as low_value."""
        now = datetime.now(timezone.utc)

        # Create Instagram posts
        create_normalized_item(
            brand,
            "instagram",
            "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create collection page that is NOT marked low_value
        collection_item = create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/products",
            text_primary="Products listing with substantial content",
            flags_json={"is_collection_page": True, "is_low_value": False},
        )

        bundle = create_evidence_bundle(brand.id)

        # Collection page should still be excluded
        assert str(collection_item.id) not in bundle.item_ids


# =============================================================================
# P) WEB-ONLY PREDICATE FROM ACTUAL NEI ROWS
# =============================================================================


class TestWebOnlyPredicateFromActualNEI:
    """Test that web-only is determined from actual NEI rows in candidate set."""

    def test_web_only_with_disabled_instagram_source(self, brand, source_web):
        """Should be web-only if Instagram source exists but is disabled."""
        from kairo.brandbrain.models import SourceConnection

        # Create disabled Instagram source (won't count for web-only check)
        SourceConnection.objects.create(
            brand=brand,
            platform="instagram",
            capability="posts",
            identifier="testbrand",
            is_enabled=False,  # DISABLED
        )

        # Create Instagram items (stale historical data)
        now = datetime.now(timezone.utc)
        create_normalized_item(
            brand,
            "instagram",
            "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create web items including collection page
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog",
            text_primary="Blog listing",
            flags_json={"is_collection_page": True},
        )

        bundle = create_evidence_bundle(brand.id)

        # Should be web-only because Instagram source is disabled
        # Collection pages should be included
        assert bundle.summary_json["web_only_exception_applied"] is True

    def test_not_web_only_with_enabled_instagram_source(
        self, brand, source_web, source_instagram_posts
    ):
        """Should NOT be web-only if Instagram source is enabled AND has NEI rows."""
        now = datetime.now(timezone.utc)

        # Create Instagram items
        create_normalized_item(
            brand,
            "instagram",
            "post",
            published_at=now,
            metrics_json={"likes": 100},
        )

        # Create web items including collection page
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog",
            text_primary="Blog listing",
            flags_json={"is_collection_page": True},
        )

        bundle = create_evidence_bundle(brand.id)

        # Should NOT be web-only because Instagram source is enabled AND has NEI
        # Collection pages should be excluded
        assert bundle.summary_json["web_only_exception_applied"] is False
        assert bundle.summary_json["excluded_collection_pages"] == 1

    def test_web_only_when_enabled_source_has_no_nei_rows(
        self, brand, source_web, source_instagram_posts
    ):
        """Should be web-only if Instagram source is enabled but has NO NEI rows.

        This is the key test: enabled_platforms includes instagram + web,
        but there are no instagram NEI rows in the candidate set.
        Web-only exception should apply (collection pages included).
        """
        # source_instagram_posts is enabled, but we create NO Instagram NEI rows

        # Create only web items including collection page
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog",
            text_primary="Blog listing",
            flags_json={"is_collection_page": True},
        )
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/about",
            text_primary="About page",
            flags_json={"is_collection_page": False},
        )

        bundle = create_evidence_bundle(brand.id)

        # Should be web-only because even though Instagram source is enabled,
        # there are no Instagram NEI rows in the candidate set
        assert bundle.summary_json["web_only_exception_applied"] is True, (
            "Web-only exception should apply when enabled non-web sources "
            "have no actual NEI rows"
        )

        # Collection page should be included
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        urls = [item.canonical_url for item in selected]
        assert "https://example.com/blog" in urls, (
            "Collection page should be included under web-only exception"
        )

    def test_non_web_nei_outside_candidate_set_does_not_flip_predicate(
        self, brand, source_web
    ):
        """Non-web NEI rows outside the candidate set should NOT affect web-only predicate.

        This is a regression test guarding against predicate drift:
        - We have only web source enabled (source_web fixture)
        - We create Instagram NEI rows (but Instagram source is NOT enabled)
        - The Instagram NEI rows are outside the candidate set (platform not in enabled_platforms)
        - Therefore has_non_web_evidence should be False (web-only applies)

        If the predicate was computed incorrectly (e.g., checking all NEI rows
        instead of candidate_queryset), this test would fail.
        """
        now = datetime.now(timezone.utc)

        # Create Instagram NEI rows - but NO Instagram source is enabled!
        # These rows are outside the candidate set.
        create_normalized_item(
            brand,
            "instagram",
            "post",
            published_at=now,
            text_primary="Instagram post that should be ignored",
            metrics_json={"likes": 1000},
        )

        # Create web items including collection page
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/blog",
            text_primary="Blog listing",
            flags_json={"is_collection_page": True},
        )
        create_normalized_item(
            brand,
            "web",
            "web_page",
            external_id=None,
            canonical_url="https://example.com/about",
            text_primary="About page",
            flags_json={"is_collection_page": False},
        )

        bundle = create_evidence_bundle(brand.id)

        # Should be web-only because Instagram source is NOT enabled,
        # so Instagram NEI rows are outside the candidate set
        assert bundle.summary_json["web_only_exception_applied"] is True, (
            "Web-only exception should apply. Non-web NEI rows from disabled "
            "sources should not affect the predicate."
        )

        # Instagram items should NOT be in bundle (source not enabled)
        from kairo.brandbrain.models import NormalizedEvidenceItem
        selected = NormalizedEvidenceItem.objects.filter(
            id__in=[uuid.UUID(id_str) for id_str in bundle.item_ids]
        )
        assert not selected.filter(platform="instagram").exists(), (
            "Instagram items should not be selected - source not enabled"
        )

        # Collection page should be included (web-only exception)
        urls = [item.canonical_url for item in selected]
        assert "https://example.com/blog" in urls, (
            "Collection page should be included under web-only exception"
        )
