import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from EvernightAI.core.error.agent import (
    AgentStateError,
)
from EvernightAI.core.schema.agent import (
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
    RUN_ID_KEY = "run_id"
    RUNTIME_KEY = "agent_runtime"
    PENDING_APPROVAL_COUNT_KEY = "pending_approval_count"
    TOOL_ROUNDS_USED_KEY = "tool_rounds_used"
    MANUAL_PAUSE_KEY = "manual_pause"
    PAUSE_REQUESTED_KEY = "pause_requested"
    PAUSE_CHECKPOINT_KEY = "pause_checkpoint"
    PAUSE_SOURCE_KEY = "pause_source"
    RECOVERY_ELIGIBLE_KEY = "recovery_eligible"
    RECOVERY_REASON_KEY = "recovery_reason"
    RETRY_OF_KEY = "retry_of"
    RETRY_ATTEMPT_KEY = "retry_attempt"

    @classmethod
    def run_id(cls, metadata: dict[str, object]) -> str | None:
        run_id = metadata.get(cls.RUN_ID_KEY)
        if isinstance(run_id, str) and run_id:
            return run_id

        return None

    @classmethod
    def with_runtime(
        cls,
        metadata: dict[str, object],
        **runtime_values: object,
    ) -> dict[str, object]:
        next_metadata = dict(metadata)
        runtime_metadata: dict[str, object] = {}
        existing_runtime_metadata = next_metadata.get(cls.RUNTIME_KEY)
        if isinstance(existing_runtime_metadata, dict):
            runtime_metadata = {
                key: value
                for key, value in existing_runtime_metadata.items()
                if isinstance(key, str)
            }

        runtime_metadata.update(runtime_values)
        next_metadata[cls.RUNTIME_KEY] = runtime_metadata
        return next_metadata

    @classmethod
    def with_tool_state(
        cls,
        metadata: dict[str, object],
        *,
        tool_rounds_used: int,
        pending_approval_count: int,
    ) -> dict[str, object]:
        return cls.with_runtime(
            metadata,
            **{
                cls.TOOL_ROUNDS_USED_KEY: tool_rounds_used,
                cls.PENDING_APPROVAL_COUNT_KEY: pending_approval_count,
            },
        )


class AgentResumeMode(StrEnum):
    APPROVAL = "approval"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True)
class AgentRunControl:
    """Typed view of the legacy control metadata stored in snapshots."""

    resume_mode: AgentResumeMode
    recoverable: bool
    pause_requested: bool
    pause_reason: str | None
    checkpoint: str | None
    source: str | None

    @classmethod
    def from_state(cls, state: AgentRunState) -> "AgentRunControl":
        values = state.metadata.get(AgentRunMetadata.RUNTIME_KEY)
        values = values if isinstance(values, dict) else {}

        def text(key: str) -> str | None:
            value = values.get(key)
            return value if isinstance(value, str) else None

        return cls(
            resume_mode=(
                AgentResumeMode.CHECKPOINT
                if values.get(AgentRunMetadata.MANUAL_PAUSE_KEY) is True
                else AgentResumeMode.APPROVAL
            ),
            recoverable=values.get(AgentRunMetadata.RECOVERY_ELIGIBLE_KEY) is not False,
            pause_requested=values.get(AgentRunMetadata.PAUSE_REQUESTED_KEY) is True,
            pause_reason=text("pause_reason"),
            checkpoint=text(AgentRunMetadata.PAUSE_CHECKPOINT_KEY),
            source=text(AgentRunMetadata.PAUSE_SOURCE_KEY),
        )


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
