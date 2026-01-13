# PR-6: Durable Compile Jobs + Real Ingestion/Normalization Wiring

## Overview

PR-6 replaces PR-5's non-durable ThreadPoolExecutor with a DB-backed job queue and wires real Apify ingestion into the compile pipeline.

### Key Deliverables

1. **Durable Job Queue**: DB-backed job model with leasing/locking
2. **Worker Command**: `python manage.py brandbrain_worker`
3. **Real Ingestion**: Apify actor runs, raw item storage, normalization
4. **Cap Enforcement**: Actor input caps + dataset fetch caps
5. **Evidence Status**: reused/refreshed/skipped/failed tracking

---

## Table of Contents

1. [Job Model](#1-job-model)
2. [Job Queue Service](#2-job-queue-service)
3. [Worker Command](#3-worker-command)
4. [Ingestion Service](#4-ingestion-service)
5. [Compile Worker](#5-compile-worker)
6. [Cap Enforcement Points](#6-cap-enforcement-points)
7. [Job Status Transitions](#7-job-status-transitions)
8. [Evidence Status Schema](#8-evidence-status-schema)
9. [Tests](#9-tests)

---

## 1. Job Model

**File**: `kairo/brandbrain/models.py`

```python
class BrandBrainJobStatus:
    """
    Status constants for BrandBrainJob.

    Job lifecycle: PENDING -> RUNNING -> SUCCEEDED/FAILED
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BrandBrainJob(models.Model):
    """
    Durable job queue for BrandBrain compile jobs.

    PR-6: DB-backed job queue for production durability.
    Replaces ThreadPoolExecutor for surviving restarts.

    Job leasing:
    - Worker claims job by setting status=RUNNING, locked_at, locked_by
    - Atomic update ensures no double-claiming
    - Stale lock detection via locked_at threshold

    Retry policy:
    - max_attempts default 3
    - available_at for exponential backoff
    - last_error for debugging
    """

    JOB_TYPE_CHOICES = [
        ("compile", "Compile BrandBrain"),
    ]

    STATUS_CHOICES = [
        (BrandBrainJobStatus.PENDING, "Pending"),
        (BrandBrainJobStatus.RUNNING, "Running"),
        (BrandBrainJobStatus.SUCCEEDED, "Succeeded"),
        (BrandBrainJobStatus.FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="brandbrain_jobs",
    )
    compile_run = models.ForeignKey(
        BrandBrainCompileRun,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="jobs",
    )
    job_type = models.CharField(max_length=50, choices=JOB_TYPE_CHOICES, default="compile")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=BrandBrainJobStatus.PENDING,
        db_index=True,
    )

    # Retry tracking
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_error = models.TextField(null=True, blank=True)

    # Job leasing
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=255, null=True, blank=True)  # worker identifier

    # Scheduling
    available_at = models.DateTimeField(auto_now_add=True)  # for backoff scheduling

    # Job parameters
    params_json = models.JSONField(default=dict)  # force_refresh, prompt_version, model

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "brandbrain"
        db_table = "brandbrain_job"
        indexes = [
            # Worker query: find next available job
            models.Index(
                fields=["status", "available_at"],
                name="idx_job_status_available",
            ),
            # Brand job history
            models.Index(
                fields=["brand", "-created_at"],
                name="idx_job_brand_created",
            ),
        ]
```

---

## 2. Job Queue Service

**File**: `kairo/brandbrain/jobs/queue.py`

### Enqueue Function

```python
def enqueue_compile_job(
    brand_id: UUID,
    compile_run_id: UUID,
    *,
    force_refresh: bool = False,
    prompt_version: str = "v1",
    model: str = "gpt-4",
) -> EnqueueResult:
    """
    Enqueue a compile job for background execution.

    Creates a BrandBrainJob in PENDING status.
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    job = BrandBrainJob.objects.create(
        brand_id=brand_id,
        compile_run_id=compile_run_id,
        job_type="compile",
        status=BrandBrainJobStatus.PENDING,
        params_json={
            "force_refresh": force_refresh,
            "prompt_version": prompt_version,
            "model": model,
        },
    )

    logger.info(
        "Enqueued compile job %s for brand %s (compile_run=%s)",
        job.id,
        brand_id,
        compile_run_id,
    )

    return EnqueueResult(
        job_id=job.id,
        compile_run_id=compile_run_id,
    )
```

### Claim/Lock Logic

```python
def claim_next_job(
    worker_id: str | None = None,
    job_type: str = "compile",
) -> ClaimResult:
    """
    Claim the next available job with atomic locking.

    Uses optimistic locking pattern:
    1. Find jobs WHERE status=PENDING AND available_at <= now
    2. Update first one to status=RUNNING, set locked_at/locked_by
    3. Return the job if successful

    SQLite compatibility:
    - Uses atomic transaction instead of SELECT FOR UPDATE
    - Single UPDATE with filter ensures no double-claiming
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    if worker_id is None:
        worker_id = f"{socket.gethostname()}-{uuid_module.uuid4().hex[:8]}"

    now = timezone.now()

    with transaction.atomic():
        # Find next available job
        # Ordered by available_at (for backoff) then created_at (FIFO)
        job = (
            BrandBrainJob.objects
            .filter(
                job_type=job_type,
                status=BrandBrainJobStatus.PENDING,
                available_at__lte=now,
            )
            .order_by("available_at", "created_at")
            .first()
        )

        if not job:
            return ClaimResult(
                job=None,
                claimed=False,
                reason="No available jobs",
            )

        # Atomic claim: only succeeds if still PENDING
        # This prevents race conditions even without SELECT FOR UPDATE
        rows_updated = BrandBrainJob.objects.filter(
            id=job.id,
            status=BrandBrainJobStatus.PENDING,
        ).update(
            status=BrandBrainJobStatus.RUNNING,
            locked_at=now,
            locked_by=worker_id,
            attempts=F("attempts") + 1,
        )

        if rows_updated == 0:
            # Another worker claimed it first
            return ClaimResult(
                job=None,
                claimed=False,
                reason="Job claimed by another worker",
            )

        # Refresh the job to get updated values
        job.refresh_from_db()

        return ClaimResult(
            job=job,
            claimed=True,
        )
```

### Fail with Retry/Backoff

```python
def fail_job(job_id: UUID, error: str) -> bool:
    """
    Mark a job as failed with retry logic.

    If attempts < max_attempts:
    - Sets status back to PENDING
    - Sets available_at for exponential backoff
    - Stores error in last_error

    If attempts >= max_attempts:
    - Sets status to FAILED permanently
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    try:
        job = BrandBrainJob.objects.get(id=job_id)
    except BrandBrainJob.DoesNotExist:
        return False

    now = timezone.now()

    if job.attempts >= job.max_attempts:
        # Permanent failure
        job.status = BrandBrainJobStatus.FAILED
        job.finished_at = now
        job.last_error = error
        job.locked_at = None
        job.locked_by = None
        job.save(update_fields=[
            "status", "finished_at", "last_error", "locked_at", "locked_by"
        ])
        return True

    # Retry with exponential backoff
    backoff_seconds = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** job.attempts)
    available_at = now + timedelta(seconds=backoff_seconds)

    job.status = BrandBrainJobStatus.PENDING
    job.available_at = available_at
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    job.save(update_fields=[
        "status", "available_at", "last_error", "locked_at", "locked_by"
    ])

    return True
```

---

## 3. Worker Command

**File**: `kairo/brandbrain/management/commands/brandbrain_worker.py`

```python
class Command(BaseCommand):
    """Run BrandBrain compile worker."""

    help = "Run BrandBrain compile worker for processing durable jobs"

    def handle(self, *args, **options):
        poll_interval = options["poll_interval"]
        stale_check_interval = options["stale_check_interval"]
        max_jobs = options["max_jobs"]
        once = options["once"]
        dry_run = options["dry_run"]

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

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
                self._execute_job(job)
                jobs_processed += 1

                # Check exit conditions
                if once or (max_jobs > 0 and jobs_processed >= max_jobs):
                    break
            else:
                # No job available - sleep and retry
                time.sleep(poll_interval)

    def _execute_job(self, job: "BrandBrainJob") -> None:
        """Execute a compile job."""
        from kairo.brandbrain.compile.worker import execute_compile_job

        try:
            params = job.params_json or {}
            force_refresh = params.get("force_refresh", False)

            execute_compile_job(
                compile_run_id=job.compile_run_id,
                force_refresh=force_refresh,
            )

            complete_job(job.id)
        except Exception as e:
            fail_job(job.id, str(e))
```

**Usage**:
```bash
# Start worker
python manage.py brandbrain_worker

# Options
python manage.py brandbrain_worker --poll-interval 5 --stale-check-interval 60
python manage.py brandbrain_worker --max-jobs 10
python manage.py brandbrain_worker --once  # Process one job and exit
python manage.py brandbrain_worker --dry-run  # Claim without processing
```

---

## 4. Ingestion Service

**File**: `kairo/brandbrain/ingestion/service.py`

```python
def ingest_source(
    source_connection: "SourceConnection",
    *,
    poll_timeout_s: int = DEFAULT_POLL_TIMEOUT_S,
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    apify_client: ApifyClient | None = None,
) -> IngestionResult:
    """
    Ingest evidence from a source connection.

    End-to-end ingestion:
    1. Get actor spec for platform/capability
    2. Build actor input with cap
    3. Start Apify actor run
    4. Poll until terminal status
    5. Fetch raw items with cap
    6. Store RawApifyItem rows
    7. Call normalization service
    """
    result = IngestionResult(source_connection_id=source_connection.id)

    # Step 1: Check capability is enabled
    if not is_capability_enabled(platform, capability):
        result.error = f"Capability {platform}.{capability} is disabled"
        return result

    # Step 2: Get actor spec
    spec = get_actor_spec(platform, capability)
    if not spec:
        result.error = f"No actor spec for {platform}.{capability}"
        return result

    # Step 3: Get cap and build input
    cap = cap_for(platform, capability)
    input_json = spec.build_input(source_connection, cap)

    # Step 4: Create/get Apify client
    if apify_client is None:
        apify_client = ApifyClient(token=token, base_url=base_url)

    # Step 5: Start actor run
    run_info = apify_client.start_actor_run(spec.actor_id, input_json)

    # Create ApifyRun record
    apify_run = ApifyRun.objects.create(
        actor_id=spec.actor_id,
        input_json=input_json,
        apify_run_id=run_info.run_id,
        dataset_id=run_info.dataset_id or "",
        status=ApifyRunStatus.RUNNING,
        started_at=run_info.started_at,
        source_connection_id=source_connection.id,
        brand_id=source_connection.brand_id,
    )
    result.apify_run_id = apify_run.id

    # Step 6: Poll until terminal status
    final_run_info = apify_client.poll_run(
        run_info.run_id,
        timeout_s=poll_timeout_s,
        interval_s=poll_interval_s,
    )

    # Step 7: Fetch raw items with cap enforcement
    # CRITICAL: Pass cap as limit to enforce dataset-fetch cap
    raw_items = apify_client.fetch_dataset_items(
        dataset_id,
        limit=cap,  # CAP ENFORCEMENT
        offset=0,
    )

    # Step 8: Store RawApifyItem rows
    with transaction.atomic():
        # Clear existing items for this run (idempotent replace)
        RawApifyItem.objects.filter(apify_run=apify_run).delete()

        # Bulk create new items
        raw_item_objects = [
            RawApifyItem(
                apify_run=apify_run,
                item_index=idx,
                raw_json=item,
            )
            for idx, item in enumerate(raw_items)
        ]
        RawApifyItem.objects.bulk_create(raw_item_objects)

    # Step 9: Call normalization service
    norm_result = normalize_apify_run(apify_run.id, fetch_limit=cap)
    result.normalized_items_created = norm_result.items_created
    result.normalized_items_updated = norm_result.items_updated
    result.success = True

    return result
```

---

## 5. Compile Worker

**File**: `kairo/brandbrain/compile/worker.py`

```python
def execute_compile_job(
    compile_run_id: UUID,
    force_refresh: bool = False,
) -> None:
    """
    Execute the compile pipeline for a compile run.

    Pipeline:
    1. Set compile_run status RUNNING
    2. Load onboarding answers
    3. For each enabled source:
       - Check capability enabled
       - Freshness decision (refresh vs reuse)
       - If refresh: run Apify actor -> fetch raw -> normalize
       - If reuse: ensure normalization exists
    4. Create EvidenceBundle
    5. Create FeatureReport
    6. LLM compile (STUB for PR-6)
    7. Create BrandBrainSnapshot
    8. Mark SUCCEEDED or FAILED
    """
    # Step 3: Process each enabled source
    for source in sources:
        source_key = f"{source.platform}.{source.capability}"

        # Check if capability is enabled (feature flag)
        if not is_capability_enabled(source.platform, source.capability):
            evidence_status["skipped"].append({
                "source": source_key,
                "reason": "Capability disabled (feature flag)",
            })
            continue

        # Check freshness
        freshness = check_source_freshness(source.id, force_refresh=force_refresh)

        if freshness.should_refresh:
            # Trigger real ingestion
            result = ingest_source(source)

            if result.success:
                evidence_status["refreshed"].append({
                    "source": source_key,
                    "reason": freshness.reason,
                    "apify_run_id": str(result.apify_run_id),
                    "apify_run_status": result.apify_run_status,
                    "raw_items_count": result.raw_items_count,
                    "normalized_created": result.normalized_items_created,
                    "normalized_updated": result.normalized_items_updated,
                })
            else:
                evidence_status["failed"].append({
                    "source": source_key,
                    "reason": freshness.reason,
                    "error": result.error,
                })
        else:
            # Reuse cached run
            if freshness.cached_run:
                result = reuse_cached_run(source, freshness.cached_run)
                evidence_status["reused"].append({
                    "source": source_key,
                    "reason": freshness.reason,
                    "run_age_hours": freshness.run_age_hours,
                    "apify_run_id": str(freshness.cached_run.id),
                })
```

---

## 6. Cap Enforcement Points

| Location | Cap Type | Enforcement |
|----------|----------|-------------|
| `ingestion/service.py:ingest_source()` | Actor input | `spec.build_input(source_connection, cap)` |
| `ingestion/service.py:ingest_source()` | Dataset fetch | `fetch_dataset_items(dataset_id, limit=cap)` |
| `normalization/service.py:normalize_apify_run()` | Raw item fetch | `[:fetch_limit]` slice on RawApifyItem query |
| `bundling/service.py:create_evidence_bundle()` | Per-platform | `_get_cap_for_item(platform, content_type)` |
| `bundling/service.py:create_evidence_bundle()` | Global max | `global_max_normalized_items()` |

---

## 7. Job Status Transitions

| From | To | Trigger | Action |
|------|-----|---------|--------|
| - | PENDING | `enqueue_compile_job()` | Job created |
| PENDING | RUNNING | `claim_next_job()` | Worker claims job |
| RUNNING | SUCCEEDED | `complete_job()` | Job completed successfully |
| RUNNING | PENDING | `fail_job()` (attempts < max) | Scheduled for retry |
| RUNNING | FAILED | `fail_job()` (attempts >= max) | Permanent failure |
| RUNNING | PENDING | `release_stale_jobs()` | Stale lock released |
| RUNNING | FAILED | `release_stale_jobs()` (max attempts) | Stale + max attempts |

---

## 8. Evidence Status Schema

```json
{
  "reused": [
    {
      "source": "instagram.posts",
      "reason": "Cached run is fresh (5.2h old, TTL=24h)",
      "run_age_hours": 5.2,
      "apify_run_id": "uuid-string",
      "normalized_created": 0,
      "normalized_updated": 0
    }
  ],
  "refreshed": [
    {
      "source": "instagram.reels",
      "reason": "Cached run is stale (26.1h old, TTL=24h)",
      "apify_run_id": "uuid-string",
      "apify_run_status": "SUCCEEDED",
      "raw_items_count": 6,
      "normalized_created": 5,
      "normalized_updated": 1
    }
  ],
  "skipped": [
    {
      "source": "linkedin.profile_posts",
      "reason": "Capability disabled (feature flag)"
    }
  ],
  "failed": [
    {
      "source": "tiktok.profile_videos",
      "reason": "No successful run exists for this source",
      "error": "Polling timed out after 300s",
      "apify_run_id": "uuid-string",
      "apify_run_status": "timed_out"
    }
  ]
}
```

---

## 9. Tests

**File**: `tests/brandbrain/test_pr6_jobs_ingestion.py`

### Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| A) Job Queue Operations | 4 | enqueue, claim, complete, fail |
| B) Job Leasing | 2 | atomic claiming, no double-execution |
| C) Stale Lock Detection | 2 | release stale jobs, fail after max attempts |
| D) Ingestion Service | 3 | success, disabled capability, poll timeout |
| E) Cap Enforcement | 2 | actor input caps, dataset fetch caps |
| F) Compile Worker | 2 | triggers ingestion, reuses fresh source |
| G) Evidence Status | 3 | refreshed, reused, skipped tracking |
| H) Cross-Brand Security | 2 | job brand association, compile status enforcement |

### Running Tests

```bash
# Run PR-6 tests only
pytest tests/brandbrain/test_pr6_jobs_ingestion.py -v --tb=short

# Run all brandbrain tests
pytest tests/brandbrain/ -v --tb=short

# Run with specific marker
pytest tests/brandbrain/ -m db -v --tb=short
```

---

## Summary

PR-6 delivers:

- ✅ **Durable Job Queue**: `BrandBrainJob` model with leasing/locking
- ✅ **Worker Command**: `brandbrain_worker` management command
- ✅ **Real Ingestion**: Apify actor runs → raw storage → normalization
- ✅ **Cap Enforcement**: Actor input + dataset fetch limits
- ✅ **Retry Policy**: Max 3 attempts, exponential backoff
- ✅ **Evidence Tracking**: reused/refreshed/skipped/failed status
- ✅ **Cross-Brand Security**: Preserved from PR-5
- ✅ **SQLite Test Compatibility**: sync mode for tests

The compile kickoff stays fast (<200ms) by enqueueing jobs instead of executing inline.

---

## Appendix A — Production Footguns: Timeouts, Idempotency, Stale Leases, Backoff

This appendix contains verbatim code pastes with risk analysis for production-critical behaviors.

---

### A1) Polling Loop + Timeout Enforcement

**File**: `kairo/integrations/apify/client.py:139-202`

```python
def poll_run(
    self,
    run_id: str,
    timeout_s: int = 180,
    interval_s: int = 3,
) -> RunInfo:
    """
    Poll run status until terminal state or timeout.

    Args:
        run_id: Apify run ID
        timeout_s: Maximum time to wait (seconds)
        interval_s: Polling interval (seconds)

    Returns:
        RunInfo with final status

    Raises:
        ApifyTimeoutError: If polling times out
        ApifyError: If API returns an error
    """
    url = f"{self.base_url}/v2/actor-runs/{run_id}"
    start_time = time.monotonic()
    logger.info("Polling run: run_id=%s, timeout_s=%d", run_id, timeout_s)

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > timeout_s:
            raise ApifyTimeoutError(
                f"Polling timed out after {timeout_s}s for run_id={run_id}"
            )

        try:
            response = self._session.get(url, timeout=30)
        except requests.RequestException as e:
            raise ApifyError(f"Request failed: {e}") from e

        if not response.ok:
            raise ApifyError(
                f"Failed to get run status: {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )

        data = response.json().get("data", {})
        # Extract actor_id from response or use empty string
        actor_id = data.get("actId", data.get("actorId", ""))
        run_info = self._parse_run_info(data, actor_id)

        if run_info.is_terminal():
            logger.info(
                "Run completed: run_id=%s, status=%s",
                run_info.run_id,
                run_info.status,
            )
            return run_info

        logger.debug(
            "Run still in progress: run_id=%s, status=%s, elapsed=%.1fs",
            run_id,
            run_info.status,
            elapsed,
        )
        time.sleep(interval_s)
```

**Terminal status recognition** (`kairo/integrations/apify/client.py:67-73`):

```python
def is_terminal(self) -> bool:
    """Return True if run is in a terminal state."""
    return self.status in ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED")

def is_success(self) -> bool:
    """Return True if run succeeded."""
    return self.status == "SUCCEEDED"
```

**Ingestion timeout handling** (`kairo/brandbrain/ingestion/service.py:57-61, 211-244`):

```python
# Default poll timeout (seconds)
DEFAULT_POLL_TIMEOUT_S = 300  # 5 minutes

# Poll interval (seconds)
DEFAULT_POLL_INTERVAL_S = 5
```

```python
# Step 6: Poll until terminal status
try:
    final_run_info = apify_client.poll_run(
        run_info.run_id,
        timeout_s=poll_timeout_s,
        interval_s=poll_interval_s,
    )
except ApifyTimeoutError as e:
    # Update ApifyRun with timeout status
    apify_run.status = ApifyRunStatus.TIMED_OUT
    apify_run.finished_at = timezone.now()
    apify_run.error_summary = str(e)
    apify_run.save(update_fields=["status", "finished_at", "error_summary"])
    result.apify_run_status = ApifyRunStatus.TIMED_OUT
    result.error = f"Polling timed out: {e}"
    logger.warning(
        "Ingestion timed out for %s: %s",
        source_connection.id,
        result.error,
    )
    return result
except ApifyError as e:
    apify_run.status = ApifyRunStatus.FAILED
    apify_run.finished_at = timezone.now()
    apify_run.error_summary = str(e)
    apify_run.save(update_fields=["status", "finished_at", "error_summary"])
    result.apify_run_status = ApifyRunStatus.FAILED
    result.error = f"Polling failed: {e}"
    logger.exception(
        "Ingestion failed for %s: %s",
        source_connection.id,
        result.error,
    )
    return result
```

**Invariants enforced:**
- `time.monotonic()` used for timeout (immune to system clock changes)
- Fixed 30s per-request timeout prevents hanging on single requests
- Terminal states explicitly enumerated: `SUCCEEDED`, `FAILED`, `TIMED-OUT`, `ABORTED`
- On timeout, `ApifyRun.status` is set to `TIMED_OUT` and saved before returning

**Failure modes + what happens:**
- **Timeout expires**: `ApifyTimeoutError` raised → ApifyRun marked `TIMED_OUT` → IngestionResult.success=False
- **Network error during poll**: `ApifyError` raised → ApifyRun marked `FAILED`
- **Apify returns non-200**: `ApifyError` with status code → ApifyRun marked `FAILED`
- **Apify run ABORTED externally**: Terminal status detected → returns RunInfo with status=ABORTED

---

### A2) Ingestion Idempotency + Partial Failure Behavior

**ApifyRun creation** (`kairo/brandbrain/ingestion/service.py:191-209`):

```python
# Create ApifyRun record
apify_run = ApifyRun.objects.create(
    actor_id=spec.actor_id,
    input_json=input_json,
    apify_run_id=run_info.run_id,
    dataset_id=run_info.dataset_id or "",
    status=ApifyRunStatus.RUNNING,
    started_at=run_info.started_at,
    source_connection_id=source_connection.id,
    brand_id=source_connection.brand_id,
)
result.apify_run_id = apify_run.id

logger.info(
    "Started Apify run %s (apify_run_id=%s) for %s",
    apify_run.id,
    run_info.run_id,
    source_connection.id,
)
```

**Raw item storage with delete-then-create** (`kairo/brandbrain/ingestion/service.py:301-327`):

```python
# Step 8: Store RawApifyItem rows
with transaction.atomic():
    # Clear existing items for this run (idempotent replace)
    RawApifyItem.objects.filter(apify_run=apify_run).delete()

    # Bulk create new items
    raw_item_objects = [
        RawApifyItem(
            apify_run=apify_run,
            item_index=idx,
            raw_json=item,
        )
        for idx, item in enumerate(raw_items)
    ]
    RawApifyItem.objects.bulk_create(raw_item_objects)

    # Update ApifyRun.raw_item_count
    apify_run.raw_item_count = len(raw_items)
    apify_run.save(update_fields=["raw_item_count"])

result.raw_items_count = len(raw_items)

logger.info(
    "Stored %d raw items for ApifyRun %s",
    len(raw_items),
    apify_run.id,
)
```

**Normalization call** (`kairo/brandbrain/ingestion/service.py:329-351`):

```python
# Step 9: Call normalization service
try:
    norm_result = normalize_apify_run(apify_run.id, fetch_limit=cap)
    result.normalized_items_created = norm_result.items_created
    result.normalized_items_updated = norm_result.items_updated
    result.success = True

    logger.info(
        "Normalization complete for ApifyRun %s: created=%d, updated=%d",
        apify_run.id,
        norm_result.items_created,
        norm_result.items_updated,
    )

except Exception as e:
    result.error = f"Normalization failed: {e}"
    logger.exception(
        "Normalization failed for %s: %s",
        source_connection.id,
        result.error,
    )
    return result
```

**Normalization upsert logic** (`kairo/brandbrain/normalization/service.py:204-276`):

```python
def _upsert_normalized_item(
    brand_id: UUID,
    normalized_data: dict,
    raw_ref: dict,
) -> bool:
    """
    Upsert a NormalizedEvidenceItem with idempotent dedupe.

    Dedupe strategy per spec:
    - Non-web: UNIQUE(brand_id, platform, content_type, external_id)
    - Web: UNIQUE(brand_id, platform, content_type, canonical_url)

    On update:
    - Merge raw_refs (append new ref if not already present)
    - Update other fields
    """
    from kairo.brandbrain.models import NormalizedEvidenceItem

    platform = normalized_data["platform"]
    content_type = normalized_data["content_type"]
    external_id = normalized_data.get("external_id")
    canonical_url = normalized_data.get("canonical_url", "")

    with transaction.atomic():
        # Build lookup query based on dedupe strategy
        if platform == "web":
            # Web: dedupe by canonical_url
            lookup = Q(
                brand_id=brand_id,
                platform=platform,
                content_type=content_type,
                canonical_url=canonical_url,
            )
        elif external_id:
            # Non-web with external_id
            lookup = Q(
                brand_id=brand_id,
                platform=platform,
                content_type=content_type,
                external_id=external_id,
            )
        else:
            # Non-web items MUST have external_id
            raise ValueError(
                f"Non-web item (platform={platform}) must have external_id for dedupe. "
                f"Received external_id=None, canonical_url={canonical_url}"
            )

        # Try to find existing item
        existing = NormalizedEvidenceItem.objects.filter(lookup).first()

        if existing:
            # Update existing item
            _update_normalized_item(existing, normalized_data, raw_ref)
            return False
        else:
            # Create new item
            _create_normalized_item(brand_id, normalized_data, raw_ref)
            return True
```

**Invariants enforced:**
- RawApifyItem storage is atomic (delete + bulk_create in single transaction)
- Normalization uses upsert pattern with explicit dedupe keys
- Non-web items require `external_id` (fails fast if missing)

**Failure modes + what happens:**

| Crash Point | On Retry |
|-------------|----------|
| After ApifyRun created, before raw storage | New `ingest_source()` call creates **new** ApifyRun (apify_run_id is unique from Apify). Old ApifyRun left with status=RUNNING, no raw items. Orphan but harmless. |
| After raw storage, before normalization | Retry creates new ApifyRun. Raw items for old run remain but orphaned. Normalization never runs on old run. |
| During normalization | Normalization is idempotent via upsert. Re-running `normalize_apify_run()` is safe. |

**Is the code safe from duplicate NEI writes on retry?**
- **Yes.** The upsert uses `external_id` (non-web) or `canonical_url` (web) as dedupe keys.
- On update, `raw_refs` is merged (appends new ref if not present).
- DB constraints: `uniq_nei_external_id` and `uniq_nei_web_canonical_url` prevent duplicates at DB level.

---

### A3) Job Leasing + Stale Release Semantics

**claim_next_job** (`kairo/brandbrain/jobs/queue.py:133-220`):

```python
def claim_next_job(
    worker_id: str | None = None,
    job_type: str = "compile",
) -> ClaimResult:
    """
    Claim the next available job with atomic locking.

    Uses optimistic locking pattern:
    1. Find jobs WHERE status=PENDING AND available_at <= now
    2. Update first one to status=RUNNING, set locked_at/locked_by
    3. Return the job if successful

    SQLite compatibility:
    - Uses atomic transaction instead of SELECT FOR UPDATE
    - Single UPDATE with filter ensures no double-claiming
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    if worker_id is None:
        worker_id = f"{socket.gethostname()}-{uuid_module.uuid4().hex[:8]}"

    now = timezone.now()

    with transaction.atomic():
        # Find next available job
        # Ordered by available_at (for backoff) then created_at (FIFO)
        job = (
            BrandBrainJob.objects
            .filter(
                job_type=job_type,
                status=BrandBrainJobStatus.PENDING,
                available_at__lte=now,
            )
            .order_by("available_at", "created_at")
            .first()
        )

        if not job:
            return ClaimResult(
                job=None,
                claimed=False,
                reason="No available jobs",
            )

        # Atomic claim: only succeeds if still PENDING
        # This prevents race conditions even without SELECT FOR UPDATE
        rows_updated = BrandBrainJob.objects.filter(
            id=job.id,
            status=BrandBrainJobStatus.PENDING,
        ).update(
            status=BrandBrainJobStatus.RUNNING,
            locked_at=now,
            locked_by=worker_id,
            attempts=F("attempts") + 1,
        )

        if rows_updated == 0:
            # Another worker claimed it first
            return ClaimResult(
                job=None,
                claimed=False,
                reason="Job claimed by another worker",
            )

        # Refresh the job to get updated values
        job.refresh_from_db()

        logger.info(
            "Claimed job %s for brand %s (attempt %d/%d, worker=%s)",
            job.id,
            job.brand_id,
            job.attempts,
            job.max_attempts,
            worker_id,
        )

        return ClaimResult(
            job=job,
            claimed=True,
            reason="",
        )
```

**Stale threshold and release_stale_jobs** (`kairo/brandbrain/jobs/queue.py:44-49, 327-388`):

```python
# Default stale lock threshold (minutes)
DEFAULT_STALE_LOCK_MINUTES = 10

# Base backoff delay (seconds)
BACKOFF_BASE_SECONDS = 30

# Backoff multiplier (exponential)
BACKOFF_MULTIPLIER = 2
```

```python
def release_stale_jobs(
    stale_threshold_minutes: int = DEFAULT_STALE_LOCK_MINUTES,
) -> int:
    """
    Release jobs with stale locks.

    Jobs with locked_at older than threshold are reset to PENDING
    for re-execution (if attempts < max_attempts).

    This handles workers that crash or become unresponsive.
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    now = timezone.now()
    threshold = now - timedelta(minutes=stale_threshold_minutes)

    # Find stale running jobs that can be retried
    stale_jobs = BrandBrainJob.objects.filter(
        status=BrandBrainJobStatus.RUNNING,
        locked_at__lt=threshold,
    )

    released_count = 0
    for job in stale_jobs:
        if job.attempts >= job.max_attempts:
            # Permanent failure due to stale lock
            job.status = BrandBrainJobStatus.FAILED
            job.finished_at = now
            job.last_error = f"Stale lock after {job.attempts} attempts"
            job.locked_at = None
            job.locked_by = None
            job.save(update_fields=[
                "status", "finished_at", "last_error", "locked_at", "locked_by"
            ])
            logger.warning(
                "Job %s failed due to stale lock after max attempts",
                job.id,
            )
        else:
            # Release for retry
            job.status = BrandBrainJobStatus.PENDING
            job.available_at = now
            job.last_error = "Released from stale lock"
            job.locked_at = None
            job.locked_by = None
            job.save(update_fields=[
                "status", "available_at", "last_error", "locked_at", "locked_by"
            ])
            logger.info(
                "Released stale job %s for retry (was locked since %s)",
                job.id,
                job.locked_at,
            )
        released_count += 1

    return released_count
```

**Invariants enforced:**
- Atomic claim via `UPDATE ... WHERE status=PENDING` (no race if two workers see same job)
- `locked_at` timestamp set on claim enables stale detection
- `attempts` incremented atomically with `F("attempts") + 1`

**Failure modes + what happens:**

| Scenario | What Happens |
|----------|--------------|
| Worker crashes during execution | Job stays RUNNING until `release_stale_jobs()` detects lock older than 10 minutes, then resets to PENDING |
| Two workers race to claim same job | One UPDATE succeeds (rows_updated=1), other fails (rows_updated=0) |
| Job takes longer than 10 minutes legitimately | **RISK**: stale release may mark it for retry while still executing → potential double execution |
| Job stuck forever | After 3 stale releases (attempts=3), marked FAILED permanently |

**Q: Under what conditions can a "still-running" job be released as stale?**
- If `locked_at` is older than `DEFAULT_STALE_LOCK_MINUTES` (10 minutes) and status is still `RUNNING`.
- **Risk**: A slow but legitimate job could be released while still executing.

**Q: What prevents double execution across two workers?**
- The atomic `UPDATE ... WHERE status=PENDING` ensures only one worker can claim.
- Once RUNNING, other workers cannot claim it.
- If released as stale, original worker may still be running → **potential double execution**.

**Q: Is there any scenario where a job can be lost (stuck forever)?**
- No. After `max_attempts` (default 3) is reached during stale releases, job is marked FAILED.
- Jobs cannot stay in PENDING forever if available_at is in the past and workers are running.

---

### A4) Retry/Backoff Calculation Correctness

**fail_job with backoff** (`kairo/brandbrain/jobs/queue.py:255-324`):

```python
def fail_job(job_id: UUID, error: str) -> bool:
    """
    Mark a job as failed with retry logic.

    If attempts < max_attempts:
    - Sets status back to PENDING
    - Sets available_at for exponential backoff
    - Stores error in last_error

    If attempts >= max_attempts:
    - Sets status to FAILED permanently
    - Stores error in last_error
    """
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    try:
        job = BrandBrainJob.objects.get(id=job_id)
    except BrandBrainJob.DoesNotExist:
        logger.warning("Job %s not found for fail", job_id)
        return False

    now = timezone.now()

    if job.attempts >= job.max_attempts:
        # Permanent failure
        job.status = BrandBrainJobStatus.FAILED
        job.finished_at = now
        job.last_error = error
        job.locked_at = None
        job.locked_by = None
        job.save(update_fields=[
            "status", "finished_at", "last_error", "locked_at", "locked_by"
        ])
        logger.warning(
            "Job %s permanently failed after %d attempts: %s",
            job_id,
            job.attempts,
            error[:200],
        )
        return True

    # Retry with exponential backoff
    backoff_seconds = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** job.attempts)
    available_at = now + timedelta(seconds=backoff_seconds)

    job.status = BrandBrainJobStatus.PENDING
    job.available_at = available_at
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    job.save(update_fields=[
        "status", "available_at", "last_error", "locked_at", "locked_by"
    ])

    logger.info(
        "Job %s scheduled for retry (attempt %d/%d, available at %s): %s",
        job_id,
        job.attempts,
        job.max_attempts,
        available_at.isoformat(),
        error[:200],
    )
    return True
```

**Constants** (`kairo/brandbrain/jobs/queue.py:51-55`):

```python
# Base backoff delay (seconds)
BACKOFF_BASE_SECONDS = 30

# Backoff multiplier (exponential)
BACKOFF_MULTIPLIER = 2
```

**Backoff calculation check:**

Formula: `backoff_seconds = 30 * (2 ** attempts)`

The `attempts` field is incremented **during claim**, so when `fail_job()` runs:

| Attempt # | `job.attempts` value at fail | Backoff calculation | Delay |
|-----------|------------------------------|---------------------|-------|
| 1st try   | 1                            | 30 × 2^1 = 60       | 60s   |
| 2nd try   | 2                            | 30 × 2^2 = 120      | 120s  |
| 3rd try   | 3                            | 30 × 2^3 = 240      | 240s (then FAILED) |

**Note**: At attempts=3 (after 3rd execution), `job.attempts >= job.max_attempts` is true (3 >= 3), so job becomes FAILED permanently.

---

### A5) EvidenceStatus Failure Recording

**Refreshed success** (`kairo/brandbrain/compile/worker.py:146-155`):

```python
if result.success:
    evidence_status["refreshed"].append({
        "source": source_key,
        "reason": freshness.reason,
        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
        "apify_run_status": result.apify_run_status,
        "raw_items_count": result.raw_items_count,
        "normalized_created": result.normalized_items_created,
        "normalized_updated": result.normalized_items_updated,
    })
```

**Failed ingestion** (`kairo/brandbrain/compile/worker.py:156-163`):

```python
else:
    evidence_status["failed"].append({
        "source": source_key,
        "reason": freshness.reason,
        "error": result.error,
        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
        "apify_run_status": result.apify_run_status,
    })
```

**Reused cached run** (`kairo/brandbrain/compile/worker.py:164-183`):

```python
else:
    # Reuse cached run
    if freshness.cached_run:
        # Ensure normalization exists
        result = reuse_cached_run(source, freshness.cached_run)

        evidence_status["reused"].append({
            "source": source_key,
            "reason": freshness.reason,
            "run_age_hours": freshness.run_age_hours,
            "apify_run_id": str(freshness.cached_run.id),
            "normalized_created": result.normalized_items_created,
            "normalized_updated": result.normalized_items_updated,
        })
    else:
        evidence_status["reused"].append({
            "source": source_key,
            "reason": freshness.reason,
            "run_age_hours": freshness.run_age_hours,
        })
```

**Skipped due to feature flag** (`kairo/brandbrain/compile/worker.py:125-130`):

```python
if not is_capability_enabled(source.platform, source.capability):
    evidence_status["skipped"].append({
        "source": source_key,
        "reason": "Capability disabled (feature flag)",
    })
    continue
```

**Q: Do we record enough detail to debug (run_id, dataset_id, error class/message)?**

| Field | Recorded? | Location |
|-------|-----------|----------|
| `apify_run_id` | ✅ Yes | In failed/refreshed entries |
| `dataset_id` | ❌ No | Not included in evidence_status |
| `error` (message) | ✅ Yes | In failed entries as `result.error` |
| Error class/type | ❌ No | Only string message, not exception type |

**Proposed minimal addition (not implemented):**

To improve debuggability without breaking schema, add `dataset_id` to failed entries:

```python
evidence_status["failed"].append({
    "source": source_key,
    "reason": freshness.reason,
    "error": result.error,
    "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
    "apify_run_status": result.apify_run_status,
    # Add dataset_id for debugging failed fetches
    # "dataset_id": <would need to be added to IngestionResult>
})
```

The `dataset_id` is stored in `ApifyRun.dataset_id`, so it can be retrieved via the `apify_run_id` if needed. Current design is acceptable for debugging.

---

## Test Suite Verification

```bash
pytest tests/brandbrain/ -v --tb=short
```

**Result**: `340 passed, 41 skipped in 1.53s`
