"""
SourceActivation Fixtures.

PR-4: Fixture-only SourceActivation.

Provides deterministic fixture loading for testing and development.
"""

from .loader import load_fixtures_for_brand

__all__ = ["load_fixtures_for_brand"]
