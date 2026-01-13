# PR-7 Backend Runtime and CORS Pack

Verbatim code for verifying the backend BrandBrain API is callable from the frontend repo during local dev.

---

## 1. CORS / Middleware Reality

### 1.1 pyproject.toml (django-cors-headers dependency)

**File**: `pyproject.toml:7-14`

```python
dependencies = [
    "django>=5.0,<6.0",
    "dj-database-url>=2.1.0",
    "psycopg2-binary>=2.9.9",
    "python-dotenv>=1.0.0",
    "django-cors-headers>=4.3.0",
    "markdown>=3.5.0",
]
```

**Verdict**: `django-cors-headers>=4.3.0` **IS INSTALLED**.

---

### 1.2 kairo/settings.py: CORS, ALLOWED_HOSTS, CSRF, Middleware

**File**: `kairo/settings.py:37`

```python
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
```

**File**: `kairo/settings.py:44-67` (INSTALLED_APPS)

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "corsheaders",
    # Kairo apps
    "kairo.core",
    "kairo.hero",
    "kairo.ingestion",
    # Integrations
    "kairo.integrations.apify.apps.ApifyConfig",
    # PR-1: BrandBrain data model
    "kairo.brandbrain.apps.BrandBrainConfig",
    # PRD-1: out of scope for PR-0 - future apps:
    # "kairo.engines.brand_brain",
    # "kairo.engines.opportunities",
    # "kairo.engines.patterns",
    # "kairo.engines.content",
    # "kairo.engines.learning",
]
```

**File**: `kairo/settings.py:69-78` (MIDDLEWARE)

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

**File**: `kairo/settings.py:219-228` (CORS settings)

```python
# =============================================================================
# CORS SETTINGS
# =============================================================================

CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000",
).split(",")

CORS_ALLOW_CREDENTIALS = True
```

---

## 2. BrandBrain Routes

### 2.1 kairo/urls.py (brandbrain include)

**File**: `kairo/urls.py:12-20`

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("kairo.hero.urls")),
    # PR-5: BrandBrain API endpoints
    path(
        "api/brands/<str:brand_id>/brandbrain/",
        include("kairo.brandbrain.api.urls", namespace="brandbrain"),
    ),
]
```

---

### 2.2 kairo/brandbrain/api/urls.py (entire file)

**File**: `kairo/brandbrain/api/urls.py:1-52`

```python
"""
BrandBrain API URL routing.

PR-5: Compile Orchestration endpoints.
PR-7: API Surface + Overrides endpoints.

URL patterns follow spec Section 10:
- POST /api/brands/:id/brandbrain/compile
- GET /api/brands/:id/brandbrain/compile/:compile_run_id/status
- GET /api/brands/:id/brandbrain/latest
- GET /api/brands/:id/brandbrain/history
- GET/PATCH /api/brands/:id/brandbrain/overrides
"""

from django.urls import path

from kairo.brandbrain.api import views

app_name = "brandbrain"

urlpatterns = [
    # Work-path: compile kickoff
    path(
        "compile",
        views.compile_kickoff,
        name="compile-kickoff",
    ),
    # Read-path: compile status
    path(
        "compile/<str:compile_run_id>/status",
        views.compile_status,
        name="compile-status",
    ),
    # Read-path: latest snapshot
    path(
        "latest",
        views.latest_snapshot,
        name="latest-snapshot",
    ),
    # Read-path: snapshot history
    path(
        "history",
        views.snapshot_history,
        name="snapshot-history",
    ),
    # Overrides: GET (read-path) + PATCH (work-path)
    path(
        "overrides",
        views.overrides_view,
        name="overrides",
    ),
]
```

---

### 2.3 kairo/brandbrain/api/views.py: 5 Handlers

#### compile_kickoff (POST /compile)

**File**: `kairo/brandbrain/api/views.py:64-159`

