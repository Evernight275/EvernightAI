from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class HeldAgentRunLease:
    run_id: str
    owner: str
    generation: int


# Set by the executor for the operation it runs, so state writes can be fenced.
held_agent_run_lease: ContextVar[HeldAgentRunLease | None] = ContextVar(
    "evernight_held_agent_run_lease",
    default=None,
)
