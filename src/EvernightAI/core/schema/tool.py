from EvernightAI.core.schema.base import EvernightAISchema
from typing import Any
from pydantic import Field


class ToolDefinition(EvernightAISchema):
    """
    工具定义schema
    """

    name: str
    description: str
    parameters_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(EvernightAISchema):
    """
    工具调用schema
    """

    tool_call_id: str = Field(description="工具调用ID")
    tool_call: dict[str, Any] = Field(description="工具调用参数")


class ToolCallResult(EvernightAISchema):
    """
    工具调用结果schema
    """

    tool_call_id: str = Field(description="工具调用ID")
    tool_call_result: dict[str, Any] = Field(description="工具调用结果")