```python
@csrf_exempt
@require_http_methods(["POST"])
def compile_kickoff(request, brand_id: str) -> JsonResponse:
    """
    POST /api/brands/:id/brandbrain/compile

    Kicks off a BrandBrain compile. Returns immediately with compile_run_id.
    Actual compilation happens asynchronously.

    Request body (optional):
        {
            "force_refresh": false  // Skip short-circuit check
        }

    Response (202 Accepted):
        {
            "compile_run_id": "uuid",
            "status": "PENDING",
            "poll_url": "/api/brands/:id/brandbrain/compile/:run_id/status"
        }

    Response (200 OK - short-circuit):
        {
            "compile_run_id": "uuid",
            "status": "UNCHANGED",
            "snapshot": {...}
        }

    Response (400/422 - gating failure):
        {
            "error": "message",
            "errors": [{"code": "...", "message": "..."}]
        }

    Response (404 - brand not found):
        {"error": "Brand not found"}
    """
    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse request body
    force_refresh = False
    if request.body:
        try:
            body = json.loads(request.body)
            force_refresh = body.get("force_refresh", False)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Check gating first for better error messages
    gating = check_compile_gating(parsed_brand_id)
    if not gating.allowed:
        return JsonResponse({
            "error": "Compile gating failed",
            "errors": [{"code": e.code, "message": e.message} for e in gating.errors],
        }, status=422)

    # Kick off compile
    result = compile_brandbrain(
        brand_id=parsed_brand_id,
        force_refresh=force_refresh,
    )

    # Handle result
    if result.status == "FAILED":
        return JsonResponse({
            "error": result.error,
        }, status=422)

    if result.status == "UNCHANGED":
        # Short-circuit - return existing snapshot
        response_data = {
            "compile_run_id": str(result.compile_run_id),
            "status": "UNCHANGED",
        }
        if result.snapshot:
            response_data["snapshot"] = {
                "snapshot_id": str(result.snapshot.id),
                "brand_id": str(result.snapshot.brand_id),
                "created_at": result.snapshot.created_at.isoformat(),
                "snapshot_json": result.snapshot.snapshot_json,
            }
        return JsonResponse(response_data, status=200)

    # Normal kickoff - return 202
    return JsonResponse({
        "compile_run_id": str(result.compile_run_id),
        "status": result.status,
        "poll_url": result.poll_url,
    }, status=202)
```

#### compile_status (GET /compile/:compile_run_id/status)

**File**: `kairo/brandbrain/api/views.py:162-221`

```python
@require_http_methods(["GET"])
def compile_status(request, brand_id: str, compile_run_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/compile/:compile_run_id/status

    Get the status of a compile run. Pure DB read, no side effects.

    SECURITY: Enforces brand ownership - compile run must belong to the
    brand specified in the URL. Returns 404 if run belongs to different brand.

    Response shape varies by status:

    PENDING/RUNNING:
        {
            "compile_run_id": "uuid",
            "status": "PENDING" | "RUNNING",
            "progress": {  // only when RUNNING
                "stage": "bundling",
                "sources_completed": 2,
                "sources_total": 4
            }
        }

    SUCCEEDED:
        {
            "compile_run_id": "uuid",
            "status": "SUCCEEDED",
            "evidence_status": {...},
            "snapshot": {
                "snapshot_id": "uuid",
                "created_at": "iso-datetime",
                "snapshot_json": {...}
            }
        }

    FAILED:
        {
            "compile_run_id": "uuid",
            "status": "FAILED",
            "error": "message",
            "evidence_status": {...}
        }
    """
    # Parse UUIDs
    parsed_brand_id = _parse_uuid(brand_id)
    parsed_run_id = _parse_uuid(compile_run_id)

    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)
    if not parsed_run_id:
        return JsonResponse({"error": "Invalid compile_run_id"}, status=400)

    # Get status (pure DB read)
    # SECURITY: Pass brand_id to enforce ownership check
    status = get_compile_status(parsed_run_id, parsed_brand_id)

    if not status:
        return JsonResponse({"error": "Compile run not found"}, status=404)

    return JsonResponse(status.to_dict(), status=200)
```

#### latest_snapshot (GET /latest)

**File**: `kairo/brandbrain/api/views.py:229-316`

