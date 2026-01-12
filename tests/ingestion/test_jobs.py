"""
Tests for ingestion pipeline jobs.

Per ingestion_spec_v2.md §13: Acceptance Tests.
"""

import pytest
from datetime import datetime, timedelta, timezone

from kairo.ingestion.jobs.aggregate import run_aggregate, _align_to_bucket
from kairo.ingestion.jobs.normalize import run_normalize
from kairo.ingestion.jobs.score import (
    run_score,
    _compute_trend_score,
    select_scoring_path,
)
from kairo.ingestion.models import (
    ArtifactClusterLink,
    CaptureRun,
    Cluster,
    ClusterBucket,
    EvidenceItem,
    NormalizedArtifact,
    Surface,
)


class TestBucketAlignment:
    """Tests for bucket time alignment."""

    def test_align_to_hour(self):
        """14:23 aligns to 14:00 with 60-min window."""
        dt = datetime(2024, 1, 1, 14, 23, 45, tzinfo=timezone.utc)
        aligned = _align_to_bucket(dt, 60)
        assert aligned.hour == 14
        assert aligned.minute == 0
        assert aligned.second == 0

    def test_align_to_30min(self):
        """14:45 aligns to 14:30 with 30-min window."""
        dt = datetime(2024, 1, 1, 14, 45, 0, tzinfo=timezone.utc)
        aligned = _align_to_bucket(dt, 30)
        assert aligned.hour == 14
        assert aligned.minute == 30


@pytest.mark.django_db
class TestNormalizeJob:
    """Tests for normalization job."""

    def test_normalize_empty(self):
        """Normalize with no items returns zero counts."""
        result = run_normalize()
        assert result["processed"] == 0
        assert result["errors"] == 0

    def test_normalize_creates_primary_and_secondary_links(self):
        """
        Given one EvidenceItem with audio_id + hashtags,
        normalization creates artifact, cluster rows,
        1 primary link (audio_id), N secondary links (hashtags).
        """
        # Create test surface and capture run
        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
        )
        capture_run = CaptureRun.objects.create(surface=surface)

        # Create evidence item with audio_id and multiple hashtags
        item = EvidenceItem.objects.create(
            capture_run=capture_run,
            platform="tiktok",
            platform_item_id="test_video_123",
            item_type="video",
            audio_id="audio_456",
            audio_title="Trending Sound",
            hashtags=["viral", "fyp", "trending"],
            text_content="Check out this #viral #fyp #trending video",
        )

        # Run normalize
        result = run_normalize()

        assert result["processed"] == 1
        assert result["errors"] == 0

        # Verify artifact was created
        artifact = NormalizedArtifact.objects.get(evidence_item=item)
        assert artifact is not None

        # Verify cluster links
        links = ArtifactClusterLink.objects.filter(artifact=artifact)
        primary_links = links.filter(role="primary")
        secondary_links = links.filter(role="secondary")

        # Should have exactly 1 primary link (audio_id)
        assert primary_links.count() == 1
        primary = primary_links.first()
        assert primary.key_type == "audio_id"
        assert primary.cluster.cluster_key_type == "audio_id"

        # Should have 3 secondary links (hashtags)
        assert secondary_links.count() == 3

        # Verify get_primary_cluster method
        primary_cluster = artifact.get_primary_cluster()
        assert primary_cluster == primary.cluster


@pytest.mark.django_db
class TestAggregateJob:
    """Tests for aggregation job."""

    def test_aggregate_empty(self):
        """Aggregate with no items returns zero counts."""
        result = run_aggregate()
        assert result["buckets_updated"] == 0
        assert result["clusters_processed"] == 0


@pytest.mark.django_db
class TestScoreJob:
    """Tests for scoring job."""

    def test_score_empty(self):
        """Score with no candidates returns zero counts."""
        result = run_score()
        assert result["candidates_created"] == 0
        assert result["candidates_updated"] == 0


@pytest.mark.django_db
class TestScoringPathSelection:
    """Tests for scoring path A/B selection."""

    def test_path_a_with_views(self):
        """Bucket with total_views > 0 chooses Path A (counters)."""
        cluster = Cluster.objects.create(
            cluster_key_type="audio_id",
            cluster_key="tiktok:audio_123",
            display_name="Audio 123",
        )
        now = datetime.now(timezone.utc)
        bucket = ClusterBucket.objects.create(
            cluster=cluster,
            bucket_start=now - timedelta(hours=1),
            bucket_end=now,
            artifact_count=10,
            unique_authors=8,
            total_views=1000,  # Has views
            total_engagement=0,
        )

        path = select_scoring_path(bucket)
        assert path == "counters"

    def test_path_a_with_engagement(self):
        """Bucket with total_engagement > 0 chooses Path A (counters)."""
        cluster = Cluster.objects.create(
            cluster_key_type="audio_id",
            cluster_key="tiktok:audio_124",
            display_name="Audio 124",
        )
        now = datetime.now(timezone.utc)
        bucket = ClusterBucket.objects.create(
            cluster=cluster,
            bucket_start=now - timedelta(hours=1),
            bucket_end=now,
            artifact_count=10,
            unique_authors=8,
            total_views=0,
            total_engagement=500,  # Has engagement
        )

        path = select_scoring_path(bucket)
        assert path == "counters"

    def test_path_b_without_counters(self):
        """Bucket with no views or engagement chooses Path B (sampling)."""
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="reddit:#discussion",
            display_name="#discussion",
        )
        now = datetime.now(timezone.utc)
        bucket = ClusterBucket.objects.create(
            cluster=cluster,
            bucket_start=now - timedelta(hours=1),
            bucket_end=now,
            artifact_count=10,
            unique_authors=8,
            total_views=0,  # No views
            total_engagement=0,  # No engagement
        )

        path = select_scoring_path(bucket)
        assert path == "sampling"

    def test_score_in_valid_range(self):
        """Computed trend scores are in [0, 100] range."""
        cluster = Cluster.objects.create(
            cluster_key_type="audio_id",
            cluster_key="tiktok:audio_125",
            display_name="Audio 125",
        )
        now = datetime.now(timezone.utc)

        # Create bucket with high activity
        bucket = ClusterBucket.objects.create(
            cluster=cluster,
            bucket_start=now - timedelta(hours=1),
            bucket_end=now,
            artifact_count=100,
            unique_authors=80,
            total_views=2_000_000,  # Very high views
            total_engagement=500_000,  # Very high engagement
            velocity=20,
        )

        score, components = _compute_trend_score(cluster, [bucket], now)

        assert 0 <= score <= 100
        assert components["path"] == "counters"

    def test_score_path_b_in_valid_range(self):
        """Path B scores are in [0, 100] range."""
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="reddit:#test",
            display_name="#test",
        )
        now = datetime.now(timezone.utc)

        # Create bucket without counters
        bucket = ClusterBucket.objects.create(
            cluster=cluster,
            bucket_start=now - timedelta(hours=1),
            bucket_end=now,
            artifact_count=100,
            unique_authors=80,
            total_views=0,
            total_engagement=0,
            velocity=15,
        )

        score, components = _compute_trend_score(cluster, [bucket], now)

        assert 0 <= score <= 100
        assert components["path"] == "sampling"
