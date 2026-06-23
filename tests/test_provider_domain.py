from collections.abc import AsyncIterator
from typing import cast

import pytest

from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.error.provider import ProviderNotFoundError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
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


def make_config(provider_id: str = "provider-1") -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        name="OpenAI",
        type=ProviderType.OPENAI,
    )


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
async def test_manager_delegates_model_queries_to_provider_instance() -> None:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build_provider)
    manager = ProviderManager(factory)
    await manager.create(make_config())

    models = await manager.list_models("provider-1")
    model = await manager.get_model("provider-1", "model-1")
    supports_chat = await manager.supports(
        "provider-1", ProviderModelCapability.CHAT
    )

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
