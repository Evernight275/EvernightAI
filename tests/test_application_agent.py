import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime, timezone
from typing import cast

import pytest

from EvernightAI.application.agent import (
    AgentApplication,
    AgentRunApplication,
    AgentRunMetadata,
    _AgentRunLifecycle,
)
from EvernightAI.core.error.agent import AgentShutdownError, AgentStateError
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentStep,
    AgentStepType,
    AgentStopReason,
    AgentTraceEvent,
    AgentTraceEventType,
    ToolExecutionAttempt,
    ToolExecutionResolution,
    ToolExecutionStatus,
)
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
from EvernightAI.core.domain.tool import BasicToolSafetyPolicy, ToolManager, ToolRegister
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatSkill,
    ChatUsage,
    Content,
    ContentPart,
    ContentPartType,
    MessageStatus,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemoryScope
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition, ToolReplayPolicy
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolPermission,
    ToolSafetyLevel,
)
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)
from tests.fakes.agent import (
    InMemoryAgentRunStateRegister,
    InMemoryAgentTraceRegister,
    InMemoryToolExecutionRegister,
)
from tests.fakes.streams import EmptyStream, EventStream


@pytest.mark.asyncio
async def test_agent_runs_tool_loop_and_persists_messages() -> None:
    async def add(arguments: dict[str, object]) -> dict[str, object]:
        left = arguments["left"]
        right = arguments["right"]
        assert isinstance(left, int)
        assert isinstance(right, int)
        return {"result": left + right}

    runtime = make_runtime()
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("What is 1 + 2?")],
            tools=runtime.tools.list_tools(),
            metadata={"run_id": "run-1"},
        )
    )
    response = result.response

    context = await runtime.contexts.get("ctx-1")
    provider = await runtime.providers.get("provider-1")

    assert isinstance(provider, ToolCallingProvider)
    assert len(provider.requests) == 2
    assert [message_text(message) for message in provider.requests[0].messages] == [
        "What is 1 + 2?"
    ]
    assert response.message == make_message("The result is 3", role=MessageRole.ASSISTANT)
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]
    assert context.messages[2].tool_call_id == "tool-call-1"
    assert "result" in message_text(context.messages[2])
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.TOOL,
        AgentStepType.CHAT,
        AgentStepType.STOP,
    ]
    assert result.steps[2].tool_call is not None
    assert result.steps[2].tool_result is not None
    assert result.stop_reason is AgentStopReason.FINISHED
    assert result.metadata == {
        "run_id": "run-1",
        AgentRunMetadata.RUNTIME_KEY: {
            AgentRunMetadata.TOOL_ROUNDS_USED_KEY: 1,
        },
    }
    assert [event.event_type for event in result.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]


@pytest.mark.asyncio
async def test_agent_renders_skills_for_each_chat_round() -> None:
    async def add(arguments: dict[str, object]) -> dict[str, object]:
        return {"result": 3}

    runtime = make_runtime()
    register_style_skill(runtime)
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = NoStreamingResponseAgentApplication(runtime)
    await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("What is 1 + 2?")],
            skills=[
                ChatSkill(
                    skill_name="style",
                    variables={"tone": "concise"},
                )
            ],
            tools=runtime.tools.list_tools(),
        )
    )
    context = await runtime.contexts.get("ctx-1")
    provider = await runtime.providers.get("provider-1")

    assert isinstance(provider, ToolCallingProvider)
    assert len(provider.requests) == 2
    assert [message_text(message) for message in provider.requests[0].messages] == [
        "Use concise style",
        "What is 1 + 2?",
    ]
    assert message_text(provider.requests[1].messages[0]) == "Use concise style"
    assert provider.requests[0].skills is None
    assert provider.requests[1].skills is None
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]
    assert message_text(context.messages[0]) == "What is 1 + 2?"
    assert "tool_call_result" in message_text(context.messages[2])
    assert message_text(context.messages[3]) == "The result is 3"


@pytest.mark.asyncio
async def test_agent_streams_tool_loop_events() -> None:
    async def add(arguments: dict[str, object]) -> dict[str, object]:
        return {"result": 3}

    runtime = make_runtime()
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    stream = app.run_agent_stream(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("What is 1 + 2?")],
            tools=runtime.tools.list_tools(),
        )
    )
    events = [event async for event in stream]
    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert [event.summary for event in events] == [
        "Agent run started",
        "Model response received",
        "Tool add completed",
        "Model response received",
        "Agent run stopped: finished",
    ]
    assert events[2].tool_result is not None
    assert events[-1].metadata["reason"] == AgentStopReason.FINISHED.value
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]


@pytest.mark.asyncio
async def test_agent_streams_chat_delta_when_requested() -> None:
    provider = StreamingAnswerProvider()
    runtime = make_runtime(provider=provider)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    stream = app.run_agent_stream(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Hello")],
            metadata={"stream": True},
        )
    )
    events = [event async for event in stream]
    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_DELTA,
        AgentTraceEventType.CHAT_DELTA,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert [event.text_delta for event in events if event.text_delta] == [
        "hel",
        "lo",
    ]
    assert events[3].response is not None
    assert message_text(events[3].response.message) == "hello"
    assert events[3].response.usage == ChatUsage(
        prompt_tokens=8,
        completion_tokens=2,
        total_tokens=10,
        cached_prompt_tokens=6,
        metadata={
            "cache_phase": "read",
            "usage_phase": "complete",
        },
    )
    assert [message_text(message) for message in context.messages] == [
        "Hello",
        "hello",
    ]


@pytest.mark.asyncio
async def test_agent_recovers_from_tool_errors() -> None:
    runtime = make_runtime(provider=RecoveringToolErrorProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Use missing tool")],
            recover_tool_errors=True,
        )
    )

    context = await runtime.contexts.get("ctx-1")

    assert result.stop_reason is AgentStopReason.FINISHED
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.TOOL_ERROR,
        AgentStepType.CHAT,
        AgentStepType.STOP,
    ]
    assert context.messages[2].metadata["error"] is True
    assert result.response.message == make_message(
        "Recovered from tool error",
        role=MessageRole.ASSISTANT,
    )


@pytest.mark.asyncio
async def test_agent_sends_tool_error_message_to_follow_up_chat() -> None:
    provider = RecoveringToolErrorProvider()
    runtime = make_runtime(provider=provider)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Use missing tool")],
            recover_tool_errors=True,
        )
    )

    assert len(provider.requests) == 2
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert provider.requests[1].messages[2].tool_call_id == "tool-call-1"
    assert provider.requests[1].messages[2].metadata["error"] is True


@pytest.mark.asyncio
async def test_agent_sends_underlying_tool_error_cause_to_follow_up_chat() -> None:
    async def broken_tool(arguments: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("pytest executable was not found")

    provider = RecoveringToolErrorProvider()
    runtime = make_runtime(provider=provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="missing",
            description="Fail with an actionable execution error",
            parameters_schema={"type": "object"},
        ),
        broken_tool,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    await AgentApplication(runtime).run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Run tests")],
            recover_tool_errors=True,
        )
    )

    error_message = provider.requests[1].messages[2]
    payload = json.loads(message_text(error_message))
    assert payload == {
        "error_type": "ToolExecutionError",
        "error_message": "The tool missing execution failed",
        "cause": {
            "error_type": "RuntimeError",
            "error_message": "pytest executable was not found",
        },
    }


