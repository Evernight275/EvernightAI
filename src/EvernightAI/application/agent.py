import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentStep,
    AgentStepType,
    AgentStopReason,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.content import (
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
)


class AgentApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult:
        state = _AgentRunState()
        async for _ in self._run_agent_events(request, state):
            pass

        return state.to_result(request)

    def run_agent_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol:
        return _AgentTraceStream(self._run_agent_events(request, _AgentRunState()))

    async def _run_agent_events(
        self,
        request: AgentRunRequest,
        state: "_AgentRunState",
    ) -> AsyncIterator[AgentTraceEvent]:
        start_step = AgentStep(
            step_type=AgentStepType.START,
            metadata={
                "provider_id": request.provider_id,
                "context_id": request.context_id,
                "model_id": request.model_id,
            },
        )
        state.steps.append(start_step)
        yield state.add_trace(
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_STARTED,
                step_type=AgentStepType.START,
                metadata={
                    "provider_id": request.provider_id,
                    "context_id": request.context_id,
                    "model_id": request.model_id,
                },
            )
        )

        response = await self._chat(
            request.provider_id,
            request.context_id,
            model_id=request.model_id,
            messages=request.messages,
            memory_query=request.memory_query,
            tools=request.tools,
            metadata=request.metadata,
        )
        state.response = response
        state.steps.append(
            AgentStep(
                step_type=AgentStepType.CHAT,
                response=response,
                message=response.message,
            )
        )
        yield state.add_trace(
            AgentTraceEvent(
                event_type=AgentTraceEventType.CHAT_COMPLETED,
                step_type=AgentStepType.CHAT,
                response=response,
                message=response.message,
            )
        )
        for message in request.messages:
            await self._runtime.contexts.append(request.context_id, message)
        await self._runtime.contexts.append(request.context_id, response.message)

        remaining_rounds = request.max_tool_rounds
        state.stop_reason = AgentStopReason.FINISHED
        approvals = self._tool_approvals_by_call_id(request.tool_approvals)
        while response.message.tool_calls and remaining_rounds > 0:
            for call in response.message.tool_calls:
                call = self._apply_tool_approval(call, approvals.get(call.tool_call_id))
                for event in self._trace_tool_approval(call, state):
                    yield event
                try:
                    tool_result = await self._runtime.tools.execute(call)
                    tool_message = self._tool_result_to_message(tool_result)
                    state.steps.append(
                        AgentStep(
                            step_type=AgentStepType.TOOL,
                            message=tool_message,
                            tool_call=call,
                            tool_result=tool_result,
                        )
                    )
                    yield state.add_trace(
                        AgentTraceEvent(
                            event_type=AgentTraceEventType.TOOL_COMPLETED,
                            step_type=AgentStepType.TOOL,
                            message=tool_message,
                            tool_call=call,
                            tool_result=tool_result,
                        )
                    )
                except Exception as exc:
                    tool_message = self._tool_error_to_message(call, exc)
                    state.steps.append(
                        AgentStep(
                            step_type=AgentStepType.TOOL_ERROR,
                            message=tool_message,
                            tool_call=call,
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                        )
                    )
                    yield state.add_trace(
                        AgentTraceEvent(
                            event_type=AgentTraceEventType.TOOL_FAILED,
                            step_type=AgentStepType.TOOL_ERROR,
                            message=tool_message,
                            tool_call=call,
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                        )
                    )
                    if not request.recover_tool_errors:
                        await self._runtime.contexts.append(
                            request.context_id,
                            tool_message,
                        )
                        state.stop_reason = AgentStopReason.TOOL_ERROR
                        state.steps.append(
                            AgentStep(
                                step_type=AgentStepType.STOP,
                                metadata={"reason": state.stop_reason.value},
                            )
                        )
                        state.tool_rounds_used = (
                            request.max_tool_rounds - remaining_rounds
                        )
                        async for event in self._write_memory_events(request, state):
                            yield event
                        yield state.add_trace(self._run_stopped_event(state.stop_reason))
                        return

                await self._runtime.contexts.append(request.context_id, tool_message)

            remaining_rounds -= 1
            if remaining_rounds < 0:
                break

            response = await self._chat(
                request.provider_id,
                request.context_id,
                model_id=request.model_id,
                messages=[],
                tools=request.tools,
                metadata=request.metadata,
            )
            state.response = response
            state.steps.append(
                AgentStep(
                    step_type=AgentStepType.CHAT,
                    response=response,
                    message=response.message,
                )
            )
            yield state.add_trace(
                AgentTraceEvent(
                    event_type=AgentTraceEventType.CHAT_COMPLETED,
                    step_type=AgentStepType.CHAT,
                    response=response,
                    message=response.message,
                )
            )
            await self._runtime.contexts.append(request.context_id, response.message)

        if response.message.tool_calls:
            state.stop_reason = AgentStopReason.TOOL_ROUNDS_EXHAUSTED

        state.steps.append(
            AgentStep(
                step_type=AgentStepType.STOP,
                metadata={"reason": state.stop_reason.value},
            )
        )
        state.tool_rounds_used = request.max_tool_rounds - remaining_rounds
        async for event in self._write_memory_events(request, state):
            yield event
        yield state.add_trace(self._run_stopped_event(state.stop_reason))

    async def run(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        max_tool_rounds: int = 1,
    ) -> ChatResponse:
        result = await self.run_agent(
            AgentRunRequest(
                provider_id=provider_id,
                context_id=context_id,
                model_id=model_id,
                messages=messages,
                memory_query=memory_query,
                tools=tools,
                max_tool_rounds=max_tool_rounds,
                recover_tool_errors=True,
                metadata=dict(metadata or {}),
            )
        )
        return result.response

    async def _chat(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatResponse:
        context = await self._runtime.contexts.get(context_id)
        memory_selection = (
            self._runtime.memory_strategy.select(
                await self._runtime.memories.list_memories(),
                memory_query,
            )
            if memory_query is not None
            else None
        )
        request = self._runtime.context_strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=memory_selection,
            tools=tools,
            metadata=metadata,
        )
        return await self._runtime.providers.chat(provider_id, request)

    def _tool_result_to_message(self, result: ToolCallResult) -> Content:
        return Content(
            role=MessageRole.TOOL,
            tool_call_id=result.tool_call_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=result.model_dump_json(),
                )
            ],
        )

    def _tool_error_to_message(self, call: ToolCall, exc: Exception) -> Content:
        payload = {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }
        return Content(
            role=MessageRole.TOOL,
            tool_call_id=call.tool_call_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=json.dumps(payload, ensure_ascii=False),
                )
            ],
            metadata={
                "error": True,
                "error_type": exc.__class__.__name__,
            },
        )

    def _tool_approvals_by_call_id(
        self,
        approvals: list[ToolApprovalDecision],
    ) -> dict[str, ToolApprovalDecision]:
        return {approval.tool_call_id: approval for approval in approvals}

    def _apply_tool_approval(
        self,
        call: ToolCall,
        approval: ToolApprovalDecision | None,
    ) -> ToolCall:
        if approval is None:
            return call

        return call.model_copy(update={"approval": approval})

    def _trace_tool_approval(
        self,
        call: ToolCall,
        state: "_AgentRunState",
    ) -> list[AgentTraceEvent]:
        tool_name = self._tool_name(call)
        if tool_name is None:
            return []

        try:
            tool = self._runtime.tool_register.get(tool_name)
            decision = self._runtime.tool_safety_policy.authorize(tool, call)
        except Exception:
            return []

        if decision.approval_request is None and not decision.requires_approval:
            return []

        events = [
            state.add_trace(
                AgentTraceEvent(
                    event_type=AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
                    tool_call=call,
                    approval_request=decision.approval_request,
                    metadata={
                        "allowed": decision.allowed,
                        "requires_approval": decision.requires_approval,
                        "reason": decision.reason,
                    },
                )
            )
        ]
        if call.approval is not None:
            events.append(
                state.add_trace(
                    AgentTraceEvent(
                        event_type=AgentTraceEventType.TOOL_APPROVAL_DECIDED,
                        tool_call=call,
                        approval_request=decision.approval_request,
                        approval_decision=call.approval,
                        metadata={"allowed": decision.allowed},
                    )
                )
            )

        return events

    def _tool_name(self, call: ToolCall) -> str | None:
        tool_name = call.tool_call.get("tool_name") or call.tool_call.get("name")
        if isinstance(tool_name, str) and tool_name:
            return tool_name

        return None

    def _run_stopped_event(self, stop_reason: AgentStopReason) -> AgentTraceEvent:
        return AgentTraceEvent(
            event_type=AgentTraceEventType.RUN_STOPPED,
            step_type=AgentStepType.STOP,
            metadata={"reason": stop_reason.value},
        )

    async def _write_memory_events(
        self,
        request: AgentRunRequest,
        state: "_AgentRunState",
    ) -> AsyncIterator[AgentTraceEvent]:
        result = state.to_result(request)
        memories = self._runtime.memory_write_strategy.create_memories(
            request,
            result,
        )
        for memory in memories:
            await self._runtime.memories.create(memory)
            memory_step = AgentStep(
                step_type=AgentStepType.MEMORY_WRITE,
                metadata={"memory_id": memory.memory_id},
            )
            state.steps.append(memory_step)
            yield state.add_trace(
                AgentTraceEvent(
                    event_type=AgentTraceEventType.MEMORY_WRITTEN,
                    step_type=AgentStepType.MEMORY_WRITE,
                    metadata={"memory_id": memory.memory_id},
                )
            )

@dataclass
class _AgentRunState:
    steps: list[AgentStep] = field(default_factory=list)
    trace: list[AgentTraceEvent] = field(default_factory=list)
    response: ChatResponse | None = None
    stop_reason: AgentStopReason = AgentStopReason.FINISHED
    tool_rounds_used: int = 0

    def add_trace(self, event: AgentTraceEvent) -> AgentTraceEvent:
        self.trace.append(event)
        return event

    def to_result(self, request: AgentRunRequest) -> AgentRunResult:
        if self.response is None:
            raise RuntimeError("Agent run did not produce a response")

        return AgentRunResult(
            response=self.response,
            stop_reason=self.stop_reason,
            steps=list(self.steps),
            trace=list(self.trace),
            metadata={
                **request.metadata,
                "tool_rounds_used": self.tool_rounds_used,
            },
        )


class _AgentTraceStream:
    def __init__(self, events: AsyncIterator[AgentTraceEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[AgentTraceEvent]:
        return self._events
