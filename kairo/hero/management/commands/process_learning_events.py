"""
Management command to process learning events.

PR-4: Decisions + Learning Pipeline (Deterministic, No LLM).

Usage:
    python manage.py process_learning_events --brand-id <uuid> [--hours <int>]

This command processes recent ExecutionEvents for a brand and generates
LearningEvents based on deterministic rules.

Per PR-map-and-standards §PR-4:
- Accepts --brand-id (required) and --hours (default 24)
- Calls learning_service.process_recent_execution_events
- Prints summary of events processed and learning events created

Failure Behavior (PR-4 Audit §5):
- If an exception occurs during processing, the command:
  1. Lets the exception propagate (Django management framework catches it)
  2. Exits with non-zero status code
  3. Logs the error via Django's error handling
- This is deterministic: any failure aborts the entire run, no partial results.
- ValidationError (invalid UUID, missing brand, invalid hours) raises CommandError.
"""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from kairo.core.models import Brand
from kairo.hero.services import learning_service


class Command(BaseCommand):
    """Process execution events and generate learning events for a brand."""

    help = "Process execution events and generate learning events for a brand"

    def add_arguments(self, parser):
        parser.add_argument(
            "--brand-id",
            type=str,
            required=True,
            help="UUID of the brand to process",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Number of hours to look back (default: 24)",
        )

    def handle(self, *args, **options):
        brand_id_str = options["brand_id"]
        hours = options["hours"]

        # Validate brand_id is a valid UUID
        try:
            brand_id = UUID(brand_id_str)
        except ValueError:
            raise CommandError(f"Invalid UUID format: {brand_id_str}")

        # Validate brand exists
        if not Brand.objects.filter(id=brand_id).exists():
            raise CommandError(f"Brand not found: {brand_id}")

        # Validate hours is positive
        if hours <= 0:
            raise CommandError(f"Hours must be positive, got: {hours}")

        self.stdout.write(
            f"Processing execution events for brand {brand_id} "
            f"(last {hours} hours)..."
        )

        # Process events
        result = learning_service.process_recent_execution_events(
            brand_id=brand_id,
            hours=hours,
        )

        # Report results
        events_processed = result["events_processed"]
        learning_events_created = result["learning_events_created"]

        if events_processed == 0:
            self.stdout.write(
                self.style.WARNING(
                    f"No execution events found for brand {brand_id} "
                    f"in the last {hours} hours"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed {events_processed} execution events, "
                    f"created {learning_events_created} learning events"
                )
            )

        # Optionally show created learning events
        if learning_events_created > 0 and options.get("verbosity", 1) >= 2:
            self.stdout.write("\nCreated learning events:")
            for event in result["learning_events"]:
                self.stdout.write(
                    f"  - {event.signal_type.value}: "
                    f"weight_delta={event.payload.get('weight_delta', 0):.2f}, "
                    f"variant_id={event.variant_id}"
                )
