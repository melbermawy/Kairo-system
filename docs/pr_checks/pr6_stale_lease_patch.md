# PR-6 Stale Lease Patch: Logging Fix + Heartbeat

Production-hardening patch for job leasing in PR-6.

## Summary

Two fixes:
1. **Logging bug**: `release_stale_jobs()` was logging `job.locked_at` after setting it to `None`
2. **Double-execution risk**: Added `extend_job_lock()` helper + heartbeat thread to prevent stale release of actively running jobs

---

## Diff Summary

| File | Change |
|------|--------|
| `kairo/brandbrain/jobs/queue.py` | Fixed logging bug, added `extend_job_lock()` |
| `kairo/brandbrain/jobs/__init__.py` | Exported `extend_job_lock` |
| `kairo/brandbrain/management/commands/brandbrain_worker.py` | Added heartbeat thread in `_execute_job()` |
| `tests/brandbrain/test_pr6_jobs_ingestion.py` | Added 4 tests for `extend_job_lock` |

---

## Code Changes

### 1. Fixed `release_stale_jobs()` logging

**File**: `kairo/brandbrain/jobs/queue.py:357-396`

```python
released_count = 0
for job in stale_jobs:
    # Capture lock info before clearing for logging
    prev_locked_at = job.locked_at
    prev_locked_by = job.locked_by

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
            "Job %s failed due to stale lock after max attempts "
            "(was locked since %s by %s)",
            job.id,
            prev_locked_at,
            prev_locked_by,
        )
    else:
        # Release for retry
        job.status = BrandBrainJobStatus.PENDING
        job.available_at = now
        job.last_error = f"Released from stale lock (was locked by {prev_locked_by})"
        job.locked_at = None
        job.locked_by = None
        job.save(update_fields=[
            "status", "available_at", "last_error", "locked_at", "locked_by"
        ])
        logger.info(
            "Released stale job %s for retry (was locked since %s by %s)",
            job.id,
            prev_locked_at,
            prev_locked_by,
        )
    released_count += 1

return released_count
```

**Fix**: Captures `prev_locked_at` and `prev_locked_by` before clearing, then logs the captured values.

---

### 2. New `extend_job_lock()` helper

**File**: `kairo/brandbrain/jobs/queue.py:401-447`

```python
def extend_job_lock(
    job_id: UUID,
    worker_id: str,
    *,
    now: "datetime | None" = None,
) -> bool:
    """
    Extend the lock on a running job (heartbeat).

    Updates locked_at timestamp ONLY if:
    - Job exists with given job_id
    - Job status is RUNNING
    - Job is locked by the given worker_id

    This prevents stale lock detection from releasing jobs that are
    still actively being processed by a worker.

    Args:
        job_id: UUID of the job
        worker_id: Worker identifier (must match locked_by)
        now: Optional timestamp override (for testing)

    Returns:
        True if lock was extended, False if job not found/not owned/not running.
    """
    from datetime import datetime as dt
    from kairo.brandbrain.models import BrandBrainJob, BrandBrainJobStatus

    if now is None:
        now = timezone.now()

    rows_updated = BrandBrainJob.objects.filter(
        id=job_id,
        status=BrandBrainJobStatus.RUNNING,
        locked_by=worker_id,
    ).update(locked_at=now)

    if rows_updated > 0:
        logger.debug(
            "Extended lock for job %s (worker=%s, locked_at=%s)",
            job_id,
            worker_id,
            now.isoformat(),
        )
        return True

    return False
```

**Semantics**:
- Atomic single-query update (no race conditions)
- Only extends if job is RUNNING and owned by caller
- Returns False for wrong worker, wrong status, or nonexistent job

---

### 3. Heartbeat thread in `_execute_job()`

**File**: `kairo/brandbrain/management/commands/brandbrain_worker.py:58-60`

```python
# Heartbeat interval for extending job locks (seconds)
# Should be less than DEFAULT_STALE_LOCK_MINUTES (10 min = 600s)
HEARTBEAT_INTERVAL_S = 30
```

