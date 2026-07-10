from __future__ import annotations

import json
import sys

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from typing import Any, cast

from EvernightAI.core.error.provider import ProviderNotFoundError
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
from EvernightAI.core.schema.data_analysis import (
    DataFilter,
    DataFilterOperator,
    DataSort,
    DataStatisticsRequest,
)
from EvernightAI.core.schema.memory import MemoryItem
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.session import Session
from EvernightAI.core.schema.skill import SkillCapability, SkillRenderRequest
from EvernightAI.core.schema.stream import ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.core.schema.tool import ToolApprovalRequest
from EvernightAI.infra.adapters.providers.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
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
    create_session_manager,
    create_session_register,
    create_skill_manager,
    create_skill_register,
    create_sqlite_runtime,
    create_tool_manager,
    create_tool_register,
    create_tool_safety_policy,
    register_builtin_skills,
    register_builtin_tools,
)


def make_openai_config(*, discover_models: bool = False) -> ProviderConfig:
    return ProviderConfig(
        provider_id="openai-main",
        name="OpenAI Main",
        type=ProviderType.OPENAI,
        discover_models=discover_models,
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
        "append_text_file",
        "list_directory",
        "find_paths",
        "search_text_files",
        "read_text_file_lines",
        "move_path",
        "delete_path",
        "apply_text_patch",
        "file_hash",
        "path_info",
        "make_directory",
        "copy_path",
        "read_json_file",
        "write_json_file",
    ]

    register_builtin_tools(
        register,
        shell_allowed_commands={"python"},
        shell_working_directory=tmp_path,
    )

    assert [tool.name for tool in register.list_tools()] == [
        "read_text_file",
        "write_text_file",
        "append_text_file",
        "list_directory",
        "find_paths",
        "search_text_files",
        "read_text_file_lines",
        "move_path",
        "delete_path",
        "apply_text_patch",
        "file_hash",
        "path_info",
        "make_directory",
        "copy_path",
        "read_json_file",
        "write_json_file",
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


def test_bootstrap_creates_session_manager() -> None:
    register = create_session_register()
    manager = create_session_manager(register)

    assert manager._register is register


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
    assert isinstance(runtime.sandbox, SubprocessSandboxExecutor)
    assert [skill.name for skill in runtime.skills.list_skills()] == ["echo"]
    assert runtime.tool_safety_policy.authorize
    assert await runtime.contexts.list_contexts() == []
    assert runtime.context_organizer.organize
    assert runtime.context_strategy.compose_chat_request
    assert await runtime.memories.list_memories() == []
    assert runtime.memory_strategy.select
    assert runtime.memory_write_strategy.create_memories
    assert await runtime.sessions.list_sessions() == []

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
async def test_bootstrap_injects_shared_sandbox_into_process_tools(tmp_path) -> None:
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=False,
        shell_allowed_commands={sys.executable},
        shell_working_directory=tmp_path,
        project_working_directory=tmp_path,
        project_commands={
            "hello": [sys.executable, "-c", "print('project')"],
        },
    )

    try:
        assert isinstance(runtime.sandbox, SubprocessSandboxExecutor)
        assert [tool.name for tool in runtime.tools.list_tools()] == [
            "restricted_shell",
            "run_project_task",
        ]
        assert (
            runtime.tool_register.get("restricted_shell").metadata[
                "sandbox_mount_path"
            ]
            == "/workspace"
        )
        assert (
            runtime.tool_register.get("run_project_task").metadata[
                "sandbox_mount_path"
            ]
            == "/workspace"
        )

        shell_result = await runtime.tools.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "restricted_shell",
                    "arguments": {
                        "command": [sys.executable, "-c", "print('shell')"],
                    },
                },
                metadata={"approved": True},
            )
        )
        project_result = await runtime.tools.execute(
            ToolCall(
                tool_call_id="call-2",
                tool_call={
                    "name": "run_project_task",
                    "arguments": {"task": "hello"},
                },
                metadata={"approved": True},
            )
        )
    finally:
        await runtime.close()

    assert shell_result.tool_call_result["stdout"].splitlines() == ["shell"]
    assert project_result.tool_call_result["stdout"].splitlines() == ["project"]


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
        "append_text_file",
        "list_directory",
        "find_paths",
        "search_text_files",
        "read_text_file_lines",
        "move_path",
        "delete_path",
        "apply_text_patch",
        "file_hash",
        "path_info",
        "make_directory",
        "copy_path",
        "read_json_file",
        "write_json_file",
    ]
    assert [skill.name for skill in runtime.skills.list_skills()] == ["echo"]
    assert runtime.agent_state_register is not None
    assert runtime.agent_trace_register is not None

    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.sessions.create(
        Session(
            session_id="session-1",
            title="Chat",
            context_id="ctx-1",
            provider_id="provider-1",
            model_id="model-1",
        )
    )
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
    assert (
        runtime.agent_trace_register.append_event(
            "run-1",
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED),
        )
        == 1
    )
    await runtime.close()

    reopened = create_sqlite_runtime(database_path, include_agent_storage=True)

    try:
        assert await reopened.contexts.get("ctx-1") == Context(context_id="ctx-1")
        assert (await reopened.sessions.get("session-1")).context_id == "ctx-1"
        assert (await reopened.memories.get("mem-1")).content == "Prefer concise answers"
        assert reopened.agent_state_register is not None
        assert reopened.agent_trace_register is not None
        assert (
            reopened.agent_state_register.get_state("run-1").status
            is AgentRunStatus.PAUSED
        )
        assert reopened.agent_trace_register.list_events("run-1") == [
            AgentTraceEvent(
                sequence=1,
                event_type=AgentTraceEventType.RUN_STARTED,
            )
        ]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_sqlite_runtime_registers_builtin_data_analysis_sources(
    tmp_path,
) -> None:
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=True,
    )

    try:
        assert [
            source.source_id
            for source in runtime.data_analysis.list_sources()
        ] == [
            "agent_runs",
            "agent_trace_events",
            "sessions",
            "contexts",
            "memories",
        ]
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_sqlite_runtime_data_analysis_summarizes_runtime_tables(
    tmp_path,
) -> None:
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=True,
    )

    assert runtime.agent_state_register is not None
    assert runtime.agent_trace_register is not None
    await runtime.contexts.create(
        Context(
            context_id="ctx-1",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hi")],
                ),
                Content(
                    role=MessageRole.ASSISTANT,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                ),
            ],
        )
    )
    await runtime.contexts.create(Context(context_id="ctx-2"))
    await runtime.sessions.create(
        Session(
            session_id="session-1",
            context_id="ctx-1",
            provider_id="provider-a",
            model_id="model-a",
        )
    )
    await runtime.sessions.create(
        Session(
            session_id="session-2",
            context_id="ctx-2",
            provider_id="provider-b",
            model_id="model-b",
        )
    )
    await runtime.memories.create(
        MemoryItem(
            memory_id="mem-1",
            content="Prefer concise answers",
            scope_id="session-1",
        )
    )
    runtime.agent_state_register.save_state(
        AgentRunState(
            run_id="run-1",
            request=AgentRunRequest(
                provider_id="provider-a",
                context_id="ctx-1",
                model_id="model-a",
                metadata={"session_id": "session-1"},
                max_tool_rounds=3,
                write_memory=True,
            ),
            status=AgentRunStatus.FINISHED,
            tool_rounds_used=2,
        )
    )
    runtime.agent_state_register.save_state(
        AgentRunState(
            run_id="run-2",
            request=AgentRunRequest(
                provider_id="provider-b",
                context_id="ctx-2",
                model_id="model-b",
                metadata={"session_id": "session-2"},
                max_tool_rounds=1,
            ),
            status=AgentRunStatus.FAILED,
            tool_rounds_used=0,
        )
    )
    runtime.agent_state_register.save_state(
        AgentRunState(
            run_id="run-3",
            request=AgentRunRequest(
                provider_id="provider-a",
                context_id="ctx-1",
                model_id="model-a",
                metadata={"session_id": "session-1"},
                pause_on_approval=True,
            ),
            status=AgentRunStatus.PAUSED,
            pending_approval_requests=[
                ToolApprovalRequest(
                    approval_id="approval-1",
                    tool_call_id="tool-call-3",
                    tool_name="write_file",
                )
            ],
        )
    )
    runtime.agent_trace_register.append_event(
        "run-1",
        AgentTraceEvent(
            event_type=AgentTraceEventType.TOOL_COMPLETED,
            tool_call=ToolCall(
                tool_call_id="tool-call-1",
                tool_call={"name": "read_file", "arguments": {}},
            ),
        ),
    )
    runtime.agent_trace_register.append_event(
        "run-2",
        AgentTraceEvent(
            event_type=AgentTraceEventType.TOOL_FAILED,
            tool_call=ToolCall(
                tool_call_id="tool-call-2",
                tool_call={"name": "search_web", "arguments": {}},
            ),
            error_type="ToolExecutionError",
        ),
    )
    runtime.agent_trace_register.append_event(
        "run-3",
        AgentTraceEvent(
            event_type=AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
            approval_request=ToolApprovalRequest(
                approval_id="approval-1",
                tool_call_id="tool-call-3",
                tool_name="write_file",
            ),
        ),
    )
    runtime.agent_trace_register.append_event(
        "run-1",
        AgentTraceEvent(
            event_type=AgentTraceEventType.MEMORY_WRITTEN,
            metadata={"memory_id": "mem-1"},
        ),
    )

    try:
        status_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="agent_runs",
                metrics=["run_count"],
                dimensions=["status"],
                sorts=[DataSort(field_id="status")],
            )
        )
        provider_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="agent_runs",
                metrics=["run_count", "average_tool_rounds"],
                dimensions=["provider_id"],
                sorts=[DataSort(field_id="provider_id")],
            )
        )
        approval_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="agent_runs",
                metrics=["pending_approvals_total"],
            )
        )
        session_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="sessions",
                metrics=["session_count"],
                dimensions=["provider_id", "model_id"],
                sorts=[
                    DataSort(field_id="provider_id"),
                    DataSort(field_id="model_id"),
                ],
            )
        )
        context_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="contexts",
                metrics=["average_message_count"],
            )
        )
        tool_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="agent_trace_events",
                metrics=["event_count"],
                dimensions=["tool_name", "event_type"],
                filters=[
                    DataFilter(
                        field_id="event_type",
                        operator=DataFilterOperator.IN,
                        value=[
                            AgentTraceEventType.TOOL_COMPLETED.value,
                            AgentTraceEventType.TOOL_FAILED.value,
                            AgentTraceEventType.TOOL_APPROVAL_REQUESTED.value,
                        ],
                    )
                ],
                sorts=[
                    DataSort(field_id="tool_name"),
                    DataSort(field_id="event_type"),
                ],
            )
        )
        memory_write_result = await runtime.data_analysis.statistics(
            DataStatisticsRequest(
                source_id="agent_trace_events",
                metrics=["memory_write_count", "distinct_session_count"],
                filters=[
                    DataFilter(
                        field_id="event_type",
                        operator=DataFilterOperator.EQUALS,
                        value=AgentTraceEventType.MEMORY_WRITTEN.value,
                    )
                ],
            )
        )
    finally:
        await runtime.close()

    assert [
        (row.dimensions["status"], row.metrics["run_count"])
        for row in status_result.rows
    ] == [
        ("failed", 1),
        ("finished", 1),
        ("paused", 1),
    ]
    assert [
        (
            row.dimensions["provider_id"],
            row.metrics["run_count"],
            row.metrics["average_tool_rounds"],
        )
        for row in provider_result.rows
    ] == [
        ("provider-a", 2, 1.0),
        ("provider-b", 1, 0.0),
    ]
    assert approval_result.rows[0].metrics == {"pending_approvals_total": 1}
    assert [
        (
            row.dimensions["provider_id"],
            row.dimensions["model_id"],
            row.metrics["session_count"],
        )
        for row in session_result.rows
    ] == [
        ("provider-a", "model-a", 1),
        ("provider-b", "model-b", 1),
    ]
    assert context_result.rows[0].metrics == {"average_message_count": 1.0}
    assert [
        (
            row.dimensions["tool_name"],
            row.dimensions["event_type"],
            row.metrics["event_count"],
        )
        for row in tool_result.rows
    ] == [
        ("read_file", "tool_completed", 1),
        ("search_web", "tool_failed", 1),
        ("write_file", "tool_approval_requested", 1),
    ]
    assert memory_write_result.rows[0].metrics == {
        "memory_write_count": 1,
        "distinct_session_count": 1,
    }


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
async def test_openai_instance_chat_maps_reasoning_effort_metadata() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config())
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
            metadata={
                "request_id": "req-1",
                "reasoning_effort": "high",
            },
        )
    )

    assert completions.params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
        "reasoning_effort": "high",
    }

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_chat_maps_timeout_metadata() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config())
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
            metadata={"timeout_seconds": 12},
        )
    )

    assert completions.params is not None
    assert completions.params["timeout"] == 12.0

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_ignores_unknown_provider_metadata() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config())
    completions = FakeCompletions()
    fake_client = FakeClient(completions)
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
                )
            ],
            metadata={
                "request_id": "req-1",
                "reasoning_effort": "extreme",
                "temperature": 0,
            },
        )
    )

    assert completions.params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
    }

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_chat_stream_maps_chunks_to_chat_stream_events() -> None:
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
    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_START,
        ChatStreamEventType.MESSAGE_DELTA,
        ChatStreamEventType.DONE,
    ]
    assert events[1].text_delta == "Hi"

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
    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_START,
        ChatStreamEventType.MESSAGE_DELTA,
        ChatStreamEventType.DONE,
    ]

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_chat_stream_maps_reasoning_effort_metadata() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config())
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
            metadata={"reasoning_effort": "medium"},
        )
    )
    _ = [event async for event in stream]

    assert completions.params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "Hello"}],
        "timeout": 30.0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "reasoning_effort": "medium",
    }

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_lists_declared_models_without_remote_discovery() -> None:
    instance = OpenAICompatibleProviderInstance(make_openai_config())
    fake_client = FakeClient(
        FakeCompletions(),
        models=FakeModels(["gpt-test", "remote-model"]),
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gpt-test"]
    with pytest.raises(ProviderNotFoundError):
        await instance.get_model("remote-model")
    assert fake_client.models.calls == 0

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_lists_remote_models_when_discovery_enabled() -> None:
    instance = OpenAICompatibleProviderInstance(
        make_openai_config(discover_models=True)
    )
    fake_client = FakeClient(
        FakeCompletions(),
        models=FakeModels(["gpt-test", "remote-model"]),
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gpt-test", "remote-model"]
    assert (await instance.get_model("remote-model")).model_id == "remote-model"
    assert fake_client.models.calls == 2

    await instance.close()


@pytest.mark.asyncio
async def test_openai_instance_falls_back_to_declared_models_when_discovery_fails() -> None:
    instance = OpenAICompatibleProviderInstance(
        make_openai_config(discover_models=True)
    )
    fake_client = FakeClient(
        FakeCompletions(),
        models=FakeModels(
            [],
            error=RuntimeError("models unavailable"),
        ),
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gpt-test"]
    assert fake_client.models.calls == 1

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


class FakeRemoteModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class FakeModelsPage:
    def __init__(self, model_ids: list[str]) -> None:
        self.data = [FakeRemoteModel(model_id) for model_id in model_ids]


class FakeModels:
    def __init__(
        self,
        model_ids: list[str],
        *,
        error: Exception | None = None,
    ) -> None:
        self._model_ids = model_ids
        self._error = error
        self.calls = 0

    async def list(self) -> FakeModelsPage:
        self.calls += 1
        if self._error is not None:
            raise self._error

        return FakeModelsPage(self._model_ids)


class FakeClient:
    def __init__(
        self,
        completions: FakeCompletions,
        *,
        models: FakeModels | None = None,
    ) -> None:
        self.chat = FakeChat(completions)
        self.models = models or FakeModels([])
        self.closed = False

    async def close(self) -> None:
        self.closed = True
