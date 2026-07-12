from enum import StrEnum
from datetime import datetime, timezone
from typing import Any

from pydantic import Field, field_validator, model_validator

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


class MemorySort(StrEnum):
    """记忆排序方式"""

    DEFAULT = "default"
    PRIORITY = "priority"
    RELEVANCE = "relevance"
    CONFIDENCE = "confidence"
    UPDATED_AT = "updated_at"
    CREATED_AT = "created_at"
    MEMORY_ID = "memory_id"


class MemoryWriteOperation(StrEnum):
    """记忆写入操作"""

    CREATE = "create"
    REPLACE = "replace"
    MERGE = "merge"


class MemoryScopeSelector(EvernightAISchema):
    """记忆作用域选择器"""

    scope: MemoryScope
    scope_id: str | None = None

    @field_validator("scope_id")
    @classmethod
    def _normalize_scope_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_scope_identity(self) -> "MemoryScopeSelector":
        if self.scope is MemoryScope.GLOBAL and self.scope_id is not None:
            raise ValueError("global memory selector must not have a scope_id")
        if self.scope is not MemoryScope.GLOBAL and self.scope_id is None:
            raise ValueError("non-global memory selector must have a scope_id")
        return self


class MemoryItem(EvernightAISchema):
    """记忆项"""

    memory_id: str
    owner_id: str | None = None
    content: str
    kind: MemoryKind = MemoryKind.FACT
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: int = 0
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_enabled: bool = True
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _content_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("memory content must not be empty")
        return normalized

    @field_validator("scope_id", "owner_id")
    @classmethod
    def _normalize_optional_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            next_tag = tag.strip().casefold()
            if not next_tag or next_tag in seen:
                continue
            seen.add(next_tag)
            normalized.append(next_tag)
        return normalized

    @field_validator("expires_at", "created_at", "updated_at")
    @classmethod
    def _normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("memory datetime values must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_scope_identity(self) -> "MemoryItem":
        if self.scope is MemoryScope.GLOBAL and self.scope_id is not None:
            raise ValueError("global memory must not have a scope_id")
        if self.scope is not MemoryScope.GLOBAL and self.scope_id is None:
            raise ValueError("non-global memory must have a scope_id")
        if self.updated_at < self.created_at:
            raise ValueError("memory updated_at must not be before created_at")
        return self


class MemoryQuery(EvernightAISchema):
    """记忆查询"""

    text: str | None = None
    scope: MemoryScope | None = None
    scope_id: str | None = None
    scopes: list[MemoryScopeSelector] = Field(default_factory=list)
    kinds: list[MemoryKind] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    minimum_relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    include_disabled: bool = False
    include_expired: bool = False
    deduplicate: bool = False
    sort: MemorySort = MemorySort.DEFAULT
    limit: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("scope_id")
    @classmethod
    def _normalize_scope_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            next_tag = tag.strip().casefold()
            if not next_tag or next_tag in seen:
                continue
            seen.add(next_tag)
            normalized.append(next_tag)
        return normalized


class MemorySelection(EvernightAISchema):
    """记忆选择结果"""

    memories: list[MemoryItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
