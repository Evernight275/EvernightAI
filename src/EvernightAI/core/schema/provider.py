from datetime import timedelta
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

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
    api_key_secret_ref: str | None = None
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


class ProviderConfigView(ProviderInfo):
    """Editable configuration without the raw API key."""

    discover_models: bool = False
    base_url: str | None = None
    api_key_secret_ref: str | None = None
    has_api_key: bool = False


class ProviderConfigUpdate(EvernightAISchema):
    """Partial update; omitted fields retain their current values."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    type: ProviderType | None = None
    is_enabled: bool | None = None
    discover_models: bool | None = None
    api_key: str | None = Field(default=None, min_length=1)
    api_key_secret_ref: str | None = Field(default=None, min_length=1)
    base_url: str | None = None
    model: dict[str, ProviderModelConfig] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "ProviderConfigUpdate":
        for name in self.model_fields_set - {"api_key", "api_key_secret_ref", "base_url"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.api_key is not None and self.api_key_secret_ref is not None:
            raise ValueError("Specify either api_key or api_key_secret_ref")
        return self


class ProviderTestRequest(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=256)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_id cannot be blank")
        return value.strip()


class ProviderTestResult(EvernightAISchema):
    provider_id: str
    model_id: str
    success: bool
    elapsed_ms: float = Field(ge=0)
    response_model_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
