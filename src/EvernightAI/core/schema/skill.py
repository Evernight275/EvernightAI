from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import Content


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


class SkillRenderRequest(EvernightAISchema):
    """
    技能渲染请求schema
    """

    render_id: str
    skill_name: str
    variables: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RenderedSkill(EvernightAISchema):
    """
    渲染后的技能schema
    """

    render_id: str
    skill_name: str
    messages: list[Content] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
