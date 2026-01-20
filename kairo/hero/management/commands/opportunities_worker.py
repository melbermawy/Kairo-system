"""
Management command for Opportunities generation worker.

PR1: Background execution infrastructure for opportunities v2.
Per opportunities_v1_prd.md §0.2 - TodayBoard State Machine.

Usage:
    python manage.py opportunities_worker

Options:
    --poll-interval: Seconds between job queue polls (default: 5)
    --stale-check-interval: Seconds between stale lock checks (default: 60)
    --max-jobs: Max jobs to process before exiting (0 = unlimited, default: 0)
    --once: Process one job and exit (for testing)
    --dry-run: Claim and log jobs without processing

The worker:
1. Polls for available jobs
2. Claims next job with atomic locking
3. Executes evidence gates (NO LLM in PR1)
4. Marks job succeeded/failed/insufficient_evidence
5. Periodically checks for stale locks

CRITICAL (PR1):
- NO LLM calls
- NO prompt execution
- NO synthesis
- ONLY evidence gates and state transitions
"""

from __future__ import annotations

import logging
import signal
import socket
import threading
import time
import uuid as uuid_module
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand

from kairo.hero.jobs.queue import (
    claim_next_job,
    complete_job,
    extend_job_lock,
    fail_job,
    fail_job_insufficient_evidence,
    release_stale_jobs,
)

if TYPE_CHECKING:
    from kairo.hero.models import OpportunitiesJob

logger = logging.getLogger(__name__)

# Heartbeat interval for extending job locks (seconds)
HEARTBEAT_INTERVAL_S = 30


class Command(BaseCommand):
    """Run Opportunities generation worker."""

    help = "Run Opportunities generation worker for processing durable jobs"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown_requested = False
        self._worker_id = f"{socket.gethostname()}-{uuid_module.uuid4().hex[:8]}"

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=5,
            help="Seconds between job queue polls (default: 5)",
        )
        parser.add_argument(
            "--stale-check-interval",
            type=int,
            default=60,
            help="Seconds between stale lock checks (default: 60)",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=0,
            help="Max jobs to process before exiting (0 = unlimited)",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process one job and exit (for testing)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Claim and log jobs without processing",
        )

    def handle(self, *args, **options):
        poll_interval = options["poll_interval"]
        stale_check_interval = options["stale_check_interval"]
        max_jobs = options["max_jobs"]
        once = options["once"]
        dry_run = options["dry_run"]

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.stdout.write(f"Starting Opportunities worker: {self._worker_id}")
        self.stdout.write(f"  Poll interval: {poll_interval}s")
        self.stdout.write(f"  Stale check interval: {stale_check_interval}s")
        if max_jobs > 0:
            self.stdout.write(f"  Max jobs: {max_jobs}")
        if dry_run:
            self.stdout.write("  DRY RUN MODE - jobs will be claimed but not processed")

        # PR1: Explicitly note that NO LLM calls are made
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("  PR1 MODE: Evidence gates only, NO LLM synthesis"))
        self.stdout.write("")

        jobs_processed = 0
        last_stale_check = time.monotonic()

        while not self._shutdown_requested:
            # Check for stale locks periodically
            now = time.monotonic()
            if now - last_stale_check >= stale_check_interval:
                released = release_stale_jobs()
                if released > 0:
                    self.stdout.write(f"Released {released} stale job(s)")
                last_stale_check = now

            # Try to claim a job
            result = claim_next_job(worker_id=self._worker_id)

            if result.claimed and result.job:
                job = result.job
                self.stdout.write(
                    f"Claimed job {job.id} (brand={job.brand_id}, "
                    f"attempt {job.attempts}/{job.max_attempts})"
                )

                if dry_run:
                    # Dry run: log and skip
                    self.stdout.write("  [DRY RUN] Skipping execution")
                    complete_job(job.id)
                else:
                    # Execute the job
                    self._execute_job(job)

                jobs_processed += 1

                # Check exit conditions
                if once:
                    self.stdout.write("Exiting after one job (--once)")
                    break
                if max_jobs > 0 and jobs_processed >= max_jobs:
                    self.stdout.write(f"Exiting after {max_jobs} job(s) (--max-jobs)")
                    break

            else:
                # No job available - sleep and retry
                time.sleep(poll_interval)

        if self._shutdown_requested:
            self.stdout.write("\nGraceful shutdown complete")

        self.stdout.write(f"Worker exiting. Jobs processed: {jobs_processed}")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        sig_name = signal.Signals(signum).name
        self.stdout.write(f"\nReceived {sig_name}, shutting down gracefully...")
        self._shutdown_requested = True

    def _execute_job(self, job: "OpportunitiesJob") -> None:
        """
        Execute an opportunities generation job.

        PR1: Evidence gates ONLY. No LLM synthesis.

        Pipeline:
        1. Fetch evidence from NormalizedEvidenceItem
        2. Run quality gates
        3. Run usability gates
        4. If gates pass: mark SUCCEEDED (no synthesis yet)
        5. If gates fail: mark INSUFFICIENT_EVIDENCE
        """
        from kairo.core.guardrails import is_apify_enabled
        from kairo.hero.tasks.generate import execute_opportunities_job

        # TASK-2: Extract mode from job params (critical for live vs fixture routing)
        job_params = job.params_json or {}
        mode = job_params.get("mode", "fixture_only")

        # TASK-2: JOB_START logging for observability
        # This is the first checkpoint - if you don't see this, the worker isn't processing jobs
        logger.info(
            "JOB_START job_id=%s brand_id=%s mode=%s apify_enabled=%s force=%s first_run=%s",
            job.id,
            job.brand_id,
            mode,
            is_apify_enabled(),
            job_params.get("force", False),
            job_params.get("first_run", False),
        )

        # Event to signal heartbeat thread to stop
        stop_heartbeat = threading.Event()

        def heartbeat_loop():
            """Background thread that extends job lock periodically."""
            while not stop_heartbeat.wait(timeout=HEARTBEAT_INTERVAL_S):
                try:
                    extended = extend_job_lock(job.id, self._worker_id)
                    if extended:
                        logger.debug(
                            "Heartbeat: extended lock for job %s",
                            job.id,
                        )
                    else:
                        logger.warning(
                            "Heartbeat: failed to extend lock for job %s",
                            job.id,
                        )
                except Exception as e:
                    logger.warning(
                        "Heartbeat error for job %s: %s",
                        job.id,
                        str(e),
                    )

        # Start heartbeat thread
        heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            name=f"heartbeat-{job.id}",
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            self.stdout.write(f"  Executing evidence gates for brand {job.brand_id} (mode={mode})...")

            # Run the generation task (PR1: gates only)
            # TASK-2: Pass mode explicitly from job params
            result = execute_opportunities_job(
                job_id=job.id,
                brand_id=job.brand_id,
                mode=mode,  # CRITICAL: Must pass mode from job params, not let it default
            )

            if result.success:
                self.stdout.write(self.style.SUCCESS(f"  Job {job.id} succeeded"))
            elif result.insufficient_evidence:
                self.stdout.write(
                    self.style.WARNING(f"  Job {job.id} completed: insufficient_evidence")
                )
            else:
                self.stdout.write(self.style.ERROR(f"  Job {job.id} failed: {result.error}"))

        except Exception as e:
            error_msg = str(e)
            logger.exception("Job %s failed: %s", job.id, error_msg)

            # Mark job failed (may retry)
            fail_job(job.id, error_msg)
            self.stdout.write(self.style.ERROR(f"  Job {job.id} failed: {error_msg[:100]}"))

        finally:
            # Stop heartbeat thread
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=1.0)
