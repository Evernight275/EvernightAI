from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import ChatResponse, ChatSkill, Content
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolDefinition


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(StrEnum):
    """会话状态"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class Session(EvernightAISchema):
    """会话"""

    session_id: str
    title: str | None = None
    context_id: str
    provider_id: str | None = None
    model_id: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionChatRequest(EvernightAISchema):
    """会话聊天请求"""

    provider_id: str | None = None
    model_id: str | None = None
    messages: list[Content] = Field(default_factory=list)
    memory_query: MemoryQuery | None = None
    skills: list[ChatSkill] | None = None
    tools: list[ToolDefinition] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionAgentRunRequest(SessionChatRequest):
    """会话 Agent 运行请求"""

    max_tool_rounds: int = Field(default=1, ge=0)
    recover_tool_errors: bool = True
    write_memory: bool = False
    tool_approvals: list[ToolApprovalDecision] = Field(default_factory=list)
    pause_on_approval: bool = False


class SessionChatResult(EvernightAISchema):
    """会话聊天结果"""

    session: Session
    response: ChatResponse
