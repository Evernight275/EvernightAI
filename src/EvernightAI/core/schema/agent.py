from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatResponse, ChatSkill, ChatUsage, Content
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.trace import TraceEvent
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalRequest,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    ToolReplayPolicy,
)


class AgentStepType(StrEnum):
    """Agent步骤类型"""

    START = "start"
    CHAT = "chat"
    TOOL = "tool"
    TOOL_ERROR = "tool_error"
    MEMORY_WRITE = "memory_write"
    STOP = "stop"


class AgentTraceEventType(StrEnum):
    """Agent追踪事件类型"""

    RUN_STARTED = "run_started"
    CHAT_DELTA = "chat_delta"
    CHAT_COMPLETED = "chat_completed"
    TOOL_APPROVAL_REQUESTED = "tool_approval_requested"
    TOOL_APPROVAL_DECIDED = "tool_approval_decided"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    TOOL_EXECUTION_RESOLVED = "tool_execution_resolved"
    MEMORY_WRITTEN = "memory_written"
    RUN_PAUSED = "run_paused"
    RUN_STOPPED = "run_stopped"


class AgentRunStatus(StrEnum):
    """Agent运行状态"""

    RUNNING = "running"
    PAUSED = "paused"
    CANCELED = "canceled"
    FINISHED = "finished"
    FAILED = "failed"


class AgentRunLease(EvernightAISchema):
    """Persisted executor lease for a running agent."""

    owner: str
    expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    generation: int = 0


class ToolExecutionStatus(StrEnum):
    SCHEDULED = "scheduled"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ToolExecutionResolution(StrEnum):
    CONFIRM_COMPLETED = "confirm_completed"
    RETRY = "retry"
    ABANDON_AND_RETRY_RUN = "abandon_and_retry_run"


class ToolExecutionAttempt(EvernightAISchema):
    run_id: str
    owner_id: str | None = None
    tool_call_id: str
    attempt: int = Field(ge=1)
    tool_name: str
    status: ToolExecutionStatus
    replay_policy: ToolReplayPolicy
    idempotency_key: str
    tool_call: ToolCall
    result: ToolCallResult | None = None
    error_type: str | None = None
    error_message: str | None = None
    resolution: ToolExecutionResolution | None = None
    resolution_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPauseCause(StrEnum):
    """Why a run stopped at a checkpoint instead of waiting for a tool approval."""

    MANUAL = "manual_pause"
    TIMEOUT = "timeout"
    SHUTDOWN = "shutdown"
    UNCLEAN_SHUTDOWN = "unclean_shutdown"
    LEASE_EXPIRED = "lease_expired"

    @property
    def source(self) -> str:
        """The name used in trace events, which record both shutdowns alike."""
        if self is AgentPauseCause.UNCLEAN_SHUTDOWN:
            return AgentPauseCause.SHUTDOWN.value
        return self.value


class AgentRunPause(EvernightAISchema):
    """A run stopped at a checkpoint: why, where, and whether it may continue.

    A resumable pause continues from its checkpoint. One that is not resumable
    can only be retried as a new run or unblocked by operator resolution. A run
    waiting for tool approval has no pause; its pending tool calls say so.
    """

    cause: AgentPauseCause
    checkpoint: str
    resumable: bool
    reason: str | None = None


class AgentPauseRequest(EvernightAISchema):
    """A request for a running run to pause at its next checkpoint."""

    reason: str | None = None


class AgentRunFailure(EvernightAISchema):
    """The error that ended a run, kept so the run can explain itself later."""

    error_type: str
    message: str
    detail: str | None = None


class AgentRunHistory(EvernightAISchema):
    """Where a run's messages sit in its context's history.

    A run records the context length it started from, then the index of each
    message it commits, so a transcript can place the run among the others.
    Fields are unset for snapshots written before they were recorded.
    """

    started_at: datetime | None = None
    message_offset: int | None = Field(default=None, ge=0)
    message_indices: list[int] | None = None
    generation: Any = None


class AgentStopReason(StrEnum):
    """Agent停止原因"""

    FINISHED = "finished"
    TOOL_ROUNDS_EXHAUSTED = "tool_rounds_exhausted"
    TOOL_ERROR = "tool_error"


