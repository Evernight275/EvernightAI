import logging
from asyncio import Event, Lock
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
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


@dataclass
class _ProviderSlot:
    provider_id: str
    generation: int
    instance: ProviderInstanceProtocol
    info: ProviderInfo
    active_calls: int = 0
    retired: bool = False
    close_started: bool = False
    call_total: int = 0
    error_total: int = 0
    idle: Event = field(default_factory=Event)

    def __post_init__(self) -> None:
        self.idle.set()


def merge_chat_usage(
    previous: ChatUsage | None,
    current: ChatUsage,
) -> ChatUsage:
    if previous is None:
        return current

    prompt_tokens = current.prompt_tokens
    if prompt_tokens is None:
        prompt_tokens = previous.prompt_tokens
    completion_tokens = current.completion_tokens
    if completion_tokens is None:
        completion_tokens = previous.completion_tokens

    total_tokens = current.total_tokens
    if total_tokens is None:
        usage_changed = (
            current.prompt_tokens is not None or current.completion_tokens is not None
        )
        if (
            usage_changed
            and prompt_tokens is not None
            and completion_tokens is not None
        ):
            total_tokens = prompt_tokens + completion_tokens
        else:
            total_tokens = previous.total_tokens

    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_prompt_tokens=(
            current.cached_prompt_tokens
            if current.cached_prompt_tokens is not None
            else previous.cached_prompt_tokens
        ),
        cache_write_prompt_tokens=(
            current.cache_write_prompt_tokens
            if current.cache_write_prompt_tokens is not None
            else previous.cache_write_prompt_tokens
        ),
        metadata={**previous.metadata, **current.metadata},
    )


