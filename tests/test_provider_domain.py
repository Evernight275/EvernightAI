from collections.abc import AsyncIterator
import asyncio
import logging
from typing import cast

import pytest

from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.error.provider import (
    ProviderCapabilityUnsupportedError,
    ProviderConfigurationError,
    ProviderConflictError,
    ProviderDisabledError,
    ProviderNotFoundError,
)
from EvernightAI.core.protocol.provider import (
    ProviderConfigStoreProtocol,
    ProviderInstanceProtocol,
    ProviderSecretResolverProtocol,
)
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatUsage,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType


class FakeProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self.closed = False
        self._models = {
            "model-1": ProviderModelConfig(
                model_id="model-1",
                capabilities=[ProviderModelCapability.CHAT],
            )
        }

    async def list_models(self) -> list[ProviderModelConfig]:
        return list(self._models.values())

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return self._models[model_id]

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return any(capability in model.capabilities for model in self._models.values())

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="ok")],
            ),
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        return FakeChatStream()

    async def close(self) -> None:
        self.closed = True


class FakeProviderConfigStore(ProviderConfigStoreProtocol):
    def __init__(self) -> None:
        self.configs: dict[str, ProviderConfig] = {}
        self.fail_saves = False
        self.fail_deletes = False

    def save(self, provider: ProviderConfig) -> None:
        if self.fail_saves:
            raise RuntimeError("config save failed")
        self.configs[provider.provider_id] = provider

    def get(self, provider_id: str) -> ProviderConfig:
        return self.configs[provider_id]

    def list_configs(self, *, enabled_only: bool = False) -> list[ProviderConfig]:
        configs = list(self.configs.values())
        if enabled_only:
            return [config for config in configs if config.is_enabled]
        return configs

    def delete(self, provider_id: str) -> None:
        if self.fail_deletes:
            raise RuntimeError("config delete failed")
        if provider_id not in self.configs:
            raise ProviderNotFoundError("Configuration not found")
        del self.configs[provider_id]


def make_config(provider_id: str = "provider-1") -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        name="OpenAI",
        type=ProviderType.OPENAI,
    )


@pytest.mark.asyncio
async def test_disabled_provider_can_be_managed_without_factory_or_secret_resolution() -> (
    None
):
    store = FakeProviderConfigStore()
    manager = ProviderManager(ProviderFactory(), config_store=store)
    config = make_config().model_copy(
        update={
            "is_enabled": False,
            "api_key_secret_ref": "env:MISSING_KEY",
            "discover_models": True,
            "model": {
                "alias": ProviderModelConfig(
                    model_id="model-1",
                    capabilities=[ProviderModelCapability.CHAT],
                )
            },
        }
    )
    assert await manager.create(config) is None
    assert await manager.list_instances() == []
    assert not (await manager.get_info("provider-1")).is_enabled
    assert len(await manager.list_infos()) == 1
    with pytest.raises(ProviderConflictError):
        await manager.create(config, replace_existing=False)

    await manager.update(
        "provider-1", ProviderConfigUpdate(name="Edited while disabled")
    )
    assert (await manager.get_config("provider-1")).name == "Edited while disabled"
    assert store.get("provider-1").name == "Edited while disabled"
    assert (await manager.list_models("provider-1"))[0].model_id == "model-1"
    assert (await manager.get_model("provider-1", "model-1")).model_id == "model-1"
    assert await manager.supports("provider-1", ProviderModelCapability.CHAT)
    with pytest.raises(ProviderNotFoundError):
        await manager.get_model("provider-1", "missing")
    request = ChatRequest(model_id="undeclared", messages=[])
    with pytest.raises(ProviderDisabledError):
        await manager.get("provider-1")
    with pytest.raises(ProviderDisabledError):
        await manager.chat("provider-1", request)
    with pytest.raises(ProviderDisabledError):
        await manager.chat_stream("provider-1", request)
    with pytest.raises(ProviderConfigurationError):
        await manager.update("provider-1", ProviderConfigUpdate(is_enabled=True))
    assert not (await manager.get_info("provider-1")).is_enabled
    assert not store.get("provider-1").is_enabled

    store.fail_deletes = True
    with pytest.raises(RuntimeError, match="config delete failed"):
        await manager.delete("provider-1")
    assert len(await manager.list_infos()) == 1
    store.fail_deletes = False
    await manager.delete("provider-1")
    assert await manager.list_infos() == []
    assert store.list_configs() == []
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["builder", "persistence"])
async def test_enable_failure_preserves_disabled_config_and_can_retry(
    failure: str,
) -> None:
    candidate = FakeProvider()
    fail_build = failure == "builder"

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        if fail_build:
            raise RuntimeError("build failed")
        return candidate

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    await manager.create(make_config().model_copy(update={"is_enabled": False}))
    store.fail_saves = failure == "persistence"
    with pytest.raises(RuntimeError):
        await manager.update(
            "provider-1", ProviderConfigUpdate(is_enabled=True, name="Not saved")
        )
    assert await manager.list_instances() == []
    assert not (await manager.get_config("provider-1")).is_enabled
    assert store.get("provider-1").name == "OpenAI"
    assert not store.get("provider-1").is_enabled
    if failure == "persistence":
        assert candidate.closed

    fail_build = False
    store.fail_saves = False
    candidate = FakeProvider()
    assert (
        await manager.update("provider-1", ProviderConfigUpdate(is_enabled=True))
        is candidate
    )
    assert store.get("provider-1").is_enabled
    assert (
        await manager.update("provider-1", ProviderConfigUpdate(is_enabled=True))
        is candidate
    )
    assert not candidate.closed
    await manager.close()


