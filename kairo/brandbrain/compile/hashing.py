"""
Deterministic hashing for compile short-circuit detection.

PR-5: Compile input hash for no-op detection.

Per spec Section 1.1, short-circuit conditions require checking:
- onboarding_answers_json hash
- overrides_json + pinned_paths hash
- enabled SourceConnection identifiers/settings
- prompt_version + model

All hashing is deterministic (sorted keys, stable json dumps).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


def _stable_json_dumps(obj) -> str:
    """
    Serialize object to JSON with deterministic key ordering.

    Ensures identical inputs produce identical hash values regardless
    of dict iteration order.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_compile_input_hash(
    brand_id: "UUID",
    prompt_version: str = "v1",
    model: str = "gpt-4",
) -> str:
    """
    Compute a deterministic hash of all compile inputs.

    Used for short-circuit detection: if hash matches the latest
    snapshot's input hash, compile can return UNCHANGED.

    Hash components:
    - onboarding answers_json (tier0/1/2 answers)
    - overrides_json + pinned_paths (user customizations)
    - enabled SourceConnection specs (platform/capability/identifier/settings)
    - prompt_version + model (compile config)

    Args:
        brand_id: UUID of the brand
        prompt_version: Compile prompt version (default "v1")
        model: LLM model identifier (default "gpt-4")

    Returns:
        SHA256 hex digest of combined inputs.
    """
    from kairo.brandbrain.models import (
        BrandOnboarding,
        BrandBrainOverrides,
        SourceConnection,
    )

    # Component 1: Onboarding answers
    try:
        onboarding = BrandOnboarding.objects.get(brand_id=brand_id)
        answers = onboarding.answers_json or {}
    except BrandOnboarding.DoesNotExist:
        answers = {}

    # Component 2: Overrides + pinned paths
    try:
        overrides = BrandBrainOverrides.objects.get(brand_id=brand_id)
        overrides_data = {
            "overrides_json": overrides.overrides_json or {},
            "pinned_paths": sorted(overrides.pinned_paths or []),
        }
    except BrandBrainOverrides.DoesNotExist:
        overrides_data = {"overrides_json": {}, "pinned_paths": []}

    # Component 3: Enabled source connections
    # Only include fields that affect ingestion/bundling
    sources = SourceConnection.objects.filter(
        brand_id=brand_id,
        is_enabled=True,
    ).order_by("platform", "capability", "identifier")

    sources_data = [
        {
            "platform": s.platform,
            "capability": s.capability,
            "identifier": s.identifier,
            # Only include relevant settings keys
            "settings": {
                k: v for k, v in (s.settings_json or {}).items()
                if k in ("extra_start_urls",)  # keys that affect ingestion
            },
        }
        for s in sources
    ]

    # Component 4: Compile config
    config_data = {
        "prompt_version": prompt_version,
        "model": model,
    }

    # Combine all components
    combined = {
        "answers": answers,
        "overrides": overrides_data,
        "sources": sources_data,
        "config": config_data,
    }

    # Hash with SHA256
    json_bytes = _stable_json_dumps(combined).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()


def compute_onboarding_hash(brand_id: "UUID") -> str:
    """
    Compute hash of just the onboarding answers.

    Useful for detecting onboarding changes independently.
    """
    from kairo.brandbrain.models import BrandOnboarding

    try:
        onboarding = BrandOnboarding.objects.get(brand_id=brand_id)
        answers = onboarding.answers_json or {}
    except BrandOnboarding.DoesNotExist:
        answers = {}

    json_bytes = _stable_json_dumps(answers).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()