```python
@require_http_methods(["GET"])
def latest_snapshot(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/latest

    Get the latest BrandBrain snapshot. Pure DB read.

    Query params:
        ?include=evidence,qa,bundle  (comma-separated, or 'full' for all)

    Response (200 OK - compact):
        {
            "snapshot_id": "uuid",
            "brand_id": "uuid",
            "snapshot_json": {...},
            "created_at": "iso-datetime",
            "compile_run_id": "uuid"
        }

    Response (200 OK - with include=full):
        {
            ... base fields ...
            "evidence_status": {...},
            "qa_report": {...},
            "bundle_summary": {...}
        }

    Response (404 - no snapshot):
        {"error": "No snapshot found"}

    Per spec Section 1.1:
    - P95 target: 50ms
    - Read-path only: DB reads, no side effects
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Get latest snapshot (indexed lookup)
    # Use select_related to minimize queries
    snapshot = (
        BrandBrainSnapshot.objects
        .filter(brand_id=parsed_brand_id)
        .select_related("compile_run", "compile_run__bundle")
        .order_by("-created_at")
        .first()
    )

    if not snapshot:
        return JsonResponse({"error": "No snapshot found"}, status=404)

    # Build response
    response_data = {
        "snapshot_id": str(snapshot.id),
        "brand_id": str(snapshot.brand_id),
        "snapshot_json": snapshot.snapshot_json,
        "created_at": snapshot.created_at.isoformat(),
        "compile_run_id": str(snapshot.compile_run_id) if snapshot.compile_run_id else None,
    }

    # Parse include params (comma-separated or 'full')
    include_param = request.GET.get("include", "")
    include_parts = {p.strip().lower() for p in include_param.split(",") if p.strip()}
    include_full = "full" in include_parts

    # Add evidence_status if requested
    if include_full or "evidence" in include_parts:
        if snapshot.compile_run:
            response_data["evidence_status"] = snapshot.compile_run.evidence_status_json

    # Add qa_report if requested
    if include_full or "qa" in include_parts:
        if snapshot.compile_run:
            response_data["qa_report"] = snapshot.compile_run.qa_report_json

    # Add bundle_summary if requested
    if include_full or "bundle" in include_parts:
        if snapshot.compile_run and snapshot.compile_run.bundle:
            response_data["bundle_summary"] = snapshot.compile_run.bundle.summary_json

    return JsonResponse(response_data, status=200)
```

#### snapshot_history (GET /history)

**File**: `kairo/brandbrain/api/views.py:319-392`

```python
@require_http_methods(["GET"])
def snapshot_history(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/history

    Get paginated snapshot history. Pure DB read.

    Query params:
        ?page=1 (default)
        ?page_size=10 (default, max 50)

    Response (200 OK):
        {
            "snapshots": [
                {
                    "snapshot_id": "uuid",
                    "created_at": "iso-datetime",
                    "diff_summary": {...}  // compact diff
                }
            ],
            "page": 1,
            "page_size": 10,
            "total": 25
        }
    """
    from kairo.brandbrain.models import BrandBrainSnapshot

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse pagination params
    try:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 10))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid pagination params"}, status=400)

    # Enforce limits
    page = max(1, page)
    page_size = min(max(1, page_size), 50)  # max 50 per spec

    # Get total count
    total = BrandBrainSnapshot.objects.filter(brand_id=parsed_brand_id).count()

    # Get paginated snapshots
    offset = (page - 1) * page_size
    snapshots = (
        BrandBrainSnapshot.objects
        .filter(brand_id=parsed_brand_id)
        .order_by("-created_at")
        [offset:offset + page_size]
    )

    # Build compact response (no full snapshot_json)
    snapshot_list = []
    for snapshot in snapshots:
        snapshot_list.append({
            "snapshot_id": str(snapshot.id),
            "created_at": snapshot.created_at.isoformat(),
            "diff_summary": _extract_diff_summary(snapshot.diff_from_previous_json),
        })

    return JsonResponse({
        "snapshots": snapshot_list,
        "page": page,
        "page_size": page_size,
        "total": total,
    }, status=200)
```

#### overrides_view (GET/PATCH /overrides)

**File**: `kairo/brandbrain/api/views.py:421-594`