class ProviderRegister(ProviderRegisterProtocol):
    def __init__(self) -> None:
        self._providers: dict[str, ProviderInfo] = {}

    def register(self, provider: ProviderInfo) -> None:
        self._providers[provider.provider_id] = provider

    def unregister(self, provider_id: str) -> None:
        if self.has(provider_id):
            self._providers.pop(provider_id, None)
        else:
            raise ProviderNotFoundError(f"The provider {provider_id} is not registered")

    def has(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def get(self, provider_id: str) -> ProviderInfo:
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
        self._builders[provider_type] = builder

    def unregister(self, provider_type: ProviderType) -> None:
        if self.has(provider_type):
            self._builders.pop(provider_type, None)
        else:
            raise ProviderNotFoundError(
                f"The provider {provider_type} is not registered"
            )

    def has(self, provider_type: ProviderType) -> bool:
        return provider_type in self._builders

    def get(self, provider_type: ProviderType) -> ProviderBuilderProtocol:
        if self.has(provider_type):
            return self._builders[provider_type]
        else:
            raise ProviderNotFoundError(
                f"The provider {provider_type} is not registered"
            )

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol:
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
        self._slots: dict[str, _ProviderSlot] = {}
        self._locks: dict[str, Lock] = {}
        self._generations: dict[str, int] = {}
        self._call_totals: dict[str, int] = {}
        self._error_totals: dict[str, int] = {}

    async def create(self, provider: ProviderConfig) -> ProviderInstanceProtocol:
        lock = self._lock_for(provider.provider_id)
        previous: _ProviderSlot | None = None
        async with lock:
            resolved = self._resolve_secret(provider)
            instance = await self._factory.create(resolved)
            try:
                info = self._provider_info(provider)
                if self._config_store is not None and not (
                    provider.api_key is not None and provider.api_key_secret_ref is None
                ):
                    self._config_store.save(
                        provider.model_copy(update={"api_key": None})
                    )
            except Exception:
                await self._close_unpublished_instance(
                    provider.provider_id,
                    instance,
                    message="Failed to close provider instance after create failure",
                )
                raise

            generation = self._generations.get(provider.provider_id, 0) + 1
            self._generations[provider.provider_id] = generation
            previous = self._slots.get(provider.provider_id)
            self._slots[provider.provider_id] = _ProviderSlot(
                provider_id=provider.provider_id,
                generation=generation,
                instance=instance,
                info=info,
            )
            if previous is not None:
                previous.retired = True

        if previous is not None:
            await self._close_if_idle(
                previous,
                message="Failed to close replaced provider instance",
            )
        return instance

    async def get(self, provider_id: str) -> ProviderInstanceProtocol:
        return self._get_slot(provider_id).instance

    async def get_info(self, provider_id: str) -> ProviderInfo:
        return self._get_slot(provider_id).info

    async def list_instances(self) -> list[ProviderInstanceProtocol]:
        return [slot.instance for slot in self._slots.values()]

    async def list_infos(self) -> list[ProviderInfo]:
        return [slot.info for slot in self._slots.values()]

    async def list_models(self, provider_id: str) -> list[ProviderModelConfig]:
        slot = await self._acquire_slot(provider_id)
        try:
            return await slot.instance.list_models()
        finally:
            await self._release_slot(slot)

    async def get_model(self, provider_id: str, model_id: str) -> ProviderModelConfig:
        slot = await self._acquire_slot(provider_id)
        try:
            return await slot.instance.get_model(model_id)
        finally:
            await self._release_slot(slot)

    async def supports(
        self, provider_id: str, capability: ProviderModelCapability
    ) -> bool:
        slot = await self._acquire_slot(provider_id)
        try:
            return await slot.instance.supports(capability)
        finally:
            await self._release_slot(slot)

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        slot = await self._acquire_slot(provider_id)
        self._validate_request_capabilities(slot.info, request)
        started = perf_counter()
        try:
            response = await slot.instance.chat(request)
        except Exception as exc:
            self._record_call(
                slot,
                request,
                started=started,
                error=exc,
            )
            raise
        else:
            self._record_call(slot, request, started=started, response=response)
            return response
        finally:
            await self._release_slot(slot)

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol:
        slot = await self._acquire_slot(provider_id)
        self._validate_request_capabilities(slot.info, request)
        started = perf_counter()
        try:
            stream = await slot.instance.chat_stream(request)
        except Exception as exc:
            self._record_call(
                slot,
                request,
                started=started,
                error=exc,
            )
            await self._release_slot(slot)
            raise
        return _ObservedChatStream(
            stream,
            manager=self,
            slot=slot,
            request=request,
            started=started,
        )

    async def delete(self, provider_id: str) -> None:
        lock = self._lock_for(provider_id)
        async with lock:
            slot = self._slots.get(provider_id)
            if slot is None:
                raise ProviderNotFoundError(f"The provider {provider_id} is not found")
            if self._config_store is not None:
                try:
                    self._config_store.delete(provider_id)
                except ProviderNotFoundError:
                    pass
            self._slots.pop(provider_id, None)
            slot.retired = True
        await self._close_when_idle(
            slot,
            message="Failed to close deleted provider instance",
        )

    async def restore(self) -> list[str]:
        if self._config_store is None:
            return []
        restored: list[str] = []
        for config in self._config_store.list_configs(enabled_only=True):
            await self.create(config)
            restored.append(config.provider_id)
        return restored

    async def close(self) -> None:
        slots = list(self._slots.values())
        self._slots.clear()
        for slot in slots:
            slot.retired = True
        for slot in slots:
            await self._close_when_idle(
                slot,
                message="Failed to close provider instance",
            )

    def _resolve_secret(self, provider: ProviderConfig) -> ProviderConfig:
        if provider.api_key is not None or provider.api_key_secret_ref is None:
            return provider
        if self._secret_resolver is None:
            raise ProviderConfigurationError(
                f"No secret resolver is configured for {provider.api_key_secret_ref}"
            )
        return provider.model_copy(
            update={
                "api_key": self._secret_resolver.resolve(provider.api_key_secret_ref)
            }
        )

    def _validate_request_capabilities(
        self,
        info: ProviderInfo,
        request: ChatRequest,
    ) -> None:
        model = next(
            (
                configured
                for configured in info.model.values()
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
        slot: _ProviderSlot,
        request: ChatRequest,
        *,
        started: float,
        response: ChatResponse | None = None,
        usage: ChatUsage | None = None,
        error: BaseException | None = None,
    ) -> None:
        provider_id = slot.provider_id
        total = self._call_totals.get(provider_id, 0) + 1
        errors = self._error_totals.get(provider_id, 0) + int(error is not None)
        self._call_totals[provider_id] = total
        self._error_totals[provider_id] = errors
        slot.call_total += 1
        slot.error_total += int(error is not None)
        usage = response.usage if response is not None else usage
        metadata = request.metadata
        extra = {
            "request_id": metadata.get("request_id"),
            "session_id": metadata.get("session_id"),
            "run_id": metadata.get("run_id"),
            "provider_id": provider_id,
            "provider_generation": slot.generation,
            "model_id": request.model_id,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "success": error is None,
            "error_type": error.__class__.__name__ if error is not None else None,
            "prompt_tokens": usage.prompt_tokens if usage is not None else None,
            "completion_tokens": usage.completion_tokens if usage is not None else None,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "cached_prompt_tokens": (
                usage.cached_prompt_tokens if usage is not None else None
            ),
            "cache_write_prompt_tokens": (
                usage.cache_write_prompt_tokens if usage is not None else None
            ),
            "provider_calls_total": total,
            "provider_errors_total": errors,
            "provider_error_rate": errors / total,
            "provider_instance_calls_total": slot.call_total,
            "provider_instance_errors_total": slot.error_total,
            "provider_instance_error_rate": slot.error_total / slot.call_total,
        }
        if error is None:
            LOGGER.info("Provider call completed", extra=extra)
        else:
            LOGGER.warning("Provider call failed", extra=extra)

    def _provider_info(self, provider: ProviderConfig) -> ProviderInfo:
        return ProviderInfo(
            provider_id=provider.provider_id,
            name=provider.name,
            type=provider.type,
            is_enabled=provider.is_enabled,
            model=provider.model,
            metadata=dict(provider.metadata),
        )

    def _lock_for(self, provider_id: str) -> Lock:
        lock = self._locks.get(provider_id)
        if lock is None:
            lock = Lock()
            self._locks[provider_id] = lock
        return lock

    def _get_slot(self, provider_id: str) -> _ProviderSlot:
        slot = self._slots.get(provider_id)
        if slot is None:
            raise ProviderNotFoundError(f"The provider {provider_id} is not found")
        return slot

    async def _acquire_slot(self, provider_id: str) -> _ProviderSlot:
        lock = self._lock_for(provider_id)
        async with lock:
            slot = self._slots.get(provider_id)
            if slot is None:
                raise ProviderNotFoundError(f"The provider {provider_id} is not found")
            slot.active_calls += 1
            slot.idle.clear()
            return slot

    async def _release_slot(self, slot: _ProviderSlot) -> None:
        lock = self._lock_for(slot.provider_id)
        async with lock:
            slot.active_calls -= 1
            if slot.active_calls == 0:
                slot.idle.set()
        await self._close_when_idle(
            slot,
            message="Failed to close retired provider instance",
        )

    async def _close_if_idle(self, slot: _ProviderSlot, *, message: str) -> None:
        if slot.active_calls > 0:
            return
        await self._close_when_idle(slot, message=message)

    async def _close_when_idle(self, slot: _ProviderSlot, *, message: str) -> None:
        if not slot.retired or slot.close_started:
            return
        await slot.idle.wait()
        if slot.close_started:
            return
        slot.close_started = True
        try:
            await slot.instance.close()
        except Exception as exc:
            LOGGER.warning(
                message,
                extra={
                    "provider_id": slot.provider_id,
                    "provider_generation": slot.generation,
                    "error_type": exc.__class__.__name__,
                },
                exc_info=True,
            )

    async def _close_unpublished_instance(
        self,
        provider_id: str,
        instance: ProviderInstanceProtocol,
        *,
        message: str,
    ) -> None:
        try:
            await instance.close()
        except Exception as exc:
            LOGGER.warning(
                message,
                extra={
                    "provider_id": provider_id,
                    "error_type": exc.__class__.__name__,
                },
                exc_info=True,
            )


class _ObservedChatStream(ChatStreamProtocol):
    def __init__(
        self,
        stream: ChatStreamProtocol,
        *,
        manager: ProviderManager,
        slot: _ProviderSlot,
        request: ChatRequest,
        started: float,
    ) -> None:
        self._stream = stream
        self._manager = manager
        self._slot = slot
        self._request = request
        self._started = started

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[ChatStreamEvent]:
        usage: ChatUsage | None = None
        try:
            async for event in self._stream:
                if event.usage is not None:
                    usage = merge_chat_usage(usage, event.usage)
                yield event
        except BaseException as exc:
            self._manager._record_call(
                self._slot,
                self._request,
                started=self._started,
                usage=usage,
                error=exc,
            )
            raise
        else:
            self._manager._record_call(
                self._slot,
                self._request,
                started=self._started,
                usage=usage,
            )
        finally:
            await self._manager._release_slot(self._slot)
