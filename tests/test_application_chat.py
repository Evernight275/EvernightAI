from collections.abc import AsyncIterator

import pytest

from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.domain.context import (
    BasicContextStrategy,
    ContextManager,
    ContextOrganizer,
    ContextRegister,
)
from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.domain.tool import BasicToolSafetyPolicy
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
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryKind,
    MemoryQuery,
    MemoryScope,
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


@pytest.mark.asyncio
async def test_chat_application_organizes_context_and_memory_flow() -> None:
    runtime = make_runtime()
    app = ChatApplication(runtime)

    await app.create_provider(make_config())
    await app.create_context(
        Context(
            context_id="ctx-1",
            messages=[make_message("Stored context", role=MessageRole.SYSTEM)],
            metadata={"topic": "application"},
        )
    )
    await app.create_memory(
        MemoryItem(
            memory_id="mem-low",
            content="Low priority memory",
            scope=MemoryScope.USER,
            scope_id="user-1",
            priority=1,
        )
    )
    await app.create_memory(
        MemoryItem(
            memory_id="mem-style",
            content="Prefer concise answers",
            kind=MemoryKind.PREFERENCE,
            scope=MemoryScope.USER,
            scope_id="user-1",
            tags=["style"],
            priority=10,
        )
    )

    user_message = make_message("Current request")
    response = await app.chat_with_context(
        "provider-1",
        "ctx-1",
        model_id="model-1",
        messages=[user_message],
        memory_query=MemoryQuery(
            scope=MemoryScope.USER,
            scope_id="user-1",
            kinds=[MemoryKind.PREFERENCE],
            tags=["style"],
            limit=1,
        ),
        metadata={"request_id": "req-1"},
    )
    provider = await runtime.providers.get("provider-1")

    assert isinstance(provider, FakeProvider)
    assert provider.last_request is not None
    assert [message_text(message) for message in provider.last_request.messages] == [
        "Stored context",
        "Relevant memory:\n- preference: Prefer concise answers",
        "Current request",
    ]
    assert provider.last_request.metadata == {
        "topic": "application",
        "request_id": "req-1",
        "memory_ids": ["mem-style"],
        "memory_selection": {
            "strategy": "BasicMemoryStrategy",
            "total_candidates": 2,
            "selected_count": 1,
        },
        "context_id": "ctx-1",
    }

    context = await app.get_context("ctx-1")

    assert response.message == make_message("ok", role=MessageRole.ASSISTANT)
    assert [message_text(message) for message in context.messages] == [
        "Stored context",
        "Current request",
        "ok",
    ]


def make_runtime() -> RuntimeKernel:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    provider_factory = ProviderFactory()
    provider_factory.register(ProviderType.OPENAI, build_provider)
    tool_register = ToolRegister()
    tool_safety_policy = BasicToolSafetyPolicy()
    context_register = ContextRegister()
    context_organizer = ContextOrganizer()
    memory_register = MemoryRegister()

    return RuntimeKernel(
        provider_factory=provider_factory,
        providers=ProviderManager(provider_factory),
        tool_register=tool_register,
        tools=ToolManager(tool_register, tool_safety_policy),
        tool_safety_policy=tool_safety_policy,
        context_register=context_register,
        contexts=ContextManager(context_register),
        context_organizer=context_organizer,
        context_strategy=BasicContextStrategy(context_organizer),
        memory_register=memory_register,
        memories=MemoryManager(memory_register),
        memory_strategy=BasicMemoryStrategy(),
        memory_write_strategy=BasicMemoryWriteStrategy(),
    )


def make_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="provider-1",
        name="Fake",
        type=ProviderType.OPENAI,
    )


def make_message(text: str, *, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def message_text(message: Content) -> str | None:
    if not message.content:
        return None

    return message.content[0].text


class FakeProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self._models = {
            "model-1": ProviderModelConfig(
                model_id="model-1",
                capabilities=[ProviderModelCapability.CHAT],
            )
        }
        self.closed = False
        self.last_request: ChatRequest | None = None

    async def list_models(self) -> list[ProviderModelConfig]:
        return list(self._models.values())

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return self._models[model_id]

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return any(capability in model.capabilities for model in self._models.values())

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        return ChatResponse(
            model_id=request.model_id,
            message=make_message("ok", role=MessageRole.ASSISTANT),
        )

    async def chat_stream(self, request: ChatRequest) -> SSEProtocol:
        self.last_request = request
        return FakeSSEStream()

    async def close(self) -> None:
        self.closed = True


class FakeSSEStream:
    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        yield SSEEvent(data="ok")
        yield SSEEvent(data="[DONE]", event="done")
