from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, model_validator

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
    is_enabled: bool = True
    is_template: bool = False
    revision: str | None = Field(default=None, min_length=1)
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


class SkillTemplateConfig(SkillDefinition):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    description: str = Field(min_length=1, max_length=2000)
    prompt: str = Field(min_length=1, max_length=65536)


class SkillTemplateUpdate(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, min_length=1, max_length=2000)
    prompt: str | None = Field(default=None, min_length=1, max_length=65536)
    is_enabled: bool | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    capabilities: list[SkillCapability] | None = None
    required_tools: list[str] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "SkillTemplateUpdate":
        for name in self.model_fields_set - {"input_schema", "output_schema"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self
