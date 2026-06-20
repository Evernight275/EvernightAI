from collections.abc import AsyncIterator

import pytest

from EvernightAI.application.agent import AgentApplication
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentStepType,
    AgentStopReason,
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
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.stream import SSEEvent
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition


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
        "tool_rounds_used": 1,
    }


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


@pytest.mark.asyncio
async def test_agent_reports_tool_rounds_exhausted() -> None:
    runtime = make_runtime(provider=EndlessToolCallingProvider())
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
    assert result.metadata["tool_rounds_used"] == 0
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
    assert memories[0].metadata["step_count"] == 3


def make_runtime(
    provider: ProviderInstanceProtocol | None = None,
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

    async def chat_stream(self, request: ChatRequest) -> SSEProtocol:
        return EmptyStream()

    async def close(self) -> None:
        pass


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


class EmptyStream:
    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        if False:
            yield SSEEvent(data="")
