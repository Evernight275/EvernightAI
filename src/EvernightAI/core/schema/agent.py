from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatResponse, ChatSkill, Content
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


class AgentStopReason(StrEnum):
    """Agent停止原因"""

    FINISHED = "finished"
    TOOL_ROUNDS_EXHAUSTED = "tool_rounds_exhausted"
    TOOL_ERROR = "tool_error"


class AgentRunRequest(EvernightAISchema):
    """Agent运行请求"""

    provider_id: str
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
    stop_reason: AgentStopReason = AgentStopReason.FINISHED
    steps: list[AgentStep] = Field(default_factory=list)
    trace: list["AgentTraceEvent"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTraceEvent(TraceEvent[AgentTraceEventType]):
    """Agent运行追踪事件。

    这是通用TraceEvent在agent领域里的强类型事件；它记录可观察时间线，
    不承担AgentRunState的恢复快照职责。
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
    stop_reason: AgentStopReason | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    trace: list[AgentTraceEvent] = Field(default_factory=list)
    remaining_tool_rounds: int = 0
    tool_rounds_used: int = 0
    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    pending_approval_requests: list[ToolApprovalRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