```python
@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def overrides_view(request, brand_id: str) -> JsonResponse:
    """
    GET/PATCH /api/brands/:id/brandbrain/overrides

    Dispatcher for overrides endpoint.
    """
    if request.method == "GET":
        return _get_overrides(request, brand_id)
    else:  # PATCH
        return _patch_overrides(request, brand_id)


def _get_overrides(request, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/:id/brandbrain/overrides

    Get user overrides and pinned fields for a brand. Pure DB read.

    Response (200 OK):
        {
            "brand_id": "uuid",
            "overrides_json": {
                "positioning.what_we_do": "Custom value",
                ...
            },
            "pinned_paths": [
                "positioning.what_we_do",
                "voice.tone"
            ],
            "updated_at": "iso-datetime"
        }

    Response (200 OK - no overrides exist):
        {
            "brand_id": "uuid",
            "overrides_json": {},
            "pinned_paths": [],
            "updated_at": null
        }

    Per spec Section 1.1:
    - P95 target: 30ms
    - Read-path only: DB reads, no side effects
    """
    from kairo.brandbrain.models import BrandBrainOverrides

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Get overrides (may not exist)
    try:
        overrides = BrandBrainOverrides.objects.get(brand_id=parsed_brand_id)
        response_data = {
            "brand_id": str(parsed_brand_id),
            "overrides_json": overrides.overrides_json,
            "pinned_paths": overrides.pinned_paths,
            "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
        }
    except BrandBrainOverrides.DoesNotExist:
        # Return empty overrides (not 404 - brand exists, just no overrides yet)
        response_data = {
            "brand_id": str(parsed_brand_id),
            "overrides_json": {},
            "pinned_paths": [],
            "updated_at": None,
        }

    return JsonResponse(response_data, status=200)


def _patch_overrides(request, brand_id: str) -> JsonResponse:
    """
    PATCH /api/brands/:id/brandbrain/overrides

    Update user overrides and pinned fields. Work-path (mutates state).

    Request body:
        {
            "overrides_json": {
                "positioning.what_we_do": "Custom value"
            },
            "pinned_paths": ["positioning.what_we_do"]
        }

    Merge semantics:
    - overrides_json: merge with existing (null value removes key)
    - pinned_paths: replace entirely (not merged)

    Response (200 OK):
        {
            "brand_id": "uuid",
            "overrides_json": {...},  # after merge
            "pinned_paths": [...],
            "updated_at": "iso-datetime"
        }

    Per spec Section 1.1:
    - P95 target: 100ms (work-path)
    - Work-path: mutates state
    """
    from kairo.brandbrain.models import BrandBrainOverrides

    # Parse brand_id
    parsed_brand_id = _parse_uuid(brand_id)
    if not parsed_brand_id:
        return JsonResponse({"error": "Invalid brand_id"}, status=400)

    # Check brand exists
    if not _brand_exists(parsed_brand_id):
        return JsonResponse({"error": "Brand not found"}, status=404)

    # Parse request body
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Validate body structure
    if not isinstance(body, dict):
        return JsonResponse({"error": "Request body must be an object"}, status=400)

    new_overrides = body.get("overrides_json")
    new_pinned = body.get("pinned_paths")

    # Validate types if provided
    if new_overrides is not None and not isinstance(new_overrides, dict):
        return JsonResponse({"error": "overrides_json must be an object"}, status=400)
    if new_pinned is not None and not isinstance(new_pinned, list):
        return JsonResponse({"error": "pinned_paths must be an array"}, status=400)

    # Get or create overrides
    overrides, created = BrandBrainOverrides.objects.get_or_create(
        brand_id=parsed_brand_id,
        defaults={
            "overrides_json": {},
            "pinned_paths": [],
        },
    )

    # Merge overrides_json if provided
    if new_overrides is not None:
        merged = dict(overrides.overrides_json)  # copy
        for key, value in new_overrides.items():
            if value is None:
                # null value removes the key
                merged.pop(key, None)
            else:
                merged[key] = value
        overrides.overrides_json = merged

    # Replace pinned_paths if provided
    if new_pinned is not None:
        # Validate all items are strings
        if not all(isinstance(p, str) for p in new_pinned):
            return JsonResponse({"error": "pinned_paths items must be strings"}, status=400)
        overrides.pinned_paths = new_pinned

    # Save
    overrides.save()

    return JsonResponse({
        "brand_id": str(parsed_brand_id),
        "overrides_json": overrides.overrides_json,
        "pinned_paths": overrides.pinned_paths,
        "updated_at": overrides.updated_at.isoformat() if overrides.updated_at else None,
    }, status=200)
```

---

## 3. Worker Wiring

### 3.1 Management Command Entrypoint

**File**: `kairo/brandbrain/management/commands/brandbrain_worker.py:1-254` (full file)

