from collections.abc import Callable
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import (
    create_runtime_with_agent_storage,
    create_sqlite_runtime,
)
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.error.skill import (
    SkillConflictError,
    SkillDisabledError,
    SkillNotFoundError,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunStatus,
    AgentStepType,
    AgentTraceEventType,
    ToolExecutionStatus,
)
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatSkill,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
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
    SkillTemplateConfig,
    SkillTemplateUpdate,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolCall,
    ToolDefinition,
    ToolSafetyLevel,
)
from EvernightAI.interface.http.app import create_http_app
from tests.fakes.agent import (
    InMemoryAgentRunStateRegister,
    InMemoryAgentTraceRegister,
    InMemoryToolExecutionRegister,
)
from tests.fakes.streams import EventStream


def message(text: str, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role, content=[ContentPart(type=ContentPartType.TEXT, text=text)]
    )


class RecordingProvider(ProviderInstanceProtocol):
    def __init__(self, tools: list[str] | None = None) -> None:
        self.requests: list[ChatRequest] = []
        self.tools = tools if tools is not None else ["add", "write_file"]

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request.model_copy(deep=True))
        calls = [
            ToolCall(tool_call_id=name, tool_call={"name": name, "arguments": {}})
            for name in self.tools
        ]
        return ChatResponse(
            model_id=request.model_id,
            message=Content(role=MessageRole.ASSISTANT, tool_calls=calls)
            if len(self.requests) == 1
            else message("Done", MessageRole.ASSISTANT),
            finish_reason="tool_calls" if len(self.requests) == 1 else "stop",
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        response = await self.chat(request)
        events = [
            ChatStreamEvent(
                event_type=ChatStreamEventType.TOOL_CALL_COMPLETED, tool_call=call
            )
            for call in response.message.tool_calls or []
        ]
        events.append(
            ChatStreamEvent(
                event_type=ChatStreamEventType.MESSAGE_COMPLETED,
                finish_reason=response.finish_reason,
            )
        )
        return EventStream(events)

    async def list_models(self) -> list[ProviderModelConfig]:
        return []

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(model_id=model_id)

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return True

    async def close(self) -> None:
        pass


def create_test_runtime(database: Path | None) -> RuntimeKernel:
    if database is not None:
        return create_sqlite_runtime(database)
    return create_runtime_with_agent_storage(
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
        tool_execution_register=InMemoryToolExecutionRegister(),
    )


def template() -> SkillTemplateConfig:
    return SkillTemplateConfig(
        name="style",
        description="Style",
        prompt="Use $tone",
        capabilities=[SkillCapability.AGENT],
    )


def mutate(runtime: RuntimeKernel, change: str) -> None:
    if change == "update":
        runtime.skills.update_template(
            "style", SkillTemplateUpdate(prompt="Changed $tone")
        )
    elif change == "disable":
        runtime.skills.update_template("style", SkillTemplateUpdate(is_enabled=False))
    else:
        runtime.skills.delete_template("style")
        if change == "recreate":
            runtime.skills.create_template(template())


def mutation_error(change: str) -> type[Exception]:
    return {"disable": SkillDisabledError, "delete": SkillNotFoundError}.get(
        change, SkillConflictError
    )


async def assemble(
    runtime: RuntimeKernel,
    provider: RecordingProvider,
    executed: list[str],
    on_add: Callable[[], None] | None = None,
) -> AgentRunApplication:
    async def build(_config: ProviderConfig) -> ProviderInstanceProtocol:
        return provider

    async def add(_arguments: dict[str, object]) -> dict[str, object]:
        executed.append("add")
        if on_add is not None:
            on_add()
        return {"result": 3}

    async def write(_arguments: dict[str, object]) -> dict[str, object]:
        executed.append("write_file")
        return {"written": True}

    runtime.provider_factory.register(ProviderType.OPENAI, build)
    runtime.tool_register.register(ToolDefinition(name="add", description="Add"), add)
    runtime.tool_register.register(
        ToolDefinition(
            name="write_file",
            description="Write",
            safety_level=ToolSafetyLevel.SENSITIVE,
        ),
        write,
    )
    await runtime.initialize()
    await runtime.providers.create(
        ProviderConfig(provider_id="fake", name="Fake", type=ProviderType.OPENAI)
    )
    return AgentRunApplication(runtime)


def request(runtime: RuntimeKernel, streaming: bool = False) -> AgentRunRequest:
    return AgentRunRequest(
        provider_id="fake",
        context_id="ctx",
        model_id="model",
        messages=[message("Add and write")],
        skills=[ChatSkill(skill_name="style", variables={"tone": "calm"})],
        tools=runtime.tools.list_tools(),
        metadata={"stream": streaming},
    )


def approvals() -> list[ToolApprovalDecision]:
    return [
        ToolApprovalDecision(
            approval_id="approval",
            tool_call_id="write_file",
            status=ToolApprovalStatus.APPROVED,
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["update", "disable", "delete", "recreate"])
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_changed_skill_blocks_resume_before_approval_or_tool_execution(
    change: str,
    restart: bool,
    streaming: bool,
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3" if restart else None
    runtime = create_test_runtime(database)
    provider = RecordingProvider()
    executed: list[str] = []
    app = await assemble(runtime, provider, executed)
    runtime.skills.create_template(template())
    await runtime.contexts.create(
        Context(context_id="ctx", messages=[message("History")])
    )
    state = await app.start(request(runtime, streaming))
    assert state.status is AgentRunStatus.PAUSED
    assert executed == ["add"]
    assert state.skill_revisions == {
        "style": runtime.skills.get_skill("style").revision
    }
    mutate(runtime, change)
    if restart:
        await app.close()
        await runtime.close()
        runtime = create_test_runtime(database)
        app = await assemble(runtime, provider, executed)
    before = app.get_state(state.run_id)
    before_trace = app.list_trace(state.run_id)
    for _ in range(2):
        with pytest.raises(mutation_error(change)):
            if streaming:
                async for _event in app.resume_stream(state.run_id, approvals()):
                    pass
            else:
                await app.resume(state.run_id, approvals())
    assert app.get_state(state.run_id) == before
    assert app.list_trace(state.run_id) == before_trace
    assert before.request.tool_approvals == []
    assert executed == ["add"]
    assert len(provider.requests) == 1
    attempts = app.list_tool_executions(state.run_id)
    assert len(attempts) == 1 and attempts[0].status is ToolExecutionStatus.COMPLETED
    assert (await runtime.contexts.get("ctx")).messages == [message("History")]
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_unchanged_skill_resumes_without_repeating_completed_tools(
    restart: bool,
    streaming: bool,
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3" if restart else None
    runtime = create_test_runtime(database)
    provider = RecordingProvider()
    executed: list[str] = []
    app = await assemble(runtime, provider, executed)
    revision = runtime.skills.create_template(template()).revision
    await runtime.contexts.create(Context(context_id="ctx"))
    state = await app.start(request(runtime, streaming))
    runtime.skills.update_template("style", SkillTemplateUpdate(prompt="Use $tone"))
    if restart:
        await app.close()
        await runtime.close()
        runtime = create_test_runtime(database)
        app = await assemble(runtime, provider, executed)
    if streaming:
        async for _event in app.resume_stream(state.run_id, approvals()):
            pass
        resumed = app.get_state(state.run_id)
    else:
        resumed = await app.resume(state.run_id, approvals())
    assert resumed.status is AgentRunStatus.FINISHED
    assert resumed.skill_revisions == {"style": revision}
    assert executed == ["add", "write_file"]
    assert len(provider.requests) == 2
    assert all(
        item.messages[0] == message("Use calm", MessageRole.SYSTEM)
        for item in provider.requests
    )
    assert [item.role for item in (await runtime.contexts.get("ctx")).messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]
    attempts = app.list_tool_executions(state.run_id)
    assert len(attempts) == 2 and all(
        item.status is ToolExecutionStatus.COMPLETED for item in attempts
    )
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["update", "disable", "delete", "recreate"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("restart", [False, True])
async def test_tool_mutation_blocks_followup_model_and_preserves_completed_execution(
    change: str,
    streaming: bool,
    restart: bool,
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3" if restart else None
    runtime = create_test_runtime(database)
    provider = RecordingProvider(["add"])
    executed: list[str] = []
    app = await assemble(runtime, provider, executed, lambda: mutate(runtime, change))
    runtime.skills.create_template(template())
    await runtime.contexts.create(Context(context_id="ctx"))
    with pytest.raises(mutation_error(change)):
        await app.start(request(runtime, streaming))
    (state,) = app.list_states()
    if restart:
        await app.close()
        await runtime.close()
        runtime = create_test_runtime(database)
        app = await assemble(runtime, provider, executed)
        state = app.get_state(state.run_id)
    assert state.status is AgentRunStatus.FAILED
    assert state.trace[-1].error_type == mutation_error(change).__name__
    expected_detail = {
        "reason": {"disable": "disabled", "delete": "deleted"}.get(
            change, "revision_changed"
        ),
        "skill_names": ["style"],
    }
    assert state.trace[-1].payload is not None
    assert json.loads(state.trace[-1].payload["error_detail"]) == expected_detail
    assert (
        json.loads(state.metadata["agent_runtime"]["failure_detail"]) == expected_detail
    )
    assert any(step.step_type is AgentStepType.TOOL for step in state.steps)
    assert executed == ["add"] and len(provider.requests) == 1
    assert (
        app.list_tool_executions(state.run_id)[0].status
        is ToolExecutionStatus.COMPLETED
    )
    assert (await runtime.contexts.get("ctx")).messages == []
    for _ in range(2):
        with pytest.raises(AgentStateError, match="not paused"):
            await app.resume(state.run_id, [])
    assert executed == ["add"] and len(provider.requests) == 1
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_skill_change_during_request_composition_blocks_provider_dispatch(
    streaming: bool,
) -> None:
    runtime = create_test_runtime(None)
    provider = RecordingProvider()
    app = await assemble(runtime, provider, [])
    runtime.skills.create_template(template())

    async def renderer(render_request: SkillRenderRequest) -> RenderedSkill:
        mutate(runtime, "update")
        return RenderedSkill(
            skill_name=render_request.skill_name, render_id=render_request.render_id
        )

    runtime.skill_register.register(
        SkillDefinition(
            name="gate",
            description="Mutation during composition",
            capabilities=[SkillCapability.AGENT],
        ),
        renderer,
    )
    await runtime.contexts.create(Context(context_id="ctx"))
    run_request = request(runtime, streaming)
    assert run_request.skills is not None
    run_request.skills.append(ChatSkill(skill_name="gate"))
    with pytest.raises(SkillConflictError):
        await app.start(run_request)
    assert provider.requests == []
    assert app.list_states()[0].status is AgentRunStatus.FAILED
    assert (await runtime.contexts.get("ctx")).messages == []
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
async def test_skill_change_after_tool_started_event_blocks_execution() -> None:
    runtime = create_test_runtime(None)
    provider = RecordingProvider(["add"])
    executed: list[str] = []
    app = await assemble(runtime, provider, executed)
    runtime.skills.create_template(template())
    await runtime.contexts.create(Context(context_id="ctx"))
    with pytest.raises(SkillConflictError):
        async for event in app.start_stream(request(runtime)):
            if event.event_type is AgentTraceEventType.TOOL_STARTED:
                mutate(runtime, "update")
    (state,) = app.list_states()
    assert state.status is AgentRunStatus.FAILED
    assert executed == [] and len(provider.requests) == 1
    assert app.list_tool_executions(state.run_id) == []
    assert (await runtime.contexts.get("ctx")).messages == []
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True])
async def test_manual_checkpoint_pause_keeps_versions_across_restart(
    restart: bool, tmp_path: Path
) -> None:
    database = tmp_path / "runtime.sqlite3" if restart else None
    runtime = create_test_runtime(database)
    provider = RecordingProvider(["add"])
    executed: list[str] = []
    app = await assemble(runtime, provider, executed)
    runtime.skills.create_template(template())
    await runtime.contexts.create(Context(context_id="ctx"))

    async def pause_during_tool(_arguments: dict[str, object]) -> dict[str, object]:
        executed.append("add")
        (running,) = app.list_states()
        await app.pause(running.run_id)
        return {"result": 3}

    runtime.tool_register.register(
        ToolDefinition(name="add", description="Add"), pause_during_tool
    )
    state = await app.start(request(runtime))
    assert state.status is AgentRunStatus.PAUSED
    mutate(runtime, "update")
    if restart:
        await app.close()
        await runtime.close()
        runtime = create_test_runtime(database)
        app = await assemble(runtime, provider, executed)
    with pytest.raises(SkillConflictError):
        await app.resume(state.run_id, [])
    assert app.get_state(state.run_id).skill_revisions == state.skill_revisions
    assert app.get_state(state.run_id).status is AgentRunStatus.PAUSED
    assert executed == ["add"] and len(provider.requests) == 1
    assert (
        app.list_tool_executions(state.run_id)[0].status
        is ToolExecutionStatus.COMPLETED
    )
    assert (await runtime.contexts.get("ctx")).messages == []
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
async def test_legacy_skill_run_cannot_silently_adopt_current_version() -> None:
    runtime = create_test_runtime(None)
    provider = RecordingProvider()
    executed: list[str] = []
    app = await assemble(runtime, provider, executed)
    runtime.skills.create_template(template())
    await runtime.contexts.create(Context(context_id="ctx"))
    state = await app.start(request(runtime))
    state.skill_revisions = None
    assert runtime.agent_state_register is not None
    runtime.agent_state_register.save_state(state)
    with pytest.raises(SkillConflictError, match="unavailable"):
        await app.resume(state.run_id, approvals())
    assert app.get_state(state.run_id).status is AgentRunStatus.PAUSED
    assert executed == ["add"] and len(provider.requests) == 1
    await app.close()
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["update", "disable", "delete", "legacy"])
async def test_http_skill_conflict_keeps_paused_run_inspectable(change: str) -> None:
    runtime = create_test_runtime(None)
    provider = RecordingProvider()
    executed: list[str] = []
    app = await assemble(runtime, provider, executed)
    runtime.skills.create_template(template())
    await runtime.contexts.create(Context(context_id="ctx"))
    state = await app.start(request(runtime))
    with TestClient(create_http_app(create_interface(runtime))) as client:
        if change == "legacy":
            state.skill_revisions = None
            assert runtime.agent_state_register is not None
            runtime.agent_state_register.save_state(state)
        else:
            mutate(runtime, change)
        error_type = mutation_error(change).__name__
        expected_detail = {
            "reason": {
                "update": "revision_changed",
                "disable": "disabled",
                "delete": "deleted",
                "legacy": "revision_unavailable",
            }[change],
            "skill_names": ["style"],
        }
        response = client.post(
            f"/agent-runs/{state.run_id}/resume",
            json={
                "approvals": [
                    approval.model_dump(mode="json") for approval in approvals()
                ],
            },
        )
        assert response.status_code == (404 if change == "delete" else 409)
        assert response.json()["error"]["type"] == error_type
        assert json.loads(response.json()["error"]["detail"]) == expected_detail
        streamed = client.post(
            f"/agent-runs/{state.run_id}/resume/stream",
            json={
                "approvals": [
                    approval.model_dump(mode="json") for approval in approvals()
                ],
            },
        )
        assert streamed.status_code == 200
        (error_event,) = [
            json.loads(line[6:])["error"]
            for line in streamed.text.splitlines()
            if line.startswith("data: ")
        ]
        assert error_event["type"] == error_type
        assert json.loads(error_event["detail"]) == expected_detail
        stored = client.get(f"/agent-runs/{state.run_id}").json()
        assert stored["status"] == "paused"
        assert stored.get("skill_revisions") == state.skill_revisions
        assert stored["pending_tool_calls"]
        assert stored["request"]["tool_approvals"] == []
    assert executed == ["add"] and len(provider.requests) == 1
    await app.close()
