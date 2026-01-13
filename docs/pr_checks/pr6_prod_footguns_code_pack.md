# PR-6 Production Footguns — Code Pack

Verbatim code snippets for quick review. See `pr6_job_runner_and_ingestion_verification.md` Appendix A for analysis.

---

## A1) Polling Loop + Timeout Enforcement

### `kairo/integrations/apify/client.py:139-202`

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

### `kairo/integrations/apify/client.py:67-73`

```python
def is_terminal(self) -> bool:
    """Return True if run is in a terminal state."""
    return self.status in ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED")

def is_success(self) -> bool:
    """Return True if run succeeded."""
    return self.status == "SUCCEEDED"
```

### `kairo/brandbrain/ingestion/service.py:57-61`

```python
# Default poll timeout (seconds)
DEFAULT_POLL_TIMEOUT_S = 300  # 5 minutes

# Poll interval (seconds)
DEFAULT_POLL_INTERVAL_S = 5
```

### `kairo/brandbrain/ingestion/service.py:211-244`

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

---

## A2) Ingestion Idempotency + Partial Failure Behavior

### `kairo/brandbrain/ingestion/service.py:191-209`

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

### `kairo/brandbrain/ingestion/service.py:301-327`

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

### `kairo/brandbrain/ingestion/service.py:329-351`

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

### `kairo/brandbrain/normalization/service.py:204-276`

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

---

## A3) Job Leasing + Stale Release Semantics

### `kairo/brandbrain/jobs/queue.py:133-220`

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

### `kairo/brandbrain/jobs/queue.py:44-55`

```python
# Default stale lock threshold (minutes)
DEFAULT_STALE_LOCK_MINUTES = 10

# Base backoff delay (seconds)
BACKOFF_BASE_SECONDS = 30

# Backoff multiplier (exponential)
BACKOFF_MULTIPLIER = 2
```

### `kairo/brandbrain/jobs/queue.py:327-388`

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

---

## A4) Retry/Backoff Calculation

### `kairo/brandbrain/jobs/queue.py:255-324`

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

### `kairo/brandbrain/jobs/queue.py:51-55`

```python
# Base backoff delay (seconds)
BACKOFF_BASE_SECONDS = 30

# Backoff multiplier (exponential)
BACKOFF_MULTIPLIER = 2
```

---

## A5) EvidenceStatus Failure Recording

### `kairo/brandbrain/compile/worker.py:146-163`

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
else:
    evidence_status["failed"].append({
        "source": source_key,
        "reason": freshness.reason,
        "error": result.error,
        "apify_run_id": str(result.apify_run_id) if result.apify_run_id else None,
        "apify_run_status": result.apify_run_status,
    })
```

### `kairo/brandbrain/compile/worker.py:164-183`

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

### `kairo/brandbrain/compile/worker.py:125-130`

```python
if not is_capability_enabled(source.platform, source.capability):
    evidence_status["skipped"].append({
        "source": source_key,
        "reason": "Capability disabled (feature flag)",
    })
    continue
```
