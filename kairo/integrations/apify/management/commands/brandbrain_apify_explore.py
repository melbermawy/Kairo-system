"""
Management command for BrandBrain Apify exploration.

Per brandbrain_spec_skeleton.md §10: Step 1 Exploration Plan.

Two modes of operation:

1. START NEW RUN (requires --actor-id AND input):
    python manage.py brandbrain_apify_explore \\
        --actor-id "apify~instagram-scraper" \\
        --input-json '{"username": ["wendys"], "resultsLimit": 20}'

2. RESUME EXISTING RUN (budget-safe, no new Apify run started):
    python manage.py brandbrain_apify_explore \\
        --existing-run-id "abc123xyz" \\
        --actor-id "apify~instagram-scraper"

    # If dataset ID is already known, skip polling:
    python manage.py brandbrain_apify_explore \\
        --existing-run-id "abc123xyz" \\
        --dataset-id "def456uvw" \\
        --actor-id "apify~instagram-scraper"

This command:
1. Starts OR resumes an Apify actor run
2. Polls until completion (unless --dataset-id provided)
3. Fetches dataset items
4. Stores ApifyRun + RawApifyItem rows (idempotent upsert)
5. Saves sample JSON files under var/apify_samples/
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from kairo.integrations.apify.client import (
    ApifyClient,
    ApifyError,
    ApifyTimeoutError,
    RunInfo,
)
from kairo.integrations.apify.models import ApifyRun, RawApifyItem


class Command(BaseCommand):
    """Run or resume Apify actor and store raw results for BrandBrain exploration."""

    help = "Run or resume Apify actor and store raw results for BrandBrain exploration"

    def add_arguments(self, parser):
        # Actor ID - required for new runs, optional for resume
        parser.add_argument(
            "--actor-id",
            type=str,
            help="Apify actor ID (e.g., 'apify~instagram-scraper'). Required for new runs.",
        )

        # Input for new runs: --input-file or --input-json
        parser.add_argument(
            "--input-file",
            type=str,
            help="Path to JSON file with actor input (for new runs)",
        )
        parser.add_argument(
            "--input-json",
            type=str,
            help="JSON string with actor input (for new runs)",
        )

        # Resume mode flags
        parser.add_argument(
            "--existing-run-id",
            type=str,
            help="Apify run ID to resume (skips starting new run, budget-safe)",
        )
        parser.add_argument(
            "--dataset-id",
            type=str,
            help="Apify dataset ID (skip polling if provided with --existing-run-id)",
        )

        # Common flags
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Max items to fetch (default: 20, hard cap: 50)",
        )
        parser.add_argument(
            "--timeout-s",
            type=int,
            default=180,
            help="Max seconds to wait for run completion (default: 180)",
        )
        parser.add_argument(
            "--interval-s",
            type=int,
            default=3,
            help="Polling interval in seconds (default: 3)",
        )
        parser.add_argument(
            "--save-samples",
            type=int,
            default=3,
            help="Number of items to save as sample files (default: 3)",
        )

    def handle(self, *args, **options):
        # Validate and determine mode
        existing_run_id = options.get("existing_run_id")
        dataset_id = options.get("dataset_id")
        actor_id = options.get("actor_id")
        input_file = options.get("input_file")
        input_json = options.get("input_json")

        limit = options["limit"]
        timeout_s = options["timeout_s"]
        interval_s = options["interval_s"]
        save_samples = options["save_samples"]

        # Validate limit (hard cap 50)
        if limit > 50:
            raise CommandError("--limit cannot exceed 50 (free-tier cap)")
        if limit <= 0:
            raise CommandError("--limit must be positive")

        # Validate token
        token = settings.APIFY_TOKEN
        if not token:
            raise CommandError("APIFY_TOKEN not set. Add it to .env or environment.")

        base_url = settings.APIFY_BASE_URL

        # Determine mode and validate arguments
        if existing_run_id:
            # RESUME MODE
            mode = "resume"
            if input_file or input_json:
                raise CommandError(
                    "--input-file/--input-json not allowed with --existing-run-id"
                )
            # actor_id is optional in resume mode (will use "unknown" if not provided)
            if not actor_id:
                actor_id = ""
        else:
            # NEW RUN MODE
            mode = "new"
            if not actor_id:
                raise CommandError("--actor-id is required for new runs")
            if not input_file and not input_json:
                raise CommandError(
                    "Either --input-file or --input-json is required for new runs"
                )
            if input_file and input_json:
                raise CommandError(
                    "--input-file and --input-json are mutually exclusive"
                )

        # Create client
        client = ApifyClient(token=token, base_url=base_url)

        if mode == "new":
            self._handle_new_run(
                client=client,
                actor_id=actor_id,
                options=options,
                limit=limit,
                timeout_s=timeout_s,
                interval_s=interval_s,
                save_samples=save_samples,
            )
        else:
            self._handle_resume(
                client=client,
                existing_run_id=existing_run_id,
                dataset_id=dataset_id,
                actor_id=actor_id,
                limit=limit,
                timeout_s=timeout_s,
                interval_s=interval_s,
                save_samples=save_samples,
            )

    def _handle_new_run(
        self,
        client: ApifyClient,
        actor_id: str,
        options: dict,
        limit: int,
        timeout_s: int,
        interval_s: int,
        save_samples: int,
    ):
        """Handle starting a new actor run."""
        input_json = self._parse_input(options)

        self.stdout.write("Starting NEW Apify exploration:")
        self.stdout.write(f"  Actor: {actor_id}")
        self.stdout.write(f"  Limit: {limit}")
        self.stdout.write(f"  Timeout: {timeout_s}s")
        self.stdout.write(f"  Save samples: {save_samples}")
        self.stdout.write("")

        try:
            # Step 1: Start actor run
            self.stdout.write("Starting actor run...")
            run_info = client.start_actor_run(actor_id, input_json)
            self.stdout.write(f"  Run ID: {run_info.run_id}")
            self.stdout.write(f"  Status: {run_info.status}")

            # Upsert ApifyRun record
            apify_run = self._upsert_apify_run(
                apify_run_id=run_info.run_id,
                actor_id=actor_id,
                input_json=input_json,
                dataset_id=run_info.dataset_id or "",
                status="running",
                started_at=run_info.started_at,
            )

            # Step 2: Poll until completion
            self.stdout.write("")
            self.stdout.write("Polling for completion...")
            run_info = client.poll_run(
                run_info.run_id,
                timeout_s=timeout_s,
                interval_s=interval_s,
            )
            self.stdout.write(f"  Final status: {run_info.status}")

            # Update ApifyRun with final status
            apify_run = self._upsert_apify_run(
                apify_run_id=run_info.run_id,
                actor_id=actor_id,
                input_json=input_json,
                dataset_id=run_info.dataset_id or "",
                status=run_info.status.lower(),
                started_at=run_info.started_at,
                finished_at=run_info.finished_at,
                error_summary=run_info.error_message or "",
            )

            if not run_info.is_success():
                self.stdout.write(
                    self.style.ERROR(f"Run failed with status: {run_info.status}")
                )
                if run_info.error_message:
                    self.stdout.write(f"Error: {run_info.error_message}")
                return

            # Fetch and store items
            self._fetch_and_store_items(
                client=client,
                apify_run=apify_run,
                dataset_id=run_info.dataset_id,
                actor_id=actor_id,
                limit=limit,
                save_samples=save_samples,
            )

        except ApifyTimeoutError as e:
            self.stdout.write(self.style.ERROR(f"Timeout: {e}"))
            raise CommandError(str(e))

        except ApifyError as e:
            self.stdout.write(self.style.ERROR(f"Apify error: {e}"))
            raise CommandError(str(e))

    def _handle_resume(
        self,
        client: ApifyClient,
        existing_run_id: str,
        dataset_id: str | None,
        actor_id: str,
        limit: int,
        timeout_s: int,
        interval_s: int,
        save_samples: int,
    ):
        """Handle resuming an existing run (budget-safe)."""
        self.stdout.write("RESUMING existing Apify run (no new run started):")
        self.stdout.write(f"  Existing Run ID: {existing_run_id}")
        if dataset_id:
            self.stdout.write(f"  Dataset ID: {dataset_id} (skipping poll)")
        if actor_id:
            self.stdout.write(f"  Actor: {actor_id}")
        self.stdout.write(f"  Limit: {limit}")
        self.stdout.write("")

        try:
            final_status = "succeeded"
            final_dataset_id = dataset_id
            started_at = None
            finished_at = None
            error_message = None

            if not dataset_id:
                # Need to poll for status and dataset_id
                self.stdout.write("Polling for run status...")
                run_info = client.poll_run(
                    existing_run_id,
                    timeout_s=timeout_s,
                    interval_s=interval_s,
                )
                self.stdout.write(f"  Final status: {run_info.status}")

                final_status = run_info.status.lower()
                final_dataset_id = run_info.dataset_id
                started_at = run_info.started_at
                finished_at = run_info.finished_at
                error_message = run_info.error_message

                # Update actor_id from run_info if we didn't have it
                if not actor_id and run_info.actor_id:
                    actor_id = run_info.actor_id

                if not run_info.is_success():
                    # Upsert failed run
                    self._upsert_apify_run(
                        apify_run_id=existing_run_id,
                        actor_id=actor_id or "",
                        input_json={},
                        dataset_id=final_dataset_id or "",
                        status=final_status,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_summary=error_message or "",
                    )
                    self.stdout.write(
                        self.style.ERROR(f"Run failed with status: {run_info.status}")
                    )
                    if error_message:
                        self.stdout.write(f"Error: {error_message}")
                    raise CommandError(f"Run failed: {run_info.status}")

            if not final_dataset_id:
                raise CommandError("No dataset_id available (run may not have completed)")

            # Upsert ApifyRun
            apify_run = self._upsert_apify_run(
                apify_run_id=existing_run_id,
                actor_id=actor_id or "",
                input_json={},
                dataset_id=final_dataset_id,
                status=final_status,
                started_at=started_at,
                finished_at=finished_at,
            )

            # Fetch and store items
            self._fetch_and_store_items(
                client=client,
                apify_run=apify_run,
                dataset_id=final_dataset_id,
                actor_id=actor_id or "",
                limit=limit,
                save_samples=save_samples,
            )

        except ApifyTimeoutError as e:
            self.stdout.write(self.style.ERROR(f"Timeout: {e}"))
            raise CommandError(str(e))

        except ApifyError as e:
            self.stdout.write(self.style.ERROR(f"Apify error: {e}"))
            raise CommandError(str(e))

    def _upsert_apify_run(
        self,
        apify_run_id: str,
        actor_id: str,
        input_json: dict,
        dataset_id: str,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_summary: str = "",
    ) -> ApifyRun:
        """Upsert ApifyRun by apify_run_id (idempotent)."""
        defaults = {
            "dataset_id": dataset_id,
            "status": status,
        }
        # Only update these if provided
        if actor_id:
            defaults["actor_id"] = actor_id
        if input_json:
            defaults["input_json"] = input_json
        if started_at:
            defaults["started_at"] = started_at
        if finished_at:
            defaults["finished_at"] = finished_at
        if error_summary:
            defaults["error_summary"] = error_summary

        apify_run, created = ApifyRun.objects.update_or_create(
            apify_run_id=apify_run_id,
            defaults=defaults,
        )

        if created:
            # Ensure actor_id is set even if empty
            if not apify_run.actor_id:
                apify_run.actor_id = actor_id or ""
                apify_run.save()

        return apify_run

    def _fetch_and_store_items(
        self,
        client: ApifyClient,
        apify_run: ApifyRun,
        dataset_id: str,
        actor_id: str,
        limit: int,
        save_samples: int,
    ):
        """Fetch dataset items and store them (idempotent)."""
        self.stdout.write("")
        self.stdout.write(f"Fetching up to {limit} items from dataset...")
        items = client.fetch_dataset_items(dataset_id, limit=limit, offset=0)
        self.stdout.write(f"  Fetched {len(items)} items")

        # Store RawApifyItem rows (idempotent - skip existing)
        self.stdout.write("")
        self.stdout.write("Storing raw items in database...")
        created_count = 0
        skipped_count = 0

        for idx, item in enumerate(items):
            _, created = RawApifyItem.objects.get_or_create(
                apify_run=apify_run,
                item_index=idx,
                defaults={"raw_json": item},
            )
            if created:
                created_count += 1
            else:
                skipped_count += 1

        # Update item count
        apify_run.item_count = apify_run.items.count()
        apify_run.save()

        self.stdout.write(f"  Created {created_count} new RawApifyItem rows")
        if skipped_count > 0:
            self.stdout.write(f"  Skipped {skipped_count} existing rows (idempotent)")

        # Save sample files
        self.stdout.write("")
        sample_dir = self._save_samples(actor_id, apify_run, items, save_samples)
        if sample_dir:
            self.stdout.write(f"  Samples saved to: {sample_dir}")

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("EXPLORATION COMPLETE"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"  ApifyRun ID: {apify_run.id}")
        self.stdout.write(f"  Apify Run ID: {apify_run.apify_run_id}")
        self.stdout.write(f"  Dataset ID: {apify_run.dataset_id}")
        self.stdout.write(f"  Items stored: {apify_run.item_count}")
        self.stdout.write("")

    def _parse_input(self, options) -> dict:
        """Parse input JSON from file or string."""
        if options.get("input_file"):
            path = Path(options["input_file"])
            if not path.exists():
                raise CommandError(f"Input file not found: {path}")
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid JSON in input file: {e}")
        elif options.get("input_json"):
            try:
                return json.loads(options["input_json"])
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid JSON in --input-json: {e}")
        return {}

    def _save_samples(
        self,
        actor_id: str,
        apify_run: ApifyRun,
        items: list[dict],
        count: int,
    ) -> Path | None:
        """
        Save sample items as JSON files under var/apify_samples/.

        Files are overwritten deterministically if they already exist.
        """
        if count <= 0 or not items:
            return None

        # Sanitize actor_id for filesystem (handle both / and ~ separators)
        safe_actor_id = re.sub(r"[^\w\-]", "_", actor_id) if actor_id else "unknown"

        # Create directory: var/apify_samples/<actor_id>/<run_uuid>/
        base_dir = Path(settings.BASE_DIR) / "var" / "apify_samples"
        sample_dir = base_dir / safe_actor_id / str(apify_run.id)
        sample_dir.mkdir(parents=True, exist_ok=True)

        # Save first N items (overwrite if exists)
        for idx, item in enumerate(items[:count]):
            sample_path = sample_dir / f"item_{idx}.json"
            sample_path.write_text(json.dumps(item, indent=2, ensure_ascii=False))
            self.stdout.write(f"  Saved: {sample_path.relative_to(settings.BASE_DIR)}")

        return sample_dir