@pytest.mark.asyncio
async def test_disable_save_failure_keeps_provider_callable() -> None:
    instance = FakeProvider()

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instance

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    await manager.create(make_config())
    store.fail_saves = True
    with pytest.raises(RuntimeError, match="config save failed"):
        await manager.update("provider-1", ProviderConfigUpdate(is_enabled=False))
    assert await manager.get("provider-1") is instance
    assert store.get("provider-1").is_enabled
    assert not instance.closed
    assert (
        await manager.chat("provider-1", ChatRequest(model_id="model-1", messages=[]))
    ).model_id == "model-1"
    await manager.close()


@pytest.mark.asyncio
async def test_concurrent_enable_and_edit_preserve_latest_config() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    built: list[FakeProvider] = []

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        started.set()
        await release.wait()
        instance = FakeProvider()
        built.append(instance)
        return instance

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    await manager.create(make_config().model_copy(update={"is_enabled": False}))
    enabling = asyncio.create_task(
        manager.update("provider-1", ProviderConfigUpdate(is_enabled=True))
    )
    await started.wait()
    assert not (await manager.get_info("provider-1")).is_enabled
    disabling = asyncio.create_task(
        manager.update(
            "provider-1", ProviderConfigUpdate(is_enabled=False, name="Edited")
        )
    )
    release.set()
    await asyncio.gather(enabling, disabling)
    assert not (await manager.get_config("provider-1")).is_enabled
    assert store.get("provider-1").name == "Edited"
    assert not store.get("provider-1").is_enabled
    assert len(built) == 1 and built[0].closed
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("disable", [False, True])
@pytest.mark.parametrize("interruption", ["cancel", "timeout"])
async def test_interrupted_stream_opening_releases_provider_for_shutdown(
    disable: bool,
    interruption: str,
) -> None:
    started = asyncio.Event()

    class WaitingProvider(FakeProvider):
        async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
            started.set()
            await asyncio.Event().wait()
            return FakeChatStream()

    instance = WaitingProvider()

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instance

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    async def open_stream() -> ChatStreamProtocol:
        async with asyncio.timeout(0.1 if interruption == "timeout" else None):
            return await manager.chat_stream(
                "provider-1", ChatRequest(model_id="model-1", messages=[])
            )

    opening = asyncio.create_task(open_stream())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        if disable:
            await manager.update("provider-1", ProviderConfigUpdate(is_enabled=False))
        if interruption == "cancel":
            opening.cancel()
        with pytest.raises(
            asyncio.CancelledError if interruption == "cancel" else TimeoutError
        ):
            await opening
        await asyncio.wait_for(manager.close(), timeout=1)
        assert instance.closed
    finally:
        opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_waits_for_calls_on_a_disabled_provider() -> None:
    started = {name: asyncio.Event() for name in ("first", "last")}
    release = {name: asyncio.Event() for name in started}
    close_started, close_release = asyncio.Event(), asyncio.Event()

    class BlockingProvider(FakeProvider):
        async def chat(self, request: ChatRequest) -> ChatResponse:
            started[request.model_id].set()
            await release[request.model_id].wait()
            return await super().chat(request)

        async def close(self) -> None:
            close_started.set()
            await close_release.wait()
            await super().close()

    instance = BlockingProvider()

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instance

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    await manager.create(make_config())
    calls = {
        name: asyncio.create_task(
            manager.chat("provider-1", ChatRequest(model_id=name, messages=[]))
        )
        for name in started
    }
    await asyncio.gather(*(event.wait() for event in started.values()))
    await manager.update("provider-1", ProviderConfigUpdate(is_enabled=False))
    release["first"].set()
    assert (await asyncio.wait_for(calls["first"], timeout=1)).model_id == "first"
    assert not instance.closed
    closing = asyncio.create_task(manager.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release["last"].set()
    await close_started.wait()
    await asyncio.sleep(0)
    assert not closing.done()
    close_release.set()
    await asyncio.wait_for(asyncio.gather(calls["last"], closing), timeout=1)
    assert instance.closed
    assert await manager.list_infos() == []


@pytest.mark.asyncio
async def test_raw_key_configuration_survives_disable_edit_and_reenable() -> None:
    built: list[ProviderConfig] = []

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        built.append(config)
        return FakeProvider()

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    await manager.create(make_config().model_copy(update={"api_key": "runtime-only"}))
    await manager.update("provider-1", ProviderConfigUpdate(is_enabled=False))
    await manager.update(
        "provider-1", ProviderConfigUpdate(base_url="https://edited.example/v1")
    )
    assert len(built) == 1
    await manager.update("provider-1", ProviderConfigUpdate(is_enabled=True))
    assert len(built) == 2
    assert built[-1].api_key == "runtime-only"
    assert built[-1].base_url == "https://edited.example/v1"
    assert store.get("provider-1").base_url == "https://edited.example/v1"
    assert store.get("provider-1").is_enabled
    await manager.close()


@pytest.mark.asyncio
async def test_update_preserves_omitted_credentials_and_model_settings() -> None:
    built: list[ProviderConfig] = []

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        built.append(config)
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    config = make_config().model_copy(
        update={
            "api_key": "original-key",
            "base_url": "https://old.example/v1",
            "discover_models": True,
            "metadata": {"tag": "keep"},
            "model": {
                "alias": ProviderModelConfig(
                    model_id="model-1",
                    capabilities=[ProviderModelCapability.CHAT],
                    metadata={"provider_option": "keep"},
                )
            },
        }
    )
    await manager.create(config)
    config.name = "caller mutation"
    await manager.update("provider-1", ProviderConfigUpdate(name="Renamed"))
    assert built[-1].name == "Renamed"
    assert built[-1].api_key == "original-key"
    assert built[-1].model == config.model
    assert built[-1].metadata == {"tag": "keep"}
    view = await manager.get_config("provider-1")
    assert view.has_api_key
    assert "original-key" not in view.model_dump_json()
    assert "api_key" not in view.model_dump()
    view.model["alias"].metadata["provider_option"] = "mutation"
    assert (await manager.get_config("provider-1")).model["alias"].metadata == {
        "provider_option": "keep"
    }
    await manager.close()


@pytest.mark.asyncio
async def test_update_switches_to_resolved_reference_and_clears_credentials() -> None:
    built: list[ProviderConfig] = []

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        built.append(config)
        return FakeProvider()

    class SecretResolver(ProviderSecretResolverProtocol):
        def resolve(self, secret_ref: str) -> str:
            assert secret_ref == "env:NEW_KEY"
            return "resolved-key"

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    factory.register(ProviderType.ANTHROPIC, build)
    manager = ProviderManager(
        factory, config_store=store, secret_resolver=SecretResolver()
    )
    await manager.create(make_config().model_copy(update={"api_key": "runtime-key"}))

    await manager.update(
        "provider-1",
        ProviderConfigUpdate(
            type=ProviderType.ANTHROPIC,
            api_key_secret_ref="env:NEW_KEY",
        ),
    )

    assert built[-1].type is ProviderType.ANTHROPIC
    assert built[-1].api_key == "resolved-key"
    assert store.get("provider-1").api_key is None
    assert store.get("provider-1").api_key_secret_ref == "env:NEW_KEY"
    assert (await manager.get_config("provider-1")).has_api_key

    await manager.update("provider-1", ProviderConfigUpdate(name="Keep reference"))
    assert built[-1].api_key == "resolved-key"

    await manager.update(
        "provider-1",
        ProviderConfigUpdate(
            api_key=None,
            api_key_secret_ref=None,
        ),
    )
    assert built[-1].api_key is None
    assert built[-1].api_key_secret_ref is None
    assert store.get("provider-1").api_key is None
    assert store.get("provider-1").api_key_secret_ref is None
    assert not (await manager.get_config("provider-1")).has_api_key
    await manager.close()


@pytest.mark.asyncio
async def test_update_missing_provider_does_not_create_it() -> None:
    manager = ProviderManager(ProviderFactory())
    with pytest.raises(ProviderNotFoundError):
        await manager.update("missing", ProviderConfigUpdate(name="New"))
    assert await manager.list_infos() == []


@pytest.mark.asyncio
async def test_empty_update_does_not_replace_provider() -> None:
    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    previous = await manager.create(make_config())
    assert await manager.update("provider-1", ProviderConfigUpdate()) is previous
    assert not cast(FakeProvider, previous).closed
    await manager.close()


@pytest.mark.asyncio
async def test_update_builder_failure_preserves_configuration_and_instance() -> None:
    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        if config.name == "Invalid":
            raise RuntimeError("build failed")
        return FakeProvider()

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    previous = await manager.create(make_config())
    with pytest.raises(RuntimeError, match="build failed"):
        await manager.update("provider-1", ProviderConfigUpdate(name="Invalid"))
    assert await manager.get("provider-1") is previous
    assert (await manager.get_config("provider-1")).name == "OpenAI"
    assert store.get("provider-1").name == "OpenAI"
    assert not cast(FakeProvider, previous).closed
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_save", [False, True])
async def test_raw_key_update_replaces_persisted_reference_atomically(
    fail_save: bool,
) -> None:
    built: list[FakeProvider] = []

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        instance = FakeProvider()
        built.append(instance)
        return instance

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    await manager.create(
        make_config().model_copy(
            update={
                "api_key": "old-key",
                "api_key_secret_ref": "env:OLD_KEY",
            }
        )
    )
    store.fail_saves = fail_save
    if fail_save:
        with pytest.raises(RuntimeError, match="config save failed"):
            await manager.update("provider-1", ProviderConfigUpdate(api_key="new-key"))
        assert await manager.get("provider-1") is built[0]
        assert not built[0].closed and built[1].closed
        assert store.get("provider-1").api_key_secret_ref == "env:OLD_KEY"
    else:
        await manager.update("provider-1", ProviderConfigUpdate(api_key="new-key"))
        assert store.get("provider-1").api_key == "new-key"
        assert store.get("provider-1").api_key_secret_ref is None
        assert built[0].closed
        assert (await manager.get_config("provider-1")).api_key_secret_ref is None
    await manager.close()


@pytest.mark.asyncio
async def test_concurrent_updates_merge_against_latest_configuration() -> None:
    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        await asyncio.sleep(0)
        return FakeProvider()

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory, config_store=store)
    await manager.create(make_config())
    await asyncio.gather(
        manager.update("provider-1", ProviderConfigUpdate(name="New")),
        manager.update(
            "provider-1", ProviderConfigUpdate(base_url="https://new.example/v1")
        ),
    )
    saved = store.get("provider-1")
    assert saved.name == "New"
    assert saved.base_url == "https://new.example/v1"
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("disable", [False, True])
async def test_update_does_not_close_active_model_stream(disable: bool) -> None:
    release = asyncio.Event()

    class BlockingStream:
        def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
            return self.events()

        async def events(self) -> AsyncIterator[ChatStreamEvent]:
            yield ChatStreamEvent(
                event_type=ChatStreamEventType.MESSAGE_DELTA, text_delta="old"
            )
            await release.wait()
            yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)

    class StreamingProvider(FakeProvider):
        async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
            return BlockingStream()

    previous = StreamingProvider()
    replacement = FakeProvider()
    instances: list[ProviderInstanceProtocol] = [previous, replacement]

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instances.pop(0)

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    await manager.create(make_config())
    stream = await manager.chat_stream(
        "provider-1", ChatRequest(model_id="model-1", messages=[])
    )
    iterator = stream.__aiter__()
    assert (await anext(iterator)).text_delta == "old"
    await asyncio.wait_for(
        manager.update(
            "provider-1", ProviderConfigUpdate(name="New", is_enabled=not disable)
        ),
        timeout=1,
    )
    assert not previous.closed
    if disable:
        with pytest.raises(ProviderDisabledError):
            await manager.chat_stream(
                "provider-1", ChatRequest(model_id="model-1", messages=[])
            )
        await manager.update("provider-1", ProviderConfigUpdate(is_enabled=True))
    assert await manager.get("provider-1") is replacement
    release.set()
    assert [event.event_type async for event in iterator] == [ChatStreamEventType.DONE]
    assert previous.closed
    await manager.close()


