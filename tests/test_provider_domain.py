from collections.abc import AsyncIterator
import logging
from typing import cast

import pytest

from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.error.provider import (
    ProviderCapabilityUnsupportedError,
    ProviderNotFoundError,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
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


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_manager_rejects_images_for_declared_text_only_model(
    stream: bool,
) -> None:
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

    record = next(item for item in caplog.records if item.name == "EvernightAI.provider")
    assert getattr(record, "prompt_tokens") == 3
    assert getattr(record, "completion_tokens") == 2
    assert getattr(record, "total_tokens") == 5


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
            usage=ChatUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)
