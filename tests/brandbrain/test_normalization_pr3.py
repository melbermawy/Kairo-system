"""
PR-3 Tests: Normalization Adapters.

Tests for raw → normalized transformation per Appendix B mappings.

Test Categories:
A) Golden tests - validate against var/apify_samples/ for each actor
B) Idempotency tests - verify no duplicates on re-run, raw_refs merge
C) Cap wiring tests - verify dataset-fetch cap enforcement
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kairo.brandbrain.normalization.adapters import (
    ADAPTER_REGISTRY,
    get_adapter,
    normalize_instagram_post,
    normalize_instagram_reel,
    normalize_linkedin_company_post,
    normalize_tiktok_video,
    normalize_web_page,
    normalize_youtube_video,
)


# =============================================================================
# FIXTURES & HELPERS
# =============================================================================


SAMPLES_DIR = Path(__file__).parent.parent.parent / "var" / "apify_samples"


def load_sample_json(actor_dir: str, run_uuid: str, item_index: int = 0) -> dict:
    """Load a sample JSON file from var/apify_samples/."""
    path = SAMPLES_DIR / actor_dir / run_uuid / f"item_{item_index}.json"
    if not path.exists():
        pytest.skip(f"Sample file not found: {path}")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def instagram_post_sample():
    """Load Instagram post sample from apify_instagram-scraper."""
    return load_sample_json(
        "apify_instagram-scraper",
        "fc694124-0928-4c32-8c8b-871483c1a51f",
        0,
    )


@pytest.fixture
def instagram_reel_sample():
    """Load Instagram reel sample from apify_instagram-reel-scraper."""
    return load_sample_json(
        "apify_instagram-reel-scraper",
        "bf1391f4-aaab-4576-8782-789d56ad0634",
        0,
    )


@pytest.fixture
def linkedin_company_post_sample():
    """Load LinkedIn company post sample from apimaestro_linkedin-company-posts."""
    return load_sample_json(
        "apimaestro_linkedin-company-posts",
        "a3373658-29e9-4c7b-81e6-07d27ff4fe24",
        0,
    )


@pytest.fixture
def tiktok_video_sample():
    """Load TikTok video sample from clockworks_tiktok-scraper."""
    return load_sample_json(
        "clockworks_tiktok-scraper",
        "ead52b8b-d2e2-4172-84d4-4355a848ec45",
        0,
    )


@pytest.fixture
def youtube_video_sample():
    """Load YouTube video sample from streamers_youtube-scraper."""
    return load_sample_json(
        "streamers_youtube-scraper",
        "22b6a3f6-4a38-43e8-a8c6-2eceb3eae85f",
        0,
    )


@pytest.fixture
def web_page_sample():
    """Load web page sample from apify_website-content-crawler."""
    return load_sample_json(
        "apify_website-content-crawler",
        "a2126ae4-1ef0-4f40-b11e-9f521f30652c",
        0,
    )


# =============================================================================
# A) GOLDEN TESTS - Per-Actor Normalization
# =============================================================================


@pytest.mark.unit
class TestAdapterRegistry:
    """Test adapter registry and lookup."""

    def test_registry_has_6_validated_actors(self):
        """Registry should have 7 adapters (6 validated + 1 unvalidated)."""
        assert len(ADAPTER_REGISTRY) == 7

    def test_get_adapter_returns_function(self):
        """get_adapter should return callable for known actors."""
        adapter = get_adapter("apify~instagram-scraper")
        assert callable(adapter)

    def test_get_adapter_returns_none_for_unknown(self):
        """get_adapter should return None for unknown actors."""
        adapter = get_adapter("unknown~actor")
        assert adapter is None

    @pytest.mark.parametrize(
        "actor_id",
        [
            "apify~instagram-scraper",
            "apify~instagram-reel-scraper",
            "apimaestro~linkedin-company-posts",
            "clockworks~tiktok-scraper",
            "streamers~youtube-scraper",
            "apify~website-content-crawler",
        ],
    )
    def test_validated_actors_have_adapters(self, actor_id):
        """All validated actors should have adapters."""
        adapter = get_adapter(actor_id)
        assert adapter is not None, f"Missing adapter for {actor_id}"


@pytest.mark.unit
class TestInstagramPostAdapter:
    """Golden tests for apify~instagram-scraper → instagram/post."""

    def test_platform_and_content_type(self, instagram_post_sample):
        """Should set platform=instagram, content_type=post."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["platform"] == "instagram"
        assert result["content_type"] == "post"

    def test_external_id_mapping(self, instagram_post_sample):
        """Should map id field to external_id."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["external_id"] == instagram_post_sample["id"]
        assert result["external_id"] == "3798485363417751904"

    def test_canonical_url_mapping(self, instagram_post_sample):
        """Should map url to canonical_url."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["canonical_url"] == instagram_post_sample["url"]
        assert "instagram.com/p/" in result["canonical_url"]

    def test_published_at_parsing(self, instagram_post_sample):
        """Should parse timestamp to datetime."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["published_at"] is not None
        assert isinstance(result["published_at"], datetime)

    def test_author_ref_mapping(self, instagram_post_sample):
        """Should map ownerUsername to author_ref."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["author_ref"] == instagram_post_sample["ownerUsername"]
        assert result["author_ref"] == "nogood.io"

    def test_text_primary_is_caption(self, instagram_post_sample):
        """Should map caption to text_primary."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["text_primary"] == instagram_post_sample["caption"]
        assert "marketingtrends" in result["text_primary"]

    def test_hashtags_mapping(self, instagram_post_sample):
        """Should map hashtags array."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["hashtags"] == instagram_post_sample["hashtags"]
        assert "marketingtrends" in result["hashtags"]

    def test_metrics_json_structure(self, instagram_post_sample):
        """Should include likes, comments, views in metrics_json."""
        result = normalize_instagram_post(instagram_post_sample)
        assert "likes" in result["metrics_json"]
        assert "comments" in result["metrics_json"]
        assert result["metrics_json"]["likes"] == 71
        assert result["metrics_json"]["comments"] == 0

    def test_flags_json_has_transcript_false(self, instagram_post_sample):
        """Posts don't have transcripts."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["flags_json"]["has_transcript"] is False

    def test_flags_json_is_low_value_false_with_caption(self, instagram_post_sample):
        """Post with caption should not be low_value."""
        result = normalize_instagram_post(instagram_post_sample)
        assert result["flags_json"]["is_low_value"] is False

    def test_flags_json_is_low_value_true_without_caption(self):
        """Post without caption should be low_value."""
        raw = {"id": "123", "caption": "", "ownerUsername": "test"}
        result = normalize_instagram_post(raw)
        assert result["flags_json"]["is_low_value"] is True


@pytest.mark.unit
class TestInstagramReelAdapter:
    """Golden tests for apify~instagram-reel-scraper → instagram/reel."""

    def test_platform_and_content_type(self, instagram_reel_sample):
        """Should set platform=instagram, content_type=reel."""
        result = normalize_instagram_reel(instagram_reel_sample)
        assert result["platform"] == "instagram"
        assert result["content_type"] == "reel"

    def test_external_id_mapping(self, instagram_reel_sample):
        """Should map id field to external_id."""
        result = normalize_instagram_reel(instagram_reel_sample)
        assert result["external_id"] == instagram_reel_sample["id"]

    def test_transcript_in_text_secondary(self, instagram_reel_sample):
        """Should map transcript to text_secondary."""
        result = normalize_instagram_reel(instagram_reel_sample)
        # This sample has a transcript
        assert result["text_secondary"] is not None
        assert "Great Meme Reset" in result["text_secondary"]

    def test_has_transcript_flag(self, instagram_reel_sample):
        """Should set has_transcript=true when transcript present."""
        result = normalize_instagram_reel(instagram_reel_sample)
        assert result["flags_json"]["has_transcript"] is True

    def test_has_transcript_false_without_transcript(self):
        """Should set has_transcript=false when no transcript."""
        raw = {"id": "123", "caption": "test", "ownerUsername": "test"}
        result = normalize_instagram_reel(raw)
        assert result["flags_json"]["has_transcript"] is False
        assert result["text_secondary"] is None

    def test_is_low_value_when_no_caption_and_no_transcript(self):
        """Should be low_value when both caption and transcript empty."""
        raw = {"id": "123", "caption": "", "transcript": "", "ownerUsername": "test"}
        result = normalize_instagram_reel(raw)
        assert result["flags_json"]["is_low_value"] is True

    def test_not_low_value_when_transcript_present(self):
        """Should not be low_value when transcript present even if no caption."""
        raw = {"id": "123", "caption": "", "transcript": "Hello world", "ownerUsername": "test"}
        result = normalize_instagram_reel(raw)
        assert result["flags_json"]["is_low_value"] is False


@pytest.mark.unit
class TestLinkedInCompanyPostAdapter:
    """Golden tests for apimaestro~linkedin-company-posts → linkedin/text_post."""

    def test_platform_and_content_type(self, linkedin_company_post_sample):
        """Should set platform=linkedin, content_type=text_post."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert result["platform"] == "linkedin"
        assert result["content_type"] == "text_post"

    def test_external_id_from_activity_urn(self, linkedin_company_post_sample):
        """Should use activity_urn as external_id."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert result["external_id"] == linkedin_company_post_sample["activity_urn"]
        assert result["external_id"] == "7414742659166302209"

    def test_canonical_url_mapping(self, linkedin_company_post_sample):
        """Should map post_url to canonical_url."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert result["canonical_url"] == linkedin_company_post_sample["post_url"]
        assert "linkedin.com/posts/" in result["canonical_url"]

    def test_published_at_from_posted_at_date(self, linkedin_company_post_sample):
        """Should parse posted_at.date to datetime."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert result["published_at"] is not None
        assert isinstance(result["published_at"], datetime)

    def test_author_ref_is_company_url(self, linkedin_company_post_sample):
        """Should use author.company_url as author_ref."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert "linkedin.com/company/nogood" in result["author_ref"]

    def test_text_primary_mapping(self, linkedin_company_post_sample):
        """Should map text to text_primary."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert result["text_primary"] == linkedin_company_post_sample["text"]
        assert "AI tools" in result["text_primary"]

    def test_hashtags_extracted_from_text(self, linkedin_company_post_sample):
        """Should extract hashtags from text."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        # LinkedIn posts don't have a separate hashtags field, so we extract from text
        # This sample doesn't have hashtags in the text
        assert isinstance(result["hashtags"], list)

    def test_metrics_json_structure(self, linkedin_company_post_sample):
        """Should include reactions in metrics_json."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert "reactions" in result["metrics_json"]
        assert result["metrics_json"]["reactions"] == 2

    def test_has_transcript_always_false(self, linkedin_company_post_sample):
        """LinkedIn posts don't have transcripts."""
        result = normalize_linkedin_company_post(linkedin_company_post_sample)
        assert result["flags_json"]["has_transcript"] is False