@pytest.mark.asyncio
async def test_factory_raises_provider_error_for_missing_builder() -> None:
    factory = ProviderFactory()

    with pytest.raises(ProviderNotFoundError):
        await factory.create(make_config())


@pytest.mark.asyncio
async def test_manager_creates_and_deletes_provider_instance() -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)

    instance = await manager.create(make_config())
    await manager.delete("provider-1")

    assert cast(FakeProvider, instance).closed is True
    assert await manager.list_instances() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_manager_keeps_previous_instance_when_config_save_fails(
    operation: str,
) -> None:
    instances = [FakeProvider(), FakeProvider()]

    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instances.pop(0)

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory, config_store=store)
    previous = await manager.create(make_config())
    replacement = instances[0]
    store.fail_saves = True

    with pytest.raises(RuntimeError, match="config save failed"):
        if operation == "update":
            await manager.update("provider-1", ProviderConfigUpdate(name="Replacement"))
        else:
            await manager.create(
                make_config().model_copy(update={"name": "Replacement"})
            )

    assert await manager.get("provider-1") is previous
    assert (await manager.list_infos())[0].name == "OpenAI"
    assert cast(FakeProvider, previous).closed is False
    assert replacement.closed is True

    await manager.close()


@pytest.mark.asyncio
async def test_manager_keeps_replacement_when_previous_close_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class CloseFailingProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("close failed")

    previous = CloseFailingProvider()
    replacement = FakeProvider()
    instances: list[ProviderInstanceProtocol] = [previous, replacement]

    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instances.pop(0)

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    with caplog.at_level(logging.WARNING, logger="EvernightAI.provider"):
        created = await manager.create(make_config())

    assert created is replacement
    assert await manager.get("provider-1") is replacement
    assert previous.close_calls == 1
    assert "Failed to close replaced provider instance" in caplog.text

    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "disable"])