@pytest.mark.asyncio
async def test_agent_can_stop_on_tool_error() -> None:
    runtime = make_runtime(provider=RecoveringToolErrorProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Use missing tool")],
            recover_tool_errors=False,
        )
    )

    assert result.stop_reason is AgentStopReason.TOOL_ERROR
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.TOOL_ERROR,
        AgentStepType.STOP,
    ]
    assert [event.event_type for event in result.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_FAILED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert result.trace[2].summary == "Tool missing failed with ToolNotFoundError"


@pytest.mark.asyncio
async def test_agent_traces_tool_approval_decision() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            tool_approvals=[
                ToolApprovalDecision(
                    approval_id="tool-call-1:approval",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.APPROVED,
                    metadata={"approved_by": "test"},
                )
            ],
        )
    )

    approval_requested = [
        event
        for event in result.trace
        if event.event_type is AgentTraceEventType.TOOL_APPROVAL_REQUESTED
    ]
    approval_decided = [
        event
        for event in result.trace
        if event.event_type is AgentTraceEventType.TOOL_APPROVAL_DECIDED
    ]

    assert result.stop_reason is AgentStopReason.FINISHED
    assert len(approval_requested) == 1
    assert approval_requested[0].approval_request is not None
    assert approval_requested[0].approval_request.tool_name == "write_file"
    assert approval_requested[0].summary == "Tool approval requested for write_file"
    assert len(approval_decided) == 1
    assert approval_decided[0].approval_decision is not None
    assert approval_decided[0].approval_decision.status is ToolApprovalStatus.APPROVED
    assert approval_decided[0].summary == "Tool approval approved for write_file"
    assert AgentTraceEventType.TOOL_COMPLETED in [
        event.event_type for event in result.trace
    ]


@pytest.mark.asyncio
async def test_agent_streams_tool_approval_events() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    events = [
        event
        async for event in app.run_agent_stream(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Write a file")],
                tools=runtime.tools.list_tools(),
                tool_approvals=[
                    ToolApprovalDecision(
                        approval_id="tool-call-1:approval",
                        tool_call_id="tool-call-1",
                        status=ToolApprovalStatus.APPROVED,
                    )
                ],
            )
        )
    ]

    assert [event.event_type for event in events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert events[2].approval_request is not None
    assert events[2].approval_request.tool_name == "write_file"
    assert events[3].approval_decision is not None
    assert events[3].approval_decision.status is ToolApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_agent_stream_pauses_for_unapproved_sensitive_tool() -> None:
    tool_executed = False

    async def write(arguments: dict[str, object]) -> dict[str, object]:
        nonlocal tool_executed
        tool_executed = True
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    events = [
        event
        async for event in app.run_agent_stream(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Write a file")],
                tools=runtime.tools.list_tools(),
                pause_on_approval=True,
            )
        )
    ]
    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
    ]
    assert events[2].approval_request is not None
    assert events[2].approval_request.tool_name == "write_file"
    assert events[3].approval_request is not None
    assert events[3].metadata["reason"] == "tool_approval_required"
    assert tool_executed is False
    assert context.messages == []


@pytest.mark.asyncio
async def test_paused_tool_run_does_not_pollute_next_run_context() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    provider = SensitiveToolProvider()
    runtime = make_runtime(provider=provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    paused = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
        )
    )

    assert paused.status is AgentRunStatus.PAUSED

    await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Second request")],
        )
    )

    assert len(provider.requests) == 2
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER
    ]
    assert message_text(provider.requests[1].messages[0]) == "Second request"
    assert not any(
        message.role is MessageRole.ASSISTANT and message.tool_calls
        for message in provider.requests[1].messages
    )


@pytest.mark.asyncio
async def test_agent_run_until_pause_returns_pending_approval_state() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            max_tool_rounds=2,
            metadata={"run_id": "run-1"},
        )
    )

    assert state.run_id == "run-1"
    assert state.status is AgentRunStatus.PAUSED
    assert state.stop_reason is None
    assert state.response is not None
    assert state.remaining_tool_rounds == 2
    assert state.tool_rounds_used == 0
    assert len(state.pending_tool_calls) == 1
    assert state.pending_tool_calls[0].tool_call_id == "tool-call-1"
    assert len(state.pending_approval_requests) == 1
    assert state.pending_approval_requests[0].tool_name == "write_file"
    assert state.metadata[AgentRunMetadata.RUNTIME_KEY] == {
        AgentRunMetadata.PENDING_APPROVAL_COUNT_KEY: 1,
        AgentRunMetadata.TOOL_ROUNDS_USED_KEY: 0,
    }
    assert [event.event_type for event in state.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
    ]


@pytest.mark.asyncio
async def test_agent_rejects_blocked_shell_command_without_approval(tmp_path) -> None:
    runtime = make_runtime(provider=BlockedShellToolProvider())
    register_restricted_shell_tool(
        runtime.tool_register,
        allowed_commands={"uv"},
        blocked_commands={"uv publish"},
        working_directory=tmp_path,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Publish the package")],
            tools=runtime.tools.list_tools(),
            recover_tool_errors=False,
        )
    )

    assert state.status is AgentRunStatus.FAILED
    assert state.stop_reason is AgentStopReason.TOOL_ERROR
    assert [event.event_type for event in state.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_FAILED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert state.pending_approval_requests == []
    assert not any(
        event.event_type is AgentTraceEventType.TOOL_APPROVAL_REQUESTED
        for event in state.trace
    )


@pytest.mark.asyncio
async def test_agent_resume_stream_continues_after_approved_tool() -> None:
    executed_arguments: list[dict[str, object]] = []

    async def write(arguments: dict[str, object]) -> dict[str, object]:
        executed_arguments.append(arguments)
        return {"written": True}

    provider = SensitiveToolProvider()
    runtime = make_runtime(provider=provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
        )
    )

    events = [
        event
        async for event in app.resume_agent_stream(
            state,
            [
                ToolApprovalDecision(
                    approval_id="tool-call-1:approval",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.APPROVED,
                    metadata={"approved_by": "test"},
                )
            ],
        )
    ]
    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in events] == [
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert events[0].approval_decision is not None
    assert events[0].approval_decision.status is ToolApprovalStatus.APPROVED
    assert state.status is AgentRunStatus.FINISHED
    assert state.stop_reason is AgentStopReason.FINISHED
    assert state.response == make_response("Written")
    assert state.pending_tool_calls == []
    assert state.pending_approval_requests == []
    assert executed_arguments == [{"path": "note.txt"}]
    assert len(provider.requests) == 2
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]