@pytest.mark.unit
class TestTikTokVideoAdapter:
    """Golden tests for clockworks~tiktok-scraper → tiktok/short_video."""

    def test_platform_and_content_type(self, tiktok_video_sample):
        """Should set platform=tiktok, content_type=short_video."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["platform"] == "tiktok"
        assert result["content_type"] == "short_video"

    def test_external_id_mapping(self, tiktok_video_sample):
        """Should map id to external_id."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["external_id"] == tiktok_video_sample["id"]
        assert result["external_id"] == "7592641437091532062"

    def test_canonical_url_from_web_video_url(self, tiktok_video_sample):
        """Should map webVideoUrl to canonical_url."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["canonical_url"] == tiktok_video_sample["webVideoUrl"]
        assert "tiktok.com/@nogood.io/video/" in result["canonical_url"]

    def test_published_at_from_create_time_iso(self, tiktok_video_sample):
        """Should parse createTimeISO to datetime."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["published_at"] is not None
        assert isinstance(result["published_at"], datetime)

    def test_author_ref_from_author_meta_name(self, tiktok_video_sample):
        """Should use authorMeta.name as author_ref."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["author_ref"] == "nogood.io"

    def test_text_primary_mapping(self, tiktok_video_sample):
        """Should map text to text_primary."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["text_primary"] == tiktok_video_sample["text"]
        assert "Pinterest" in result["text_primary"]

    def test_hashtags_extracted_from_objects(self, tiktok_video_sample):
        """Should extract hashtag names from hashtag objects."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert "pinterest" in result["hashtags"]
        assert "openai" in result["hashtags"]

    def test_metrics_json_structure(self, tiktok_video_sample):
        """Should include plays, likes, comments, shares, saves."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["metrics_json"]["plays"] == 295
        assert result["metrics_json"]["likes"] == 23
        assert result["metrics_json"]["comments"] == 0

    def test_has_transcript_false(self, tiktok_video_sample):
        """TikTok subtitleLinks are URLs, not text - has_transcript=false."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["flags_json"]["has_transcript"] is False

    def test_media_json_has_duration(self, tiktok_video_sample):
        """Should include duration in media_json."""
        result = normalize_tiktok_video(tiktok_video_sample)
        assert result["media_json"]["duration"] == 73


@pytest.mark.unit
class TestYouTubeVideoAdapter:
    """Golden tests for streamers~youtube-scraper → youtube/video."""

    def test_platform_and_content_type(self, youtube_video_sample):
        """Should set platform=youtube, content_type=video."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["platform"] == "youtube"
        assert result["content_type"] == "video"

    def test_external_id_mapping(self, youtube_video_sample):
        """Should map id to external_id."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["external_id"] == youtube_video_sample["id"]
        assert result["external_id"] == "8eEOaCCxGwo"

    def test_canonical_url_mapping(self, youtube_video_sample):
        """Should map url to canonical_url."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["canonical_url"] == youtube_video_sample["url"]
        assert "youtube.com/watch?v=" in result["canonical_url"]

    def test_published_at_from_date(self, youtube_video_sample):
        """Should parse date to datetime."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["published_at"] is not None
        assert isinstance(result["published_at"], datetime)

    def test_author_ref_is_channel_id(self, youtube_video_sample):
        """Should use channelId as author_ref."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["author_ref"] == youtube_video_sample["channelId"]

    def test_title_mapping(self, youtube_video_sample):
        """Should map title field."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["title"] == youtube_video_sample["title"]
        assert "SXSW" in result["title"]

    def test_text_primary_is_title(self, youtube_video_sample):
        """Per spec: text_primary = title for YouTube."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["text_primary"] == youtube_video_sample["title"]

    def test_text_secondary_is_description(self, youtube_video_sample):
        """Should map text (description) to text_secondary."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["text_secondary"] == youtube_video_sample["text"]
        assert "AI search" in result["text_secondary"]

    def test_metrics_json_structure(self, youtube_video_sample):
        """Should include views, likes, comments."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["metrics_json"]["views"] == 316
        assert result["metrics_json"]["likes"] == 2
        assert result["metrics_json"]["comments"] == 4

    def test_has_transcript_false(self, youtube_video_sample):
        """This actor doesn't provide transcripts."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["flags_json"]["has_transcript"] is False

    def test_media_json_has_duration(self, youtube_video_sample):
        """Should include duration in media_json."""
        result = normalize_youtube_video(youtube_video_sample)
        assert result["media_json"]["duration"] == "00:27:11"


@pytest.mark.unit
class TestWebPageAdapter:
    """Golden tests for apify~website-content-crawler → web/web_page."""

    def test_platform_and_content_type(self, web_page_sample):
        """Should set platform=web, content_type=web_page."""
        result = normalize_web_page(web_page_sample)
        assert result["platform"] == "web"
        assert result["content_type"] == "web_page"

    def test_external_id_is_none(self, web_page_sample):
        """Web pages use canonical_url for dedupe, not external_id."""
        result = normalize_web_page(web_page_sample)
        assert result["external_id"] is None

    def test_canonical_url_from_metadata(self, web_page_sample):
        """Should use metadata.canonicalUrl with fallback to url."""
        result = normalize_web_page(web_page_sample)
        assert result["canonical_url"] == "https://nogood.io/"

    def test_title_from_metadata(self, web_page_sample):
        """Should map metadata.title."""
        result = normalize_web_page(web_page_sample)
        assert "NoGood" in result["title"]
        assert "Growth Marketing" in result["title"]

    def test_text_primary_from_text(self, web_page_sample):
        """Should map text to text_primary."""
        result = normalize_web_page(web_page_sample)
        assert result["text_primary"] == web_page_sample["text"]
        assert "growth squad" in result["text_primary"]

    def test_text_secondary_from_description(self, web_page_sample):
        """Should map metadata.description to text_secondary."""
        result = normalize_web_page(web_page_sample)
        assert result["text_secondary"] == web_page_sample["metadata"]["description"]

    def test_hashtags_empty(self, web_page_sample):
        """Web pages don't have hashtags."""
        result = normalize_web_page(web_page_sample)
        assert result["hashtags"] == []

    def test_metrics_json_empty(self, web_page_sample):
        """Web pages don't have metrics."""
        result = normalize_web_page(web_page_sample)
        assert result["metrics_json"] == {}

    def test_is_collection_page_false_for_homepage(self, web_page_sample):
        """Homepage should not be marked as collection page."""
        result = normalize_web_page(web_page_sample)
        # This sample is a homepage, not a collection/blog index
        assert result["flags_json"]["is_collection_page"] is False

    def test_is_low_value_based_on_text_length(self):
        """Should be low_value if text < 200 chars."""
        raw = {
            "url": "https://example.com",
            "text": "Short",
            "metadata": {},
        }
        result = normalize_web_page(raw)
        assert result["flags_json"]["is_low_value"] is True

    def test_author_ref_is_domain(self, web_page_sample):
        """Should use domain as author_ref."""
        result = normalize_web_page(web_page_sample)
        assert result["author_ref"] == "nogood.io"


