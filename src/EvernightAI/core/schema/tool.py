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


class ToolApprovalStatus(StrEnum):
    """工具审批状态"""

    REQUESTED = "requested"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ToolApprovalMode(StrEnum):
    AUTO = "auto"
    REQUIRED = "required"
    NEVER = "never"


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
    approval_mode: ToolApprovalMode = ToolApprovalMode.AUTO
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolApprovalRequest(EvernightAISchema):
    """
    工具审批请求schema
    """

    approval_id: str
    tool_call_id: str
    tool_name: str
    tool_call: dict[str, Any] = Field(default_factory=dict)
    permissions: list[ToolPermission] = Field(default_factory=list)
    safety_level: ToolSafetyLevel = ToolSafetyLevel.SAFE
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolApprovalDecision(EvernightAISchema):
    """
    工具审批决策schema
    """

    approval_id: str
    tool_call_id: str
    status: ToolApprovalStatus
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(EvernightAISchema):
    """
    工具调用schema
    """

    tool_call_id: str = Field(description="工具调用ID")
    tool_call: dict[str, Any] = Field(description="工具调用参数")
    approval: ToolApprovalDecision | None = None
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
    requires_approval: bool = False
    approval_request: ToolApprovalRequest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