@pytest.mark.asyncio
async def test_agent_state_metadata_namespaces_runtime_values() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            metadata={
                "run_id": "run-1",
                "pending_approval_count": "caller-value",
                "tool_rounds_used": "caller-value",
            },
        )
    )

    assert state.metadata["pending_approval_count"] == "caller-value"
    assert state.metadata["tool_rounds_used"] == "caller-value"
    assert state.metadata[AgentRunMetadata.RUNTIME_KEY] == {
        AgentRunMetadata.PENDING_APPROVAL_COUNT_KEY: 1,
        AgentRunMetadata.TOOL_ROUNDS_USED_KEY: 0,
    }

    resumed = await app.resume_agent_until_pause(
        state,
        [
            ToolApprovalDecision(
                approval_id="tool-call-1:approval",
                tool_call_id="tool-call-1",
                status=ToolApprovalStatus.APPROVED,
            )
        ],
    )

    assert resumed.status is AgentRunStatus.FINISHED
    assert resumed.metadata["pending_approval_count"] == "caller-value"
    assert resumed.metadata["tool_rounds_used"] == "caller-value"
    assert resumed.metadata[AgentRunMetadata.RUNTIME_KEY] == {
        AgentRunMetadata.PENDING_APPROVAL_COUNT_KEY: 0,
        AgentRunMetadata.TOOL_ROUNDS_USED_KEY: 1,
    }


@pytest.mark.asyncio
async def test_agent_pause_keeps_current_and_remaining_tool_calls() -> None:
    executed_tools: list[str] = []

    async def write(arguments: dict[str, object]) -> dict[str, object]:
        executed_tools.append("write_file")
        return {"written": True}

    async def add(arguments: dict[str, object]) -> dict[str, object]:
        executed_tools.append("add")
        return {"result": 3}

    provider = SensitiveThenSafeToolProvider()
    runtime = make_runtime(provider=provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write and add")],
            tools=runtime.tools.list_tools(),
        )
    )

    assert state.status is AgentRunStatus.PAUSED
    assert [call.tool_call_id for call in state.pending_tool_calls] == [
        "tool-call-1",
        "tool-call-2",
    ]
    assert len(state.pending_approval_requests) == 1
    assert state.pending_approval_requests[0].tool_call_id == "tool-call-1"
    assert executed_tools == []

    events = [
        event
        async for event in app.resume_agent_stream(
            state,
            [
                ToolApprovalDecision(
                    approval_id="tool-call-1:approval",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.APPROVED,
                )
            ],
        )
    ]
    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in events] == [
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert executed_tools == ["write_file", "add"]
    assert state.status is AgentRunStatus.FINISHED
    assert state.pending_tool_calls == []
    assert state.pending_approval_requests == []
    assert len(provider.requests) == 2
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
    ]
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]


@pytest.mark.asyncio
async def test_agent_resume_stream_records_denied_approval_as_tool_error() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    provider = SensitiveToolProvider()
    runtime = make_runtime(provider=provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            recover_tool_errors=False,
        )
    )

    events = [
        event
        async for event in app.resume_agent_stream(
            state,
            [
                ToolApprovalDecision(
                    approval_id="tool-call-1:approval",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.DENIED,
                    reason="Denied by test",
                )
            ],
        )
    ]
    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in events] == [
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_FAILED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert events[0].approval_decision is not None
    assert events[0].approval_decision.status is ToolApprovalStatus.DENIED
    assert state.status is AgentRunStatus.FAILED
    assert state.stop_reason is AgentStopReason.TOOL_ERROR
    assert len(provider.requests) == 1
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert context.messages[2].metadata["error"] is True


@pytest.mark.asyncio
async def test_agent_resume_requires_paused_state() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Hello")],
        )
    )

    assert AgentRunMetadata.RUNTIME_KEY not in state.metadata

    with pytest.raises(AgentStateError, match="not paused"):
        await app.resume_agent_until_pause(state, [])


@pytest.mark.asyncio
async def test_agent_resume_requires_pending_approval_decision() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
        )
    )

    with pytest.raises(AgentStateError, match="Missing approval"):
        await app.resume_agent_until_pause(state, [])


@pytest.mark.asyncio
async def test_agent_start_and_resume_run_persist_state_and_trace() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=SensitiveToolProvider(),
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.start_agent_run(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            metadata={"run_id": "run-1"},
        )
    )

    assert state.status is AgentRunStatus.PAUSED
    assert state_register.get_state("run-1").status is AgentRunStatus.PAUSED
    assert [event.event_type for event in trace_register.list_events("run-1")] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
    ]

    resumed = await app.resume_agent_run(
        "run-1",
        [
            ToolApprovalDecision(
                approval_id="tool-call-1:approval",
                tool_call_id="tool-call-1",
                status=ToolApprovalStatus.APPROVED,
            )
        ],
    )

    assert resumed.status is AgentRunStatus.FINISHED
    assert state_register.get_state("run-1").status is AgentRunStatus.FINISHED
    assert [event.event_type for event in trace_register.list_events("run-1")] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]


@pytest.mark.asyncio
async def test_agent_start_run_requires_storage_registers() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)

    with pytest.raises(AgentStateError, match="state register"):
        await app.start_agent_run(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Hello")],
            )
        )


@pytest.mark.asyncio
async def test_agent_run_application_retry_marks_old_branch() -> None:
    provider = FinalAnswerProvider()
    runtime = make_runtime(
        provider=provider,
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    await runtime.contexts.create(
        Context(
            context_id="ctx-1",
            messages=[
                make_message("Original question"),
                make_message("Bad answer", role=MessageRole.ASSISTANT),
                make_message("Follow-up"),
            ],
        )
    )
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    await app.start(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            retry_from_message_index=1,
            max_tool_rounds=0,
        )
    )

    context = await runtime.contexts.get("ctx-1")

    assert [message_text(message) for message in provider.requests[0].messages] == [
        "Original question",
    ]
    assert [message.status for message in context.messages] == [
        None,
        MessageStatus.REJECTED,
        MessageStatus.REJECTED,
        None,
    ]


@pytest.mark.asyncio
async def test_agent_run_application_retries_terminal_run_with_new_approval() -> None:
    async def write_file(_arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=SensitiveToolProvider(),
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write_file,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())
    source_request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("Write a file")],
        tools=runtime.tools.list_tools(),
        tool_approvals=[
            ToolApprovalDecision(
                approval_id="tool-call-1:approval",
                tool_call_id="tool-call-1",
                status=ToolApprovalStatus.APPROVED,
            )
        ],
        metadata={"run_id": "run-source"},
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-source",
            request=source_request,
            status=AgentRunStatus.CANCELED,
        )
    )

    retried = await AgentRunApplication(runtime).retry("run-source")

    assert retried.run_id != "run-source"
    assert retried.status is AgentRunStatus.PAUSED
    assert retried.request.tool_approvals == []
    assert retried.request.metadata[AgentRunMetadata.RETRY_OF_KEY] == "run-source"
    assert retried.request.metadata[AgentRunMetadata.RETRY_ATTEMPT_KEY] == 1
    assert len(retried.pending_approval_requests) == 1


@pytest.mark.asyncio
async def test_agent_run_application_rejects_retry_of_nonterminal_run() -> None:
    state_register = InMemoryAgentRunStateRegister()
    runtime = make_runtime(
        agent_state_register=state_register,
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-active",
            request=AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
            ),
        )
    )

    with pytest.raises(AgentStateError, match="Only canceled, failed"):
        await AgentRunApplication(runtime).retry("run-active")


