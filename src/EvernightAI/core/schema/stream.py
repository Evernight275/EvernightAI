from typing import Any
from enum import StrEnum

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.agent import AgentTraceEvent
from EvernightAI.core.schema.content import ChatUsage, ContentPart, MessageRole
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolCall


class SSEEvent(EvernightAISchema):
    """SSE事件"""

    data: str
    event: str | None = None
    event_id: str | None = Field(default=None, alias="id")
    retry: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatStreamEventType(StrEnum):
    """聊天流式事件类型"""

    RAW = "raw"
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETED = "message_completed"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


class ChatStreamEvent(EvernightAISchema):
    """聊天流式语义事件"""

    event_type: ChatStreamEventType
    response_id: str | None = None
    model_id: str | None = None
    role: MessageRole | None = None
    content_part: ContentPart | None = None
    text_delta: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: str | None = None
    usage: ChatUsage | None = None
    raw_event: str | None = None
    raw_data: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketMessageType(StrEnum):
    """WebSocket消息类型"""

    HELLO = "hello"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    AGENT_TRACE = "agent_trace"
    AGENT_CONTROL = "agent_control"
    TOOL_APPROVAL = "tool_approval"
    CLIENT_EVENT = "client_event"
    ERROR = "error"


class WebSocketAgentControlAction(StrEnum):
    """WebSocket Agent控制动作"""

    CANCEL = "cancel"
    PAUSE = "pause"
    RESUME = "resume"


class WebSocketHeartbeat(EvernightAISchema):
    """WebSocket心跳载荷"""

    sequence: int | None = Field(default=None, ge=0)
    sent_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketHello(EvernightAISchema):
    """WebSocket握手载荷"""

    protocol_version: str = "1"
    connection_id: str | None = None
    capabilities: list[WebSocketMessageType] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketAgentControl(EvernightAISchema):
    """WebSocket Agent运行控制载荷"""

    run_id: str
    action: WebSocketAgentControlAction
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketToolApproval(EvernightAISchema):
    """WebSocket工具审批载荷"""

    run_id: str
    decision: ToolApprovalDecision
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketClientEvent(EvernightAISchema):
    """WebSocket前端控制事件载荷"""

    event_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketError(EvernightAISchema):
    """WebSocket错误载荷"""

    error_type: str
    error_message: str
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSocketMessage(EvernightAISchema):
    """WebSocket传输消息信封"""

    message_type: WebSocketMessageType
    message_id: str | None = None
    correlation_id: str | None = None
    run_id: str | None = None
    hello: WebSocketHello | None = None
    heartbeat: WebSocketHeartbeat | None = None
    agent_control: WebSocketAgentControl | None = None
    tool_approval: WebSocketToolApproval | None = None
    client_event: WebSocketClientEvent | None = None
    trace_event: AgentTraceEvent | None = None
    error: WebSocketError | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
