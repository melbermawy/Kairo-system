"""
Normalization adapters for BrandBrain.

PR-3: Raw → Normalized transformation.

Exports:
- normalize_apify_run: Main entrypoint to normalize all items from an ApifyRun
- get_adapter: Get normalization adapter for an actor_id
- NormalizationResult: Result of a normalization operation
"""

from kairo.brandbrain.normalization.service import (
    normalize_apify_run,
    NormalizationResult,
)
from kairo.brandbrain.normalization.adapters import get_adapter

__all__ = [
    "normalize_apify_run",
    "NormalizationResult",
    "get_adapter",
]
