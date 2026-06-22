from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from pydantic import Field
from enum import StrEnum
from typing import Any


class MessageRole(StrEnum):
    """消息角色"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ContentPartType(StrEnum):
    """内容部分类型"""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    EMBED = "embed"
    LINK = "link"
    TABLE = "table"
    CODE = "code"
    FUNCTION_CALL = "function_call"


class ContentPart(EvernightAISchema):
    """内容部分"""

    type: ContentPartType = Field(description="内容部分类型")
    text: str | None = None
    url: str | None = None
    data: str | None = None
    mime_type: str | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Content(EvernightAISchema):
    """内容部分schema"""

    role: MessageRole
    content: list[ContentPart] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatSkill(EvernightAISchema):
    """聊天请求中的技能提示词声明"""

    skill_name: str
    render_id: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatUsage(EvernightAISchema):
    """聊天调用用量"""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(EvernightAISchema):
    """聊天请求"""

    model_id: str
    messages: list[Content]
    skills: list[ChatSkill] | None = None
    tools: list[ToolDefinition] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(EvernightAISchema):
    """聊天响应"""

    response_id: str | None = None
    model_id: str
    message: Content
    finish_reason: str | None = None
    usage: ChatUsage | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
