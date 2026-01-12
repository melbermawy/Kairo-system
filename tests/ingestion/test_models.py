"""
Tests for ingestion models.

Per ingestion_spec_v2.md §13: Acceptance Tests.
"""

import pytest
from django.db import IntegrityError

from kairo.ingestion.models import (
    ArtifactClusterLink,
    CaptureRun,
    Cluster,
    ClusterBucket,
    EvidenceItem,
    NormalizedArtifact,
    Surface,
    TrendCandidate,
)


@pytest.mark.django_db
class TestSurfaceModel:
    """Tests for Surface model."""

    def test_create_surface(self):
        """Surface can be created with required fields."""
        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
        )
        assert surface.id is not None
        assert surface.platform == "tiktok"

    def test_surface_unique_constraint(self):
        """Duplicate (platform, surface_type, surface_key) raises IntegrityError."""
        Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
            surface_key="",
        )
        with pytest.raises(IntegrityError):
            Surface.objects.create(
                platform="tiktok",
                surface_type="discover",
                surface_key="",
            )


@pytest.mark.django_db
class TestClusterModel:
    """Tests for Cluster model."""

    def test_create_cluster(self):
        """Cluster can be created with required fields."""
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#viral",
            display_name="#viral",
        )
        assert cluster.id is not None
        assert cluster.platforms == []

    def test_cluster_unique_constraint(self):
        """Duplicate (cluster_key_type, cluster_key) raises IntegrityError."""
        Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#viral",
        )
        with pytest.raises(IntegrityError):
            Cluster.objects.create(
                cluster_key_type="hashtag",
                cluster_key="tiktok:#viral",
            )


@pytest.mark.django_db
class TestEvidenceItemModel:
    """Tests for EvidenceItem model."""

    def test_create_evidence_item(self):
        """EvidenceItem can be created with required fields."""
        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
        )
        capture_run = CaptureRun.objects.create(surface=surface)
        item = EvidenceItem.objects.create(
            capture_run=capture_run,
            platform="tiktok",
            platform_item_id="12345",
            item_type="video",
        )
        assert item.id is not None

    def test_evidence_item_unique_constraint(self):
        """Duplicate (platform, platform_item_id) raises IntegrityError."""
        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
        )
        capture_run = CaptureRun.objects.create(surface=surface)
        EvidenceItem.objects.create(
            capture_run=capture_run,
            platform="tiktok",
            platform_item_id="12345",
            item_type="video",
        )
        with pytest.raises(IntegrityError):
            EvidenceItem.objects.create(
                capture_run=capture_run,
                platform="tiktok",
                platform_item_id="12345",
                item_type="video",
            )


@pytest.mark.django_db
class TestArtifactClusterLink:
    """Tests for ArtifactClusterLink model and constraints."""

    def _create_artifact(self) -> NormalizedArtifact:
        """Helper to create an artifact with required dependencies."""
        surface = Surface.objects.create(
            platform="tiktok",
            surface_type="discover",
        )
        capture_run = CaptureRun.objects.create(surface=surface)
        item = EvidenceItem.objects.create(
            capture_run=capture_run,
            platform="tiktok",
            platform_item_id=f"item_{NormalizedArtifact.objects.count()}",
            item_type="video",
        )
        return NormalizedArtifact.objects.create(
            evidence_item=item,
            normalized_text="Test content",
            engagement_score=50.0,
        )

    def test_create_primary_link(self):
        """Primary link can be created."""
        artifact = self._create_artifact()
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#test",
            display_name="#test",
        )
        link = ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster,
            role="primary",
            key_type="hashtag",
            key_value="#test",
        )
        assert link.id is not None
        assert link.role == "primary"

    def test_exactly_one_primary_per_artifact(self):
        """Exactly one primary link per artifact enforced by constraint."""
        artifact = self._create_artifact()
        cluster1 = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#test1",
            display_name="#test1",
        )
        cluster2 = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#test2",
            display_name="#test2",
        )

        # First primary link
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster1,
            role="primary",
            key_type="hashtag",
        )

        # Second primary link should fail
        with pytest.raises(IntegrityError):
            ArtifactClusterLink.objects.create(
                artifact=artifact,
                cluster=cluster2,
                role="primary",
                key_type="hashtag",
            )

    def test_multiple_secondary_links_allowed(self):
        """Artifact can have multiple secondary links."""
        artifact = self._create_artifact()
        cluster1 = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#test1",
            display_name="#test1",
        )
        cluster2 = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#test2",
            display_name="#test2",
        )
        cluster3 = Cluster.objects.create(
            cluster_key_type="audio_id",
            cluster_key="tiktok:audio123",
            display_name="Audio 123",
        )

        # Create primary
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster3,
            role="primary",
            key_type="audio_id",
        )

        # Create multiple secondary links
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster1,
            role="secondary",
            key_type="hashtag",
            rank=0,
        )
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster2,
            role="secondary",
            key_type="hashtag",
            rank=1,
        )

        # Verify all links exist
        assert artifact.cluster_links.count() == 3
        assert artifact.cluster_links.filter(role="primary").count() == 1
        assert artifact.cluster_links.filter(role="secondary").count() == 2

    def test_get_primary_cluster_method(self):
        """NormalizedArtifact.get_primary_cluster() returns the primary cluster."""
        artifact = self._create_artifact()
        cluster = Cluster.objects.create(
            cluster_key_type="audio_id",
            cluster_key="tiktok:audio999",
            display_name="Audio 999",
        )
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster,
            role="primary",
            key_type="audio_id",
        )

        assert artifact.get_primary_cluster() == cluster

    def test_cascade_delete_on_evidence_item(self):
        """Deleting EvidenceItem cascades to artifact and links."""
        artifact = self._create_artifact()
        evidence_item = artifact.evidence_item
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#cascade",
            display_name="#cascade",
        )
        ArtifactClusterLink.objects.create(
            artifact=artifact,
            cluster=cluster,
            role="primary",
            key_type="hashtag",
        )

        artifact_id = artifact.id
        link_count_before = ArtifactClusterLink.objects.count()

        # Delete the evidence item
        evidence_item.delete()

        # Verify cascade
        assert not NormalizedArtifact.objects.filter(id=artifact_id).exists()
        assert ArtifactClusterLink.objects.count() < link_count_before
