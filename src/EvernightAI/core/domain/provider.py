import logging
from collections.abc import AsyncIterator
from time import perf_counter

from EvernightAI.core.protocol.provider import (
    ProviderRegisterProtocol,
    ProviderManageProtocol,
    ProviderInstanceProtocol,
    ProviderFactoryProtocol,
    ProviderBuilderProtocol,
    ProviderConfigStoreProtocol,
    ProviderSecretResolverProtocol,
)
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatUsage,
    ContentPartType,
)
from EvernightAI.core.schema.stream import ChatStreamEvent

from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.error.provider import (
    ProviderCapabilityUnsupportedError,
    ProviderConfigurationError,
    ProviderNotFoundError,
)


LOGGER = logging.getLogger("EvernightAI.provider")


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
    def __init__(
        self,
        factory: ProviderFactoryProtocol,
        config_store: ProviderConfigStoreProtocol | None = None,
        secret_resolver: ProviderSecretResolverProtocol | None = None,
    ) -> None:
        self._factory = factory
        self._config_store = config_store
        self._secret_resolver = secret_resolver
        self._instances: dict[str, ProviderInstanceProtocol] = {}
        self._infos: dict[str, ProviderInfo] = {}
        self._call_totals: dict[str, int] = {}
        self._error_totals: dict[str, int] = {}

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol:
        """创建提供实例"""
        resolved = self._resolve_secret(provider)
        instance = await self._factory.create(resolved)
        previous = self._instances.get(provider.provider_id)
        self._instances[provider.provider_id] = instance
        self._infos[provider.provider_id] = ProviderInfo(
            provider_id=provider.provider_id,
            name=provider.name,
            type=provider.type,
            is_enabled=provider.is_enabled,
            model=provider.model,
            metadata=dict(provider.metadata),
        )
        if self._config_store is not None and not (
            provider.api_key is not None and provider.api_key_secret_ref is None
        ):
            self._config_store.save(provider.model_copy(update={"api_key": None}))
        if previous is not None and previous is not instance:
            await previous.close()
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

    async def list_infos(self) -> list[ProviderInfo]:
        """获取所有提供信息"""
        return list(self._infos.values())

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
        self._validate_request_capabilities(provider_id, request)
        started = perf_counter()
        try:
            response = await instance.chat(request)
        except Exception as exc:
            self._record_call(
                provider_id,
                request,
                started=started,
                error=exc,
            )
            raise
        self._record_call(
            provider_id,
            request,
            started=started,
            response=response,
        )
        return response

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol:
        """执行流式聊天请求"""
        instance = await self.get(provider_id)
        self._validate_request_capabilities(provider_id, request)
        started = perf_counter()
        try:
            stream = await instance.chat_stream(request)
        except Exception as exc:
            self._record_call(
                provider_id,
                request,
                started=started,
                error=exc,
            )
            raise
        return _ObservedChatStream(
            stream,
            manager=self,
            provider_id=provider_id,
            request=request,
            started=started,
        )

    async def delete(self, provider_id: str) -> None:
        """删除提供实例"""
        instance = await self.get(provider_id)
        await instance.close()
        self._instances.pop(provider_id, None)
        self._infos.pop(provider_id, None)
        if self._config_store is not None:
            try:
                self._config_store.delete(provider_id)
            except ProviderNotFoundError:
                pass

    async def restore(self) -> list[str]:
        if self._config_store is None:
            return []
        restored: list[str] = []
        for config in self._config_store.list_configs(enabled_only=True):
            await self.create(config)
            restored.append(config.provider_id)
        return restored

    async def close(self) -> None:
        """关闭所有提供实例"""
        for instance in list(self._instances.values()):
            await instance.close()
        self._instances.clear()
        self._infos.clear()

    def _resolve_secret(self, provider: ProviderConfig) -> ProviderConfig:
        if provider.api_key is not None or provider.api_key_secret_ref is None:
            return provider
        if self._secret_resolver is None:
            raise ProviderConfigurationError(
                f"No secret resolver is configured for {provider.api_key_secret_ref}"
            )
        return provider.model_copy(
            update={"api_key": self._secret_resolver.resolve(provider.api_key_secret_ref)}
        )

    def _validate_request_capabilities(
        self,
        provider_id: str,
        request: ChatRequest,
    ) -> None:
        model = next(
            (
                configured
                for configured in self._infos[provider_id].model.values()
                if configured.model_id == request.model_id
            ),
            None,
        )
        if model is None:
            return

        has_image = any(
            part.type is ContentPartType.IMAGE
            for message in request.messages
            for part in message.content or []
        )
        if (
            has_image
            and ProviderModelCapability.IMAGE_RECOGNITION not in model.capabilities
        ):
            raise ProviderCapabilityUnsupportedError(
                f"The model {request.model_id} does not support image recognition"
            )

    def _record_call(
        self,
        provider_id: str,
        request: ChatRequest,
        *,
        started: float,
        response: ChatResponse | None = None,
        usage: ChatUsage | None = None,
        error: BaseException | None = None,
    ) -> None:
        total = self._call_totals.get(provider_id, 0) + 1
        errors = self._error_totals.get(provider_id, 0) + int(error is not None)
        self._call_totals[provider_id] = total
        self._error_totals[provider_id] = errors
        usage = response.usage if response is not None else usage
        metadata = request.metadata
        extra = {
            "request_id": metadata.get("request_id"),
            "session_id": metadata.get("session_id"),
            "run_id": metadata.get("run_id"),
            "provider_id": provider_id,
            "model_id": request.model_id,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "success": error is None,
            "error_type": error.__class__.__name__ if error is not None else None,
            "prompt_tokens": usage.prompt_tokens if usage is not None else None,
            "completion_tokens": usage.completion_tokens if usage is not None else None,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "provider_calls_total": total,
            "provider_errors_total": errors,
            "provider_error_rate": errors / total,
        }
        if error is None:
            LOGGER.info("Provider call completed", extra=extra)
        else:
            LOGGER.warning("Provider call failed", extra=extra)


class _ObservedChatStream(ChatStreamProtocol):
    def __init__(
        self,
        stream: ChatStreamProtocol,
        *,
        manager: ProviderManager,
        provider_id: str,
        request: ChatRequest,
        started: float,
    ) -> None:
        self._stream = stream
        self._manager = manager
        self._provider_id = provider_id
        self._request = request
        self._started = started

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[ChatStreamEvent]:
        usage: ChatUsage | None = None
        try:
            async for event in self._stream:
                if event.usage is not None:
                    usage = event.usage
                yield event
        except BaseException as exc:
            self._manager._record_call(
                self._provider_id,
                self._request,
                started=self._started,
                usage=usage,
                error=exc,
            )
            raise
        else:
            self._manager._record_call(
                self._provider_id,
                self._request,
                started=self._started,
                usage=usage,
            )
