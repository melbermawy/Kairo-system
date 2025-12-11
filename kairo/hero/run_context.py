"""
Run Context for Hero Flows.

PR-6: Minimal Observability + Run IDs (Before Any LLM).

RunContext is an in-memory context object. It is NOT persisted.

It carries:
- run_id: Unique identifier for a single execution run
- brand_id: The brand being operated on
- flow: Which hero flow is executing (F1_today, F2_package, F3_learning)
- trigger_source: What initiated the run (api, cron, eval, manual)
- step: Optional current step within the flow

Per docs/technical/04-orchestrator-and-flows.md and PR-map-and-standards §PR-6.
"""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4


FlowType = Literal["F1_today", "F2_package", "F3_learning"]
TriggerSource = Literal["api", "cron", "eval", "manual"]


@dataclass(frozen=True)
class RunContext:
    """
    In-memory context for a hero flow execution.

    RunContext is an in-memory context object. It is NOT persisted.
    It must NOT be saved to the database or have a .save() method.

    Attributes:
        run_id: Unique UUID for this run (auto-generated if not provided)
        brand_id: UUID of the brand this run operates on
        flow: The flow type (F1_today, F2_package, F3_learning)
        trigger_source: What initiated the run (api, cron, eval, manual)
        step: Optional current step within the flow
    """

    brand_id: UUID
    flow: FlowType
    trigger_source: TriggerSource
    run_id: UUID = field(default_factory=uuid4)
    step: str | None = None

    def with_step(self, step: str) -> "RunContext":
        """
        Create a new RunContext with an updated step.

        Since RunContext is frozen, this returns a new instance.

        Args:
            step: The new step name

        Returns:
            New RunContext with the step set
        """
        return RunContext(
            run_id=self.run_id,
            brand_id=self.brand_id,
            flow=self.flow,
            trigger_source=self.trigger_source,
            step=step,
        )


def create_run_context(
    brand_id: UUID,
    flow: FlowType,
    trigger_source: TriggerSource,
    run_id: UUID | None = None,
    step: str | None = None,
) -> RunContext:
    """
    Factory function to create a RunContext.

    Convenience function that generates a run_id if not provided.

    Args:
        brand_id: UUID of the brand
        flow: The flow type (F1_today, F2_package, F3_learning)
        trigger_source: What initiated the run
        run_id: Optional existing run_id (auto-generated if None)
        step: Optional current step

    Returns:
        New RunContext instance
    """
    return RunContext(
        run_id=run_id or uuid4(),
        brand_id=brand_id,
        flow=flow,
        trigger_source=trigger_source,
        step=step,
    )