@pytest.mark.asyncio
async def test_agent_run_application_facade_manages_persisted_runs() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=SensitiveToolProvider(),
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    state = await app.start(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            metadata={"run_id": "run-1"},
        )
    )

    assert state.status is AgentRunStatus.PAUSED
    assert app.get_state("run-1") == state
    assert app.list_states() == [state]
    assert [event.event_type for event in app.list_trace("run-1")] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
    ]
    assert [event.sequence for event in state.trace] == [1, 2, 3, 4]
    assert [
        event.sequence
        for event in app.list_trace("run-1", after_sequence=2, limit=1)
    ] == [3]

    resumed = await app.resume(
        "run-1",
        [
            ToolApprovalDecision(
                approval_id="tool-call-1:approval",
                tool_call_id="tool-call-1",
                status=ToolApprovalStatus.APPROVED,
            )
        ],
    )

    assert resumed.status is AgentRunStatus.FINISHED
    assert app.get_state("run-1") == resumed
    assert [event.event_type for event in app.list_trace("run-1")] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert [event.sequence for event in resumed.trace] == list(range(1, 9))


@pytest.mark.asyncio
async def test_agent_run_application_requires_storage_registers() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)

    with pytest.raises(AgentStateError, match="state register"):
        app.get_state("missing")

    with pytest.raises(AgentStateError, match="trace register"):
        app.list_trace("missing")

    with pytest.raises(AgentStateError, match="state register"):
        await app.start(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Hello")],
            )
        )


@pytest.mark.asyncio
async def test_agent_run_application_shutdown_blocks_new_runs_and_waits_for_active_run() -> None:
    provider = BlockingFinalAnswerProvider()
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=provider,
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    start_task = asyncio.create_task(
        app.start(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Wait for shutdown")],
                metadata={"run_id": "run-active"},
            )
        )
    )
    await provider.started.wait()

    close_task = asyncio.create_task(app.close())
    await asyncio.sleep(0)

    assert close_task.done() is False
    with pytest.raises(AgentShutdownError, match="shutting down"):
        await app.start(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("New run")],
            )
        )

    provider.release.set()
    state = await start_task
    await close_task

    assert state.status is AgentRunStatus.FINISHED
    assert state_register.get_state("run-active").status is AgentRunStatus.FINISHED


@pytest.mark.asyncio
async def test_agent_run_application_shutdown_marks_stale_running_runs_paused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=FinalAnswerProvider(),
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("Interrupted")],
        metadata={"run_id": "run-stale"},
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-stale",
            request=request,
            status=AgentRunStatus.RUNNING,
            metadata={"run_id": "run-stale"},
        )
    )

    app = AgentRunApplication(runtime)
    with caplog.at_level(logging.INFO, logger="EvernightAI.application.agent"):
        await app.close()

    state = state_register.get_state("run-stale")
    trace = trace_register.list_events("run-stale")

    assert state.status is AgentRunStatus.PAUSED
    assert state.stop_reason is None
    assert state.metadata[AgentRunMetadata.RUNTIME_KEY] == {
        "manual_pause": True,
        "pause_checkpoint": "run_started",
        "pause_source": "shutdown",
        "recovery_eligible": True,
        "recovery_reason": "shutdown",
        "shutdown_reason": "shutdown",
    }
    assert [event.event_type for event in trace] == [AgentTraceEventType.RUN_PAUSED]
    assert trace[0].metadata == {
        "reason": "shutdown",
        "source": "shutdown",
        "checkpoint": "run_started",
        "recovery_eligible": True,
    }
    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "EvernightAI.application.agent"
    ] == [
        "EvernightAI agent shutdown: blocking new agent runs",
        "EvernightAI agent shutdown: active agent runs drained",
        "EvernightAI agent shutdown: persisted running states reconciled",
    ]


def test_agent_run_application_timeout_marks_checkpoint_recovery_metadata() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-timeout",
            request=AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
            ),
        )
    )

    AgentRunApplication(runtime)._mark_interrupted("run-timeout", "timeout")

    state = state_register.get_state("run-timeout")
    runtime_metadata = state.metadata[AgentRunMetadata.RUNTIME_KEY]
    assert state.status is AgentRunStatus.PAUSED
    assert runtime_metadata["pause_source"] == "timeout"
    assert runtime_metadata["pause_checkpoint"] == "run_started"
    assert runtime_metadata["recovery_eligible"] is True
    assert trace_register.list_events("run-timeout")[-1].metadata == {
        "reason": "timeout",
        "interrupted": True,
        "checkpoint": "run_started",
        "recovery_eligible": True,
    }


@pytest.mark.asyncio
async def test_agent_records_denied_tool_approval_as_tool_error() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
            recover_tool_errors=False,
            tool_approvals=[
                ToolApprovalDecision(
                    approval_id="tool-call-1:approval",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.DENIED,
                    reason="Denied by test",
                )
            ],
        )
    )

    assert result.stop_reason is AgentStopReason.TOOL_ERROR
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.TOOL_ERROR,
        AgentStepType.STOP,
    ]
    assert [event.event_type for event in result.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_FAILED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert result.steps[2].error_type == "ToolPolicyError"


@pytest.mark.asyncio
async def test_agent_metadata_hides_tool_runtime_without_tool_calls() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Hello")],
            metadata={"run_id": "run-1", "source": "test"},
        )
    )

    assert result.stop_reason is AgentStopReason.FINISHED
    assert result.metadata == {"run_id": "run-1", "source": "test"}
    assert AgentRunMetadata.RUNTIME_KEY not in result.metadata


@pytest.mark.asyncio
async def test_agent_reports_tool_rounds_exhausted() -> None:
    provider = EndlessToolCallingProvider()
    runtime = make_runtime(provider=provider)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Keep using tools")],
            max_tool_rounds=0,
        )
    )

    assert result.stop_reason is AgentStopReason.TOOL_ROUNDS_EXHAUSTED
    assert (
        result.metadata[AgentRunMetadata.RUNTIME_KEY][
            AgentRunMetadata.TOOL_ROUNDS_USED_KEY
        ]
        == 0
    )
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.STOP,
    ]

    context = await runtime.contexts.get("ctx-1")

    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]

    await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Try again")],
            max_tool_rounds=0,
        )
    )

    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER,
        MessageRole.USER,
    ]
    assert not any(
        message.role is MessageRole.ASSISTANT and message.tool_calls
        for message in provider.requests[1].messages
    )


@pytest.mark.asyncio
async def test_agent_can_write_memory_after_run() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Remember this")],
            write_memory=True,
        )
    )

    memories = await runtime.memories.list_memories()

    assert len(memories) == 1
    assert memories[0].scope_id == "ctx-1"
    assert "Remember this" in memories[0].content
    assert result.steps[-1].step_type is AgentStepType.MEMORY_WRITE
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.STOP,
        AgentStepType.MEMORY_WRITE,
    ]
    assert [event.event_type for event in result.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.MEMORY_WRITTEN,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert memories[0].metadata["step_count"] == 3
    assert memories[0].metadata["write_operation"] == "create"
    assert result.steps[-1].metadata["operation"] == "create"


@pytest.mark.asyncio
async def test_agent_writes_memory_to_session_scope_when_session_id_is_present() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Remember this")],
            write_memory=True,
            metadata={"session_id": "session-1"},
        )
    )

    memories = await runtime.memories.list_memories()

    assert len(memories) == 1
    assert memories[0].scope is MemoryScope.SESSION
    assert memories[0].scope_id == "session-1"
    assert memories[0].metadata["context_id"] == "ctx-1"


