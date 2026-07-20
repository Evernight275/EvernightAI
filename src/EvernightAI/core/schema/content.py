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


class MessageStatus(StrEnum):
    """消息状态"""

    ACTIVE = "active"
    REJECTED = "rejected"
    ERROR = "error"


class PromptCacheMode(StrEnum):
    PROVIDER_DEFAULT = "provider_default"
    PREFER_EXPLICIT = "prefer_explicit"


class PromptCacheScope(StrEnum):
    CONTEXT = "context"
    OWNER = "owner"
    GLOBAL = "global"


class PromptCachePolicy(EvernightAISchema):
    mode: PromptCacheMode = PromptCacheMode.PROVIDER_DEFAULT
    scope: PromptCacheScope = PromptCacheScope.CONTEXT
    scope_id: str | None = Field(default=None, min_length=1, max_length=256)


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
    status: MessageStatus | None = None
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

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_prompt_tokens: int | None = Field(default=None, ge=0)
    cache_write_prompt_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(EvernightAISchema):
    """聊天请求"""

    model_id: str
    messages: list[Content]
    skills: list[ChatSkill] | None = None
    tools: list[ToolDefinition] | None = None
    prompt_cache: PromptCachePolicy | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(EvernightAISchema):
    """聊天响应"""

    response_id: str | None = None
    model_id: str
    message: Content
    finish_reason: str | None = None
    usage: ChatUsage | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
