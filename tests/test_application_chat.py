from collections.abc import AsyncIterator

import pytest

from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.domain.context import (
    ContextManager,
    ContextOrganizer,
    ContextRegister,
)
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import SSEProtocol
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
from EvernightAI.core.schema.stream import SSEEvent


@pytest.mark.asyncio
async def test_chat_application_commands_core_runtime() -> None:
    runtime = make_runtime()
    app = ChatApplication(runtime)

    await app.create_provider(make_config())
    response = await app.chat(
        "provider-1",
        ChatRequest(model_id="model-1", messages=[]),
    )
    stream = await app.chat_stream(
        "provider-1",
        ChatRequest(model_id="model-1", messages=[]),
    )
    events = [event async for event in stream]

    assert response.message == Content(
        role=MessageRole.ASSISTANT,
        content=[ContentPart(type=ContentPartType.TEXT, text="ok")],
    )
    assert [event.data for event in events] == ["ok", "[DONE]"]

    await app.close()


def make_runtime() -> RuntimeKernel:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    provider_factory = ProviderFactory()
    provider_factory.register(ProviderType.OPENAI, build_provider)
    tool_register = ToolRegister()
    context_register = ContextRegister()

    return RuntimeKernel(
        provider_factory=provider_factory,
        providers=ProviderManager(provider_factory),
        tool_register=tool_register,
        tools=ToolManager(tool_register),
        context_register=context_register,
        contexts=ContextManager(context_register),
        context_organizer=ContextOrganizer(),
    )


def make_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="provider-1",
        name="Fake",
        type=ProviderType.OPENAI,
    )


class FakeProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self._models = {
            "model-1": ProviderModelConfig(
                model_id="model-1",
                capabilities=[ProviderModelCapability.CHAT],
            )
        }
        self.closed = False

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

    async def chat_stream(self, request: ChatRequest) -> SSEProtocol:
        return FakeSSEStream()

    async def close(self) -> None:
        self.closed = True


class FakeSSEStream:
    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        yield SSEEvent(data="ok")
        yield SSEEvent(data="[DONE]", event="done")