async def test_manager_keeps_in_flight_call_on_replaced_generation(
    operation: str,
) -> None:
    class BlockingProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def chat(self, request: ChatRequest) -> ChatResponse:
            self.started.set()
            await self.release.wait()
            return await super().chat(request)

    previous = BlockingProvider()
    replacement = FakeProvider()
    instances: list[ProviderInstanceProtocol] = [previous, replacement]

    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return instances.pop(0)

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    request = ChatRequest(model_id="model-1", messages=[])
    chat_task = asyncio.create_task(manager.chat("provider-1", request))
    await previous.started.wait()

    created = (
        await manager.update(
            "provider-1",
            ProviderConfigUpdate(name="New", is_enabled=operation != "disable"),
        )
        if operation != "create"
        else await manager.create(make_config().model_copy(update={"name": "New"}))
    )

    if operation == "disable":
        assert created is None
        with pytest.raises(ProviderDisabledError):
            await manager.chat("provider-1", request)
    else:
        assert created is replacement
        assert await manager.get("provider-1") is replacement
    assert previous.closed is False

    previous.release.set()
    response = await chat_task

    assert response.model_id == "model-1"
    assert previous.closed is True
    assert replacement.closed is False

    await manager.close()


@pytest.mark.asyncio
async def test_manager_keeps_provider_published_when_config_delete_fails() -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    store = FakeProviderConfigStore()
    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory, config_store=store)
    instance = await manager.create(make_config())
    store.fail_deletes = True

    with pytest.raises(RuntimeError, match="config delete failed"):
        await manager.delete("provider-1")

    assert await manager.get("provider-1") is instance
    assert cast(FakeProvider, instance).closed is False

    store.fail_deletes = False
    await manager.delete("provider-1")

    assert cast(FakeProvider, instance).closed is True
    assert await manager.list_instances() == []


