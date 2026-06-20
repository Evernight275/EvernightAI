from __future__ import annotations

import json

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from typing import Any, cast

from EvernightAI.core.schema.content import (
    ChatRequest,
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
from EvernightAI.infra.adapters.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)
from EvernightAI.infra.bootstrap import (
    RuntimeKernel,
    create_context_manager,
    create_context_organizer,
    create_context_register,
    create_memory_manager,
    create_memory_register,
    create_memory_strategy,
    create_provider_factory,
    create_provider_manager,
    create_runtime,
    create_tool_manager,
    create_tool_register,
)


def make_openai_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="openai-main",
        name="OpenAI Main",
        type=ProviderType.OPENAI,
        model={
            "gpt-test": ProviderModelConfig(
                model_id="gpt-test",
                capabilities=[
                    ProviderModelCapability.CHAT,
                    ProviderModelCapability.TOOL_CALL,
                ],
            )
        },
    )


def make_openai_config_without_models() -> ProviderConfig:
    return ProviderConfig(
        provider_id="openai-main",
        name="OpenAI Main",
        type=ProviderType.OPENAI,
    )


def test_bootstrap_registers_openai_compatible_builder() -> None:
    factory = create_provider_factory()

    assert factory.has(ProviderType.OPENAI) is True
    assert factory.has(ProviderType.OPENAI_RESPONSES) is True
    assert factory.has(ProviderType.GOOGLE) is True
    assert factory.has(ProviderType.ANTHROPIC) is True


def test_bootstrap_creates_tool_manager() -> None:
    register = create_tool_register()
    manager = create_tool_manager(register)

    assert manager.list_tools() == []


def test_bootstrap_creates_context_manager() -> None:
    register = create_context_register()
    manager = create_context_manager(register)

    assert manager._register is register


def test_bootstrap_creates_context_organizer() -> None:
    organizer = create_context_organizer()

    assert organizer.organize.__name__ == "organize"


def test_bootstrap_creates_memory_services() -> None:
    register = create_memory_register()
    manager = create_memory_manager(register)
    strategy = create_memory_strategy()

    assert manager._register is register
    assert strategy.select.__name__ == "select"


@pytest.mark.asyncio
async def test_bootstrap_provider_manager_creates_openai_instance() -> None:
    manager = create_provider_manager()

    instance = await manager.create(make_openai_config())
    model = await manager.get_model("openai-main", "gpt-test")

    assert isinstance(instance, OpenAICompatibleProviderInstance)
    assert model.model_id == "gpt-test"
    assert (
        await manager.supports("openai-main", ProviderModelCapability.TOOL_CALL) is True
    )

    await manager.close()

    assert instance.is_closed is True


@pytest.mark.asyncio
async def test_bootstrap_creates_runtime_kernel() -> None:
    runtime = create_runtime()

    assert isinstance(runtime, RuntimeKernel)
    assert runtime.provider_factory.has(ProviderType.OPENAI) is True
    assert runtime.tools.list_tools() == []
    assert await runtime.contexts.list_contexts() == []
    assert runtime.context_organizer.organize
    assert await runtime.memories.list_memories() == []
    assert runtime.memory_strategy.select

    instance = await runtime.providers.create(make_openai_config())
    model = await runtime.providers.get_model("openai-main", "gpt-test")

    assert isinstance(instance, OpenAICompatibleProviderInstance)
    assert model.model_id == "gpt-test"

    await runtime.close()

    assert instance.is_closed is True


@pytest.mark.asyncio
async def test_openai_instance_chat_maps_request_and_response() -> None:
    config = make_openai_config()
    instance = OpenAICompatibleProviderInstance(config)
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    response = await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
        )
    )

    assert completions.params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
    }
    assert response.model_id == "gpt-test"
    assert response.message == Content(
        role=MessageRole.ASSISTANT,
        content=[ContentPart(type=ContentPartType.TEXT, text="Hi")],
    )

    await instance.close()

    assert instance.is_closed is True
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_openai_instance_chat_allows_undeclared_model() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config_without_models())
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    response = await instance.chat(
        ChatRequest(
            model_id="provider-specific-model",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
        )
    )

    assert completions.params == {
        "model": "provider-specific-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
    }
    assert response.message == Content(
        role=MessageRole.ASSISTANT,
        content=[ContentPart(type=ContentPartType.TEXT, text="Hi")],
    )

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_chat_stream_maps_chunks_to_sse_events() -> None:
    config = make_openai_config()
    instance = OpenAICompatibleProviderInstance(config)
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(
            model_id="gpt-test",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
        )
    )
    events = [event async for event in stream]

    assert completions.params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert [event.event for event in events] == ["chat.completion.chunk", "done"]
    assert json.loads(events[0].data)["choices"][0]["delta"] == {
        "content": "Hi",
        "role": "assistant",
    }
    assert events[1].data == "[DONE]"

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_chat_stream_allows_undeclared_model() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config_without_models())
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(
            model_id="provider-specific-model",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
        )
    )
    events = [event async for event in stream]

    assert completions.params == {
        "model": "provider-specific-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert [event.event for event in events] == ["chat.completion.chunk", "done"]

    await instance.close()


class FakeCompletions:
    def __init__(self) -> None:
        self.params: dict[str, object] | None = None

    async def create(self, **params: object) -> ChatCompletion | FakeOpenAIStream:
        self.params = params
        if params.get("stream") is True:
            return FakeOpenAIStream(
                [
                    ChatCompletionChunk(
                        id="chatcmpl-1",
                        choices=cast(
                            Any,
                            [
                                {
                                    "delta": {
                                        "role": "assistant",
                                        "content": "Hi",
                                    },
                                    "finish_reason": None,
                                    "index": 0,
                                }
                            ],
                        ),
                        created=123,
                        model="gpt-test",
                        object="chat.completion.chunk",
                    )
                ]
            )

        return ChatCompletion(
            id="chatcmpl-1",
            choices=cast(
                Any,
                [
                    {
                        "finish_reason": "stop",
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hi"},
                    }
                ],
            ),
            created=123,
            model="gpt-test",
            object="chat.completion",
        )


class FakeOpenAIStream:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "FakeOpenAIStream":
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        if not self._chunks:
            raise StopAsyncIteration

        return self._chunks.pop(0)


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = FakeChat(completions)
        self.closed = False

    async def close(self) -> None:
        self.closed = True