@pytest.mark.asyncio
async def test_agent_replaces_existing_memory_with_same_memory_key() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    first = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Remember first")],
            write_memory=True,
        )
    )
    second = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Remember second")],
            write_memory=True,
        )
    )

    memories = await runtime.memories.list_memories()

    assert len(memories) == 1
    assert "Remember second" in memories[0].content
    assert "Remember first" not in memories[0].content
    assert memories[0].metadata["write_operation"] == "replace"
    assert memories[0].metadata["previous_memory_id"] == memories[0].memory_id
    assert memories[0].metadata["previous_content_fingerprint"] != (
        memories[0].metadata["content_fingerprint"]
    )
    assert first.steps[-1].metadata["operation"] == "create"
    assert second.steps[-1].metadata["operation"] == "replace"


@pytest.mark.asyncio
async def test_agent_selects_session_memory_from_metadata() -> None:
    provider = FinalAnswerProvider()
    runtime = make_runtime(provider=provider)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.memories.create(
        MemoryItem(
            memory_id="session-memory",
            content="This session prefers concise replies",
            scope=MemoryScope.SESSION,
            scope_id="session-1",
        )
    )
    await runtime.memories.create(
        MemoryItem(
            memory_id="other-session-memory",
            content="Other session memory",
            scope=MemoryScope.SESSION,
            scope_id="session-2",
        )
    )
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Current request")],
            metadata={"session_id": "session-1"},
        )
    )

    assert [message_text(message) for message in provider.requests[0].messages] == [
        "Relevant memory:\n- fact: This session prefers concise replies",
        "Current request",
    ]
    assert provider.requests[0].metadata["memory_ids"] == ["session-memory"]
    assert provider.requests[0].metadata["session_id"] == "session-1"


@pytest.mark.asyncio
async def test_agent_run_convenience_method_recovers_tool_errors() -> None:
    provider = RecoveringToolErrorProvider()
    runtime = make_runtime(provider=provider)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    response = await app.run(
        "provider-1",
        "ctx-1",
        model_id="model-1",
        messages=[make_message("Use missing tool")],
        metadata={"source": "convenience"},
    )

    assert response.message == make_message(
        "Recovered from tool error",
        role=MessageRole.ASSISTANT,
    )
    assert len(provider.requests) == 2
    assert provider.requests[0].metadata["source"] == "convenience"


@pytest.mark.asyncio
async def test_agent_resume_agent_returns_result_after_approved_tool() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    runtime = make_runtime(provider=SensitiveToolProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    state = await app.run_agent_until_pause(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Write a file")],
            tools=runtime.tools.list_tools(),
        )
    )
    result = await app.resume_agent(
        state,
        [
            ToolApprovalDecision(
                approval_id="tool-call-1:approval",
                tool_call_id="tool-call-1",
                status=ToolApprovalStatus.APPROVED,
            )
        ],
    )

    assert result.stop_reason is AgentStopReason.FINISHED
    assert result.response == make_response("Written")
    assert [event.event_type for event in result.trace][-4:] == [
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]


@pytest.mark.asyncio
async def test_agent_resume_requires_response_and_pending_tool_calls() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("Hello")],
    )
    app = AgentApplication(runtime)

    with pytest.raises(AgentStateError, match="did not produce a response"):
        await app.resume_agent_until_pause(
            AgentRunState(
                run_id="run-1",
                request=request,
                status=AgentRunStatus.PAUSED,
            ),
            [],
        )

    with pytest.raises(AgentStateError, match="no pending tool calls"):
        await app.resume_agent_until_pause(
            AgentRunState(
                run_id="run-2",
                request=request,
                status=AgentRunStatus.PAUSED,
                response=make_response("Stored"),
            ),
            [],
        )


@pytest.mark.asyncio
async def test_agent_close_handles_missing_state_register_and_repeated_close() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    app = AgentApplication(runtime)

    await app.close()
    await app.close()

    with pytest.raises(AgentShutdownError, match="shutting down"):
        await app.run_agent(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Hello")],
            )
        )


@pytest.mark.asyncio
async def test_agent_close_pauses_running_state_without_trace_register() -> None:
    state_register = InMemoryAgentRunStateRegister()
    runtime = make_runtime(
        provider=FinalAnswerProvider(),
        agent_state_register=state_register,
    )
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("Interrupted")],
        metadata={"run_id": "run-stale"},
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-stale",
            request=request,
            status=AgentRunStatus.RUNNING,
            metadata={"run_id": "run-stale"},
        )
    )

    await AgentApplication(runtime).close()

    state = state_register.get_state("run-stale")
    assert state.status is AgentRunStatus.PAUSED
    assert state.trace[0].event_type is AgentTraceEventType.RUN_PAUSED


@pytest.mark.asyncio
async def test_agent_run_events_requires_chat_response() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("Hello")],
    )
    app = NoResponseAgentApplication(runtime)
    state = app._new_run_state(request)

    with pytest.raises(AgentStateError, match="did not produce a response"):
        _ = [event async for event in app._run_agent_events(request, state)]


@pytest.mark.asyncio
async def test_agent_lifecycle_allows_multiple_active_runs_before_notifying() -> None:
    lifecycle = _AgentRunLifecycle()

    async with lifecycle.active_run():
        async with lifecycle.active_run():
            assert lifecycle._active_count == 2
        assert lifecycle._active_count == 1

    assert lifecycle._active_count == 0


@pytest.mark.asyncio
async def test_agent_tool_error_can_write_memory_before_stopping() -> None:
    runtime = make_runtime(provider=RecoveringToolErrorProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    result = await app.run_agent(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Use missing tool")],
            recover_tool_errors=False,
            write_memory=True,
        )
    )

    memories = await runtime.memories.list_memories()

    assert result.stop_reason is AgentStopReason.TOOL_ERROR
    assert [event.event_type for event in result.trace] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_FAILED,
        AgentTraceEventType.MEMORY_WRITTEN,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert len(memories) == 1
    assert memories[0].metadata["stop_reason"] == AgentStopReason.TOOL_ERROR.value


@pytest.mark.asyncio
async def test_agent_followup_chat_must_produce_response() -> None:
    async def add(arguments: dict[str, object]) -> dict[str, object]:
        return {"result": 3}

    runtime = make_runtime(provider=NoFollowupResponseProvider())
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = NoFollowupResponseAgentApplication(runtime)

    with pytest.raises(AgentStateError, match="did not produce a response"):
        await app.run_agent(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("What is 1 + 2?")],
                tools=runtime.tools.list_tools(),
            )
        )


@pytest.mark.asyncio
async def test_agent_streaming_chat_requires_completed_response() -> None:
    runtime = make_runtime(provider=EmptyStreamingProvider())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = NoStreamingResponseAgentApplication(runtime)

    with pytest.raises(AgentStateError, match="did not produce a response"):
        _ = [
            event
            async for event in app.run_agent_stream(
                AgentRunRequest(
                    provider_id="provider-1",
                    context_id="ctx-1",
                    model_id="model-1",
                    messages=[make_message("Hello")],
                    metadata={"stream": True},
                )
            )
        ]


