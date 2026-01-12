"""
Apify raw storage models.

Per brandbrain_spec_skeleton.md §7: Apify Integration Contract.

Models:
- ApifyRun: Metadata for a single actor run
- RawApifyItem: Raw JSON item from a dataset (immutable)

Design principle: Store raw first. Normalization is a second pass.
"""

from __future__ import annotations

import uuid

from django.db import models


class ApifyRun(models.Model):
    """
    Metadata for a single Apify actor run.

    Tracks the run lifecycle from start to completion,
    including any errors encountered.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("timed_out", "Timed Out"),
        ("aborted", "Aborted"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_id = models.CharField(max_length=255)  # e.g., "apify/instagram-reel-scraper"
    input_json = models.JSONField(default=dict)  # Actor input configuration
    apify_run_id = models.CharField(max_length=255, unique=True)  # Apify's run ID
    dataset_id = models.CharField(max_length=255, blank=True)  # May be null until run completes
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="pending")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    item_count = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)  # Error message if failed
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "apify"
        db_table = "apify_run"
        indexes = [
            models.Index(fields=["actor_id", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.actor_id} @ {self.created_at.isoformat()}"


class RawApifyItem(models.Model):
    """
    Raw JSON item from an Apify dataset.

    Immutable after creation. Contains the exact JSON
    returned by the Apify API, unmodified.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    apify_run = models.ForeignKey(
        ApifyRun,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_index = models.PositiveIntegerField()  # Position in dataset (0-indexed)
    raw_json = models.JSONField(default=dict)  # Exact JSON from Apify
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "apify"
        db_table = "apify_raw_item"
        constraints = [
            models.UniqueConstraint(
                fields=["apify_run", "item_index"],
                name="uniq_run_item_index",
            )
        ]
        indexes = [
            models.Index(fields=["apify_run", "item_index"]),
        ]

    def __str__(self) -> str:
        return f"{self.apify_run.actor_id}[{self.item_index}]"
