"""
Management command to run capture for a surface.

Usage:
    python manage.py ingest_capture --surface=tiktok_discover
    python manage.py ingest_capture --surface=reddit_rising --args='{"subreddit":"marketing"}'
"""

from __future__ import annotations

import json
import logging

from django.core.management.base import BaseCommand, CommandError

from kairo.ingestion.capture.adapters import ADAPTER_REGISTRY

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run capture for a surface"

    def add_arguments(self, parser):
        parser.add_argument(
            "--surface",
            type=str,
            required=True,
            help="Surface type to capture (e.g., tiktok_discover, reddit_rising)",
        )
        parser.add_argument(
            "--args",
            type=str,
            default="{}",
            help="JSON args for adapter (e.g., '{\"subreddit\": \"marketing\"}')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print captured items without saving to DB",
        )

    def handle(self, *args, **options):
        surface_type = options["surface"]
        adapter_args = json.loads(options["args"])
        dry_run = options["dry_run"]

        if surface_type not in ADAPTER_REGISTRY:
            available = ", ".join(ADAPTER_REGISTRY.keys())
            raise CommandError(
                f"Unknown surface: {surface_type}. Available: {available}"
            )

        adapter_class = ADAPTER_REGISTRY[surface_type]
        adapter = adapter_class(**adapter_args)

        self.stdout.write(f"Running capture for {surface_type}...")

        try:
            items = adapter.capture()
        except Exception as e:
            raise CommandError(f"Capture failed: {e}")

        self.stdout.write(f"Captured {len(items)} items")

        if dry_run:
            for item in items[:5]:
                self.stdout.write(f"  - {item.platform_item_id}: {item.text_content[:50]}...")
            if len(items) > 5:
                self.stdout.write(f"  ... and {len(items) - 5} more")
            return

        # TODO: Save items to EvidenceItem
        # For now, just report
        self.stdout.write(
            self.style.SUCCESS(f"Captured {len(items)} items (saving not implemented)")
        )