@pytest.mark.asyncio
async def test_agent_stream_uses_content_part_delta_and_tool_completion_metadata() -> None:
    provider = ContentPartAndToolStreamProvider()
    runtime = make_runtime(provider=provider)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentApplication(runtime)
    events = [
        event
        async for event in app.run_agent_stream(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Stream tool")],
                recover_tool_errors=False,
                metadata={"stream": True},
            )
        )
    ]

    assert [event.event_type for event in events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_DELTA,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_FAILED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert events[1].text_delta == "part"
    assert events[2].response is not None
    assert events[2].response.response_id == "resp-stream"
    assert events[2].response.model_id == "model-stream"
    assert events[2].response.finish_reason == "tool_calls"


def test_agent_private_helpers_cover_fallbacks() -> None:
    runtime = make_runtime(provider=FinalAnswerProvider())
    app = AgentApplication(runtime)
    state = AgentRunState(
        run_id="run-1",
        request=AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Hello")],
        ),
        status=AgentRunStatus.PAUSED,
        response=make_response("Stored"),
        stop_reason=AgentStopReason.FINISHED,
        pending_tool_calls=[ToolCall(tool_call_id="call-1", tool_call={})],
    )

    with pytest.raises(AgentStateError, match="paused"):
        app._state_to_result(state)

    state.status = AgentRunStatus.FINISHED
    state.response = None
    with pytest.raises(AgentStateError, match="did not produce"):
        app._state_to_result(state)

    state.response = make_response("Stored")
    state.stop_reason = None
    with pytest.raises(AgentStateError, match="did not stop"):
        app._state_to_result(state)

    assert app._tool_name(ToolCall(tool_call_id="call-1", tool_call={})) is None
    assert (
        app._event_tool_name(
            AgentTraceEvent(
                event_type=AgentTraceEventType.TOOL_COMPLETED,
                tool_call=ToolCall(tool_call_id="call-1", tool_call={}),
            )
        )
        == "unknown tool"
    )
    assert (
        app._trace_summary(
            AgentTraceEvent(
                event_type=AgentTraceEventType.TOOL_APPROVAL_DECIDED,
                tool_call=ToolCall(tool_call_id="call-1", tool_call={}),
            )
        )
        == "Tool approval unknown for unknown tool"
    )
    assert (
        app._trace_summary(
            AgentTraceEvent(event_type=AgentTraceEventType.MEMORY_WRITTEN)
        )
        == "Memory written"
    )
    assert (
        app._trace_summary(
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_PAUSED)
        )
        == "Agent run paused"
    )
    assert (
        app._trace_summary(
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STOPPED)
        )
        == "Agent run stopped"
    )
    assert (
        app._trace_summary(
            AgentTraceEvent.model_construct(
                event_type=UnknownTraceEventType(),
                metadata={},
            )
        )
        == "unknown_event"
    )
    assert (
        app._event_tool_name(AgentTraceEvent(event_type=AgentTraceEventType.TOOL_FAILED))
        == "unknown tool"
    )
    assert app._tool_safety_decision(ToolCall(tool_call_id="call-1", tool_call={})) is None
    missing_tool_decision = app._tool_safety_decision(
        ToolCall(tool_call_id="call-2", tool_call={"name": "missing"})
    )
    assert missing_tool_decision is not None
    assert missing_tool_decision.allowed is False
    assert missing_tool_decision.reason == (
        "Tool safety policy failed: The tool missing is not found"
    )
    assert missing_tool_decision.metadata["safety_policy_error"] is True
    assert app._chat_stream_text_delta(
        ChatStreamEvent(event_type=ChatStreamEventType.MESSAGE_DELTA)
    ) is None

    state.steps.append(AgentStep(step_type=AgentStepType.CHAT))
    assert app._run_transcript(state) == state.request.messages
    assert app._has_tool_runtime(state) is True

    trace_event = AgentTraceEvent(
        event_type=AgentTraceEventType.RUN_STARTED,
        summary="Already summarized",
    )
    assert app._add_trace(state, trace_event) is trace_event
    assert state.trace[-1].summary == "Already summarized"

    missing_register_app = AgentApplication(make_runtime(provider=FinalAnswerProvider()))
    with pytest.raises(AgentStateError, match="state register is not configured"):
        missing_register_app._get_agent_state("missing-run")
    with pytest.raises(AgentStateError, match="trace register is not configured"):
        missing_register_app._append_agent_trace_event(
            "missing-run",
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED),
        )


@pytest.mark.asyncio
async def test_agent_run_application_start_and_resume_stream_persist_state_and_trace() -> None:
    async def write(arguments: dict[str, object]) -> dict[str, object]:
        return {"written": True}

    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=SensitiveToolProvider(),
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write a file",
            parameters_schema={"type": "object"},
            permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.contexts.create(
        Context(
            context_id="ctx-1",
            messages=[
                make_message("Original question"),
                make_message("Bad answer", role=MessageRole.ASSISTANT),
            ],
        )
    )
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    start_events = [
        event
        async for event in app.start_stream(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                messages=[make_message("Write a file")],
                tools=runtime.tools.list_tools(),
                metadata={"run_id": "run-stream"},
                retry_from_message_index=1,
            )
        )
    ]
    resumed_events = [
        event
        async for event in app.resume_stream(
            "run-stream",
            [
                ToolApprovalDecision(
                    approval_id="tool-call-1:approval",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.APPROVED,
                )
            ],
        )
    ]

    context = await runtime.contexts.get("ctx-1")

    assert [event.event_type for event in start_events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
        AgentTraceEventType.RUN_PAUSED,
    ]
    assert [event.event_type for event in resumed_events] == [
        AgentTraceEventType.TOOL_APPROVAL_DECIDED,
        AgentTraceEventType.TOOL_COMPLETED,
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert state_register.get_state("run-stream").status is AgentRunStatus.FINISHED
    assert len(trace_register.list_events("run-stream")) == 8
    assert [message.status for message in context.messages[:2]] == [
        None,
        MessageStatus.REJECTED,
    ]


@pytest.mark.asyncio
async def test_agent_run_application_stream_persists_state_when_consumer_stops_early() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        provider=FinalAnswerProvider(),
        agent_state_register=state_register,
        agent_trace_register=trace_register,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    stream = app.start_stream(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Hello")],
            metadata={"run_id": "run-early"},
        )
    )
    iterator = cast(AsyncGenerator[AgentTraceEvent, None], stream.__aiter__())

    first_event = await anext(iterator)
    await iterator.aclose()

    assert first_event.event_type is AgentTraceEventType.RUN_STARTED
    assert state_register.get_state("run-early").trace == [first_event]
    assert trace_register.list_events("run-early") == [first_event]


