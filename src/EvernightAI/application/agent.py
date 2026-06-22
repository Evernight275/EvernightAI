import json
from collections.abc import AsyncIterator
from uuid import uuid4

from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
)
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
    AgentStep,
    AgentStepType,
    AgentStopReason,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.content import (
    ChatResponse,
    ChatSkill,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.skill import SkillCapability
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    ToolSafetyDecision,
)
from EvernightAI.application.skill_prompt import compose_skill_prompted_chat_request


class AgentRunMetadata:
    RUN_ID_KEY = "run_id"
    RUNTIME_KEY = "agent_runtime"
    PENDING_APPROVAL_COUNT_KEY = "pending_approval_count"
    TOOL_ROUNDS_USED_KEY = "tool_rounds_used"

    @classmethod
    def run_id(cls, metadata: dict[str, object]) -> str | None:
        run_id = metadata.get(cls.RUN_ID_KEY)
        if isinstance(run_id, str) and run_id:
            return run_id

        return None

    @classmethod
    def with_runtime(
        cls,
        metadata: dict[str, object],
        **runtime_values: object,
    ) -> dict[str, object]:
        next_metadata = dict(metadata)
        runtime_metadata: dict[str, object] = {}
        existing_runtime_metadata = next_metadata.get(cls.RUNTIME_KEY)
        if isinstance(existing_runtime_metadata, dict):
            runtime_metadata = {
                key: value
                for key, value in existing_runtime_metadata.items()
                if isinstance(key, str)
            }

        runtime_metadata.update(runtime_values)
        next_metadata[cls.RUNTIME_KEY] = runtime_metadata
        return next_metadata

    @classmethod
    def with_tool_state(
        cls,
        metadata: dict[str, object],
        *,
        tool_rounds_used: int,
        pending_approval_count: int,
    ) -> dict[str, object]:
        return cls.with_runtime(
            metadata,
            **{
                cls.TOOL_ROUNDS_USED_KEY: tool_rounds_used,
                cls.PENDING_APPROVAL_COUNT_KEY: pending_approval_count,
            },
        )


