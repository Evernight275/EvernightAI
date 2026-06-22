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
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.skill import SkillCapability, SkillRenderRequest
from EvernightAI.infra.adapters.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)
from EvernightAI.bootstrap.runtime import (
    RuntimeKernel,
    create_context_manager,
    create_context_organizer,
    create_context_register,
    create_context_strategy,
    create_memory_manager,
    create_memory_register,
    create_memory_strategy,
    create_memory_write_strategy,
    create_provider_factory,
    create_provider_manager,
    create_runtime,
    create_skill_manager,
    create_skill_register,
    create_sqlite_runtime,
    create_tool_manager,
    create_tool_register,
    create_tool_safety_policy,
    register_builtin_skills,
    register_builtin_tools,
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
    policy = create_tool_safety_policy()
    manager = create_tool_manager(register, policy)

    assert manager.list_tools() == []
    assert policy.authorize.__name__ == "authorize"


def test_bootstrap_registers_builtin_tools_explicitly(tmp_path) -> None:
    register = create_tool_register()

    register_builtin_tools(register)

    assert register.list_tools() == []

    register_builtin_tools(register, filesystem_root=tmp_path)

    assert [tool.name for tool in register.list_tools()] == [
        "read_text_file",
        "write_text_file",
        "list_directory",
    ]

    register_builtin_tools(
        register,
        shell_allowed_commands={"python"},
        shell_working_directory=tmp_path,
    )

    assert [tool.name for tool in register.list_tools()] == [
        "read_text_file",
        "write_text_file",
        "list_directory",
        "restricted_shell",
    ]


def test_bootstrap_registers_builtin_skills_explicitly() -> None:
    register = create_skill_register()
    manager = create_skill_manager(register)

    register_builtin_skills(register)

    skills = manager.list_skills()
    assert [skill.name for skill in skills] == ["echo"]
    assert skills[0].capabilities == [SkillCapability.AGENT]
    assert skills[0].metadata == {"builtin": True}


def test_bootstrap_creates_context_manager() -> None:
    register = create_context_register()
    manager = create_context_manager(register)

    assert manager._register is register


def test_bootstrap_creates_context_organizer() -> None:
    organizer = create_context_organizer()
    strategy = create_context_strategy(organizer)

    assert organizer.organize.__name__ == "organize"
    assert strategy.compose_chat_request.__name__ == "compose_chat_request"


def test_bootstrap_creates_memory_services() -> None:
    register = create_memory_register()
    manager = create_memory_manager(register)
    strategy = create_memory_strategy()
    write_strategy = create_memory_write_strategy()

    assert manager._register is register
    assert strategy.select.__name__ == "select"
    assert write_strategy.create_memories.__name__ == "create_memories"


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
    assert [skill.name for skill in runtime.skills.list_skills()] == ["echo"]
    assert runtime.tool_safety_policy.authorize
    assert await runtime.contexts.list_contexts() == []
    assert runtime.context_organizer.organize
    assert runtime.context_strategy.compose_chat_request
    assert await runtime.memories.list_memories() == []
    assert runtime.memory_strategy.select
    assert runtime.memory_write_strategy.create_memories

    instance = await runtime.providers.create(make_openai_config())
    model = await runtime.providers.get_model("openai-main", "gpt-test")
    rendered_skill = await runtime.skills.render(
        SkillRenderRequest(
            render_id="skill-render-1",
            skill_name="echo",
            variables={"text": "hello"},
        )
    )

    assert isinstance(instance, OpenAICompatibleProviderInstance)
    assert model.model_id == "gpt-test"
    assert rendered_skill.messages[0].role is MessageRole.SYSTEM
    assert rendered_skill.messages[0].content is not None
    assert rendered_skill.messages[0].content[0].text == (
        'Echo skill variables: {"text": "hello"}'
    )

    await runtime.close()

    assert instance.is_closed is True


@pytest.mark.asyncio
async def test_bootstrap_creates_sqlite_runtime(tmp_path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    tools_root = tmp_path / "tools"
    tools_root.mkdir()

    runtime = create_sqlite_runtime(
        database_path,
        filesystem_root=tools_root,
        include_agent_storage=True,
    )

    assert isinstance(runtime, RuntimeKernel)
    assert [tool.name for tool in runtime.tools.list_tools()] == [
        "read_text_file",
        "write_text_file",
        "list_directory",
    ]
    assert [skill.name for skill in runtime.skills.list_skills()] == ["echo"]
    assert runtime.agent_state_register is not None
    assert runtime.agent_trace_register is not None

    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.memories.create(
        MemoryItem(memory_id="mem-1", content="Prefer concise answers")
    )
    runtime.agent_state_register.save_state(
        AgentRunState(
            run_id="run-1",
            request=AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
            ),
            status=AgentRunStatus.PAUSED,
        )
    )
    runtime.agent_trace_register.append_event(
        "run-1",
        AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED),
    )
    await runtime.close()

    reopened = create_sqlite_runtime(database_path, include_agent_storage=True)

    try:
        assert await reopened.contexts.get("ctx-1") == Context(context_id="ctx-1")
        assert (await reopened.memories.get("mem-1")).content == "Prefer concise answers"
        assert reopened.agent_state_register is not None
        assert reopened.agent_trace_register is not None
        assert (
            reopened.agent_state_register.get_state("run-1").status
            is AgentRunStatus.PAUSED
        )
        assert reopened.agent_trace_register.list_events("run-1") == [
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)
        ]
    finally:
        await reopened.close()


def test_bootstrap_can_create_sqlite_runtime_without_agent_storage(tmp_path) -> None:
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=False,
    )

    assert runtime.agent_state_register is None
    assert runtime.agent_trace_register is None

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
