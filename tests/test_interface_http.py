import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

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
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import SSEProtocol
from EvernightAI.core.schema.agent import AgentRunState, AgentTraceEvent
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
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
from EvernightAI.core.schema.skill import SkillCall, SkillDefinition, SkillResult
from EvernightAI.core.schema.stream import SSEEvent
from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.interface.http.app import create_http_app


def test_http_app_exposes_chat_context_flow() -> None:
    provider = FakeProvider()
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        provider_response = client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        context_response = client.post(
            "/contexts",
            json={
                "context_id": "ctx-1",
                "messages": [message_json("Stored", role="system")],
            },
        )
        chat_response = client.post(
            "/chat/context",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"request_id": "req-1"},
            },
        )
        stored_context_response = client.get("/contexts/ctx-1")

    assert provider_response.status_code == 201
    assert provider_response.json() == {
        "provider_id": "provider-1",
        "name": "Fake",
        "type": "openai",
        "is_enabled": True,
        "model": {},
        "metadata": {},
    }
    assert context_response.status_code == 201
    assert chat_response.status_code == 200
    assert chat_response.json()["message"]["content"][0]["text"] == "ok"
    assert stored_context_response.status_code == 200
    assert [
        message["content"][0]["text"]
        for message in stored_context_response.json()["messages"]
    ] == ["Stored", "Hello", "ok"]
    assert provider.last_request is not None
    assert provider.last_request.metadata["request_id"] == "req-1"
    assert provider.last_request.metadata["context_id"] == "ctx-1"


def test_http_app_exposes_memory_and_tool_routes() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        memory_response = client.post(
            "/memories",
            json={
                "memory_id": "mem-1",
                "content": "Use short answers",
                "kind": "preference",
                "scope": "user",
                "scope_id": "user-1",
                "priority": 3,
            },
        )
        memories_response = client.get("/memories")
        selected_response = client.post(
            "/memories/select",
            json={"scope": "user", "scope_id": "user-1", "limit": 1},
        )
        tools_response = client.get("/tools")

    assert memory_response.status_code == 201
    assert memory_response.json()["memory_id"] == "mem-1"
    assert memories_response.status_code == 200
    assert [memory["memory_id"] for memory in memories_response.json()] == ["mem-1"]
    assert selected_response.status_code == 200
    assert [memory["memory_id"] for memory in selected_response.json()["memories"]] == [
        "mem-1"
    ]
    assert tools_response.status_code == 200
    assert tools_response.json() == []


def test_http_app_exposes_skill_routes() -> None:
    async def summarize(call: SkillCall) -> SkillResult:
        return SkillResult(
            skill_call_id=call.skill_call_id,
            skill_name=call.skill_name,
            result={"summary": call.arguments["text"]},
            metadata={"source": "fake"},
        )

    runtime = make_runtime()
    runtime.skill_register.register(
        SkillDefinition(
            name="summarize",
            description="Summarize text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
        ),
        summarize,
    )
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        skills_response = client.get("/skills")
        execute_response = client.post(
            "/skills/summarize/execute",
            json={
                "skill_call_id": "skill-call-1",
                "arguments": {"text": "hello"},
            },
        )

    assert skills_response.status_code == 200
    assert [skill["name"] for skill in skills_response.json()] == ["summarize"]
    assert execute_response.status_code == 200
    assert execute_response.json() == {
        "skill_call_id": "skill-call-1",
        "skill_name": "summarize",
        "result": {"summary": "hello"},
        "metadata": {"source": "fake"},
    }


def test_http_app_exposes_provider_management_routes() -> None:
    interface = create_interface(make_runtime(provider=FakeProvider()))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        models_response = client.get("/providers/provider-1/models")
        model_response = client.get("/providers/provider-1/models/model-1")
        supports_response = client.get(
            "/providers/provider-1/supports",
            params={"capability": "chat"},
        )
        delete_response = client.delete("/providers/provider-1")
        missing_response = client.get("/providers/provider-1/models")

    assert models_response.status_code == 200
    assert [model["model_id"] for model in models_response.json()] == ["model-1"]
    assert model_response.status_code == 200
    assert model_response.json()["model_id"] == "model-1"
    assert supports_response.status_code == 200
    assert supports_response.json() is True
    assert delete_response.status_code == 204
    assert missing_response.status_code == 404


def test_http_app_exposes_chat_stream_route() -> None:
    provider = FakeProvider(
        stream_events=[
            SSEEvent(data='{"delta":"hello"}', event="message", id="evt-1"),
            SSEEvent(data="[DONE]", event="done"),
        ]
    )
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        stream_response = client.post(
            "/chat/stream",
            json={
                "provider_id": "provider-1",
                "request": {
                    "model_id": "model-1",
                    "messages": [message_json("Hello")],
                },
            },
        )

    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: message" in stream_response.text
    assert "id: evt-1" in stream_response.text
    assert 'data: {"delta":"hello"}' in stream_response.text
    assert "event: done" in stream_response.text
    assert "data: [DONE]" in stream_response.text
    assert provider.last_request is not None
    assert provider.last_request.model_id == "model-1"


