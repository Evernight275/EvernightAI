from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import Content


class Context(EvernightAISchema):
    """会话上下文"""

    context_id: str
    owner_id: str | None = None
    revision: int = Field(default=0, ge=0)
    messages: list[Content] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextWindow(EvernightAISchema):
    """已组织的基础上下文窗口"""

    context_id: str
    messages: list[Content] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