@pytest.mark.asyncio
async def test_manager_delegates_model_queries_to_provider_instance() -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    models = await manager.list_models("provider-1")
    model = await manager.get_model("provider-1", "model-1")
    supports_chat = await manager.supports("provider-1", ProviderModelCapability.CHAT)

    assert models == [model]
    assert model.model_id == "model-1"
    assert supports_chat is True


@pytest.mark.asyncio
async def test_manager_delegates_chat_to_provider_instance() -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    request = ChatRequest(model_id="model-1", messages=[])
    response = await manager.chat("provider-1", request)
    stream = await manager.chat_stream("provider-1", request)
    events = [event async for event in stream]

    assert response.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="ok")
    ]
    assert [event.event_type for event in events] == [
        ChatStreamEventType.RAW,
        ChatStreamEventType.DONE,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("cleanup", ["delete", "close"])
async def test_manager_rejects_images_for_declared_text_only_model(
    stream: bool,
    cleanup: str,
) -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    instance = await manager.create(
        ProviderConfig(
            provider_id="provider-1",
            name="OpenAI",
            type=ProviderType.OPENAI,
            model={
                "text": ProviderModelConfig(
                    model_id="model-1",
                    capabilities=[ProviderModelCapability.CHAT],
                )
            },
        )
    )
    request = ChatRequest(
        model_id="model-1",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.IMAGE,
                        url="https://example.com/image.png",
                    )
                ],
            )
        ],
    )

    with pytest.raises(
        ProviderCapabilityUnsupportedError,
        match="model-1 does not support image recognition",
    ):
        if stream:
            await manager.chat_stream("provider-1", request)
        else:
            await manager.chat("provider-1", request)

    if cleanup == "delete":
        await asyncio.wait_for(manager.delete("provider-1"), timeout=1)
    else:
        await asyncio.wait_for(manager.close(), timeout=1)
    assert cast(FakeProvider, instance).closed is True
    assert await manager.list_instances() == []


