"""
Management command to run scoring and lifecycle job.

Usage:
    python manage.py ingest_score
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from kairo.ingestion.jobs.score import run_score

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run scoring and lifecycle job"

    def handle(self, *args, **options):
        self.stdout.write("Running scoring job...")

        result = run_score()

        self.stdout.write(
            self.style.SUCCESS(
                f"Scoring complete: "
                f"created={result['candidates_created']}, "
                f"updated={result['candidates_updated']}, "
                f"transitions={result['transitions']}, "
                f"stale={result['stale_count']}"
            )
        )
