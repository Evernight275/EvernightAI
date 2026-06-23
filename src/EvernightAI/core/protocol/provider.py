from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    FactoryProtocol,
    InstanceProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import (
    ProviderInfo,
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from collections.abc import Awaitable, Callable


class ProviderProtocol(EvernightAIProtocol):
    """
    提供商协议
    """


class ProviderInstanceProtocol(ProviderProtocol, InstanceProtocol):
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


class ProviderRegisterProtocol(ProviderProtocol, RegisterProtocol):
    """
    提供商注册协议
    """

    def register(self, provider: ProviderInfo) -> None: ...

    def unregister(self, provider_id: str) -> None: ...

    def get(self, provider_id: str) -> ProviderInfo: ...

    def has(self, provider_id: str) -> bool: ...


class ProviderResponsibilityProtocol(ProviderProtocol, ResponsibilityProtocol):
    """
    提供商职责协议
    """


class ProviderManageProtocol(ProviderProtocol, ManageProtocol):
    """
    提供商管理协议
    """

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol: ...

    async def get(self, provider_id: str) -> ProviderInstanceProtocol: ...

    async def list_instances(self) -> list[ProviderInstanceProtocol]: ...

    async def list_models(self, provider_id: str) -> list[ProviderModelConfig]: ...

    async def get_model(
        self, provider_id: str, model_id: str
    ) -> ProviderModelConfig: ...

    async def supports(
        self, provider_id: str, capability: ProviderModelCapability
    ) -> bool: ...

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse: ...

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol: ...

    async def delete(self, provider_id: str) -> None: ...

    async def close(self) -> None: ...


class ProviderFactoryProtocol(ProviderProtocol, FactoryProtocol, RegisterProtocol):
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
