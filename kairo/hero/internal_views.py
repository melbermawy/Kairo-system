"""
Internal Admin Views.

PR-11: Observability, Classification, and Admin Surfaces.

Django-only admin/debug views for internal use. NOT part of the Next.js customer-facing UI.

Features:
- Run browser: List and inspect hero loop runs (HTML + JSON)
- Eval report browser: View eval markdown reports
- Brand detail: View brand snapshot, opportunities, packages, variants

Access control:
- Token via X-Kairo-Internal-Token header
- Token configured via KAIRO_INTERNAL_ADMIN_TOKEN env var
- Returns 404 if token missing, wrong, or env var unset (NO dev mode)

Per PR-map-and-standards §PR-11:
- No business logic in admin; read-only views only
- These surfaces live inside Django only (not part of Next.js UI)
"""

import html
import os
import re
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import UUID

import markdown
from django.http import HttpRequest, HttpResponse, JsonResponse

from kairo.core.models import Brand, ContentPackage, Opportunity, Variant
from kairo.hero.observability_store import get_run_detail, list_runs


# =============================================================================
# AUTH DECORATOR
# =============================================================================


def _get_admin_token() -> str | None:
    """Get the admin token from environment."""
    return os.getenv("KAIRO_INTERNAL_ADMIN_TOKEN")


def _get_eval_reports_dir() -> Path:
    """Get the eval reports directory."""
    default = Path("docs/eval/hero_loop")
    return Path(os.getenv("KAIRO_EVAL_REPORTS_DIR", str(default)))


