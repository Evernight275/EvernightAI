from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import (
    ProviderInfo,
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderConfigView,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable
from EvernightAI.core.schema.image import ImageEditRequest, ImageGenerationRequest, ImageGenerationResponse


@runtime_checkable
class ImageGenerationProviderProtocol(Protocol):
    async def generate_images(self, request: ImageGenerationRequest) -> ImageGenerationResponse: ...


@runtime_checkable
class ImageEditProviderProtocol(Protocol):
    async def edit_images(self, request: ImageEditRequest) -> ImageGenerationResponse: ...


class ProviderInstanceProtocol(Protocol):
    """
    提供商实例协议
    """

    async def list_models(self) -> list[ProviderModelConfig]:
        """列出支持的模型"""
        ...

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        """获取模型配置"""
        ...

    async def supports(self, capability: ProviderModelCapability) -> bool:
        """检查是否支持指定能力"""
        ...

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """聊天"""
        ...

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        """流式聊天"""
        ...

    async def close(self) -> None:
        """关闭实例"""
        ...


ProviderBuilderProtocol = Callable[
    [ProviderConfig], Awaitable[ProviderInstanceProtocol]
]


class ProviderRegisterProtocol(Protocol):
    """
    提供商注册协议
    """

    def register(self, provider: ProviderInfo) -> None: ...

    def unregister(self, provider_id: str) -> None: ...

    def get(self, provider_id: str) -> ProviderInfo: ...

    def has(self, provider_id: str) -> bool: ...


class ProviderConfigStoreProtocol(Protocol):
    """可恢复的Provider配置存储；实现须加密密钥并以引用替代明文。"""

    def save(self, provider: ProviderConfig) -> None: ...

    def get(self, provider_id: str) -> ProviderConfig: ...

    def list_configs(self, *, enabled_only: bool = False) -> list[ProviderConfig]: ...

    def delete(self, provider_id: str) -> None: ...


class ProviderSecretResolverProtocol(Protocol):
    def resolve(self, secret_ref: str) -> str: ...


class ProviderManageProtocol(Protocol):
    """
    提供商管理协议
    """

    async def create(
        self, provider: ProviderConfig, *, replace_existing: bool = True,
    ) -> ProviderInstanceProtocol | None: ...

    async def get(self, provider_id: str) -> ProviderInstanceProtocol: ...

    async def get_info(self, provider_id: str) -> ProviderInfo: ...

    async def get_config(self, provider_id: str) -> ProviderConfigView: ...

    async def update(
        self, provider_id: str, update: ProviderConfigUpdate,
    ) -> ProviderInstanceProtocol | None: ...

    async def list_instances(self) -> list[ProviderInstanceProtocol]: ...

    async def list_infos(self) -> list[ProviderInfo]: ...

    async def list_models(self, provider_id: str) -> list[ProviderModelConfig]: ...

    async def get_model(
        self, provider_id: str, model_id: str
    ) -> ProviderModelConfig: ...

    async def supports(
        self, provider_id: str, capability: ProviderModelCapability
    ) -> bool: ...

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse: ...

    async def generate_images(
        self, provider_id: str, request: ImageGenerationRequest,
    ) -> ImageGenerationResponse: ...

    async def edit_images(
        self, provider_id: str, request: ImageEditRequest,
    ) -> ImageGenerationResponse: ...

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol: ...

    async def delete(self, provider_id: str) -> None: ...

    async def close(self) -> None: ...

    async def restore(self) -> list[str]: ...


class ProviderFactoryProtocol(Protocol):
    """
    提供商工厂协议
    """

    def register(
        self, provider_type: ProviderType, builder: ProviderBuilderProtocol
    ) -> None: ...

    def unregister(self, provider_type: ProviderType) -> None: ...

    def get(self, provider_type: ProviderType) -> ProviderBuilderProtocol: ...

    def has(self, provider_type: ProviderType) -> bool: ...

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol: ...
