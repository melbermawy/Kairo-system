"""
Management command to run bucket aggregation job.

Usage:
    python manage.py ingest_aggregate
    python manage.py ingest_aggregate --window=30
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from kairo.ingestion.jobs.aggregate import run_aggregate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run bucket aggregation job"

    def add_arguments(self, parser):
        parser.add_argument(
            "--window",
            type=int,
            default=60,
            help="Bucket window size in minutes (default: 60)",
        )

    def handle(self, *args, **options):
        window = options["window"]

        self.stdout.write(f"Running aggregation job (window={window}min)...")

        result = run_aggregate(window_minutes=window)

        self.stdout.write(
            self.style.SUCCESS(
                f"Aggregation complete: "
                f"buckets_updated={result['buckets_updated']}, "
                f"clusters_processed={result['clusters_processed']}"
            )
        )
