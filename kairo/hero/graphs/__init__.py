"""
Kairo Hero Graphs Package.

PR-8: Opportunities Graph Wired via Opportunities Engine (F1).

This package contains deepagents/langgraph-style graph definitions for the hero loop flows.
Per docs/technical/05-llm-and-deepagents-conventions.md:

- Graphs define workflows that compose engine calls + LLM nodes + transforms
- Graphs are pure: no ORM imports, no DB reads/writes, only DTOs
- All LLM calls use kairo.hero.llm_client.LLMClient
- Graphs return DTOs only (e.g., OpportunityDraftDTO)

Graphs available:
- opportunities_graph: F1 - Generate opportunities for the Today board
"""

from kairo.hero.graphs.opportunities_graph import (
    GraphError,
    graph_hero_generate_opportunities,
)

__all__ = [
    "graph_hero_generate_opportunities",
    "GraphError",
]