```python
"""
Management command for BrandBrain compile worker.

PR-6: Durable job worker for compile orchestration.

Usage:
    python manage.py brandbrain_worker

Options:
    --poll-interval: Seconds between job queue polls (default: 5)
    --stale-check-interval: Seconds between stale lock checks (default: 60)
    --max-jobs: Max jobs to process before exiting (0 = unlimited, default: 0)
    --once: Process one job and exit (for testing)
    --dry-run: Claim and log jobs without processing

The worker:
1. Polls for available jobs
2. Claims next job with atomic locking
3. Executes the compile pipeline with heartbeat
4. Marks job succeeded/failed with retry logic
5. Periodically checks for stale locks

Heartbeat:
- During job execution, lock is extended every HEARTBEAT_INTERVAL_S
- Prevents stale lock detection from releasing actively running jobs
- Uses background thread that stops when job completes

Graceful shutdown:
- SIGINT/SIGTERM triggers graceful exit after current job completes
- Current job is NOT interrupted
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

from kairo.brandbrain.jobs.queue import (
    claim_next_job,
    complete_job,
    extend_job_lock,
    fail_job,
    release_stale_jobs,
)

if TYPE_CHECKING:
    from kairo.brandbrain.models import BrandBrainJob

logger = logging.getLogger(__name__)

# Heartbeat interval for extending job locks (seconds)
# Should be less than DEFAULT_STALE_LOCK_MINUTES (10 min = 600s)
HEARTBEAT_INTERVAL_S = 30


class Command(BaseCommand):
    """Run BrandBrain compile worker."""

    help = "Run BrandBrain compile worker for processing durable jobs"

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

        self.stdout.write(f"Starting BrandBrain worker: {self._worker_id}")
        self.stdout.write(f"  Poll interval: {poll_interval}s")
        self.stdout.write(f"  Stale check interval: {stale_check_interval}s")
        if max_jobs > 0:
            self.stdout.write(f"  Max jobs: {max_jobs}")
        if dry_run:
            self.stdout.write("  DRY RUN MODE - jobs will be claimed but not processed")
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

---

### 3.2 Job Queue Claim Loop

**File**: `kairo/brandbrain/jobs/queue.py:135-222`

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

    Args:
        worker_id: Identifier for this worker (defaults to hostname+uuid)
        job_type: Type of job to claim (default: "compile")

    Returns:
        ClaimResult with claimed job or None.
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

---

### 3.3 Dev Scripts for Starting Worker

**File**: `README.md:32-51` (local dev instructions)

```markdown
### Local Development (without Docker)

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Set up environment variables
cp .env.example .env
# Edit .env with your DATABASE_URL (requires local postgres)

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```
```

**Note**: No explicit dev script exists for the worker. Run manually (see Section 4 below).

---

## 4. Exact Local Run Commands (Backend)

### 4.1 Migrate Steps

```bash
# Activate virtualenv
source .venv/bin/activate

# Apply all migrations
python manage.py migrate
```

### 4.2 Start Server

```bash
# Terminal 1: Django dev server
python manage.py runserver 0.0.0.0:8000
```

### 4.3 Start Worker

```bash
# Terminal 2: BrandBrain compile worker
python manage.py brandbrain_worker --poll-interval=5
```

### 4.4 Smoke Curl Sequence

#### POST /compile

```bash
curl -X POST http://localhost:8000/api/brands/{BRAND_UUID}/brandbrain/compile \
  -H "Content-Type: application/json" \
  -d '{"force_refresh": false}'
```

**Expected Response (202 Accepted)**:
```json
{
  "compile_run_id": "uuid",
  "status": "PENDING",
  "poll_url": "/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
}
```

**Expected Response (200 OK - short-circuit)**:
```json
{
  "compile_run_id": "uuid",
  "status": "UNCHANGED",
  "snapshot": {
    "snapshot_id": "uuid",
    "brand_id": "uuid",
    "created_at": "iso-datetime",
    "snapshot_json": {...}
  }
}
```

**Expected Response (422 - gating failed)**:
```json
{
  "error": "Compile gating failed",
  "errors": [{"code": "...", "message": "..."}]
}
```

---

#### GET /compile/:id/status

