from collections.abc import AsyncIterator

import pytest

from EvernightAI.application.session import SessionApplication
from EvernightAI.bootstrap.runtime import create_runtime
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
from EvernightAI.core.domain.session import SessionManager, SessionRegister
from EvernightAI.core.domain.tool import BasicToolSafetyPolicy, ToolManager, ToolRegister
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
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
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType


@pytest.mark.asyncio
async def test_session_application_creates_context_for_session() -> None:
    runtime = create_runtime()
    app = SessionApplication(runtime)

    session = await app.create_session(
        Session(
            session_id="session-1",
            title="First chat",
            context_id="ctx-1",
        )
    )

    context = await runtime.contexts.get("ctx-1")

    assert session.context_id == "ctx-1"
    assert context.context_id == "ctx-1"
    assert context.messages == []
    assert context.metadata == {"session_id": "session-1"}


@pytest.mark.asyncio
async def test_session_application_reuses_existing_context() -> None:
    runtime = create_runtime()
    app = SessionApplication(runtime)
    existing_context = Context(
        context_id="ctx-1",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="Stored")]
            )
        ],
        metadata={"source": "existing"},
    )
    await runtime.contexts.create(existing_context)

    await app.create_session(
        Session(
            session_id="session-1",
            title="First chat",
            context_id="ctx-1",
        )
    )

    context = await runtime.contexts.get("ctx-1")

    assert context == existing_context


@pytest.mark.asyncio
async def test_session_application_creates_context_when_replacing_session() -> None:
    runtime = create_runtime()
    app = SessionApplication(runtime)
    await app.create_session(
        Session(
            session_id="session-1",
            title="First chat",
            context_id="ctx-1",
        )
    )

    replaced = await app.replace_session(
        Session(
            session_id="session-1",
            title="Moved chat",
            context_id="ctx-2",
        )
    )

    context = await runtime.contexts.get("ctx-2")

    assert replaced.context_id == "ctx-2"
    assert context.metadata == {"session_id": "session-1"}


@pytest.mark.asyncio
async def test_session_chat_request_provider_and_model_override_session_defaults() -> None:
    provider = RecordingProvider()
    runtime = make_runtime(provider)
    app = SessionApplication(runtime)
    await runtime.providers.create(make_config("request-provider"))
    await app.create_session(
        Session(
            session_id="session-1",
            context_id="ctx-1",
            provider_id="session-provider",
            model_id="session-model",
        )
    )

    await app.chat_with_session(
        "session-1",
        SessionChatRequest(
            provider_id="request-provider",
            model_id="request-model",
            messages=[make_message("Use request provider")],
            metadata={"reasoning_effort": "high"},
        ),
    )

    assert provider.requests[-1].model_id == "request-model"
    assert provider.requests[-1].metadata["context_id"] == "ctx-1"
    assert provider.requests[-1].metadata["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_session_agent_request_provider_and_model_override_session_defaults() -> None:
    provider = RecordingProvider()
    runtime = make_runtime(provider)
    app = SessionApplication(runtime)
    await runtime.providers.create(make_config("request-provider"))
    await app.create_session(
        Session(
            session_id="session-1",
            context_id="ctx-1",
            provider_id="session-provider",
            model_id="session-model",
        )
    )

    state = await app.start_agent_run_for_session(
        "session-1",
        SessionAgentRunRequest(
            provider_id="request-provider",
            model_id="request-model",
            messages=[make_message("Use request provider")],
            max_tool_rounds=0,
            metadata={"reasoning_effort": "high"},
        ),
    )

    assert state.request.provider_id == "request-provider"
    assert state.request.model_id == "request-model"
    assert state.request.metadata["reasoning_effort"] == "high"
    assert provider.requests[-1].model_id == "request-model"
    assert provider.requests[-1].metadata["reasoning_effort"] == "high"


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def make_config(provider_id: str) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        name=provider_id,
        type=ProviderType.OPENAI,
    )


def make_runtime(provider: ProviderInstanceProtocol) -> RuntimeKernel:
    async def build_provider(_config: ProviderConfig) -> ProviderInstanceProtocol:
        return provider

    provider_factory = ProviderFactory()
    provider_factory.register(ProviderType.OPENAI, build_provider)
    tool_register = ToolRegister()
    tool_safety_policy = BasicToolSafetyPolicy()
    context_register = ContextRegister()
    context_organizer = ContextOrganizer()
    memory_register = MemoryRegister()
    session_register = SessionRegister()

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
        session_register=session_register,
        sessions=SessionManager(session_register),
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )


class RecordingProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def list_models(self) -> list[ProviderModelConfig]:
        return [ProviderModelConfig(model_id="request-model")]

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(model_id=model_id)

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return capability is ProviderModelCapability.CHAT

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="ok")],
            ),
            finish_reason="stop",
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.requests.append(request)
        return EmptyStream()

    async def close(self) -> None:
        pass


class EmptyStream:
    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        if False:
            yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)


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