@pytest.mark.asyncio
async def test_agent_run_manual_pause_resumes_from_persisted_chat_checkpoint() -> None:
    provider = FinalAnswerProvider()
    state_register = InMemoryAgentRunStateRegister()
    runtime = make_runtime(
        provider=provider,
        agent_state_register=state_register,
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    stream = app.start_stream(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("Hello")],
            metadata={"run_id": "run-checkpoint"},
        )
    )
    iterator = cast(AsyncGenerator[AgentTraceEvent, None], stream.__aiter__())

    assert (await anext(iterator)).event_type is AgentTraceEventType.RUN_STARTED
    assert (await anext(iterator)).event_type is AgentTraceEventType.CHAT_COMPLETED
    requested = await app.pause("run-checkpoint", reason="test pause")
    assert requested.status is AgentRunStatus.RUNNING
    checkpoint_events = [event async for event in iterator]
    resumed_events = [
        event
        async for event in app.resume_stream("run-checkpoint", [])
    ]

    assert [event.event_type for event in checkpoint_events] == [
        AgentTraceEventType.RUN_PAUSED,
    ]
    assert checkpoint_events[-1].metadata["checkpoint"] == "chat_completed"
    assert [event.event_type for event in resumed_events] == [
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert len(provider.requests) == 1
    assert state_register.get_state("run-checkpoint").status is AgentRunStatus.FINISHED


@pytest.mark.asyncio
async def test_agent_run_manual_pause_does_not_repeat_completed_tool() -> None:
    provider = ToolCallingProvider()
    executed_calls: list[dict[str, object]] = []

    async def add(arguments: dict[str, object]) -> dict[str, object]:
        executed_calls.append(arguments)
        return {"result": 3}

    runtime = make_runtime(
        provider=provider,
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    app = AgentRunApplication(runtime)
    stream = app.start_stream(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("What is 1 + 2?")],
            tools=runtime.tools.list_tools(),
            metadata={"run_id": "run-tool-checkpoint"},
        )
    )
    iterator = cast(AsyncGenerator[AgentTraceEvent, None], stream.__aiter__())

    assert (await anext(iterator)).event_type is AgentTraceEventType.RUN_STARTED
    assert (await anext(iterator)).event_type is AgentTraceEventType.CHAT_COMPLETED
    assert (await anext(iterator)).event_type is AgentTraceEventType.TOOL_COMPLETED
    await app.pause("run-tool-checkpoint")
    assert (await anext(iterator)).event_type is AgentTraceEventType.RUN_PAUSED
    resumed_events = [
        event
        async for event in app.resume_stream("run-tool-checkpoint", [])
    ]

    assert [event.event_type for event in resumed_events] == [
        AgentTraceEventType.CHAT_COMPLETED,
        AgentTraceEventType.RUN_STOPPED,
    ]
    assert executed_calls == [{"left": 1, "right": 2}]
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_agent_tool_execution_ledger_persists_result_and_idempotency_key() -> None:
    execution_register = InMemoryToolExecutionRegister()
    received_arguments: list[dict[str, object]] = []

    async def add(arguments: dict[str, object]) -> dict[str, object]:
        received_arguments.append(arguments)
        return {"result": 3}

    runtime = make_runtime(
        provider=ToolCallingProvider(),
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
        tool_execution_register=execution_register,
    )
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            parameters_schema={"type": "object"},
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            idempotency_key_parameter="request_id",
        ),
        add,
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())

    state = await AgentRunApplication(runtime).start(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[make_message("What is 1 + 2?")],
            tools=runtime.tools.list_tools(),
            metadata={"run_id": "run-ledger"},
        )
    )

    attempts = execution_register.list_attempts("run-ledger")
    assert state.status is AgentRunStatus.FINISHED
    assert len(attempts) == 1
    assert attempts[0].status is ToolExecutionStatus.COMPLETED
    assert attempts[0].result is not None
    assert attempts[0].idempotency_key == "run-ledger:tool-call-1"
    assert received_arguments == [
        {"left": 1, "right": 2, "request_id": "run-ledger:tool-call-1"}
    ]


@pytest.mark.asyncio
async def test_agent_replays_safe_unknown_tool_as_new_attempt() -> None:
    execution_register = InMemoryToolExecutionRegister()
    state_register = InMemoryAgentRunStateRegister()
    executed_calls: list[dict[str, object]] = []

    async def add(arguments: dict[str, object]) -> dict[str, object]:
        executed_calls.append(arguments)
        return {"result": 3}

    runtime = make_runtime(
        provider=ToolCallingProvider(),
        agent_state_register=state_register,
        agent_trace_register=InMemoryAgentTraceRegister(),
        tool_execution_register=execution_register,
    )
    tool = ToolDefinition(
        name="add",
        description="Add numbers",
        parameters_schema={"type": "object"},
        replay_policy=ToolReplayPolicy.SAFE,
    )
    runtime.tool_register.register(tool, add)
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())
    call = ToolCall(
        tool_call_id="tool-call-1",
        tool_call={
            "name": "add",
            "arguments": {"left": 1, "right": 2},
        },
    )
    response = ChatResponse(
        model_id="model-1",
        message=Content(role=MessageRole.ASSISTANT, tool_calls=[call]),
        finish_reason="tool_calls",
    )
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("What is 1 + 2?")],
        tools=[tool],
        metadata={"run_id": "run-replay"},
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-replay",
            request=request,
            status=AgentRunStatus.PAUSED,
            response=response,
            steps=[AgentStep(step_type=AgentStepType.CHAT, response=response)],
            remaining_tool_rounds=1,
            metadata={
                "agent_runtime": {
                    "manual_pause": True,
                    "recovery_eligible": True,
                }
            },
        )
    )
    execution_register.create_attempt(
        ToolExecutionAttempt(
            run_id="run-replay",
            tool_call_id="tool-call-1",
            attempt=1,
            tool_name="add",
            status=ToolExecutionStatus.UNKNOWN,
            replay_policy=ToolReplayPolicy.SAFE,
            idempotency_key="run-replay:tool-call-1",
            tool_call=call,
            created_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
    )

    resumed = await AgentRunApplication(runtime).resume("run-replay", [])

    attempts = execution_register.list_attempts("run-replay")
    assert resumed.status is AgentRunStatus.FINISHED
    assert [attempt.status for attempt in attempts] == [
        ToolExecutionStatus.UNKNOWN,
        ToolExecutionStatus.COMPLETED,
    ]
    assert executed_calls == [{"left": 1, "right": 2}]


@pytest.mark.asyncio
async def test_agent_operator_confirms_unknown_non_replayable_tool() -> None:
    execution_register = InMemoryToolExecutionRegister()
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    runtime = make_runtime(
        agent_state_register=state_register,
        agent_trace_register=trace_register,
        tool_execution_register=execution_register,
    )
    call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "write_file", "arguments": {"path": "a.txt"}},
    )
    state_register.save_state(
        AgentRunState(
            run_id="run-unknown",
            request=AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
            ),
            status=AgentRunStatus.PAUSED,
            metadata={
                "agent_runtime": {
                    "recovery_eligible": False,
                    "manual_pause": False,
                }
            },
        )
    )
    execution_register.create_attempt(
        ToolExecutionAttempt(
            run_id="run-unknown",
            tool_call_id="call-1",
            attempt=1,
            tool_name="write_file",
            status=ToolExecutionStatus.UNKNOWN,
            replay_policy=ToolReplayPolicy.NON_REPLAYABLE,
            idempotency_key="run-unknown:call-1",
            tool_call=call,
            created_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
    )
    app = AgentRunApplication(runtime)

    resolved = await app.resolve_tool_execution(
        "run-unknown",
        "call-1",
        1,
        ToolExecutionResolution.CONFIRM_COMPLETED,
        result={"written": True},
        reason="Verified externally",
    )

    execution = execution_register.get_attempt("run-unknown", "call-1", 1)
    assert execution.status is ToolExecutionStatus.COMPLETED
    assert execution.result is not None
    assert execution.result.tool_call_result == {"written": True}
    assert resolved.metadata[AgentRunMetadata.RUNTIME_KEY]["recovery_eligible"] is True
    assert trace_register.list_events("run-unknown")[-1].event_type is AgentTraceEventType.TOOL_EXECUTION_RESOLVED


def make_runtime(
    provider: ProviderInstanceProtocol | None = None,
    agent_state_register: AgentRunStateRegisterProtocol | None = None,
    agent_trace_register: AgentTraceRegisterProtocol | None = None,
    tool_execution_register: InMemoryToolExecutionRegister | None = None,
) -> RuntimeKernel:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return provider or ToolCallingProvider()

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
        agent_state_register=agent_state_register,
        agent_trace_register=agent_trace_register,
        tool_execution_register=tool_execution_register,
    )


