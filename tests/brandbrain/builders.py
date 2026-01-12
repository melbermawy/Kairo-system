"""
BrandBrain dict builders for test fixtures.

PR-0: Pure-Python dict builders matching the BrandBrain spec schema.
These do NOT assume DB models exist yet - they return dicts shaped
like the spec (Section 2 of brandbrain_system_spec_v2.md).

These builders will be upgraded to factory_boy factories in PR-1
when the actual Django models land.

Usage:
    from tests.brandbrain.builders import build_brand, build_onboarding_answers_tier0

    brand = build_brand(name="Acme Corp")
    answers = build_onboarding_answers_tier0(what_we_do="We help teams ship faster")
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def _now() -> str:
    """Generate current timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# BRAND & ONBOARDING BUILDERS
# =============================================================================


def build_brand(
    *,
    id: str | None = None,
    tenant_id: str | None = None,
    name: str = "Test Brand",
    website_url: str | None = "https://example.com",
    created_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a Brand dict matching spec Section 2.1.

    Per spec:
        class Brand:
            id: UUID
            tenant_id: UUID
            name: str
            website_url: str (nullable)
            created_at: datetime
    """
    return {
        "id": id or _uuid(),
        "tenant_id": tenant_id or _uuid(),
        "name": name,
        "website_url": website_url,
        "created_at": created_at or _now(),
    }


def build_onboarding_answers_tier0(
    *,
    what_we_do: str = "We help businesses grow through innovative solutions",
    who_for: str = "Marketing teams at mid-size B2B companies",
    edge: list[str] | None = None,
    tone_words: list[str] | None = None,
    taboos: list[str] | None = None,
    primary_goal: str = "awareness",
    cta_posture: str = "soft",
) -> dict[str, Any]:
    """
    Build Tier 0 onboarding answers matching spec Section 6.

    Required fields per spec v2.2+:
        - tier0.what_we_do (required)
        - tier0.who_for (required)
        - tier0.primary_goal (required)
        - tier0.cta_posture (required)

    Strongly recommended (optional):
        - tier0.edge
        - tier0.tone_words
        - tier0.taboos
    """
    answers = {
        "tier0.what_we_do": what_we_do,
        "tier0.who_for": who_for,
        "tier0.primary_goal": primary_goal,
        "tier0.cta_posture": cta_posture,
    }

    # Optional but strongly recommended fields
    if edge is not None:
        answers["tier0.edge"] = edge
    if tone_words is not None:
        answers["tier0.tone_words"] = tone_words
    if taboos is not None:
        answers["tier0.taboos"] = taboos

    return answers


def build_onboarding_answers_tier1(
    *,
    priority_platforms: list[str] | None = None,
    pillars_seed: list[str] | None = None,
    good_examples: list[dict[str, str]] | None = None,
    key_pages: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build Tier 1 onboarding answers matching spec Section 6.

    Required:
        - tier1.priority_platforms

    Optional:
        - tier1.pillars_seed
        - tier1.good_examples
        - tier1.key_pages
    """
    answers: dict[str, Any] = {
        "tier1.priority_platforms": priority_platforms or ["instagram", "linkedin"],
    }

    if pillars_seed is not None:
        answers["tier1.pillars_seed"] = pillars_seed
    if good_examples is not None:
        answers["tier1.good_examples"] = good_examples
    if key_pages is not None:
        answers["tier1.key_pages"] = key_pages

    return answers


def build_brand_onboarding(
    *,
    brand_id: str | None = None,
    tier: int = 0,
    answers_json: dict[str, Any] | None = None,
    updated_at: str | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """
    Build a BrandOnboarding dict matching spec Section 2.1.

    Per spec:
        class BrandOnboarding:
            brand_id: UUID  # 1:1 relationship
            tier: int  # 0, 1, or 2
            answers_json: dict  # JSONB - keyed by stable question_id
            updated_at: datetime
            updated_by: UUID
    """
    return {
        "brand_id": brand_id or _uuid(),
        "tier": tier,
        "answers_json": answers_json or build_onboarding_answers_tier0(),
        "updated_at": updated_at or _now(),
        "updated_by": updated_by or _uuid(),
    }


# =============================================================================
# SOURCE CONNECTION BUILDER
# =============================================================================


def build_source_connection(
    *,
    id: str | None = None,
    brand_id: str | None = None,
    platform: str = "instagram",
    capability: str = "posts",
    identifier: str = "https://www.instagram.com/testaccount/",
    is_enabled: bool = True,
    settings_json: dict[str, Any] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a SourceConnection dict matching spec Section 2.2.

    Per spec:
        class SourceConnection:
            brand_id: UUID
            platform: str  # enum: instagram|linkedin|tiktok|youtube|web
            capability: str  # enum (see below)
            identifier: str  # handle/url/channel id depending on platform/capability
            is_enabled: bool
            settings_json: dict  # JSONB - optional per-source knobs
            created_at: datetime
            updated_at: datetime

    Capability enum by platform:
        instagram: posts, reels
        linkedin: company_posts, profile_posts
        tiktok: profile_videos
        youtube: channel_videos
        web: crawl_pages
    """
    return {
        "id": id or _uuid(),
        "brand_id": brand_id or _uuid(),
        "platform": platform,
        "capability": capability,
        "identifier": identifier,
        "is_enabled": is_enabled,
        "settings_json": settings_json or {},
        "created_at": created_at or _now(),
        "updated_at": updated_at or _now(),
    }


# =============================================================================
# APIFY RUN BUILDERS
# =============================================================================


def build_apify_run_stub(
    *,
    id: str | None = None,
    actor_id: str = "apify~instagram-scraper",
    apify_run_id: str | None = None,
    dataset_id: str | None = None,
    status: str = "SUCCEEDED",
    input_json: dict[str, Any] | None = None,
    source_connection_id: str | None = None,
    brand_id: str | None = None,
    raw_item_count: int = 0,
    normalized_item_count: int = 0,
    created_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    """
    Build an ApifyRun stub dict matching spec Section 2.2.

    Per spec (extended fields):
        class ApifyRun:
            # ... existing fields (actor_id, run_id, dataset_id, status, input_json, etc.) ...

            # NEW optional fields for BrandBrain integration:
            source_connection_id: UUID (nullable)
            brand_id: UUID (nullable)
            raw_item_count: int (default 0)
            normalized_item_count: int (default 0)
    """
    return {
        "id": id or _uuid(),
        "actor_id": actor_id,
        "apify_run_id": apify_run_id or _uuid(),
        "dataset_id": dataset_id or _uuid(),
        "status": status,
        "input_json": input_json or {},
        "source_connection_id": source_connection_id,
        "brand_id": brand_id,
        "raw_item_count": raw_item_count,
        "normalized_item_count": normalized_item_count,
        "created_at": created_at or _now(),
        "finished_at": finished_at or _now(),
    }


def build_raw_apify_item_stub(
    *,
    id: str | None = None,
    apify_run_id: str | None = None,
    item_index: int = 0,
    raw_json: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a RawApifyItem stub dict.

    Per spec:
        class RawApifyItem:
            apify_run: FK
            item_index: int
            raw_json: JSONB
    """
    return {
        "id": id or _uuid(),
        "apify_run_id": apify_run_id or _uuid(),
        "item_index": item_index,
        "raw_json": raw_json or {},
        "created_at": created_at or _now(),
    }


# =============================================================================
# NORMALIZED EVIDENCE ITEM BUILDER
# =============================================================================


def build_normalized_evidence_item_stub(
    *,
    id: str | None = None,
    brand_id: str | None = None,
    platform: str = "instagram",
    content_type: str = "post",
    external_id: str | None = None,
    canonical_url: str = "https://instagram.com/p/abc123/",
    published_at: str | None = None,
    author_ref: str = "testaccount",
    title: str | None = None,
    text_primary: str = "Sample post content",
    text_secondary: str | None = None,
    hashtags: list[str] | None = None,
    metrics_json: dict[str, Any] | None = None,
    media_json: dict[str, Any] | None = None,
    raw_refs: list[dict[str, str]] | None = None,
    flags_json: dict[str, Any] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a NormalizedEvidenceItem stub dict matching spec Section 2.3.

    Per spec:
        class NormalizedEvidenceItem:
            brand_id: UUID
            platform: str  # enum: instagram|linkedin|tiktok|youtube|web
            content_type: str  # enum: post|reel|text_post|short_video|video|web_page
            external_id: str (nullable)
            canonical_url: str
            published_at: datetime (nullable)
            author_ref: str
            title: str (nullable)
            text_primary: str
            text_secondary: str (nullable)
            hashtags: list[str]
            metrics_json: dict
            media_json: dict
            raw_refs: list[dict]  # [{apify_run_uuid, raw_item_id}]
            flags_json: dict  # {has_transcript, is_low_value, is_collection_page}
            created_at: datetime
            updated_at: datetime
    """
    return {
        "id": id or _uuid(),
        "brand_id": brand_id or _uuid(),
        "platform": platform,
        "content_type": content_type,
        "external_id": external_id or _uuid(),
        "canonical_url": canonical_url,
        "published_at": published_at or _now(),
        "author_ref": author_ref,
        "title": title,
        "text_primary": text_primary,
        "text_secondary": text_secondary,
        "hashtags": hashtags or [],
        "metrics_json": metrics_json or {"likes": 0, "comments": 0},
        "media_json": media_json or {"type": "Image"},
        "raw_refs": raw_refs or [],
        "flags_json": flags_json or {
            "has_transcript": False,
            "is_low_value": False,
            "is_collection_page": False,
        },
        "created_at": created_at or _now(),
        "updated_at": updated_at or _now(),
    }


# =============================================================================
# OVERRIDES BUILDER
# =============================================================================


def build_overrides_stub(
    *,
    brand_id: str | None = None,
    overrides_json: dict[str, Any] | None = None,
    pinned_paths: list[str] | None = None,
    updated_at: str | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """
    Build a BrandBrainOverrides stub dict matching spec Section 2.5.

    Per spec:
        class BrandBrainOverrides:
            brand_id: UUID  # 1:1 relationship
            overrides_json: dict  # field_path -> override_value
            pinned_paths: list[str]  # array of field_paths
            updated_at: datetime
            updated_by: UUID
    """
    return {
        "brand_id": brand_id or _uuid(),
        "overrides_json": overrides_json or {},
        "pinned_paths": pinned_paths or [],
        "updated_at": updated_at or _now(),
        "updated_by": updated_by or _uuid(),
    }


# =============================================================================
# COMPILE RUN BUILDER
# =============================================================================


def build_compile_run_stub(
    *,
    id: str | None = None,
    brand_id: str | None = None,
    bundle_id: str | None = None,
    onboarding_snapshot_json: dict[str, Any] | None = None,
    prompt_version: str = "v1.0",
    model: str = "claude-3-5-sonnet",
    status: str = "SUCCEEDED",
    draft_json: dict[str, Any] | None = None,
    qa_report_json: dict[str, Any] | None = None,
    evidence_status_json: dict[str, Any] | None = None,
    created_at: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    Build a BrandBrainCompileRun stub dict matching spec Section 2.5.

    Per spec:
        class BrandBrainCompileRun:
            brand_id: UUID
            bundle_id: UUID
            onboarding_snapshot_json: dict
            prompt_version: str
            model: str
            status: str  # enum: SUCCEEDED|FAILED
            draft_json: dict
            qa_report_json: dict
            evidence_status_json: dict
            created_at: datetime
            error: str (nullable)
    """
    return {
        "id": id or _uuid(),
        "brand_id": brand_id or _uuid(),
        "bundle_id": bundle_id or _uuid(),
        "onboarding_snapshot_json": onboarding_snapshot_json or build_onboarding_answers_tier0(),
        "prompt_version": prompt_version,
        "model": model,
        "status": status,
        "draft_json": draft_json or {},
        "qa_report_json": qa_report_json or {},
        "evidence_status_json": evidence_status_json or {
            "reused": [],
            "refreshed": [],
            "skipped": [],
            "failed": [],
        },
        "created_at": created_at or _now(),
        "error": error,
    }


# =============================================================================
# SNAPSHOT BUILDER
# =============================================================================


def build_field_node(
    *,
    value: Any,
    confidence: float = 0.9,
    sources: list[dict[str, str]] | None = None,
    locked: bool = False,
    override_value: Any = None,
) -> dict[str, Any]:
    """
    Build a FieldNode dict matching spec Section 8.1.

    Per spec:
        {
          "value": "...",
          "confidence": 0.0,
          "sources": [
            {"type": "answer", "id": "tier0.what_we_do"},
            {"type": "evidence", "id": "nei_123"}
          ],
          "locked": false,
          "override_value": null
        }
    """
    return {
        "value": value,
        "confidence": confidence,
        "sources": sources or [],
        "locked": locked,
        "override_value": override_value,
    }


def build_snapshot_stub(
    *,
    id: str | None = None,
    brand_id: str | None = None,
    compile_run_id: str | None = None,
    snapshot_json: dict[str, Any] | None = None,
    diff_from_previous_json: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a BrandBrainSnapshot stub dict matching spec Section 2.5 & 8.

    Per spec:
        class BrandBrainSnapshot:
            brand_id: UUID
            compile_run_id: UUID
            snapshot_json: dict  # final merged
            diff_from_previous_json: dict
            created_at: datetime

    The snapshot_json follows the schema in Section 8.2:
        positioning, voice, pillars, constraints, platform_profiles, examples, meta
    """
    default_snapshot = {
        "positioning": {
            "what_we_do": build_field_node(value="We help businesses grow"),
            "who_for": build_field_node(value="Marketing teams"),
            "differentiators": build_field_node(value=["AI-powered", "Fast"]),
            "proof_types": build_field_node(value=[]),
        },
        "voice": {
            "tone_tags": build_field_node(value=["professional", "friendly"]),
            "do": build_field_node(value=["Use clear language"]),
            "dont": build_field_node(value=["Use jargon"]),
            "cta_policy": build_field_node(value="soft"),
            "emoji_policy": build_field_node(value="minimal"),
        },
        "pillars": [],
        "constraints": {
            "taboos": build_field_node(value=[]),
            "risk_boundaries": build_field_node(value=[]),
        },
        "platform_profiles": {},
        "examples": {
            "canonical_evidence": [],
            "user_examples": build_field_node(value=[]),
        },
        "meta": {
            "compiled_at": _now(),
            "evidence_summary": {},
            "missing_inputs": [],
            "confidence_summary": {},
            "content_goal": build_field_node(value="awareness"),
            "priority_platforms": build_field_node(value=["instagram"]),
        },
    }

    return {
        "id": id or _uuid(),
        "brand_id": brand_id or _uuid(),
        "compile_run_id": compile_run_id or _uuid(),
        "snapshot_json": snapshot_json or default_snapshot,
        "diff_from_previous_json": diff_from_previous_json or {},
        "created_at": created_at or _now(),
    }


# =============================================================================
# EVIDENCE STATUS BUILDER
# =============================================================================


def build_evidence_source_entry(
    *,
    source_connection_id: str | None = None,
    platform: str = "instagram",
    capability: str = "posts",
    reason: str = "Cached run within TTL",
    apify_run_id: str | None = None,
    item_count: int | None = None,
    run_age_hours: float | None = None,
) -> dict[str, Any]:
    """
    Build an EvidenceSourceEntry dict matching spec Section 2.5.

    Per spec:
        interface EvidenceSourceEntry {
          source_connection_id: UUID;
          platform: string;
          capability: string;
          reason: string;
          apify_run_id?: UUID;
          item_count?: number;
          run_age_hours?: number;
        }
    """
    entry: dict[str, Any] = {
        "source_connection_id": source_connection_id or _uuid(),
        "platform": platform,
        "capability": capability,
        "reason": reason,
    }

    if apify_run_id is not None:
        entry["apify_run_id"] = apify_run_id
    if item_count is not None:
        entry["item_count"] = item_count
    if run_age_hours is not None:
        entry["run_age_hours"] = run_age_hours

    return entry


def build_evidence_status(
    *,
    reused: list[dict[str, Any]] | None = None,
    refreshed: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build an EvidenceStatus dict matching spec Section 2.5.

    Per spec:
        interface EvidenceStatus {
          reused: EvidenceSourceEntry[];
          refreshed: EvidenceSourceEntry[];
          skipped: EvidenceSourceEntry[];
          failed: EvidenceSourceEntry[];
        }
    """
    return {
        "reused": reused or [],
        "refreshed": refreshed or [],
        "skipped": skipped or [],
        "failed": failed or [],
    }