**File**: `kairo/brandbrain/management/commands/brandbrain_worker.py:178-253`

```python
def _execute_job(self, job: "BrandBrainJob") -> None:
    """
    Execute a compile job with heartbeat.

    Calls the compile worker function with job parameters.
    Runs a heartbeat thread to extend the lock periodically,
    preventing stale lock detection from releasing active jobs.
    """
    from kairo.brandbrain.compile.worker import execute_compile_job

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
                    # Lock extension failed - job may have been released
                    logger.warning(
                        "Heartbeat: failed to extend lock for job %s "
                        "(job may have been released or completed)",
                        job.id,
                    )
            except Exception as e:
                # Log but don't crash - heartbeat failure is non-fatal
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
        # Extract job parameters
        params = job.params_json or {}
        force_refresh = params.get("force_refresh", False)

        self.stdout.write(f"  Executing compile for brand {job.brand_id}...")

        # Run the compile
        execute_compile_job(
            compile_run_id=job.compile_run_id,
            force_refresh=force_refresh,
        )

        # Mark job succeeded
        complete_job(job.id)
        self.stdout.write(self.style.SUCCESS(f"  Job {job.id} succeeded"))

    except Exception as e:
        error_msg = str(e)
        logger.exception("Job %s failed: %s", job.id, error_msg)

        # Mark job failed (may retry)
        fail_job(job.id, error_msg)
        self.stdout.write(self.style.ERROR(f"  Job {job.id} failed: {error_msg[:100]}"))

    finally:
        # Stop heartbeat thread
        stop_heartbeat.set()
        # Wait briefly for thread to exit (non-blocking since daemon=True)
        heartbeat_thread.join(timeout=1.0)
```

