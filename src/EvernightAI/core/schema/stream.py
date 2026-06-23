from typing import Any
from enum import StrEnum

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatUsage, ContentPart, MessageRole
from EvernightAI.core.schema.tool import ToolCall


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
