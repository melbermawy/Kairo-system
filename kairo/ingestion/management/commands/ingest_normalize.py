"""
Management command to run normalization job.

Usage:
    python manage.py ingest_normalize
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from kairo.ingestion.jobs.normalize import run_normalize

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run normalization job on pending EvidenceItems"

    def handle(self, *args, **options):
        self.stdout.write("Running normalization job...")

        result = run_normalize()

        self.stdout.write(
            self.style.SUCCESS(
                f"Normalization complete: "
                f"processed={result['processed']}, "
                f"skipped={result['skipped']}, "
                f"errors={result['errors']}"
            )
        )
