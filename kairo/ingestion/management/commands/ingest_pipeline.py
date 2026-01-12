"""
Management command to run full ingestion pipeline.

Usage:
    python manage.py ingest_pipeline
    python manage.py ingest_pipeline --skip-capture
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from kairo.ingestion.jobs.aggregate import run_aggregate
from kairo.ingestion.jobs.normalize import run_normalize
from kairo.ingestion.jobs.score import run_score

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run full ingestion pipeline (normalize -> aggregate -> score)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-capture",
            action="store_true",
            help="Skip capture stage (process existing EvidenceItems only)",
        )

    def handle(self, *args, **options):
        skip_capture = options["skip_capture"]

        if not skip_capture:
            self.stdout.write(
                self.style.WARNING(
                    "Capture stage not implemented in pipeline. "
                    "Run ingest_capture separately."
                )
            )

        # Stage 2: Normalize
        self.stdout.write("Stage 2: Normalizing...")
        norm_result = run_normalize()
        self.stdout.write(
            f"  Normalized: {norm_result['processed']} items, "
            f"{norm_result['errors']} errors"
        )

        # Stage 3: Aggregate
        self.stdout.write("Stage 3: Aggregating...")
        agg_result = run_aggregate()
        self.stdout.write(
            f"  Aggregated: {agg_result['buckets_updated']} buckets"
        )

        # Stage 4: Score
        self.stdout.write("Stage 4: Scoring...")
        score_result = run_score()
        self.stdout.write(
            f"  Scored: {score_result['candidates_created']} new, "
            f"{score_result['transitions']} transitions"
        )

        self.stdout.write(self.style.SUCCESS("Pipeline complete!"))
