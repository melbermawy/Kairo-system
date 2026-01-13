"""
BrandBrain Ingestion Service.

PR-6: Real Apify actor execution, raw item storage, and normalization.
"""

from kairo.brandbrain.ingestion.service import (
    ingest_source,
    IngestionResult,
)

__all__ = [
    "ingest_source",
    "IngestionResult",
]
