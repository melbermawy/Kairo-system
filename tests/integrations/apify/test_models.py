"""
Tests for Apify models.

Tests model constraints and relationships.
"""

import pytest
from django.db import IntegrityError

from kairo.integrations.apify.models import ApifyRun, RawApifyItem


@pytest.mark.django_db
class TestApifyRunModel:
    """Tests for ApifyRun model."""

    def test_create_apify_run(self):
        """Can create ApifyRun with required fields."""
        run = ApifyRun.objects.create(
            actor_id="apify/instagram-reel-scraper",
            input_json={"username": ["wendys"]},
            apify_run_id="run123",
        )
        assert run.id is not None
        assert run.status == "pending"
        assert run.item_count == 0

    def test_apify_run_id_unique(self):
        """apify_run_id must be unique."""
        ApifyRun.objects.create(
            actor_id="actor1",
            apify_run_id="run123",
        )
        with pytest.raises(IntegrityError):
            ApifyRun.objects.create(
                actor_id="actor2",
                apify_run_id="run123",  # Duplicate
            )

    def test_apify_run_str(self):
        """ApifyRun __str__ includes actor_id."""
        run = ApifyRun.objects.create(
            actor_id="apify/instagram-reel-scraper",
            apify_run_id="run123",
        )
        assert "instagram-reel-scraper" in str(run)


@pytest.mark.django_db
class TestRawApifyItemModel:
    """Tests for RawApifyItem model."""

    def test_create_raw_apify_item(self):
        """Can create RawApifyItem with required fields."""
        run = ApifyRun.objects.create(
            actor_id="actor/test",
            apify_run_id="run123",
        )
        item = RawApifyItem.objects.create(
            apify_run=run,
            item_index=0,
            raw_json={"id": "post123", "caption": "Hello world"},
        )
        assert item.id is not None
        assert item.raw_json["caption"] == "Hello world"

    def test_item_index_unique_per_run(self):
        """item_index must be unique per apify_run."""
        run = ApifyRun.objects.create(
            actor_id="actor/test",
            apify_run_id="run123",
        )
        RawApifyItem.objects.create(apify_run=run, item_index=0, raw_json={})

        with pytest.raises(IntegrityError):
            RawApifyItem.objects.create(apify_run=run, item_index=0, raw_json={})

    def test_item_index_can_repeat_across_runs(self):
        """Same item_index allowed in different runs."""
        run1 = ApifyRun.objects.create(
            actor_id="actor/test",
            apify_run_id="run1",
        )
        run2 = ApifyRun.objects.create(
            actor_id="actor/test",
            apify_run_id="run2",
        )

        # Both can have item_index=0
        RawApifyItem.objects.create(apify_run=run1, item_index=0, raw_json={})
        item2 = RawApifyItem.objects.create(apify_run=run2, item_index=0, raw_json={})
        assert item2.id is not None

    def test_cascade_delete(self):
        """Deleting ApifyRun cascades to RawApifyItem."""
        run = ApifyRun.objects.create(
            actor_id="actor/test",
            apify_run_id="run123",
        )
        RawApifyItem.objects.create(apify_run=run, item_index=0, raw_json={})
        RawApifyItem.objects.create(apify_run=run, item_index=1, raw_json={})

        assert RawApifyItem.objects.count() == 2

        run.delete()

        assert RawApifyItem.objects.count() == 0

    def test_items_related_name(self):
        """Can access items via ApifyRun.items."""
        run = ApifyRun.objects.create(
            actor_id="actor/test",
            apify_run_id="run123",
        )
        RawApifyItem.objects.create(apify_run=run, item_index=0, raw_json={"a": 1})
        RawApifyItem.objects.create(apify_run=run, item_index=1, raw_json={"b": 2})

        items = list(run.items.order_by("item_index"))
        assert len(items) == 2
        assert items[0].raw_json == {"a": 1}
        assert items[1].raw_json == {"b": 2}
