"""
SourceActivation Module.

PR-4: Fixture-only SourceActivation end-to-end.
PR-6: Live-cap-limited Apify path.
Per opportunities_v1_prd.md Section B.0.4 and D.3.2.

This module handles:
- Evidence acquisition from external sources
- Deterministic fixture loading for testing (fixture_only mode)
- Live Apify execution with budget controls (live_cap_limited mode)
- EvidenceBundle creation and adaptation to signals

IMPORTANT:
- fixture_only: NO Apify calls, loads from fixtures
- live_cap_limited: Apify calls with budget guards (PR-6)
- SourceActivation makes ZERO LLM calls (all LLM stays in graph/engine)
- All calls happen in background jobs only (never GET /today)
"""