def _sanitize_html(html_content: str) -> str:
    """
    Sanitize HTML content to remove XSS vectors.

    Removes:
    - <script> tags and their contents
    - Event handler attributes (onclick, onerror, onload, etc.)
    - javascript: URLs
    - data: URLs (which can contain scripts)

    This is a defense-in-depth measure. The markdown library
    doesn't render raw HTML by default, but this ensures
    safety even if content slips through.
    """
    # Remove script tags and their contents
    html_content = re.sub(
        r"<script[^>]*>.*?</script>",
        "",
        html_content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove script tags (self-closing or unclosed)
    html_content = re.sub(
        r"<script[^>]*/>",
        "",
        html_content,
        flags=re.IGNORECASE,
    )
    html_content = re.sub(
        r"<script[^>]*>",
        "",
        html_content,
        flags=re.IGNORECASE,
    )
    html_content = re.sub(
        r"</script>",
        "",
        html_content,
        flags=re.IGNORECASE,
    )

    # Remove event handlers (on*)
    html_content = re.sub(
        r'\s+on\w+\s*=\s*["\'][^"\']*["\']',
        "",
        html_content,
        flags=re.IGNORECASE,
    )
    html_content = re.sub(
        r"\s+on\w+\s*=\s*[^\s>]+",
        "",
        html_content,
        flags=re.IGNORECASE,
    )

    # Remove javascript: URLs
    html_content = re.sub(
        r'href\s*=\s*["\']javascript:[^"\']*["\']',
        'href="#"',
        html_content,
        flags=re.IGNORECASE,
    )

    # Remove data: URLs (can contain scripts)
    html_content = re.sub(
        r'(src|href)\s*=\s*["\']data:[^"\']*["\']',
        r'\1="#"',
        html_content,
        flags=re.IGNORECASE,
    )

    return html_content


def require_internal_token(view_func):
    """
    Decorator to require internal admin token.

    Checks X-Kairo-Internal-Token header against KAIRO_INTERNAL_ADMIN_TOKEN.
    Returns 404 if:
    - Env var is not set
    - Token is missing
    - Token is wrong

    NO dev mode. Always enforce 404.
    """

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        expected_token = _get_admin_token()

        # If no token configured, return 404 (no dev mode)
        if not expected_token:
            return HttpResponse(status=404)

        # Check token in header
        provided_token = request.headers.get("X-Kairo-Internal-Token", "")
        if provided_token != expected_token:
            return HttpResponse(status=404)

        return view_func(request, *args, **kwargs)

    return wrapper


# =============================================================================
# HTML HELPERS
# =============================================================================


def _html_page(title: str, content: str) -> HttpResponse:
    """Wrap content in a basic HTML page."""
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(title)}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f5f5f5; }}
        tr:hover {{ background: #f9f9f9; }}
        a {{ color: #0066cc; }}
        pre {{ background: #f5f5f5; padding: 1rem; overflow-x: auto; }}
        code {{ background: #f5f5f5; padding: 2px 4px; }}
        .nav {{ margin-bottom: 1rem; }}
        .nav a {{ margin-right: 1rem; }}
        h1, h2, h3 {{ margin-top: 1.5rem; }}
    </style>
</head>
<body>
    <div class="nav">
        <a href="/hero/internal/runs/">Runs</a>
        <a href="/hero/internal/evals/">Evals</a>
        <a href="/hero/internal/brands/">Brands</a>
    </div>
    <h1>{html.escape(title)}</h1>
    {content}
</body>
</html>"""
    return HttpResponse(html_content, content_type="text/html")


# =============================================================================
# RUN BROWSER VIEWS
# =============================================================================


@require_internal_token
def list_hero_runs(request: HttpRequest) -> HttpResponse:
    """
    List recent hero loop runs.

    GET /hero/internal/runs/

    Returns HTML page listing runs, each row links to run detail.
    """
    try:
        limit = min(int(request.GET.get("limit", "50")), 200)
    except ValueError:
        limit = 50

    runs = list_runs(limit=limit)

    # Build HTML table
    rows = []
    for run in runs:
        run_id = run.get("run_id", "unknown")
        timestamp = run.get("timestamp", "")[:19] if run.get("timestamp") else "-"
        brand_id = run.get("brand_id", "-")[:8] + "..." if run.get("brand_id") else "-"
        flow = run.get("flow", "-")
        status = run.get("status", "-")
        obs_health = run.get("obs_health") or "-"

        rows.append(f"""
        <tr>
            <td><a href="/hero/internal/runs/{html.escape(run_id)}/">{html.escape(run_id[:8])}...</a></td>
            <td>{html.escape(timestamp)}</td>
            <td>{html.escape(brand_id)}</td>
            <td>{html.escape(flow)}</td>
            <td>{html.escape(status)}</td>
            <td>{html.escape(obs_health)}</td>
            <td><a href="/hero/internal/runs/{html.escape(run_id)}.json">JSON</a></td>
        </tr>""")

    table = f"""
    <p>Showing {len(runs)} runs (limit: {limit})</p>
    <table>
        <thead>
            <tr>
                <th>Run ID</th>
                <th>Timestamp</th>
                <th>Brand ID</th>
                <th>Flow</th>
                <th>Status</th>
                <th>Health</th>
                <th>JSON</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows) if rows else '<tr><td colspan="7">No runs found</td></tr>'}
        </tbody>
    </table>
    """

    return _html_page("Hero Runs", table)


@require_internal_token
def get_hero_run(request: HttpRequest, run_id: str) -> HttpResponse:
    """
    Get detailed information about a specific run.

    GET /hero/internal/runs/<run_id>/

    Returns HTML run detail page showing:
    - Run meta fields (run_id, brand_id, flow, trigger_source, status)
    - Engine events list
    - LLM calls list
    """
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        return HttpResponse(status=400)

    detail = get_run_detail(run_uuid)

    if not detail.get("exists", False):
        return HttpResponse(status=404)

    events = detail.get("events", {})
    stats = detail.get("stats", {})

    # Build run meta section
    run_start = events.get("run_start", [{}])[0] if events.get("run_start") else {}
    run_complete = events.get("run_complete", [{}])[0] if events.get("run_complete") else {}
    run_fail = events.get("run_fail", [{}])[0] if events.get("run_fail") else {}

    meta_html = f"""
    <h2>Run Meta</h2>
    <table>
        <tr><th>Run ID</th><td>{html.escape(str(run_id))}</td></tr>
        <tr><th>Brand ID</th><td>{html.escape(str(run_start.get('brand_id', '-')))}</td></tr>
        <tr><th>Flow</th><td>{html.escape(str(run_start.get('flow', '-')))}</td></tr>
        <tr><th>Trigger Source</th><td>{html.escape(str(run_start.get('trigger_source', '-')))}</td></tr>
        <tr><th>Status</th><td>{html.escape('complete' if run_complete else ('fail' if run_fail else 'running'))}</td></tr>
        <tr><th>Timestamp</th><td>{html.escape(str(run_start.get('ts', '-')))}</td></tr>
    </table>
    """

    # Build engine events section
    engine_events = events.get("engine_step", [])
    if engine_events:
        engine_rows = []
        for ev in engine_events:
            engine_rows.append(f"<tr><td>{html.escape(str(ev.get('ts', '-')))}</td><td><pre>{html.escape(str(ev))}</pre></td></tr>")
        engine_html = f"""
        <h2>Engine Events ({len(engine_events)})</h2>
        <table>
            <thead><tr><th>Timestamp</th><th>Event</th></tr></thead>
            <tbody>{''.join(engine_rows)}</tbody>
        </table>
        """
    else:
        engine_html = "<h2>Engine Events</h2><p>No engine events recorded.</p>"

    # Build LLM calls section
    llm_calls = events.get("llm_call", [])
    if llm_calls:
        llm_rows = []
        for call in llm_calls:
            llm_rows.append(f"""
            <tr>
                <td>{html.escape(str(call.get('ts', '-')[:19]))}</td>
                <td>{html.escape(str(call.get('model', '-')))}</td>
                <td>{html.escape(str(call.get('role', '-')))}</td>
                <td>{call.get('latency_ms', 0)}ms</td>
                <td>{call.get('tokens_in', 0)} / {call.get('tokens_out', 0)}</td>
                <td>{html.escape(str(call.get('status', '-')))}</td>
            </tr>""")
        llm_html = f"""
        <h2>LLM Calls ({len(llm_calls)})</h2>
        <table>
            <thead><tr><th>Timestamp</th><th>Model</th><th>Role</th><th>Latency</th><th>Tokens In/Out</th><th>Status</th></tr></thead>
            <tbody>{''.join(llm_rows)}</tbody>
        </table>
        <p>Total latency: {stats.get('total_latency_ms', 0)}ms | Total tokens in: {stats.get('total_tokens_in', 0)} | Total tokens out: {stats.get('total_tokens_out', 0)}</p>
        """
    else:
        llm_html = "<h2>LLM Calls</h2><p>No LLM calls recorded.</p>"

    content = meta_html + engine_html + llm_html
    return _html_page(f"Run {run_id[:8]}...", content)


@require_internal_token
def get_hero_run_json(request: HttpRequest, run_id: str) -> HttpResponse:
    """
    Get run detail as JSON.

    GET /hero/internal/runs/<run_id>.json

    Returns JSON:
    {
      "run": {...},
      "engine_events": [...],
      "llm_calls": [...]
    }
    """
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        return HttpResponse(status=400)

    detail = get_run_detail(run_uuid)

    if not detail.get("exists", False):
        return HttpResponse(status=404)

    events = detail.get("events", {})

    # Build run meta from start event
    run_start = events.get("run_start", [{}])[0] if events.get("run_start") else {}
    run_complete = events.get("run_complete", [{}])[0] if events.get("run_complete") else None
    run_fail = events.get("run_fail", [{}])[0] if events.get("run_fail") else None

    run_meta = {
        "run_id": str(run_id),
        "brand_id": run_start.get("brand_id"),
        "flow": run_start.get("flow"),
        "trigger_source": run_start.get("trigger_source"),
        "status": "complete" if run_complete else ("fail" if run_fail else "running"),
        "timestamp": run_start.get("ts"),
    }

    return JsonResponse({
        "run": run_meta,
        "engine_events": events.get("engine_step", []),
        "llm_calls": events.get("llm_call", []),
    })


# =============================================================================
# EVAL BROWSER VIEWS
# =============================================================================


@require_internal_token
def list_evals(request: HttpRequest) -> HttpResponse:
    """
    List eval report files.

    GET /hero/internal/evals/

    Lists markdown report files from docs/eval/hero_loop/ (or KAIRO_EVAL_REPORTS_DIR).
    """
    reports_dir = _get_eval_reports_dir()

    if not reports_dir.exists():
        return _html_page("Eval Reports", f"<p>Reports directory not found: {html.escape(str(reports_dir))}</p>")

    # List markdown files
    files = sorted(reports_dir.glob("*.md"), reverse=True)

    rows = []
    for f in files[:100]:  # Limit to 100
        name = f.name
        stat = f.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_kb = stat.st_size // 1024
        rows.append(f"""
        <tr>
            <td><a href="/hero/internal/evals/{html.escape(name)}">{html.escape(name)}</a></td>
            <td>{mtime}</td>
            <td>{size_kb} KB</td>
        </tr>""")

    table = f"""
    <p>Reports from: {html.escape(str(reports_dir))}</p>
    <table>
        <thead>
            <tr><th>Filename</th><th>Modified</th><th>Size</th></tr>
        </thead>
        <tbody>
            {''.join(rows) if rows else '<tr><td colspan="3">No reports found</td></tr>'}
        </tbody>
    </table>
    """

    return _html_page("Eval Reports", table)


@require_internal_token
def get_eval_detail(request: HttpRequest, filename: str) -> HttpResponse:
    """
    Render an eval report as HTML.

    GET /hero/internal/evals/<filename>

    Renders the markdown report as HTML (safe rendering; no script injection).
    """
    # Security: only allow .md files, no path traversal
    if not filename.endswith(".md") or "/" in filename or "\\" in filename or ".." in filename:
        return HttpResponse(status=400)

    reports_dir = _get_eval_reports_dir()
    file_path = reports_dir / filename

    if not file_path.exists() or not file_path.is_file():
        return HttpResponse(status=404)

    try:
        content = file_path.read_text(encoding="utf-8")
        # Render markdown to HTML
        html_content = markdown.markdown(
            content,
            extensions=["tables", "fenced_code"],
            output_format="html5"
        )
        # Sanitize to remove any XSS vectors (defense in depth)
        html_content = _sanitize_html(html_content)
        return _html_page(f"Eval: {filename}", html_content)
    except Exception:
        return HttpResponse(status=500)


# =============================================================================
# BRAND DETAIL VIEWS
# =============================================================================


@require_internal_token
def list_brands(request: HttpRequest) -> HttpResponse:
    """
    List all brands (for internal admin).

    GET /hero/internal/brands/

    Returns HTML page with brand list.
    """
    brands = Brand.objects.all().order_by("-created_at")[:100]

    rows = []
    for brand in brands:
        created = brand.created_at.strftime("%Y-%m-%d") if brand.created_at else "-"
        rows.append(f"""
        <tr>
            <td><a href="/hero/internal/brands/{html.escape(str(brand.id))}/">{html.escape(str(brand.id)[:8])}...</a></td>
            <td>{html.escape(brand.name)}</td>
            <td>{html.escape(brand.slug)}</td>
            <td>{created}</td>
        </tr>""")

    table = f"""
    <table>
        <thead>
            <tr><th>ID</th><th>Name</th><th>Slug</th><th>Created</th></tr>
        </thead>
        <tbody>
            {''.join(rows) if rows else '<tr><td colspan="4">No brands found</td></tr>'}
        </tbody>
    </table>
    """

    return _html_page("Brands", table)


@require_internal_token
def get_brand_detail(request: HttpRequest, brand_id: str) -> HttpResponse:
    """
    Get detailed information about a brand.

    GET /hero/internal/brands/<brand_id>/

    Returns HTML page with brand info and counts.
    """
    try:
        brand_uuid = UUID(brand_id)
    except ValueError:
        return HttpResponse(status=400)

    try:
        brand = Brand.objects.get(id=brand_uuid)
    except Brand.DoesNotExist:
        return HttpResponse(status=404)

    # Count related objects
    opportunity_count = Opportunity.objects.filter(brand=brand).count()
    package_count = ContentPackage.objects.filter(brand=brand).count()
    variant_count = Variant.objects.filter(brand=brand).count()
    persona_count = brand.personas.count()
    pillar_count = brand.pillars.count()

    content = f"""
    <h2>Brand Info</h2>
    <table>
        <tr><th>ID</th><td>{html.escape(str(brand.id))}</td></tr>
        <tr><th>Name</th><td>{html.escape(brand.name)}</td></tr>
        <tr><th>Slug</th><td>{html.escape(brand.slug)}</td></tr>
        <tr><th>Positioning</th><td>{html.escape(brand.positioning or '-')}</td></tr>
        <tr><th>Tone Tags</th><td>{html.escape(str(brand.tone_tags or []))}</td></tr>
        <tr><th>Taboos</th><td>{html.escape(str(brand.taboos or []))}</td></tr>
    </table>

    <h2>Related Objects</h2>
    <table>
        <tr><th>Personas</th><td>{persona_count}</td></tr>
        <tr><th>Pillars</th><td>{pillar_count}</td></tr>
        <tr><th>Opportunities</th><td>{opportunity_count}</td></tr>
        <tr><th>Packages</th><td>{package_count}</td></tr>
        <tr><th>Variants</th><td>{variant_count}</td></tr>
    </table>
    """

    return _html_page(f"Brand: {brand.name}", content)