def make_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="provider-1",
        name="Fake",
        type=ProviderType.OPENAI,
    )


def register_style_skill(runtime: RuntimeKernel) -> None:
    async def render_style(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[
                make_message(
                    f"Use {request.variables['tone']} style",
                    role=MessageRole.SYSTEM,
                )
            ],
        )

    runtime.skill_register.register(
        SkillDefinition(
            name="style",
            description="Render style instructions",
            capabilities=[SkillCapability.AGENT],
        ),
        render_style,
    )


def make_message(text: str, *, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def make_response(text: str) -> ChatResponse:
    return ChatResponse(
        model_id="model-1",
        message=make_message(text, role=MessageRole.ASSISTANT),
        finish_reason="stop",
    )


def message_text(message: Content) -> str:
    if not message.content or message.content[0].text is None:
        return ""
    return message.content[0].text


class ToolCallingProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def list_models(self) -> list[ProviderModelConfig]:
        return [
            ProviderModelConfig(
                model_id="model-1",
                capabilities=[ProviderModelCapability.CHAT],
            )
        ]

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(
            model_id=model_id,
            capabilities=[ProviderModelCapability.CHAT],
        )

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return capability is ProviderModelCapability.CHAT

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="tool-call-1",
                            tool_call={
                                "name": "add",
                                "arguments": {"left": 1, "right": 2},
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )

        return ChatResponse(
            model_id=request.model_id,
            message=make_message("The result is 3", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        return EmptyStream()

    async def close(self) -> None:
        pass


class SensitiveToolProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="tool-call-1",
                            tool_call={
                                "name": "write_file",
                                "arguments": {"path": "note.txt"},
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )

        return ChatResponse(
            model_id=request.model_id,
            message=make_message("Written", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )


class BlockedShellToolProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        tool_call_id="tool-call-1",
                        tool_call={
                            "name": "restricted_shell",
                            "arguments": {"command": ["uv", "publish"]},
                        },
                    )
                ],
            ),
            finish_reason="tool_calls",
        )


class SensitiveThenSafeToolProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="tool-call-1",
                            tool_call={
                                "name": "write_file",
                                "arguments": {"path": "note.txt"},
                            },
                        ),
                        ToolCall(
                            tool_call_id="tool-call-2",
                            tool_call={
                                "name": "add",
                                "arguments": {"left": 1, "right": 2},
                            },
                        ),
                    ],
                ),
                finish_reason="tool_calls",
            )

        return ChatResponse(
            model_id=request.model_id,
            message=make_message("Done", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )


class RecoveringToolErrorProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="tool-call-1",
                            tool_call={
                                "name": "missing",
                                "arguments": {},
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )

        return ChatResponse(
            model_id=request.model_id,
            message=make_message("Recovered from tool error", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )


class EndlessToolCallingProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        tool_call_id=f"tool-call-{len(self.requests)}",
                        tool_call={
                            "name": "missing",
                            "arguments": {},
                        },
                    )
                ],
            ),
            finish_reason="tool_calls",
        )


class FinalAnswerProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            model_id=request.model_id,
            message=make_message("Stored", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )


class StreamingAnswerProvider(FinalAnswerProvider):
    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.requests.append(request)
        return EventStream(
            [
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_DELTA,
                    text_delta="hel",
                ),
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_DELTA,
                    text_delta="lo",
                    finish_reason="stop",
                ),
                ChatStreamEvent(
                    event_type=ChatStreamEventType.USAGE,
                    usage=ChatUsage(
                        prompt_tokens=8,
                        cached_prompt_tokens=6,
                        metadata={"cache_phase": "read"},
                    ),
                ),
                ChatStreamEvent(
                    event_type=ChatStreamEventType.USAGE,
                    usage=ChatUsage(
                        completion_tokens=2,
                        metadata={"usage_phase": "complete"},
                    ),
                ),
                ChatStreamEvent(event_type=ChatStreamEventType.DONE),
            ]
        )


class EmptyStreamingProvider(FinalAnswerProvider):
    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.requests.append(request)
        return EventStream([])


class ContentPartAndToolStreamProvider(FinalAnswerProvider):
    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.requests.append(request)
        return EventStream(
            [
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_START,
                    response_id="resp-stream",
                    model_id="model-stream",
                ),
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_DELTA,
                    content_part=ContentPart(type=ContentPartType.TEXT, text="part"),
                ),
                ChatStreamEvent(
                    event_type=ChatStreamEventType.TOOL_CALL_COMPLETED,
                    tool_call=ToolCall(
                        tool_call_id="tool-call-stream",
                        tool_call={"tool_name": "missing", "arguments": {}},
                    ),
                    finish_reason="tool_calls",
                ),
            ]
        )


class NoFollowupResponseProvider(ToolCallingProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="tool-call-1",
                            tool_call={
                                "name": "add",
                                "arguments": {"left": 1, "right": 2},
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )

        raise AssertionError("Follow-up chat should be overridden by NoFollowupAgent")


class BlockingFinalAnswerProvider(FinalAnswerProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return ChatResponse(
            model_id=request.model_id,
            message=make_message("Stored", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )


class NoResponseAgentApplication(AgentApplication):
    async def _chat_events(
        self,
        provider_id: str,
        context_id: str,
        state: AgentRunState,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        if False:
            yield AgentTraceEvent(event_type=AgentTraceEventType.CHAT_COMPLETED)


class NoFollowupResponseAgentApplication(AgentApplication):
    def __init__(self, runtime: RuntimeKernel) -> None:
        super().__init__(runtime)
        self._chat_event_calls = 0

    async def _chat_events(
        self,
        provider_id: str,
        context_id: str,
        state: AgentRunState,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        self._chat_event_calls += 1
        if self._chat_event_calls == 1:
            async for event in super()._chat_events(
                provider_id,
                context_id,
                state,
                model_id=model_id,
                messages=messages,
                memory_query=memory_query,
                skills=skills,
                tools=tools,
                metadata=metadata,
            ):
                yield event
            return

        if False:
            yield AgentTraceEvent(event_type=AgentTraceEventType.CHAT_COMPLETED)


class NoStreamingResponseAgentApplication(AgentApplication):
    async def _stream_chat_events(
        self,
        stream: ChatStreamProtocol,
        fallback_model_id: str,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        if False:
            yield AgentTraceEvent(event_type=AgentTraceEventType.CHAT_COMPLETED)


class UnknownTraceEventType:
    value = "unknown_event"
