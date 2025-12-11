"""
Kairo Hero Services Layer.

PR-3: Service Layer + Engines Layer Skeleton.

Services sit between HTTP/API and engines/models. They:
- Own DB access
- Own transactions
- Orchestrate multiple engines when needed
- Return DTOs, not Django HttpResponses

Services must NOT:
- Call LLMs (now or later)
- Contain business logic that belongs in engines (scoring, ranking, etc.)

Per docs/technical/01-system-architecture.md §3.
"""

from .brands_service import get_brand
from .content_packages_service import get_package
from .decisions_service import (
    record_opportunity_decision,
    record_package_decision,
    record_variant_decision,
)
from .learning_service import get_learning_summary
from .opportunities_service import create_package_for_opportunity
from .today_service import get_today_board, regenerate_today_board
from .variants_service import (
    generate_variants_for_package,
    list_variants_for_package,
    update_variant,
)

__all__ = [
    "get_brand",
    "get_today_board",
    "regenerate_today_board",
    "create_package_for_opportunity",
    "get_package",
    "generate_variants_for_package",
    "list_variants_for_package",
    "update_variant",
    "record_opportunity_decision",
    "record_package_decision",
    "record_variant_decision",
    "get_learning_summary",
]