class AgentApplication(AgentInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult:
        state = self._new_run_state(request)
        async for _ in self._run_agent_events(request, state):
            pass

        return self._state_to_result(state)

    async def run_agent_until_pause(self, request: AgentRunRequest) -> AgentRunState:
        pause_request = (
            request
            if request.pause_on_approval
            else request.model_copy(update={"pause_on_approval": True})
        )
        state = self._new_run_state(pause_request)
        async for _ in self._run_agent_events(pause_request, state):
            pass

        return state

    async def resume_agent(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunResult:
        async for _ in self._resume_agent_events(state, approvals):
            pass

        return self._state_to_result(state)

    async def resume_agent_until_pause(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        async for _ in self._resume_agent_events(state, approvals):
            pass

        return state

    async def start_agent_run(self, request: AgentRunRequest) -> AgentRunState:
        stored_request = (
            request
            if request.pause_on_approval
            else request.model_copy(update={"pause_on_approval": True})
        )
        state = self._new_run_state(stored_request)
        self._save_agent_state(state)

        async for event in self._run_agent_events(stored_request, state):
            self._append_agent_trace_event(state.run_id, event)
            self._save_agent_state(state)

        self._save_agent_state(state)
        return state

    async def resume_agent_run(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        state = self._get_agent_state(run_id)
        async for event in self._resume_agent_events(state, approvals):
            self._append_agent_trace_event(state.run_id, event)
            self._save_agent_state(state)

        self._save_agent_state(state)
        return state

    def run_agent_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol:
        return _AgentTraceStream(
            self._run_agent_events(request, self._new_run_state(request))
        )

    def resume_agent_stream(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol:
        return _AgentTraceStream(self._resume_agent_events(state, approvals))

    async def _run_agent_events(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
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
        yield self._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_STARTED,
                step_type=AgentStepType.START,
                metadata={
                    "provider_id": request.provider_id,
                    "context_id": request.context_id,
                    "model_id": request.model_id,
                },
            ),
        )

        response = await self._chat(
            request.provider_id,
            request.context_id,
            model_id=request.model_id,
            messages=request.messages,
            memory_query=request.memory_query,
            skills=request.skills,
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
        yield self._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.CHAT_COMPLETED,
                step_type=AgentStepType.CHAT,
                response=response,
                message=response.message,
            ),
        )
        for message in request.messages:
            await self._runtime.contexts.append(request.context_id, message)
        await self._runtime.contexts.append(request.context_id, response.message)

        async for event in self._continue_tool_loop(
            request,
            state,
            response,
            request.max_tool_rounds,
            self._tool_approvals_by_call_id(request.tool_approvals),
            already_requested_approval_call_ids=set(),
        ):
            yield event

    async def _resume_agent_events(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AsyncIterator[AgentTraceEvent]:
        if state.status is not AgentRunStatus.PAUSED:
            raise AgentStateError("Agent run is not paused")
        if state.response is None:
            raise AgentStateError("Agent run did not produce a response")
        if not state.pending_tool_calls:
            raise AgentStateError("Agent run has no pending tool calls")

        pending_approval_call_ids = {
            request.tool_call_id for request in state.pending_approval_requests
        }
        merged_approvals = self._merge_tool_approvals(
            state.request.tool_approvals,
            approvals,
        )
        approvals_by_call_id = self._tool_approvals_by_call_id(merged_approvals)
        missing_approval_call_ids = [
            call_id
            for call_id in pending_approval_call_ids
            if call_id not in approvals_by_call_id
        ]
        if missing_approval_call_ids:
            missing = ", ".join(sorted(missing_approval_call_ids))
            raise AgentStateError(f"Missing approval for pending tool call: {missing}")

        request = state.request.model_copy(
            update={
                "tool_approvals": merged_approvals,
                "pause_on_approval": True,
            }
        )
        pending_tool_calls = list(state.pending_tool_calls)
        state.request = request
        state.status = AgentRunStatus.RUNNING
        state.stop_reason = AgentStopReason.FINISHED
        state.pending_tool_calls = []
        state.pending_approval_requests = []
        state.metadata = AgentRunMetadata.with_tool_state(
            state.metadata,
            tool_rounds_used=state.tool_rounds_used,
            pending_approval_count=0,
        )

        async for event in self._continue_tool_loop(
            request,
            state,
            state.response,
            state.remaining_tool_rounds,
            approvals_by_call_id,
            pending_tool_calls=pending_tool_calls,
            already_requested_approval_call_ids=pending_approval_call_ids,
        ):
            yield event

    async def run(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
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
                skills=skills,
                tools=tools,
                max_tool_rounds=max_tool_rounds,
                recover_tool_errors=True,
                metadata=dict(metadata or {}),
            )
        )
        return result.response

    async def _continue_tool_loop(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
        response: ChatResponse,
        remaining_rounds: int,
        approvals: dict[str, ToolApprovalDecision],
        *,
        already_requested_approval_call_ids: set[str],
        pending_tool_calls: list[ToolCall] | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        current_response = response
        current_tool_calls = (
            pending_tool_calls
            if pending_tool_calls is not None
            else list(current_response.message.tool_calls or [])
        )
        has_tool_runtime = bool(current_tool_calls)
        state.remaining_tool_rounds = remaining_rounds
        state.stop_reason = AgentStopReason.FINISHED

        while current_tool_calls and remaining_rounds > 0:
            has_tool_runtime = True
            state.remaining_tool_rounds = remaining_rounds
            for index, raw_call in enumerate(current_tool_calls):
                call = self._apply_tool_approval(
                    raw_call,
                    approvals.get(raw_call.tool_call_id),
                )
                decision = self._tool_safety_decision(call)
                include_approval_request = (
                    call.tool_call_id not in already_requested_approval_call_ids
                )
                for event in self._trace_tool_approval(
                    call,
                    state,
                    decision,
                    include_approval_request=include_approval_request,
                ):
                    yield event
                if request.pause_on_approval and self._should_pause_for_approval(
                    call,
                    decision,
                ):
                    assert decision is not None
                    yield self._add_trace(
                        state,
                        self._run_paused_event(
                            request,
                            state,
                            [call, *current_tool_calls[index + 1 :]],
                            decision,
                            remaining_rounds,
                        ),
                    )
                    return

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
                    yield self._add_trace(
                        state,
                        AgentTraceEvent(
                            event_type=AgentTraceEventType.TOOL_COMPLETED,
                            step_type=AgentStepType.TOOL,
                            message=tool_message,
                            tool_call=call,
                            tool_result=tool_result,
                        ),
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
                    yield self._add_trace(
                        state,
                        AgentTraceEvent(
                            event_type=AgentTraceEventType.TOOL_FAILED,
                            step_type=AgentStepType.TOOL_ERROR,
                            message=tool_message,
                            tool_call=call,
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                        ),
                    )
                    if not request.recover_tool_errors:
                        await self._runtime.contexts.append(
                            request.context_id,
                            tool_message,
                        )
                        state.stop_reason = AgentStopReason.TOOL_ERROR
                        state.status = AgentRunStatus.FAILED
                        state.steps.append(
                            AgentStep(
                                step_type=AgentStepType.STOP,
                                metadata={"reason": state.stop_reason.value},
                            )
                        )
                        state.tool_rounds_used = (
                            request.max_tool_rounds - remaining_rounds
                        )
                        state.metadata = AgentRunMetadata.with_tool_state(
                            state.metadata,
                            tool_rounds_used=state.tool_rounds_used,
                            pending_approval_count=0,
                        )
                        async for event in self._write_memory_events(request, state):
                            yield event
                        yield self._add_trace(
                            state,
                            self._run_stopped_event(state.stop_reason),
                        )
                        return

                await self._runtime.contexts.append(request.context_id, tool_message)

            remaining_rounds -= 1
            state.remaining_tool_rounds = remaining_rounds
            if remaining_rounds < 0:
                break

            current_response = await self._chat(
                request.provider_id,
                request.context_id,
                model_id=request.model_id,
                messages=[],
                skills=request.skills,
                tools=request.tools,
                metadata=request.metadata,
            )
            state.response = current_response
            state.steps.append(
                AgentStep(
                    step_type=AgentStepType.CHAT,
                    response=current_response,
                    message=current_response.message,
                )
            )
            yield self._add_trace(
                state,
                AgentTraceEvent(
                    event_type=AgentTraceEventType.CHAT_COMPLETED,
                    step_type=AgentStepType.CHAT,
                    response=current_response,
                    message=current_response.message,
                ),
            )
            await self._runtime.contexts.append(
                request.context_id,
                current_response.message,
            )
            current_tool_calls = list(current_response.message.tool_calls or [])
            already_requested_approval_call_ids = set()
            has_tool_runtime = has_tool_runtime or bool(current_tool_calls)

        if current_tool_calls:
            state.stop_reason = AgentStopReason.TOOL_ROUNDS_EXHAUSTED

        state.status = AgentRunStatus.FINISHED
        state.pending_tool_calls = []
        state.pending_approval_requests = []
        state.tool_rounds_used = request.max_tool_rounds - remaining_rounds
        if has_tool_runtime:
            state.metadata = AgentRunMetadata.with_tool_state(
                state.metadata,
                tool_rounds_used=state.tool_rounds_used,
                pending_approval_count=0,
            )
        state.steps.append(
            AgentStep(
                step_type=AgentStepType.STOP,
                metadata={"reason": state.stop_reason.value},
            )
        )
        async for event in self._write_memory_events(request, state):
            yield event
        yield self._add_trace(state, self._run_stopped_event(state.stop_reason))

    async def _chat(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
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
        request = request.model_copy(update={"skills": skills})
        request = await compose_skill_prompted_chat_request(
            self._runtime,
            request,
            SkillCapability.AGENT,
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

    def _merge_tool_approvals(
        self,
        existing: list[ToolApprovalDecision],
        new: list[ToolApprovalDecision],
    ) -> list[ToolApprovalDecision]:
        approvals = self._tool_approvals_by_call_id(existing)
        approvals.update(self._tool_approvals_by_call_id(new))
        return list(approvals.values())

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
        state: AgentRunState,
        decision: ToolSafetyDecision | None,
        *,
        include_approval_request: bool = True,
    ) -> list[AgentTraceEvent]:
        if decision is None:
            return []
        if decision.approval_request is None and not decision.requires_approval:
            return []

        events: list[AgentTraceEvent] = []
        if include_approval_request:
            events.append(
                self._add_trace(
                    state,
                    AgentTraceEvent(
                        event_type=AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
                        tool_call=call,
                        approval_request=decision.approval_request,
                        metadata={
                            "allowed": decision.allowed,
                            "requires_approval": decision.requires_approval,
                            "reason": decision.reason,
                        },
                    ),
                )
            )
        if call.approval is not None:
            events.append(
                self._add_trace(
                    state,
                    AgentTraceEvent(
                        event_type=AgentTraceEventType.TOOL_APPROVAL_DECIDED,
                        tool_call=call,
                        approval_request=decision.approval_request,
                        approval_decision=call.approval,
                        metadata={"allowed": decision.allowed},
                    ),
                )
            )

        return events

    def _tool_safety_decision(self, call: ToolCall) -> ToolSafetyDecision | None:
        tool_name = self._tool_name(call)
        if tool_name is None:
            return None

        try:
            tool = self._runtime.tool_register.get(tool_name)
            return self._runtime.tool_safety_policy.authorize(tool, call)
        except Exception:
            return None

    def _should_pause_for_approval(
        self,
        call: ToolCall,
        decision: ToolSafetyDecision | None,
    ) -> bool:
        return (
            decision is not None
            and decision.requires_approval
            and not decision.allowed
            and decision.approval_request is not None
            and call.approval is None
        )

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

    def _run_paused_event(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
        pending_tool_calls: list[ToolCall],
        decision: ToolSafetyDecision,
        remaining_rounds: int,
    ) -> AgentTraceEvent:
        approval_request = decision.approval_request
        call = pending_tool_calls[0]
        state.status = AgentRunStatus.PAUSED
        state.stop_reason = None
        state.remaining_tool_rounds = remaining_rounds
        state.tool_rounds_used = request.max_tool_rounds - remaining_rounds
        state.pending_tool_calls = pending_tool_calls
        state.pending_approval_requests = (
            [approval_request] if approval_request is not None else []
        )
        state.metadata = AgentRunMetadata.with_tool_state(
            state.metadata,
            tool_rounds_used=state.tool_rounds_used,
            pending_approval_count=len(state.pending_approval_requests),
        )
        return AgentTraceEvent(
            event_type=AgentTraceEventType.RUN_PAUSED,
            tool_call=call,
            approval_request=approval_request,
            metadata={
                "reason": "tool_approval_required",
                "remaining_tool_rounds": remaining_rounds,
                "tool_rounds_used": state.tool_rounds_used,
            },
        )

    async def _write_memory_events(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        result = self._state_to_result(state)
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
            yield self._add_trace(
                state,
                AgentTraceEvent(
                    event_type=AgentTraceEventType.MEMORY_WRITTEN,
                    step_type=AgentStepType.MEMORY_WRITE,
                    metadata={"memory_id": memory.memory_id},
                ),
            )

    def _add_trace(
        self,
        state: AgentRunState,
        event: AgentTraceEvent,
    ) -> AgentTraceEvent:
        if event.summary is None:
            event = event.model_copy(update={"summary": self._trace_summary(event)})
        state.trace.append(event)
        return event

    def _trace_summary(self, event: AgentTraceEvent) -> str:
        if event.event_type is AgentTraceEventType.RUN_STARTED:
            return "Agent run started"
        if event.event_type is AgentTraceEventType.CHAT_COMPLETED:
            return "Model response received"
        if event.event_type is AgentTraceEventType.TOOL_APPROVAL_REQUESTED:
            tool_name = self._event_tool_name(event)
            return f"Tool approval requested for {tool_name}"
        if event.event_type is AgentTraceEventType.TOOL_APPROVAL_DECIDED:
            tool_name = self._event_tool_name(event)
            status = (
                event.approval_decision.status.value
                if event.approval_decision is not None
                else "unknown"
            )
            return f"Tool approval {status} for {tool_name}"
        if event.event_type is AgentTraceEventType.TOOL_COMPLETED:
            tool_name = self._event_tool_name(event)
            return f"Tool {tool_name} completed"
        if event.event_type is AgentTraceEventType.TOOL_FAILED:
            tool_name = self._event_tool_name(event)
            error_type = event.error_type or "error"
            return f"Tool {tool_name} failed with {error_type}"
        if event.event_type is AgentTraceEventType.MEMORY_WRITTEN:
            memory_id = event.metadata.get("memory_id")
            if isinstance(memory_id, str) and memory_id:
                return f"Memory {memory_id} written"
            return "Memory written"
        if event.event_type is AgentTraceEventType.RUN_PAUSED:
            reason = event.metadata.get("reason")
            if isinstance(reason, str) and reason:
                return f"Agent run paused: {reason}"
            return "Agent run paused"
        if event.event_type is AgentTraceEventType.RUN_STOPPED:
            reason = event.metadata.get("reason")
            if isinstance(reason, str) and reason:
                return f"Agent run stopped: {reason}"
            return "Agent run stopped"

        return event.event_type.value

    def _event_tool_name(self, event: AgentTraceEvent) -> str:
        if event.approval_request is not None:
            return event.approval_request.tool_name
        if event.tool_call is not None:
            tool_name = self._tool_name(event.tool_call)
            if tool_name is not None:
                return tool_name

        return "unknown tool"

    def _new_run_state(self, request: AgentRunRequest) -> AgentRunState:
        run_id = AgentRunMetadata.run_id(request.metadata)
        if run_id is None:
            run_id = uuid4().hex

        return AgentRunState(
            run_id=run_id,
            request=request,
            remaining_tool_rounds=request.max_tool_rounds,
            metadata=dict(request.metadata),
        )

    def _state_to_result(self, state: AgentRunState) -> AgentRunResult:
        if state.status is AgentRunStatus.PAUSED:
            raise AgentStateError("Agent run paused for tool approval")
        if state.response is None:
            raise AgentStateError("Agent run did not produce a response")
        if state.stop_reason is None:
            raise AgentStateError("Agent run did not stop")

        metadata = dict(state.request.metadata)
        if self._has_tool_runtime(state):
            metadata = AgentRunMetadata.with_runtime(
                metadata,
                **{AgentRunMetadata.TOOL_ROUNDS_USED_KEY: state.tool_rounds_used},
            )

        return AgentRunResult(
            response=state.response,
            stop_reason=state.stop_reason,
            steps=list(state.steps),
            trace=list(state.trace),
            metadata=metadata,
        )

    def _has_tool_runtime(self, state: AgentRunState) -> bool:
        if state.pending_tool_calls or state.pending_approval_requests:
            return True
        if state.stop_reason is AgentStopReason.TOOL_ROUNDS_EXHAUSTED:
            return True

        return any(
            step.step_type in {AgentStepType.TOOL, AgentStepType.TOOL_ERROR}
            for step in state.steps
        )

    def _get_agent_state(self, run_id: str) -> AgentRunState:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")

        return register.get_state(run_id)

    def _save_agent_state(self, state: AgentRunState) -> None:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")

        register.save_state(state)

    def _append_agent_trace_event(
        self,
        run_id: str,
        event: AgentTraceEvent,
    ) -> None:
        register = self._runtime.agent_trace_register
        if register is None:
            raise AgentStateError("Agent trace register is not configured")

        register.append_event(run_id, event)


class _AgentTraceStream:
    def __init__(self, events: AsyncIterator[AgentTraceEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[AgentTraceEvent]:
        return self._events


class AgentRunApplication(AgentRunInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime
        self._agent = AgentApplication(runtime)

    async def start(self, request: AgentRunRequest) -> AgentRunState:
        return await self._agent.start_agent_run(request)

    async def resume(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        return await self._agent.resume_agent_run(run_id, approvals)

    def start_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol:
        stored_request = (
            request
            if request.pause_on_approval
            else request.model_copy(update={"pause_on_approval": True})
        )
        state = self._agent._new_run_state(stored_request)
        self._state_register().save_state(state)
        return _AgentTraceStream(
            self._stream_and_store(
                self._agent._run_agent_events(stored_request, state),
                state,
            )
        )

    def resume_stream(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol:
        state = self.get_state(run_id)
        return _AgentTraceStream(
            self._stream_and_store(
                self._agent._resume_agent_events(state, approvals),
                state,
            )
        )

    def get_state(self, run_id: str) -> AgentRunState:
        return self._state_register().get_state(run_id)

    def list_states(self) -> list[AgentRunState]:
        return self._state_register().list_states()

    def list_trace(self, run_id: str) -> list[AgentTraceEvent]:
        return self._trace_register().list_events(run_id)

    async def _stream_and_store(
        self,
        events: AsyncIterator[AgentTraceEvent],
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        async for event in events:
            self._trace_register().append_event(state.run_id, event)
            self._state_register().save_state(state)
            yield event

        self._state_register().save_state(state)

    def _state_register(self) -> AgentRunStateRegisterProtocol:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")

        return register

    def _trace_register(self) -> AgentTraceRegisterProtocol:
        register = self._runtime.agent_trace_register
        if register is None:
            raise AgentStateError("Agent trace register is not configured")

        return register
