"""
Tests for trend emitter service.

Per ingestion_spec_v2.md §11: Hero Integration.
"""

import pytest
from datetime import datetime, timezone

from kairo.ingestion.models import Cluster, TrendCandidate
from kairo.ingestion.services.trend_emitter import (
    get_trend_signals_for_brand,
    get_external_signal_bundle,
)


@pytest.mark.django_db
class TestTrendEmitter:
    """Tests for trend emitter service."""

    def test_get_signals_empty(self):
        """Returns empty list when no candidates exist."""
        signals = get_trend_signals_for_brand("test-brand-id")
        assert signals == []

    def test_get_bundle_empty(self):
        """Returns bundle with empty trends when no candidates exist."""
        bundle = get_external_signal_bundle("test-brand-id")
        assert bundle.trends == []
        assert bundle.competitor_posts == []
        assert bundle.social_moments == []

    def test_get_signals_with_candidates(self):
        """Returns signals for active candidates."""
        # Create test cluster and candidate
        cluster = Cluster.objects.create(
            cluster_key_type="hashtag",
            cluster_key="tiktok:#test",
            display_name="#test",
            platforms=["tiktok"],
        )
        candidate = TrendCandidate.objects.create(
            cluster=cluster,
            status="emerging",
            trend_score=75.0,
            detected_at=datetime.now(timezone.utc),
        )

        signals = get_trend_signals_for_brand("test-brand-id")

        assert len(signals) == 1
        assert signals[0].topic == "#test"
        assert signals[0].source == "tiktok"
        assert signals[0].relevance_score == 0.75
