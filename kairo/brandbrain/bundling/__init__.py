"""
Evidence bundling for BrandBrain.

PR-4: Bundle creation and deterministic FeatureReport.

Exports:
- create_evidence_bundle: Main entrypoint to create an EvidenceBundle
- create_feature_report: Create deterministic FeatureReport from bundle
- BundleCriteria: Configuration for bundle selection
"""

from kairo.brandbrain.bundling.service import (
    create_evidence_bundle,
    create_feature_report,
    UnknownContentTypeError,
)
from kairo.brandbrain.bundling.criteria import BundleCriteria

__all__ = [
    "create_evidence_bundle",
    "create_feature_report",
    "BundleCriteria",
    "UnknownContentTypeError",
]
