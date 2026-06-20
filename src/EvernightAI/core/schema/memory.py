from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class MemoryKind(StrEnum):
    """记忆类型"""

    FACT = "fact"
    PREFERENCE = "preference"
    SUMMARY = "summary"
    DEFINITION = "definition"
    INSTRUCTION = "instruction"
    EPISODIC = "episodic"


class MemoryScope(StrEnum):
    """记忆作用域"""

    GLOBAL = "global"
    USER = "user"
    SESSION = "session"
    CONTEXT = "context"


class MemoryItem(EvernightAISchema):
    """记忆项"""

    memory_id: str
    content: str
    kind: MemoryKind = MemoryKind.FACT
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: int = 0
    is_enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryQuery(EvernightAISchema):
    """记忆查询"""

    scope: MemoryScope | None = None
    scope_id: str | None = None
    kinds: list[MemoryKind] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySelection(EvernightAISchema):
    """记忆选择结果"""

    memories: list[MemoryItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
