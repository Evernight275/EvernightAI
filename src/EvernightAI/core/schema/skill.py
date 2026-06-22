from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class SkillCapability(StrEnum):
    """技能能力"""

    CHAT = "chat"
    TOOL_USE = "tool_use"
    MEMORY = "memory"
    CONTEXT = "context"
    AGENT = "agent"
    STREAMING = "streaming"


class SkillDefinition(EvernightAISchema):
    """
    技能定义schema
    """

    name: str
    description: str
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    capabilities: list[SkillCapability] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillCall(EvernightAISchema):
    """
    技能调用schema
    """

    skill_call_id: str
    skill_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillResult(EvernightAISchema):
    """
    技能调用结果schema
    """

    skill_call_id: str
    skill_name: str
    result: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
