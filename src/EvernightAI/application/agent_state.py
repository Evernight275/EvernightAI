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
    PAUSE_REASON_KEY = "pause_reason"
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


class AgentPauseCause(StrEnum):
    """Why a run stopped at a checkpoint instead of waiting for a tool approval."""

    MANUAL = "manual_pause"
    TIMEOUT = "timeout"
    SHUTDOWN = "shutdown"
    UNCLEAN_SHUTDOWN = "unclean_shutdown"
    LEASE_EXPIRED = "lease_expired"

    @property
    def source(self) -> str:
        """The name persisted in snapshots and traces.

        Snapshots do not distinguish a run found still running at startup from
        one paused by a graceful shutdown; both are recorded as "shutdown".
        """
        if self is AgentPauseCause.UNCLEAN_SHUTDOWN:
            return AgentPauseCause.SHUTDOWN.value
        return self.value


@dataclass(frozen=True)
class AgentRunPause:
    """A run stopped at a checkpoint: why, where, and whether it may continue.

    A resumable pause continues from its checkpoint. One that is not resumable
    can only be retried as a new run or unblocked by operator resolution.
    """

    cause: AgentPauseCause
    checkpoint: str
    resumable: bool
    reason: str | None = None

    def apply(self, metadata: dict[str, object]) -> dict[str, object]:
        source = self.cause.source
        values: dict[str, object] = {
            # Named for manual pauses, but it selects checkpoint resumption for
            # every cause; see AgentRunControl.resume_mode.
            AgentRunMetadata.MANUAL_PAUSE_KEY: self.resumable,
            AgentRunMetadata.PAUSE_CHECKPOINT_KEY: self.checkpoint,
            AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: self.resumable,
            AgentRunMetadata.RECOVERY_REASON_KEY: source,
            AgentRunMetadata.PAUSE_SOURCE_KEY: source,
        }
        if self.cause is AgentPauseCause.MANUAL:
            values[AgentRunMetadata.PAUSE_REQUESTED_KEY] = False
            values[AgentRunMetadata.PAUSE_REASON_KEY] = (
                self.reason if self.reason is not None else "pause"
            )
        elif self.cause is AgentPauseCause.TIMEOUT:
            values["interruption_reason"] = source
        elif self.cause is AgentPauseCause.SHUTDOWN:
            values["shutdown_reason"] = source
        return AgentRunMetadata.with_runtime(metadata, **values)


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
            pause_reason=text(AgentRunMetadata.PAUSE_REASON_KEY),
            checkpoint=text(AgentRunMetadata.PAUSE_CHECKPOINT_KEY),
            source=text(AgentRunMetadata.PAUSE_SOURCE_KEY),
        )

    @staticmethod
    def request_pause(
        metadata: dict[str, object],
        reason: str | None,
    ) -> dict[str, object]:
        """Ask a running run to pause at its next checkpoint."""
        return AgentRunMetadata.with_runtime(
            metadata,
            **{
                AgentRunMetadata.PAUSE_REQUESTED_KEY: True,
                AgentRunMetadata.PAUSE_REASON_KEY: reason,
            },
        )

    @staticmethod
    def resolved_by_operator(
        metadata: dict[str, object],
        *,
        resumable: bool,
    ) -> dict[str, object]:
        """Record whether operator resolution left the pause resumable."""
        return AgentRunMetadata.with_runtime(
            metadata,
            **{
                AgentRunMetadata.MANUAL_PAUSE_KEY: resumable,
                AgentRunMetadata.PAUSE_CHECKPOINT_KEY: "operator_resolution",
                AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: resumable,
            },
        )

    @staticmethod
    def resumed(metadata: dict[str, object]) -> dict[str, object]:
        """Clear the pause once a run continues from its checkpoint."""
        return AgentRunMetadata.with_runtime(
            metadata,
            **{
                AgentRunMetadata.MANUAL_PAUSE_KEY: False,
                AgentRunMetadata.PAUSE_REQUESTED_KEY: False,
            },
        )

    @staticmethod
    def canceled(metadata: dict[str, object], reason: str) -> dict[str, object]:
        return AgentRunMetadata.with_runtime(
            metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: False},
            cancel_reason=reason,
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
