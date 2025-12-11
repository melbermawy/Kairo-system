"""
Kairo Hero Engines Layer.

PR-3: Service Layer + Engines Layer Skeleton.

Engines are pure Python modules that:
- Take UUIDs / DTOs as inputs
- Return DTOs or model instances as outputs
- Contain no HTTP / no request objects / no Django views
- Own deterministic business logic (scoring, ranking, etc.)

Per docs/technical/03-engines-overview.md:
- Engines are services, not agents
- Django views / API never hit DB directly for domain logic - they call engines
- Agents never bypass engines to mutate state
"""

from .content_engine import (
    create_package_from_opportunity,
    generate_variants_for_package,
)
from .learning_engine import (
    process_execution_events,
    summarize_learning_for_brand,
)
from .opportunities_engine import generate_today_board

__all__ = [
    "generate_today_board",
    "create_package_from_opportunity",
    "generate_variants_for_package",
    "summarize_learning_for_brand",
    "process_execution_events",
]