```bash
curl http://localhost:8000/api/brands/{BRAND_UUID}/brandbrain/compile/{COMPILE_RUN_ID}/status
```

**Expected Response (PENDING/RUNNING)**:
```json
{
  "compile_run_id": "uuid",
  "status": "PENDING",
  "progress": null
}
```

**Expected Response (SUCCEEDED)**:
```json
{
  "compile_run_id": "uuid",
  "status": "SUCCEEDED",
  "evidence_status": {...},
  "snapshot": {
    "snapshot_id": "uuid",
    "created_at": "iso-datetime",
    "snapshot_json": {...}
  }
}
```

**Expected Response (FAILED)**:
```json
{
  "compile_run_id": "uuid",
  "status": "FAILED",
  "error": "message",
  "evidence_status": {...}
}
```

---

#### GET /latest?include=full

```bash
curl "http://localhost:8000/api/brands/{BRAND_UUID}/brandbrain/latest?include=full"
```

**Expected Response (200 OK)**:
```json
{
  "snapshot_id": "uuid",
  "brand_id": "uuid",
  "snapshot_json": {...},
  "created_at": "iso-datetime",
  "compile_run_id": "uuid",
  "evidence_status": {...},
  "qa_report": {...},
  "bundle_summary": {...}
}
```

**Expected Response (404 - no snapshot)**:
```json
{
  "error": "No snapshot found"
}
```

---

#### GET /overrides

```bash
curl http://localhost:8000/api/brands/{BRAND_UUID}/brandbrain/overrides
```

**Expected Response (200 OK)**:
```json
{
  "brand_id": "uuid",
  "overrides_json": {"positioning.what_we_do": "Custom value"},
  "pinned_paths": ["positioning.what_we_do"],
  "updated_at": "iso-datetime"
}
```

**Expected Response (200 OK - no overrides yet)**:
```json
{
  "brand_id": "uuid",
  "overrides_json": {},
  "pinned_paths": [],
  "updated_at": null
}
```

---

#### PATCH /overrides

```bash
curl -X PATCH http://localhost:8000/api/brands/{BRAND_UUID}/brandbrain/overrides \
  -H "Content-Type: application/json" \
  -d '{"overrides_json": {"positioning.tagline": "New tagline"}, "pinned_paths": ["positioning.tagline"]}'
```

**Expected Response (200 OK)**:
```json
{
  "brand_id": "uuid",
  "overrides_json": {"positioning.tagline": "New tagline"},
  "pinned_paths": ["positioning.tagline"],
  "updated_at": "iso-datetime"
}
```

---

## 5. Frontend Will Fail Unless...

| Requirement | Current Status | Action Required |
|-------------|----------------|-----------------|
| **CORS origin whitelisted** | `CORS_ALLOWED_ORIGINS` defaults to `http://localhost:3000` | If frontend runs on different port, set `CORS_ALLOWED_ORIGINS=http://localhost:{port}` in `.env` |
| **CorsMiddleware enabled** | `corsheaders.middleware.CorsMiddleware` in MIDDLEWARE | Already configured |
| **Backend server running** | Manual: `python manage.py runserver` | Must be started before frontend calls APIs |
| **Worker running** | Manual: `python manage.py brandbrain_worker` | Required for compile jobs to execute (otherwise jobs stay PENDING forever) |
| **Migrations applied** | Manual: `python manage.py migrate` | Required before any API call |
| **Brand exists** | Must create brand in DB first | Frontend needs valid `brand_id` UUID |
| **Base URL correct** | Backend runs on `http://localhost:8000` | Frontend must use `http://localhost:8000/api/brands/{id}/brandbrain/...` |
| **No auth required** | Auth is NOT implemented (out of scope for PRD v1) | Frontend can call APIs directly without tokens |
| **JSON Content-Type** | POST/PATCH require `Content-Type: application/json` | Frontend fetch must set header |
| **Valid UUID format** | `brand_id` must be valid UUID | Frontend must pass valid UUID strings |

---

## Summary

- **CORS**: django-cors-headers IS installed; defaults to `http://localhost:3000`
- **Routes**: 5 endpoints under `/api/brands/{brand_id}/brandbrain/`
- **Worker**: `python manage.py brandbrain_worker` (polls every 5s, heartbeat every 30s)
- **No auth**: All endpoints publicly accessible (PRD v1 scope)
