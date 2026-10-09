import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from EvernightAI.core.error.agent import (
    AgentStateError,
)
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.error.skill import (
    SkillConflictError,
    SkillDisabledError,
    SkillNotFoundError,
)
from EvernightAI.core.schema.agent import (
    AgentRunFailure,
    AgentRunRequest,
    AgentRunState,
    AgentStepType,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import (
    ChatUsage,
)

LOGGER = logging.getLogger("EvernightAI.application.agent")


def _owner_scope(owner_id: str | None) -> PrincipalScope | None:
    return PrincipalScope(owner_id=owner_id) if owner_id is not None else None


def _aggregate_run_usage(state: AgentRunState) -> ChatUsage | None:
    usages = [
        step.response.usage
        for step in state.steps
        if step.step_type is AgentStepType.CHAT and step.response is not None
    ]
    if not any(usage is not None for usage in usages):
        return None

    def total(select: Callable[[ChatUsage], int | None]) -> int | None:
        values = [select(usage) if usage is not None else None for usage in usages]
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    return ChatUsage(
        prompt_tokens=total(lambda usage: usage.prompt_tokens),
        completion_tokens=total(lambda usage: usage.completion_tokens),
        total_tokens=total(lambda usage: usage.total_tokens),
        cached_prompt_tokens=total(lambda usage: usage.cached_prompt_tokens),
        cache_write_prompt_tokens=total(lambda usage: usage.cache_write_prompt_tokens),
        metadata={
            "calls": [
                usage.model_dump(mode="json") if usage is not None else None
                for usage in usages
            ],
        },
    )


def _require_request_scope(
    request: AgentRunRequest,
    principal_scope: PrincipalScope | None,
) -> None:
    if principal_scope is not None and not principal_scope.permits(request.owner_id):
        raise AgentStateError("Agent run owner does not match the principal scope")


class AgentRunMetadata:
    """Keys a run request carries in its free-form metadata."""

    RUN_ID_KEY = "run_id"
    RETRY_OF_KEY = "retry_of"
    RETRY_ATTEMPT_KEY = "retry_attempt"

    @classmethod
    def run_id(cls, metadata: dict[str, object]) -> str | None:
        run_id = metadata.get(cls.RUN_ID_KEY)
        if isinstance(run_id, str) and run_id:
            return run_id

        return None


def agent_run_failure(error: Exception) -> AgentRunFailure:
    return AgentRunFailure(
        error_type=error.__class__.__name__,
        message=str(error),
        # Only these errors carry detail that is safe and useful to show.
        detail=(
            error.detail
            if isinstance(
                error,
                (
                    SkillConflictError,
                    SkillDisabledError,
                    SkillNotFoundError,
                    ProviderResponseError,
                ),
            )
            else None
        ),
    )


class AgentResumeMode(StrEnum):
    APPROVAL = "approval"
    CHECKPOINT = "checkpoint"


def agent_resume_mode(state: AgentRunState) -> AgentResumeMode:
    """A paused run continues from its checkpoint, or from its pending approvals."""
    if state.pause is not None and state.pause.resumable:
        return AgentResumeMode.CHECKPOINT
    return AgentResumeMode.APPROVAL


def agent_run_can_resume(state: AgentRunState) -> bool:
    return state.pause is None or state.pause.resumable


@dataclass(frozen=True)
class AgentRunRetryPlan:
    source: AgentRunState
    request: AgentRunRequest
    retried_run_id: str
    abandon_unrecoverable_pause: bool = False


@dataclass(frozen=True)
class AbandonedToolExecution:
    tool_call_id: str
    attempt: int

    def to_trace_metadata(self) -> dict[str, object]:
        return {
            "tool_call_id": self.tool_call_id,
            "attempt": self.attempt,
        }