# =============================================================================
# B) IDEMPOTENCY TESTS - Database Operations
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        name="Test Tenant",
        slug="test-tenant",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand."""
    from kairo.core.models import Brand

    return Brand.objects.create(
        tenant=tenant,
        name="Test Brand",
        slug="test-brand",
    )


@pytest.fixture
def source_connection(db, brand):
    """Create a test source connection."""
    from kairo.brandbrain.models import SourceConnection

    return SourceConnection.objects.create(
        brand=brand,
        platform="instagram",
        capability="posts",
        identifier="https://instagram.com/test/",
        is_enabled=True,
    )


@pytest.fixture
def apify_run(db, brand, source_connection):
    """Create a test ApifyRun with raw items."""
    from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus, RawApifyItem

    run = ApifyRun.objects.create(
        actor_id="apify~instagram-scraper",
        apify_run_id=str(uuid.uuid4()),
        source_connection_id=source_connection.id,
        brand_id=brand.id,
        status=ApifyRunStatus.SUCCEEDED,
        dataset_id=str(uuid.uuid4()),
    )

    # Create raw items
    for i in range(3):
        RawApifyItem.objects.create(
            apify_run=run,
            item_index=i,
            raw_json={
                "id": f"post_{i}",
                "url": f"https://instagram.com/p/abc{i}/",
                "caption": f"Test post {i}",
                "hashtags": ["test"],
                "ownerUsername": "testuser",
                "timestamp": "2025-01-01T00:00:00.000Z",
                "likesCount": 10,
                "commentsCount": 2,
            },
        )

    return run


@pytest.mark.db
@pytest.mark.django_db
class TestNormalizationIdempotency:
    """Test idempotent dedupe and raw_refs merging."""

    def test_normalize_creates_items(self, apify_run):
        """First normalization should create items."""
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run

        result = normalize_apify_run(apify_run.id)

        assert result.items_created == 3
        assert result.items_updated == 0
        assert result.items_skipped == 0

        # Verify items created in DB
        items = NormalizedEvidenceItem.objects.filter(brand_id=apify_run.brand_id)
        assert items.count() == 3

    def test_normalize_twice_no_duplicates(self, apify_run):
        """Re-running normalization should not create duplicates."""
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run

        # First run
        result1 = normalize_apify_run(apify_run.id)
        assert result1.items_created == 3

        # Second run - same data
        result2 = normalize_apify_run(apify_run.id)
        assert result2.items_created == 0
        assert result2.items_updated == 3

        # Still only 3 items in DB
        items = NormalizedEvidenceItem.objects.filter(brand_id=apify_run.brand_id)
        assert items.count() == 3

    def test_raw_refs_merged_on_update(self, apify_run, brand, source_connection):
        """raw_refs should be merged (not replaced) on update."""
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus, RawApifyItem
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run

        # First run
        result1 = normalize_apify_run(apify_run.id)
        assert result1.items_created == 3

        # Check initial raw_refs
        item = NormalizedEvidenceItem.objects.get(
            brand_id=apify_run.brand_id,
            external_id="post_0",
        )
        assert len(item.raw_refs) == 1

        # Create a second ApifyRun with same content
        run2 = ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=brand.id,
            status=ApifyRunStatus.SUCCEEDED,
            dataset_id=str(uuid.uuid4()),
        )
        RawApifyItem.objects.create(
            apify_run=run2,
            item_index=0,
            raw_json={
                "id": "post_0",  # Same external_id
                "url": "https://instagram.com/p/abc0/",
                "caption": "Updated caption",
                "hashtags": ["updated"],
                "ownerUsername": "testuser",
                "timestamp": "2025-01-01T00:00:00.000Z",
                "likesCount": 20,
                "commentsCount": 5,
            },
        )

        # Normalize second run
        result2 = normalize_apify_run(run2.id)
        assert result2.items_updated == 1

        # raw_refs should now have 2 entries
        item.refresh_from_db()
        assert len(item.raw_refs) == 2

        # Both runs should be referenced
        run_ids = [ref["apify_run_id"] for ref in item.raw_refs]
        assert str(apify_run.id) in run_ids
        assert str(run2.id) in run_ids

    def test_raw_refs_not_duplicated(self, apify_run):
        """Same raw_ref should not be added twice."""
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run

        # Normalize same run twice
        normalize_apify_run(apify_run.id)
        normalize_apify_run(apify_run.id)

        # raw_refs should still have only 1 entry (not 2)
        item = NormalizedEvidenceItem.objects.get(
            brand_id=apify_run.brand_id,
            external_id="post_0",
        )
        assert len(item.raw_refs) == 1


@pytest.mark.db
@pytest.mark.django_db
class TestWebDeduplication:
    """Test web page deduplication by canonical_url."""

    @pytest.fixture
    def web_apify_run(self, db, brand):
        """Create a web ApifyRun."""
        from kairo.brandbrain.models import SourceConnection
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus, RawApifyItem

        source = SourceConnection.objects.create(
            brand=brand,
            platform="web",
            capability="crawl_pages",
            identifier="https://example.com/",
            is_enabled=True,
        )

        run = ApifyRun.objects.create(
            actor_id="apify~website-content-crawler",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source.id,
            brand_id=brand.id,
            status=ApifyRunStatus.SUCCEEDED,
            dataset_id=str(uuid.uuid4()),
        )

        RawApifyItem.objects.create(
            apify_run=run,
            item_index=0,
            raw_json={
                "url": "https://example.com/",
                "text": "This is a test page with enough content to pass the 200 char threshold for low value detection.",
                "metadata": {
                    "canonicalUrl": "https://example.com/",
                    "title": "Test Page",
                    "description": "A test page",
                },
            },
        )

        return run

    def test_web_dedupe_by_canonical_url(self, web_apify_run):
        """Web pages should dedupe by canonical_url, not external_id."""
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run

        # First run
        result1 = normalize_apify_run(web_apify_run.id)
        assert result1.items_created == 1

        # Second run - same data
        result2 = normalize_apify_run(web_apify_run.id)
        assert result2.items_created == 0
        assert result2.items_updated == 1

        # Only 1 item in DB
        items = NormalizedEvidenceItem.objects.filter(
            brand_id=web_apify_run.brand_id,
            platform="web",
        )
        assert items.count() == 1


# =============================================================================
# C) CAP WIRING TESTS
# =============================================================================


@pytest.mark.db
@pytest.mark.django_db
class TestCapEnforcement:
    """Test dataset-fetch cap enforcement in normalization."""

    @pytest.fixture
    def apify_run_with_many_items(self, db, brand, source_connection):
        """Create ApifyRun with more items than cap."""
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus, RawApifyItem

        run = ApifyRun.objects.create(
            actor_id="apify~instagram-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source_connection.id,
            brand_id=brand.id,
            status=ApifyRunStatus.SUCCEEDED,
            dataset_id=str(uuid.uuid4()),
        )

        # Create 20 items (way more than default cap of 8)
        for i in range(20):
            RawApifyItem.objects.create(
                apify_run=run,
                item_index=i,
                raw_json={
                    "id": f"post_{i}",
                    "url": f"https://instagram.com/p/post{i}/",
                    "caption": f"Test post {i}",
                    "hashtags": [],
                    "ownerUsername": "testuser",
                    "timestamp": "2025-01-01T00:00:00.000Z",
                    "likesCount": 10,
                    "commentsCount": 2,
                },
            )

        return run

    def test_normalization_respects_cap(self, apify_run_with_many_items, monkeypatch):
        """Normalization should only process up to cap items."""
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run
        from kairo.brandbrain.caps import clear_caps_cache

        # Set cap to 5
        monkeypatch.setenv("BRANDBRAIN_CAP_IG_POSTS", "5")
        clear_caps_cache()

        result = normalize_apify_run(apify_run_with_many_items.id)

        # Should only process 5 items due to cap
        assert result.items_processed == 5
        assert result.items_created == 5

        # Only 5 items in DB
        items = NormalizedEvidenceItem.objects.filter(
            brand_id=apify_run_with_many_items.brand_id,
        )
        assert items.count() == 5

    def test_fetch_limit_override(self, apify_run_with_many_items):
        """fetch_limit parameter should override cap."""
        from kairo.brandbrain.models import NormalizedEvidenceItem
        from kairo.brandbrain.normalization import normalize_apify_run

        result = normalize_apify_run(
            apify_run_with_many_items.id,
            fetch_limit=3,
        )

        # Should only process 3 items due to override
        assert result.items_processed == 3
        assert result.items_created == 3

    def test_cap_applied_from_platform_capability(self, db, brand):
        """Cap should be looked up from platform/capability."""
        from kairo.brandbrain.models import SourceConnection
        from kairo.integrations.apify.models import ApifyRun, ApifyRunStatus, RawApifyItem
        from kairo.brandbrain.normalization import normalize_apify_run
        from kairo.brandbrain.caps import clear_caps_cache, cap_for

        # Create TikTok source (default cap is 6)
        source = SourceConnection.objects.create(
            brand=brand,
            platform="tiktok",
            capability="profile_videos",
            identifier="testuser",
            is_enabled=True,
        )

        run = ApifyRun.objects.create(
            actor_id="clockworks~tiktok-scraper",
            apify_run_id=str(uuid.uuid4()),
            source_connection_id=source.id,
            brand_id=brand.id,
            status=ApifyRunStatus.SUCCEEDED,
            dataset_id=str(uuid.uuid4()),
        )

        # Create 10 items
        for i in range(10):
            RawApifyItem.objects.create(
                apify_run=run,
                item_index=i,
                raw_json={
                    "id": f"video_{i}",
                    "webVideoUrl": f"https://tiktok.com/@test/video/{i}",
                    "text": f"Video {i}",
                    "hashtags": [],
                    "createTimeISO": "2025-01-01T00:00:00.000Z",
                    "authorMeta": {"name": "test"},
                    "playCount": 100,
                    "diggCount": 10,
                    "commentCount": 5,
                    "shareCount": 2,
                    "collectCount": 1,
                    "videoMeta": {"duration": 30},
                },
            )

        clear_caps_cache()
        expected_cap = cap_for("tiktok", "profile_videos")  # Default 6

        result = normalize_apify_run(run.id)

        # Should process exactly cap items
        assert result.items_processed == expected_cap


@pytest.mark.unit
class TestCapWiringMocked:
    """Unit tests for cap wiring without database."""

    def test_service_calls_cap_for(self):
        """Verify normalize_apify_run calls cap_for for limit."""
        from unittest.mock import MagicMock, patch

        mock_run = MagicMock()
        mock_run.id = uuid.uuid4()
        mock_run.source_connection_id = uuid.uuid4()
        mock_run.brand_id = uuid.uuid4()
        mock_run.actor_id = "apify~instagram-scraper"

        mock_source = MagicMock()
        mock_source.platform = "instagram"
        mock_source.capability = "posts"

        with patch("kairo.brandbrain.normalization.service.ApifyRun") as mock_apify:
            with patch("kairo.brandbrain.normalization.service._get_source_connection") as mock_get_source:
                with patch("kairo.brandbrain.normalization.service._fetch_raw_items") as mock_fetch:
                    with patch("kairo.brandbrain.normalization.service.cap_for") as mock_cap_for:
                        mock_apify.objects.get.return_value = mock_run
                        mock_get_source.return_value = mock_source
                        mock_fetch.return_value = []
                        mock_cap_for.return_value = 8

                        from kairo.brandbrain.normalization.service import normalize_apify_run

                        normalize_apify_run(mock_run.id)

                        # Verify cap_for was called with correct args
                        mock_cap_for.assert_called_once_with("instagram", "posts")

                        # Verify fetch was called with cap as limit
                        mock_fetch.assert_called_once()
                        call_args = mock_fetch.call_args
                        assert call_args.kwargs["limit"] == 8


# =============================================================================
# ADDITIONAL EDGE CASE TESTS
# =============================================================================


@pytest.mark.unit
class TestAdapterEdgeCases:
    """Test adapter edge cases and defensive behavior."""

    def test_missing_fields_handled_gracefully(self):
        """Adapters should handle missing fields without crashing."""
        # Minimal raw data
        raw = {"id": "123"}
        result = normalize_instagram_post(raw)

        assert result["external_id"] == "123"
        assert result["canonical_url"] == ""
        assert result["text_primary"] == ""
        assert result["hashtags"] == []

    def test_none_values_handled(self):
        """Adapters should handle None values."""
        raw = {
            "id": "123",
            "caption": None,
            "hashtags": None,
            "timestamp": None,
        }
        result = normalize_instagram_post(raw)

        assert result["text_primary"] == ""
        assert result["hashtags"] == []
        assert result["published_at"] is None

    def test_invalid_timestamp_returns_none(self):
        """Invalid timestamps should return None, not crash."""
        raw = {
            "id": "123",
            "timestamp": "not-a-date",
        }
        result = normalize_instagram_post(raw)
        assert result["published_at"] is None

    def test_deeply_nested_missing_field(self):
        """Missing deeply nested fields should return default."""
        raw = {"id": "123"}
        result = normalize_tiktok_video(raw)

        # authorMeta.name is deeply nested
        assert result["author_ref"] == ""

    def test_collection_page_detection(self):
        """Test collection page detection from JSON-LD."""
        # CollectionPage type
        raw = {
            "url": "https://example.com/blog",
            "text": "Blog index page",
            "metadata": {
                "jsonLd": [
                    {"@type": "CollectionPage"}
                ]
            }
        }
        result = normalize_web_page(raw)
        assert result["flags_json"]["is_collection_page"] is True

        # CollectionPage in @graph
        raw2 = {
            "url": "https://example.com/blog",
            "text": "Blog index page",
            "metadata": {
                "jsonLd": [
                    {"@graph": [{"@type": "CollectionPage"}]}
                ]
            }
        }
        result2 = normalize_web_page(raw2)
        assert result2["flags_json"]["is_collection_page"] is True

        # Not a collection page
        raw3 = {
            "url": "https://example.com/about",
            "text": "About page with lots of content " * 20,
            "metadata": {
                "jsonLd": [
                    {"@type": "WebPage"}
                ]
            }
        }
        result3 = normalize_web_page(raw3)
        assert result3["flags_json"]["is_collection_page"] is False


# =============================================================================
# D) FEATURE FLAG TESTS - LinkedIn Profile Posts Gating
# =============================================================================


class TestLinkedInProfilePostsFeatureFlag:
    """Test that LinkedIn profile posts adapter is gated behind feature flag."""

    def test_adapter_not_available_by_default(self):
        """LinkedIn profile posts adapter should not be returned without feature flag."""
        # Ensure feature flag is not set
        import os
        os.environ.pop("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", None)

        adapter = get_adapter("apimaestro~linkedin-profile-posts")
        assert adapter is None, "Unvalidated adapter should not be available without feature flag"

    def test_adapter_available_with_feature_flag(self):
        """LinkedIn profile posts adapter should be available when feature flag is set."""
        import os
        os.environ["BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS"] = "true"

        try:
            adapter = get_adapter("apimaestro~linkedin-profile-posts")
            assert adapter is not None, "Adapter should be available with feature flag"
        finally:
            os.environ.pop("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", None)

    def test_validated_adapters_always_available(self):
        """Validated adapters should always be available regardless of feature flags."""
        import os
        # Ensure feature flag is not set
        os.environ.pop("BRANDBRAIN_ENABLE_LINKEDIN_PROFILE_POSTS", None)

        # All validated actors should have adapters
        validated_actors = [
            "apify~instagram-scraper",
            "apify~instagram-reel-scraper",
            "apimaestro~linkedin-company-posts",
            "clockworks~tiktok-scraper",
            "streamers~youtube-scraper",
            "apify~website-content-crawler",
        ]

        for actor_id in validated_actors:
            adapter = get_adapter(actor_id)
            assert adapter is not None, f"Validated adapter {actor_id} should always be available"


# =============================================================================
# E) DEDUPE CONSTRAINT TESTS - Non-web items must have external_id
# =============================================================================


class TestDedupeConstraintEnforcement:
    """Test that dedupe constraints are properly enforced."""

    def test_non_web_item_without_external_id_raises(self, brand, source_connection, apify_run):
        """Non-web items without external_id should raise ValueError."""
        from kairo.brandbrain.normalization.service import _upsert_normalized_item

        # Create normalized data for Instagram without external_id
        normalized_data = {
            "platform": "instagram",
            "content_type": "post",
            "external_id": None,  # Missing external_id!
            "canonical_url": "https://instagram.com/p/abc123",
            "published_at": None,
            "author_ref": "testuser",
            "title": None,
            "text_primary": "Test caption",
            "text_secondary": None,
            "hashtags": [],
            "metrics_json": {},
            "media_json": {},
            "flags_json": {},
        }

        raw_ref = {
            "apify_run_id": str(apify_run.id),
            "raw_item_id": str(uuid.uuid4()),
        }

        with pytest.raises(ValueError) as exc_info:
            _upsert_normalized_item(
                brand_id=brand.id,
                normalized_data=normalized_data,
                raw_ref=raw_ref,
            )

        assert "must have external_id for dedupe" in str(exc_info.value)
        assert "platform=instagram" in str(exc_info.value)

    def test_web_item_without_external_id_allowed(self, brand, source_connection, apify_run):
        """Web items can have external_id=None (they use canonical_url for dedupe)."""
        from kairo.brandbrain.normalization.service import _upsert_normalized_item

        # Create normalized data for web page without external_id (normal for web)
        normalized_data = {
            "platform": "web",
            "content_type": "web_page",
            "external_id": None,  # Expected for web - they use canonical_url
            "canonical_url": "https://example.com/about",
            "published_at": None,
            "author_ref": "example.com",
            "title": "About Us",
            "text_primary": "About page content",
            "text_secondary": None,
            "hashtags": [],
            "metrics_json": {},
            "media_json": {},
            "flags_json": {},
        }

        raw_ref = {
            "apify_run_id": str(apify_run.id),
            "raw_item_id": str(uuid.uuid4()),
        }

        # Should NOT raise - web items use canonical_url for dedupe
        created = _upsert_normalized_item(
            brand_id=brand.id,
            normalized_data=normalized_data,
            raw_ref=raw_ref,
        )

        assert created is True

    def test_non_web_item_with_external_id_works(self, brand, source_connection, apify_run):
        """Non-web items with external_id should work normally."""
        from kairo.brandbrain.normalization.service import _upsert_normalized_item

        # Create normalized data for Instagram with external_id
        normalized_data = {
            "platform": "instagram",
            "content_type": "post",
            "external_id": "12345678901234567",  # Has external_id
            "canonical_url": "https://instagram.com/p/abc123",
            "published_at": None,
            "author_ref": "testuser",
            "title": None,
            "text_primary": "Test caption",
            "text_secondary": None,
            "hashtags": [],
            "metrics_json": {},
            "media_json": {},
            "flags_json": {},
        }

        raw_ref = {
            "apify_run_id": str(apify_run.id),
            "raw_item_id": str(uuid.uuid4()),
        }

        # Should work fine with external_id
        created = _upsert_normalized_item(
            brand_id=brand.id,
            normalized_data=normalized_data,
            raw_ref=raw_ref,
        )

        assert created is True