**Semantics**:
- Heartbeat runs every 30 seconds (well under 10 min stale threshold)
- Uses `threading.Event.wait()` for clean shutdown
- Errors are logged but don't crash the worker
- Thread is stopped in `finally` block (runs on success or failure)
- Thread is daemon=True (won't block process exit)

---

### 4. New tests for `extend_job_lock`

**File**: `tests/brandbrain/test_pr6_jobs_ingestion.py`

```python
@pytest.mark.db
class TestJobLockExtension:
    """Test job lock extension (heartbeat) functionality."""

    def test_extend_job_lock_updates_locked_at_for_owned_running_job(
        self, db, brand, compile_run
    ):
        """extend_job_lock updates locked_at for a job owned by the worker."""
        old_time = timezone.now() - timedelta(minutes=5)
        new_time = timezone.now()

        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            locked_at=old_time,
            locked_by="worker-1",
            attempts=1,
        )

        result = extend_job_lock(job.id, "worker-1", now=new_time)

        assert result is True
        job.refresh_from_db()
        assert job.locked_at == new_time
        # Status and locked_by should remain unchanged
        assert job.status == BrandBrainJobStatus.RUNNING
        assert job.locked_by == "worker-1"

    def test_extend_job_lock_noop_for_wrong_worker(self, db, brand, compile_run):
        """extend_job_lock returns False and doesn't change lock for wrong worker."""
        old_time = timezone.now() - timedelta(minutes=5)
        new_time = timezone.now()

        job = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.RUNNING,
            locked_at=old_time,
            locked_by="worker-1",
            attempts=1,
        )

        # Try to extend with different worker
        result = extend_job_lock(job.id, "worker-2", now=new_time)

        assert result is False
        job.refresh_from_db()
        # locked_at should be unchanged
        assert job.locked_at == old_time
        assert job.locked_by == "worker-1"

    def test_extend_job_lock_noop_for_non_running_status(self, db, brand, compile_run):
        """extend_job_lock returns False for jobs not in RUNNING status."""
        old_time = timezone.now() - timedelta(minutes=5)
        new_time = timezone.now()

        # Test with PENDING status
        job_pending = BrandBrainJob.objects.create(
            brand_id=brand.id,
            compile_run_id=compile_run.id,
            status=BrandBrainJobStatus.PENDING,
            locked_at=old_time,
            locked_by="worker-1",
        )

        result = extend_job_lock(job_pending.id, "worker-1", now=new_time)

        assert result is False
        job_pending.refresh_from_db()
        assert job_pending.locked_at == old_time

    def test_extend_job_lock_noop_for_nonexistent_job(self, db):
        """extend_job_lock returns False for nonexistent job."""
        fake_id = uuid.uuid4()
        result = extend_job_lock(fake_id, "worker-1")
        assert result is False
```

---

## Test Results

### PR-6 Tests

```bash
pytest tests/brandbrain/test_pr6_jobs_ingestion.py -v --tb=short
```

```
============================= test session starts ==============================
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobEnqueue::test_enqueue_creates_job PASSED [  3%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobEnqueue::test_enqueue_stores_params PASSED [  6%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobClaim::test_claim_available_job PASSED [ 10%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobClaim::test_claim_returns_none_when_empty PASSED [ 13%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobClaim::test_claim_respects_available_at PASSED [ 17%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobComplete::test_complete_running_job PASSED [ 20%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobComplete::test_complete_nonexistent_job PASSED [ 24%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobFail::test_fail_with_retry PASSED [ 27%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobFail::test_fail_permanent_after_max_attempts PASSED [ 31%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobLeasing::test_claim_is_atomic PASSED [ 34%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobLeasing::test_running_job_not_claimable PASSED [ 37%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestStaleLocks::test_release_stale_jobs PASSED [ 41%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestStaleLocks::test_stale_job_fails_after_max_attempts PASSED [ 44%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobLockExtension::test_extend_job_lock_updates_locked_at_for_owned_running_job PASSED [ 48%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobLockExtension::test_extend_job_lock_noop_for_wrong_worker PASSED [ 51%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobLockExtension::test_extend_job_lock_noop_for_non_running_status PASSED [ 55%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestJobLockExtension::test_extend_job_lock_noop_for_nonexistent_job PASSED [ 58%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestIngestionService::test_ingest_source_success PASSED [ 62%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestIngestionService::test_ingest_source_disabled_capability PASSED [ 65%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestIngestionService::test_ingest_source_poll_timeout PASSED [ 68%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestCapEnforcement::test_actor_input_uses_cap PASSED [ 72%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestCapEnforcement::test_dataset_fetch_uses_cap PASSED [ 75%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestCompileWorkerIngestion::test_compile_triggers_ingestion_when_stale PASSED [ 79%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestCompileWorkerIngestion::test_compile_reuses_fresh_source PASSED [ 82%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestEvidenceStatusTracking::test_evidence_status_refreshed PASSED [ 86%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestEvidenceStatusTracking::test_evidence_status_reused PASSED [ 89%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestEvidenceStatusTracking::test_evidence_status_skipped_disabled PASSED [ 93%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestCrossBrandSecurity::test_get_job_status_respects_brand PASSED [ 96%]
tests/brandbrain/test_pr6_jobs_ingestion.py::TestCrossBrandSecurity::test_compile_status_requires_brand_match PASSED [100%]

============================== 29 passed in 0.86s ==============================
```

### Full BrandBrain Test Suite

```bash
pytest tests/brandbrain/ -v --tb=short
```

```
======================= 344 passed, 41 skipped in 1.42s ========================
```

---

## Invariants

| Invariant | Enforced By |
|-----------|-------------|
| No stale release of actively running job | Heartbeat extends `locked_at` every 30s (threshold is 10 min) |
| Only owning worker can extend lock | `extend_job_lock()` filters by `locked_by=worker_id` |
| Heartbeat stops on job completion | `stop_heartbeat.set()` in `finally` block |
| Heartbeat errors don't crash worker | `try/except` with warning log in heartbeat loop |
| Logging shows actual lock time | `prev_locked_at` captured before clearing |

---

## No New Dependencies

- Uses only `threading.Thread` and `threading.Event` (stdlib)
- No Redis, Celery, or external services
- SQLite compatible (tested with in-memory SQLite)
