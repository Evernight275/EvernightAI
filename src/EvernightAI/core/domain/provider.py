from EvernightAI.core.protocol.provider import (
    ProviderRegisterProtocol,
    ProviderManageProtocol,
    ProviderInstanceProtocol,
    ProviderFactoryProtocol,
    ProviderBuilderProtocol,
)
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse

from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.error.provider import ProviderNotFoundError


class ProviderRegister(ProviderRegisterProtocol):
    def __init__(self) -> None:
        self._providers: dict[str, ProviderInfo] = {}

    def register(self, provider: ProviderInfo) -> None:
        """注册提供"""
        self._providers[provider.provider_id] = provider

    def unregister(self, provider_id: str) -> None:
        """注销提供"""
        if self.has(provider_id):
            self._providers.pop(provider_id, None)
        else:
            raise ProviderNotFoundError(f"The provider {provider_id} is not registered")

    def has(self, provider_id: str) -> bool:
        """检查提供是否存在"""
        return provider_id in self._providers

    def get(self, provider_id: str) -> ProviderInfo:
        """获取提供"""
        if provider_id in self._providers:
            return self._providers[provider_id]
        else:
            raise ProviderNotFoundError(f"The provider {provider_id} is not found")


class ProviderFactory(ProviderFactoryProtocol):
    def __init__(self) -> None:
        self._builders: dict[ProviderType, ProviderBuilderProtocol] = {}

    def register(
        self, provider_type: ProviderType, builder: ProviderBuilderProtocol
    ) -> None:
        """注册提供构建器"""
        self._builders[provider_type] = builder

    def unregister(self, provider_type: ProviderType) -> None:
        """注销提供构建器"""
        if self.has(provider_type):
            self._builders.pop(provider_type, None)
        else:
            raise ProviderNotFoundError(f"The provider {provider_type} is not registered")

    def has(self, provider_type: ProviderType) -> bool:
        """检查提供构建器是否存在"""
        return provider_type in self._builders

    def get(self, provider_type: ProviderType) -> ProviderBuilderProtocol:
        """获取提供构建器"""
        if self.has(provider_type):
            return self._builders[provider_type]
        else:
            raise ProviderNotFoundError(f"The provider {provider_type} is not registered")

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol:
        """创建提供实例"""
        builder = self.get(provider.type)
        return await builder(provider)


class ProviderManager(ProviderManageProtocol):
    def __init__(self, factory: ProviderFactoryProtocol) -> None:
        self._factory = factory
        self._instances: dict[str, ProviderInstanceProtocol] = {}

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol:
        """创建提供实例"""
        instance = await self._factory.create(provider)
        self._instances[provider.provider_id] = instance
        return instance

    async def get(self, provider_id: str) -> ProviderInstanceProtocol:
        """获取提供实例"""
        if provider_id in self._instances:
            return self._instances[provider_id]
        else:
            raise ProviderNotFoundError(f"The provider {provider_id} is not found")

    async def list_instances(self) -> list[ProviderInstanceProtocol]:
        """获取所有提供实例"""
        return list(self._instances.values())

    async def list_models(self, provider_id: str) -> list[ProviderModelConfig]:
        """获取提供实例支持的模型"""
        instance = await self.get(provider_id)
        return await instance.list_models()

    async def get_model(self, provider_id: str, model_id: str) -> ProviderModelConfig:
        """获取提供实例的模型配置"""
        instance = await self.get(provider_id)
        return await instance.get_model(model_id)

    async def supports(
        self, provider_id: str, capability: ProviderModelCapability
    ) -> bool:
        """检查提供实例是否支持指定能力"""
        instance = await self.get(provider_id)
        return await instance.supports(capability)

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        """执行聊天请求"""
        instance = await self.get(provider_id)
        return await instance.chat(request)

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol:
        """执行流式聊天请求"""
        instance = await self.get(provider_id)
        return await instance.chat_stream(request)

    async def delete(self, provider_id: str) -> None:
        """删除提供实例"""
        instance = await self.get(provider_id)
        await instance.close()
        self._instances.pop(provider_id, None)

    async def close(self) -> None:
        """关闭所有提供实例"""
        for instance in list(self._instances.values()):
            await instance.close()
        self._instances.clear()