def test_http_app_exposes_persisted_agent_run_routes() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    interface = create_interface(
        make_runtime(
            provider=FakeProvider(),
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        start_response = client.post(
            "/agent-runs",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"run_id": "run-1"},
            },
        )
        get_response = client.get("/agent-runs/run-1")
        list_response = client.get("/agent-runs")
        trace_response = client.get("/agent-runs/run-1/trace")

    assert start_response.status_code == 201
    assert start_response.json()["run_id"] == "run-1"
    assert start_response.json()["status"] == "finished"
    assert get_response.status_code == 200
    assert get_response.json()["run_id"] == "run-1"
    assert list_response.status_code == 200
    assert [state["run_id"] for state in list_response.json()] == ["run-1"]
    assert trace_response.status_code == 200
    assert [event["event_type"] for event in trace_response.json()] == [
        "run_started",
        "chat_completed",
        "run_stopped",
    ]


def test_http_app_streams_agent_trace_events() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    interface = create_interface(
        make_runtime(
            provider=FakeProvider(),
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        with client.stream(
            "POST",
            "/agent-runs/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"run_id": "run-1"},
            },
        ) as stream_response:
            body = stream_response.read().decode("utf-8")
            content_type = stream_response.headers["content-type"]
        state_response = client.get("/agent-runs/run-1")
        trace_response = client.get("/agent-runs/run-1/trace")

    events = parse_sse_events(body)

    assert content_type.startswith("text/event-stream")
    assert [event["event_type"] for event in events] == [
        "run_started",
        "chat_completed",
        "run_stopped",
    ]
    assert events[-1]["metadata"]["reason"] == "finished"
    assert state_response.status_code == 200
    assert state_response.json()["status"] == "finished"
    assert [event["event_type"] for event in trace_response.json()] == [
        "run_started",
        "chat_completed",
        "run_stopped",
    ]


def test_http_app_streams_agent_pause_for_tool_approval() -> None:
    tool_executed = False

    async def write_file(_arguments: dict[str, object]) -> dict[str, object]:
        nonlocal tool_executed
        tool_executed = True
        return {"written": True}

    runtime = make_runtime(
        provider=SensitiveToolProvider(),
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    tool = sensitive_tool_definition()
    runtime.tool_register.register(tool, write_file)
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        with client.stream(
            "POST",
            "/agent-runs/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Write a file")],
                "tools": [tool.model_dump(mode="json")],
                "pause_on_approval": True,
            },
        ) as stream_response:
            body = stream_response.read().decode("utf-8")

    events = parse_sse_events(body)

    assert [event["event_type"] for event in events] == [
        "run_started",
        "chat_completed",
        "tool_approval_requested",
        "run_paused",
    ]
    assert events[2]["approval_request"]["tool_name"] == "write_file"
    assert events[3]["metadata"]["reason"] == "tool_approval_required"
    assert tool_executed is False


def test_http_app_maps_domain_errors() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        missing_context_response = client.get("/contexts/missing")
        missing_agent_storage_response = client.get("/agent-runs/missing")

    assert missing_context_response.status_code == 404
    assert missing_context_response.json()["error"]["type"] == "ContextNotFoundError"
    assert missing_agent_storage_response.status_code == 409
    assert missing_agent_storage_response.json()["error"]["type"] == "AgentStateError"


def make_runtime(
    *,
    provider: ProviderInstanceProtocol | None = None,
    agent_state_register: AgentRunStateRegisterProtocol | None = None,
    agent_trace_register: AgentTraceRegisterProtocol | None = None,
) -> RuntimeKernel:
    async def build_provider(_config: ProviderConfig) -> ProviderInstanceProtocol:
        return provider or FakeProvider()

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
    )


def message_json(text: str, *, role: str = "user") -> dict[str, object]:
    return {
        "role": role,
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
    }


def make_message(text: str, *, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        data_lines = [
            line.removeprefix("data: ")
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))

    return events


def sensitive_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="write_file",
        description="Write a file",
        parameters_schema={"type": "object"},
        permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
        safety_level=ToolSafetyLevel.SENSITIVE,
    )


class FakeProvider(ProviderInstanceProtocol):
    def __init__(self, stream_events: list[SSEEvent] | None = None) -> None:
        self.last_request: ChatRequest | None = None
        self.stream_events = stream_events or []

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
        self.last_request = request
        return ChatResponse(
            model_id=request.model_id,
            message=make_message("ok", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )

    async def chat_stream(self, request: ChatRequest) -> SSEProtocol:
        self.last_request = request
        return EventStream(self.stream_events)

    async def close(self) -> None:
        pass


class SensitiveToolProvider(FakeProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
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


class InMemoryAgentRunStateRegister(AgentRunStateRegisterProtocol):
    def __init__(self) -> None:
        self.states: dict[str, AgentRunState] = {}

    def save_state(self, state: AgentRunState) -> None:
        self.states[state.run_id] = state

    def get_state(self, run_id: str) -> AgentRunState:
        try:
            return self.states[run_id]
        except KeyError as exc:
            raise AgentStateError(f"The agent run state {run_id} is not found") from exc

    def list_states(self) -> list[AgentRunState]:
        return list(self.states.values())

    def delete_state(self, run_id: str) -> None:
        self.states.pop(run_id, None)


class InMemoryAgentTraceRegister(AgentTraceRegisterProtocol):
    def __init__(self) -> None:
        self.events: dict[str, list[AgentTraceEvent]] = {}

    def append_event(self, run_id: str, event: AgentTraceEvent) -> None:
        self.events.setdefault(run_id, []).append(event)

    def list_events(self, run_id: str) -> list[AgentTraceEvent]:
        return list(self.events.get(run_id, []))

    def clear_events(self, run_id: str) -> None:
        self.events.pop(run_id, None)


class EventStream:
    def __init__(self, events: list[SSEEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        for event in self._events:
            yield event
