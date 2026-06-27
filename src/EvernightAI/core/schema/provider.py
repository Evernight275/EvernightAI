from datetime import timedelta
from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class ProviderType(StrEnum):
    """提供商类型"""

    OPENAI = "openai"
    OPENAI_RESPONSES = "openai_responses"
    GOOGLE = "google"
    ANTHROPIC = "anthropic"


class ProviderModelCapability(StrEnum):
    """模型能力"""

    CHAT = "chat"
    TOOL_CALL = "tool_call"
    IMAGE_GENERATION = "image_generation"
    IMAGE_RECOGNITION = "image_recognition"
    VIDEO_GENERATION = "video_generation"
    VIDEO_RECOGNITION = "video_recognition"


class ProviderModelConfig(EvernightAISchema):
    model_id: str = Field(description="模型ID")
    timeout: timedelta = Field(
        description="超时时间，默认30秒", default=timedelta(seconds=30)
    )
    capabilities: list[ProviderModelCapability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderConfig(EvernightAISchema):
    """提供商配置"""

    provider_id: str
    name: str
    type: ProviderType
    is_enabled: bool = True
    discover_models: bool = False
    api_key: str | None = None
    base_url: str | None = None
    model: dict[str, ProviderModelConfig] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderInfo(EvernightAISchema):
    """提供商信息"""

    provider_id: str
    name: str
    type: ProviderType
    is_enabled: bool = True
    model: dict[str, ProviderModelConfig] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