class AgentRunRequest(EvernightAISchema):
    """Agent运行请求"""

    provider_id: str
    working_directory: str | None = None
    owner_id: str | None = None
    context_id: str
    model_id: str
    messages: list[Content] = Field(default_factory=list)
    retry_from_message_index: int | None = Field(default=None, ge=0)
    memory_query: MemoryQuery | None = None
    skills: list[ChatSkill] | None = None
    tools: list[ToolDefinition] | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    recover_tool_errors: bool = True
    write_memory: bool = False
    tool_approvals: list[ToolApprovalDecision] = Field(default_factory=list)
    pause_on_approval: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentStep(EvernightAISchema):
    """Agent运行步骤"""

    step_type: AgentStepType
    trace_event_id: str | None = None
    response: ChatResponse | None = None
    message: Content | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolCallResult | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(EvernightAISchema):
    """Agent运行结果"""

    response: ChatResponse
    usage: ChatUsage | None = None
    stop_reason: AgentStopReason = AgentStopReason.FINISHED
    tool_rounds_used: int | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    trace: list["AgentTraceEvent"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTraceEvent(TraceEvent[AgentTraceEventType]):
    """Agent运行追踪事件。

    这是通用TraceEvent在agent领域里的强类型事件；它记录可观察时间线，
    AgentRunState是恢复快照；持久化顺序号用于补齐快照之后的已完成步骤，
    trace不替代完整快照，也不证明外部写入已经提交。
    """

    event_type: AgentTraceEventType
    step_type: AgentStepType | None = None
    message: Content | None = None
    response: ChatResponse | None = None
    tool_call: ToolCall | None = None
    text_delta: str | None = None
    tool_result: ToolCallResult | None = None
    approval_request: ToolApprovalRequest | None = None
    approval_decision: ToolApprovalDecision | None = None


class AgentRunState(EvernightAISchema):
    """Agent运行状态快照"""

    run_id: str
    owner_id: str | None = None
    request: AgentRunRequest
    status: AgentRunStatus = AgentRunStatus.RUNNING
    response: ChatResponse | None = None
    usage: ChatUsage | None = None
    stop_reason: AgentStopReason | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    trace: list[AgentTraceEvent] = Field(default_factory=list)
    applied_trace_sequence: int | None = Field(default=None, ge=0)
    skill_revisions: dict[str, str | None] | None = None
    remaining_tool_rounds: int = 0
    tool_rounds_used: int = 0
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    pending_approval_requests: list[ToolApprovalRequest] = Field(default_factory=list)
    pause: AgentRunPause | None = None
    pause_request: AgentPauseRequest | None = None
    failure: AgentRunFailure | None = None
    cancel_reason: str | None = None
    history: AgentRunHistory = Field(default_factory=AgentRunHistory)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _lift_legacy_control_metadata(cls, data: Any) -> Any:
        """Read snapshots that kept control state under metadata["agent_runtime"]."""
        if not isinstance(data, dict):
            return data
        metadata = data.get("metadata")
        if not isinstance(metadata, dict) or not (
            _LEGACY_CONTROL_KEYS & metadata.keys()
        ):
            return data

        legacy = metadata.get("agent_runtime")
        legacy = legacy if isinstance(legacy, dict) else {}
        lifted = dict(data)
        lifted["metadata"] = {
            key: value
            for key, value in metadata.items()
            if key not in _LEGACY_CONTROL_KEYS
        }
        lifted.setdefault(
            "history",
            {
                "started_at": legacy.get("history_started_at"),
                "message_offset": legacy.get("context_message_offset"),
                "message_indices": (
                    legacy.get("context_message_indices")
                    if isinstance(legacy.get("context_message_indices"), list)
                    else None
                ),
                "generation": legacy.get("context_history_generation"),
            },
        )
        if legacy.get("pause_requested") is True:
            lifted.setdefault("pause_request", {"reason": legacy.get("pause_reason")})
        pause = _legacy_pause(data.get("status"), legacy, metadata)
        if pause is not None:
            lifted.setdefault("pause", pause)
        if isinstance(legacy.get("failure_type"), str):
            lifted.setdefault(
                "failure",
                {
                    "error_type": legacy["failure_type"],
                    "message": str(legacy.get("failure_message") or ""),
                    "detail": legacy.get("failure_detail"),
                },
            )
        if isinstance(legacy.get("cancel_reason"), str):
            lifted.setdefault("cancel_reason", legacy["cancel_reason"])
        return lifted


_LEGACY_CONTROL_KEYS = frozenset(
    {"agent_runtime", "interrupted", "interruption_reason"}
)


def _legacy_pause(
    status: Any,
    legacy: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    if status not in (AgentRunStatus.PAUSED, AgentRunStatus.PAUSED.value):
        return None
    # Legacy snapshots named the checkpoint-resume flag "manual_pause" and set
    # it for every resumable pause; "recovery_eligible" marked the blocked ones.
    if legacy.get("recovery_eligible") is False:
        resumable = False
    elif legacy.get("manual_pause") is True:
        resumable = True
    else:
        return None

    source = legacy.get("pause_source")
    if source == AgentPauseCause.SHUTDOWN.value and metadata.get("interrupted"):
        cause = AgentPauseCause.UNCLEAN_SHUTDOWN
    elif isinstance(source, str) and source in {cause.value for cause in AgentPauseCause}:
        cause = AgentPauseCause(source)
    else:
        cause = (
            AgentPauseCause.MANUAL if resumable else AgentPauseCause.UNCLEAN_SHUTDOWN
        )
    checkpoint = legacy.get("pause_checkpoint")
    reason = legacy.get("pause_reason")
    return {
        "cause": cause,
        "checkpoint": checkpoint if isinstance(checkpoint, str) else "unknown",
        "resumable": resumable,
        "reason": reason if isinstance(reason, str) else None,
    }
