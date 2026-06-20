from EvernightAI.core.schema.base import EvernightAISchema
from typing import Any
from enum import StrEnum
from pydantic import Field


class ToolPermission(StrEnum):
    """工具权限"""

    READ = "read"
    WRITE = "write"
    PROCESS = "process"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    DATABASE = "database"
    EXTERNAL_API = "external_api"
    DESTRUCTIVE = "destructive"


class ToolSafetyLevel(StrEnum):
    """工具安全等级"""

    SAFE = "safe"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class ToolDefinition(EvernightAISchema):
    """
    工具定义schema
    """

    name: str
    description: str
    parameters_schema: dict[str, Any] | None = None
    permissions: list[ToolPermission] = Field(default_factory=list)
    safety_level: ToolSafetyLevel = ToolSafetyLevel.SAFE
    requires_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(EvernightAISchema):
    """
    工具调用schema
    """

    tool_call_id: str = Field(description="工具调用ID")
    tool_call: dict[str, Any] = Field(description="工具调用参数")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(EvernightAISchema):
    """
    工具调用结果schema
    """

    tool_call_id: str = Field(description="工具调用ID")
    tool_call_result: dict[str, Any] = Field(description="工具调用结果")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolSafetyDecision(EvernightAISchema):
    """
    工具安全决策schema
    """

    allowed: bool
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