@pytest.mark.asyncio
async def test_manager_allows_images_for_declared_vision_model() -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(
        ProviderConfig(
            provider_id="provider-1",
            name="OpenAI",
            type=ProviderType.OPENAI,
            model={
                "vision": ProviderModelConfig(
                    model_id="model-1",
                    capabilities=[
                        ProviderModelCapability.CHAT,
                        ProviderModelCapability.IMAGE_RECOGNITION,
                    ],
                )
            },
        )
    )
    request = ChatRequest(
        model_id="model-1",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.IMAGE,
                        url="https://example.com/image.png",
                    )
                ],
            )
        ],
    )

    response = await manager.chat("provider-1", request)

    assert response.model_id == "model-1"


@pytest.mark.asyncio
async def test_manager_logs_stream_usage_after_consumption(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return UsageProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    with caplog.at_level(logging.INFO, logger="EvernightAI.provider"):
        stream = await manager.chat_stream(
            "provider-1",
            ChatRequest(model_id="model-1", messages=[]),
        )
        _ = [event async for event in stream]

    record = next(
        item for item in caplog.records if item.name == "EvernightAI.provider"
    )
    assert getattr(record, "prompt_tokens") == 3
    assert getattr(record, "completion_tokens") == 2
    assert getattr(record, "total_tokens") == 5
    assert getattr(record, "cached_prompt_tokens") == 2
    assert getattr(record, "cache_write_prompt_tokens") == 1


class FakeChatStream:
    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        yield ChatStreamEvent(
            event_type=ChatStreamEventType.RAW,
            raw_event="message",
            raw_data={"delta": "ok"},
        )
        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)


class UsageProvider(FakeProvider):
    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        return UsageChatStream()


class UsageChatStream:
    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        yield ChatStreamEvent(
            event_type=ChatStreamEventType.USAGE,
            usage=ChatUsage(
                prompt_tokens=3,
                cached_prompt_tokens=2,
                cache_write_prompt_tokens=1,
            ),
        )
        yield ChatStreamEvent(
            event_type=ChatStreamEventType.USAGE,
            usage=ChatUsage(completion_tokens=2),
        )
        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)
