import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from EvernightAI.core.error.agent import (
    AgentStateError,
)
from EvernightAI.core.error.tool import ToolExecutionError
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.error.skill import (
    SkillConflictError,
    SkillDisabledError,
    SkillNotFoundError,
)
from EvernightAI.core.domain.provider import merge_chat_usage
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import (
    AgentTraceStreamProtocol,
    ChatStreamProtocol,
)
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
    ToolExecutionAttempt,
    ToolExecutionStatus,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatSkill,
    ChatUsage,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.skill import SkillCapability
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.trace import TraceSubject
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    ToolSafetyDecision,
)
from EvernightAI.application.chat_request import ChatRequestComposer
from EvernightAI.application.memory import (
    write_memory_candidate,
)

from EvernightAI.application.agent_state import (
    AgentRunMetadata,
    AgentRunControl,
    AgentResumeMode,
    LOGGER,
    _owner_scope,
    _aggregate_run_usage,
)
from EvernightAI.application.agent_lifecycle import _agent_run_lifecycle
from EvernightAI.application.agent_recovery import (
    _latest_tool_execution_attempts,
    _tool_call_can_resume,
)


def _tool_error_payload(
    exc: Exception, *, max_cause_depth: int = 3
) -> dict[str, object]:
    payload: dict[str, object] = {
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
    }
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail:
        payload["error_detail"] = detail
    cause = getattr(exc, "cause", None)
    if isinstance(cause, Exception) and max_cause_depth > 0:
        payload["cause"] = _tool_error_payload(
            cause,
            max_cause_depth=max_cause_depth - 1,
        )
    return payload


class AgentExecutionApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime
        self._request_composer = ChatRequestComposer(runtime)
        self._lifecycle = _agent_run_lifecycle(runtime)

    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult:
        async with self._lifecycle.active_run():
            state = self._new_run_state(request)
            async for _ in self._run_agent_events(request, state):
                pass

            return self._state_to_result(state)

    async def run_agent_until_pause(self, request: AgentRunRequest) -> AgentRunState:
        async with self._lifecycle.active_run():
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
        async with self._lifecycle.active_run():
            async for _ in self._resume_agent_events(state, approvals):
                pass

            return self._state_to_result(state)

    async def resume_agent_until_pause(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        async with self._lifecycle.active_run():
            async for _ in self._resume_agent_events(state, approvals):
                pass

            return state

    def _prepare_agent_run(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> tuple[AgentRunRequest, AgentRunState]:
        stored_request = (
            request
            if request.pause_on_approval
            else request.model_copy(update={"pause_on_approval": True})
        )
        state = self._new_run_state(stored_request)
        self._create_agent_state(state, principal_scope=principal_scope)
        return stored_request, state

    async def close(self) -> None:
        await self._lifecycle.close(
            state_register=self._runtime.agent_state_register,
            trace_register=self._runtime.agent_trace_register,
            tool_execution_register=self._runtime.tool_execution_register,
        )

    def run_agent_stream(
        self,
        request: AgentRunRequest,
    ) -> AgentTraceStreamProtocol:
        return _AgentTraceStream(
            self._lifecycle.track_stream(
                self._run_agent_events(request, self._new_run_state(request))
            )
        )

    def resume_agent_stream(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> AgentTraceStreamProtocol:
        return _AgentTraceStream(
            self._lifecycle.track_stream(self._resume_agent_events(state, approvals))
        )

    async def _run_agent_events(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        context = await self._runtime.contexts.get(
            request.context_id,
            principal_scope=_owner_scope(request.owner_id),
        )
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            context_message_offset=len(context.messages),
            context_message_indices=[],
            context_history_generation=context.metadata.get("chat_history_generation"),
        )
        state.skill_revisions = {
            skill.skill_name: self._runtime.skills.get_skill(skill.skill_name).revision
            for skill in request.skills or []
        }
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

        async for event in self._run_initial_chat_events(request, state):
            yield event

    async def _run_initial_chat_events(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:

        response = None
        async for event in self._chat_events(
            request.provider_id,
            request.context_id,
            state,
            model_id=request.model_id,
            messages=request.messages,
            memory_query=request.memory_query,
            skills=request.skills,
            tools=self._available_tools(request),
            metadata=request.metadata,
        ):
            if event.response is not None:
                response = event.response
                self._record_chat_response(state, response)
            yield event

        if response is None:
            raise AgentStateError("Agent run did not produce a response")

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
        if not self._is_recovery_eligible(state):
            raise AgentStateError("Agent run cannot resume safely; retry it instead")
        self._check_skill_revisions(state)
        state.usage = _aggregate_run_usage(state)
        if AgentRunControl.from_state(state).resume_mode is AgentResumeMode.CHECKPOINT:
            state.request = state.request.model_copy(
                update={
                    "tool_approvals": self._merge_tool_approvals(
                        state.request.tool_approvals,
                        approvals,
                    ),
                }
            )
            async for event in self._resume_checkpoint_events(state):
                yield event
            return
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

    async def _resume_checkpoint_events(
        self,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        state.status = AgentRunStatus.RUNNING
        state.stop_reason = None
        state.pending_tool_calls = []
        state.pending_approval_requests = []
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: False},
            **{AgentRunMetadata.PAUSE_REQUESTED_KEY: False},
        )
        if state.response is None:
            async for event in self._run_initial_chat_events(state.request, state):
                yield event
            return

        response_tool_calls = list(state.response.message.tool_calls or [])
        completed_tool_call_ids = self._completed_tool_call_ids(state)
        remaining_tool_calls = [
            call
            for call in response_tool_calls
            if call.tool_call_id not in completed_tool_call_ids
        ]
        if remaining_tool_calls:
            async for event in self._continue_tool_loop(
                state.request,
                state,
                state.response,
                state.remaining_tool_rounds,
                approvals=self._tool_approvals_by_call_id(state.request.tool_approvals),
                pending_tool_calls=remaining_tool_calls,
                already_requested_approval_call_ids=set(),
            ):
                yield event
            return

        if response_tool_calls:
            async for event in self._continue_after_completed_tool_round(
                state.request,
                state,
                approvals=self._tool_approvals_by_call_id(state.request.tool_approvals),
            ):
                yield event
            return

        async for event in self._continue_tool_loop(
            state.request,
            state,
            state.response,
            state.remaining_tool_rounds,
            approvals={},
            pending_tool_calls=[],
            already_requested_approval_call_ids=set(),
        ):
            yield event

    def _is_recovery_eligible(self, state: AgentRunState) -> bool:
        return AgentRunControl.from_state(state).recoverable

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
        has_completed_tool_round: bool = False,
    ) -> AsyncIterator[AgentTraceEvent]:
        current_response = response
        current_tool_calls = (
            pending_tool_calls
            if pending_tool_calls is not None
            else list(current_response.message.tool_calls or [])
        )
        has_tool_runtime = has_completed_tool_round or bool(current_tool_calls)
        state.remaining_tool_rounds = remaining_rounds
        state.stop_reason = AgentStopReason.FINISHED

        while current_tool_calls and remaining_rounds > 0:
            has_tool_runtime = True
            state.remaining_tool_rounds = remaining_rounds
            for index, raw_call in enumerate(current_tool_calls):
                self._check_skill_revisions(state)
                call = self._apply_tool_approval(
                    raw_call,
                    approvals.get(raw_call.tool_call_id),
                )
                call = call.model_copy(
                    update={
                        "metadata": {
                            **call.metadata,
                            "working_directory": request.working_directory,
                            "owner_id": state.owner_id,
                            "session_id": request.metadata.get("session_id"),
                            "run_id": state.run_id,
                        }
                    }
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
                if (
                    request.pause_on_approval
                    and decision is not None
                    and self._should_pause_for_approval(call, decision)
                ):
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

                if decision is None or decision.allowed:
                    yield self._add_trace(
                        state,
                        AgentTraceEvent(
                            event_type=AgentTraceEventType.TOOL_STARTED,
                            step_type=AgentStepType.TOOL,
                            tool_call=call,
                        ),
                    )
                tool_started = perf_counter()
                self._check_skill_revisions(state)
                try:
                    tool_result = await self._execute_tool_call(state, call)
                    self._log_tool_execution(
                        state,
                        call,
                        started=tool_started,
                        success=True,
                    )
                    duration_ms = round((perf_counter() - tool_started) * 1000, 3)
                    tool_message = self._tool_result_to_message(tool_result)
                    state.steps.append(
                        AgentStep(
                            step_type=AgentStepType.TOOL,
                            message=tool_message,
                            tool_call=call,
                            tool_result=tool_result,
                            metadata={"duration_ms": duration_ms},
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
                            metadata={"duration_ms": duration_ms},
                        ),
                    )
                except Exception as exc:
                    self._log_tool_execution(
                        state,
                        call,
                        started=tool_started,
                        success=False,
                        error=exc,
                    )
                    duration_ms = round((perf_counter() - tool_started) * 1000, 3)
                    tool_message = self._tool_error_to_message(call, exc)
                    state.steps.append(
                        AgentStep(
                            step_type=AgentStepType.TOOL_ERROR,
                            message=tool_message,
                            tool_call=call,
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                            metadata={"duration_ms": duration_ms},
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
                            metadata={"duration_ms": duration_ms},
                        ),
                    )
                    if not request.recover_tool_errors:
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
                        state.metadata = AgentRunMetadata.with_tool_state(
                            state.metadata,
                            tool_rounds_used=state.tool_rounds_used,
                            pending_approval_count=0,
                        )
                        await self._commit_run_transcript(request.context_id, state)
                        async for event in self._write_memory_events(request, state):
                            yield event
                        state.status = AgentRunStatus.FAILED
                        yield self._add_trace(
                            state,
                            self._run_stopped_event(state.stop_reason),
                        )
                        return

            remaining_rounds -= 1
            state.remaining_tool_rounds = remaining_rounds

            async for event in self._continue_after_completed_tool_round(
                request,
                state,
                remaining_tool_rounds=remaining_rounds,
                approvals=approvals,
            ):
                yield event
            return

        if current_tool_calls:
            state.stop_reason = AgentStopReason.TOOL_ROUNDS_EXHAUSTED
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
        await self._commit_run_transcript(request.context_id, state)
        async for event in self._write_memory_events(request, state):
            yield event
        state.status = (
            AgentRunStatus.FINISHED
            if state.stop_reason is AgentStopReason.FINISHED
            else AgentRunStatus.FAILED
        )
        yield self._add_trace(state, self._run_stopped_event(state.stop_reason))

    async def _continue_after_completed_tool_round(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
        *,
        approvals: dict[str, ToolApprovalDecision],
        remaining_tool_rounds: int | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        remaining_rounds = (
            max(state.remaining_tool_rounds - 1, 0)
            if remaining_tool_rounds is None
            else remaining_tool_rounds
        )
        state.remaining_tool_rounds = remaining_rounds
        response = None
        async for event in self._chat_events(
            request.provider_id,
            request.context_id,
            state,
            model_id=request.model_id,
            messages=self._run_transcript(state),
            skills=request.skills,
            tools=self._available_tools(request),
            metadata=request.metadata,
        ):
            if event.response is not None:
                response = event.response
                self._record_chat_response(state, response)
            yield event

        if response is None:
            raise AgentStateError("Agent run did not produce a response")

        async for event in self._continue_tool_loop(
            request,
            state,
            response,
            remaining_rounds,
            approvals=approvals,
            already_requested_approval_call_ids=set(),
            has_completed_tool_round=True,
        ):
            yield event

    def _record_chat_response(
        self,
        state: AgentRunState,
        response: ChatResponse,
    ) -> None:
        state.response = response
        state.steps.append(
            AgentStep(
                step_type=AgentStepType.CHAT,
                trace_event_id=state.trace[-1].event_id,
                response=response,
                message=response.message,
            )
        )
        state.usage = _aggregate_run_usage(state)

    def _completed_tool_call_ids(self, state: AgentRunState) -> set[str]:
        return {
            step.tool_call.tool_call_id
            for step in state.steps
            if step.step_type in {AgentStepType.TOOL, AgentStepType.TOOL_ERROR}
            and step.tool_call is not None
        }

    async def _execute_tool_call(
        self,
        state: AgentRunState,
        call: ToolCall,
    ) -> ToolCallResult:
        register = self._runtime.tool_execution_register
        if register is None:
            return await self._runtime.tools.execute(call)

        attempts = register.list_attempts(
            state.run_id,
            principal_scope=_owner_scope(state.owner_id),
        )
        latest = _latest_tool_execution_attempts(attempts).get(call.tool_call_id)
        if latest is not None and latest.status is ToolExecutionStatus.COMPLETED:
            if latest.result is None:
                raise AgentStateError(
                    "Completed tool execution has no persisted result"
                )
            return latest.result
        if latest is not None and latest.status is ToolExecutionStatus.FAILED:
            raise ToolExecutionError(
                latest.error_message or "Persisted tool execution failed"
            )
        if (
            latest is not None
            and latest.status
            in {ToolExecutionStatus.STARTED, ToolExecutionStatus.UNKNOWN}
            and not _tool_call_can_resume(
                call.tool_call_id,
                {call.tool_call_id: latest},
            )
        ):
            raise AgentStateError(
                "Tool execution outcome is unknown and requires operator resolution"
            )

        tool_name = self._tool_name(call)
        if tool_name is None:
            raise AgentStateError("Tool execution has no tool name")
        tool = self._runtime.tool_register.get(tool_name)
        idempotency_key = (
            latest.idempotency_key
            if latest is not None
            else f"{state.run_id}:{call.tool_call_id}"
        )
        persisted_call = call.model_copy(
            update={
                "metadata": {
                    **call.metadata,
                    "idempotency_key": idempotency_key,
                }
            }
        )
        now = datetime.now(timezone.utc)
        if latest is not None and latest.status is ToolExecutionStatus.SCHEDULED:
            attempt = latest
        else:
            attempt = ToolExecutionAttempt(
                run_id=state.run_id,
                owner_id=state.owner_id,
                tool_call_id=call.tool_call_id,
                attempt=(latest.attempt + 1 if latest is not None else 1),
                tool_name=tool_name,
                status=ToolExecutionStatus.SCHEDULED,
                replay_policy=tool.replay_policy,
                idempotency_key=idempotency_key,
                tool_call=persisted_call,
                created_at=now,
            )
            register.create_attempt(
                attempt,
                principal_scope=_owner_scope(state.owner_id),
            )

        attempt = attempt.model_copy(
            update={
                "status": ToolExecutionStatus.STARTED,
                "started_at": now,
                "tool_call": persisted_call,
            }
        )
        register.save_attempt(
            attempt,
            principal_scope=_owner_scope(state.owner_id),
        )
        try:
            result = await self._runtime.tools.execute(persisted_call)
        except Exception as exc:
            failed = attempt.model_copy(
                update={
                    "status": ToolExecutionStatus.FAILED,
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            register.save_attempt(
                failed,
                principal_scope=_owner_scope(state.owner_id),
            )
            raise

        completed = attempt.model_copy(
            update={
                "status": ToolExecutionStatus.COMPLETED,
                "result": result,
                "finished_at": datetime.now(timezone.utc),
            }
        )
        register.save_attempt(
            completed,
            principal_scope=_owner_scope(state.owner_id),
        )
        return result

    async def _chat(
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
        principal_scope: PrincipalScope | None = None,
    ) -> ChatResponse:
        request = await self._request_composer.compose(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=principal_scope,
            skill_capability=SkillCapability.AGENT,
        )
        self._check_skill_revisions(state)
        return await self._runtime.providers.chat(provider_id, request)

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
        self._check_skill_revisions(state)
        if not self._should_stream_chat(metadata):
            response = await self._chat(
                provider_id,
                context_id,
                state,
                model_id=model_id,
                messages=messages,
                memory_query=memory_query,
                skills=skills,
                tools=tools,
                metadata=metadata,
                principal_scope=_owner_scope(state.owner_id),
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
            return

        request = await self._compose_agent_chat_request(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=_owner_scope(state.owner_id),
        )
        self._check_skill_revisions(state)
        stream = await self._runtime.providers.chat_stream(provider_id, request)
        response = None
        async for event in self._stream_chat_events(stream, request.model_id, state):
            if event.response is not None:
                response = event.response
            yield event

        if response is None:
            raise AgentStateError("Agent run did not produce a response")

    async def _stream_chat_events(
        self,
        stream: ChatStreamProtocol,
        fallback_model_id: str,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        text_deltas: list[str] = []
        tool_calls: list[ToolCall] = []
        response_id: str | None = None
        model_id = fallback_model_id
        finish_reason: str | None = None
        usage: ChatUsage | None = None
        completed = False
        final_message: Content | None = None

        async for event in stream:
            if event.event_type is ChatStreamEventType.ERROR:
                raise ProviderResponseError(
                    event.error_message or "Provider chat stream failed",
                    detail=event.error_type,
                )
            if event.event_type in {
                ChatStreamEventType.MESSAGE_COMPLETED,
                ChatStreamEventType.DONE,
            }:
                completed = True
            if event.response_id is not None:
                response_id = event.response_id
            if event.message is not None and event.event_type in {
                ChatStreamEventType.MESSAGE_COMPLETED,
                ChatStreamEventType.DONE,
            }:
                final_message = event.message
            if event.model_id is not None:
                model_id = event.model_id
            if event.finish_reason is not None:
                finish_reason = event.finish_reason
                completed = True
            if event.usage is not None:
                usage = merge_chat_usage(usage, event.usage)

            text_delta = self._chat_stream_text_delta(event)
            if text_delta:
                text_deltas.append(text_delta)
                yield self._add_trace(
                    state,
                    AgentTraceEvent(
                        event_type=AgentTraceEventType.CHAT_DELTA,
                        step_type=AgentStepType.CHAT,
                        text_delta=text_delta,
                    ),
                )

            if (
                event.event_type is ChatStreamEventType.TOOL_CALL_COMPLETED
                and event.tool_call is not None
            ):
                tool_calls.append(event.tool_call)

        if not completed:
            raise ProviderResponseError("Provider chat stream ended without completion")

        text = "".join(text_deltas)
        content = [ContentPart(type=ContentPartType.TEXT, text=text)] if text else None
        response = ChatResponse(
            response_id=response_id,
            model_id=model_id,
            message=final_message
            or Content(
                role=MessageRole.ASSISTANT,
                content=content,
                tool_calls=tool_calls or None,
            ),
            finish_reason=finish_reason,
            usage=usage,
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

    async def _compose_agent_chat_request(
        self,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ChatRequest:
        return await self._request_composer.compose(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=principal_scope,
            skill_capability=SkillCapability.AGENT,
        )

    def _chat_stream_text_delta(self, event: ChatStreamEvent) -> str | None:
        if event.event_type is not ChatStreamEventType.MESSAGE_DELTA:
            return None
        if event.text_delta:
            return event.text_delta
        if event.content_part is not None:
            return event.content_part.text

        return None

    def _should_stream_chat(self, metadata: dict[str, object] | None) -> bool:
        return (metadata or {}).get("stream") is True

    async def _commit_run_transcript(
        self,
        context_id: str,
        state: AgentRunState,
    ) -> None:
        principal_scope = _owner_scope(state.owner_id)
        indices: list[int] = []
        for message in self._run_transcript(state):
            context = await self._runtime.contexts.append(
                context_id,
                message,
                principal_scope=principal_scope,
            )
            indices.append(len(context.messages) - 1)
            state.metadata = AgentRunMetadata.with_runtime(
                state.metadata,
                context_message_indices=list(indices),
            )

    def _run_transcript(self, state: AgentRunState) -> list[Content]:
        transcript = list(state.request.messages)
        for step in state.steps:
            if step.step_type not in {
                AgentStepType.CHAT,
                AgentStepType.TOOL,
                AgentStepType.TOOL_ERROR,
            }:
                continue
            if step.message is not None:
                transcript.append(step.message)

        return transcript

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
        payload = _tool_error_payload(exc)
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

    def _available_tools(self, request: AgentRunRequest) -> list[ToolDefinition] | None:
        if request.tools is None:
            return None
        available = {
            tool.name: tool
            for tool in self._runtime.tools.list_tools(
                principal_scope=_owner_scope(request.owner_id)
            )
        }
        return [
            available.get(tool.name, tool)
            for tool in request.tools
            if tool.name in available or not self._runtime.tool_register.has(tool.name)
        ]

    def _apply_tool_approval(
        self, call: ToolCall, approval: ToolApprovalDecision | None
    ) -> ToolCall:
        metadata = dict(call.metadata)
        metadata.pop("approved", None)
        return call.model_copy(update={"approval": approval, "metadata": metadata})

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
            return self._runtime.tools.authorize(call)
        except Exception as exc:
            return ToolSafetyDecision(
                allowed=False,
                reason=f"Tool safety policy failed: {exc}",
                metadata={
                    "safety_policy_error": True,
                    "error_type": exc.__class__.__name__,
                },
            )

    def _should_pause_for_approval(
        self,
        call: ToolCall,
        decision: ToolSafetyDecision,
    ) -> bool:
        return (
            decision.requires_approval
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
            written_memory, operation = await write_memory_candidate(
                self._runtime,
                memory,
                principal_scope=_owner_scope(request.owner_id),
            )
            memory_step = AgentStep(
                step_type=AgentStepType.MEMORY_WRITE,
                metadata={
                    "memory_id": written_memory.memory_id,
                    "operation": operation.value,
                },
            )
            state.steps.append(memory_step)
            yield self._add_trace(
                state,
                AgentTraceEvent(
                    event_type=AgentTraceEventType.MEMORY_WRITTEN,
                    step_type=AgentStepType.MEMORY_WRITE,
                    metadata={
                        "memory_id": written_memory.memory_id,
                        "operation": operation.value,
                    },
                ),
            )

    def _add_trace(
        self,
        state: AgentRunState,
        event: AgentTraceEvent,
    ) -> AgentTraceEvent:
        if event.occurred_at is None and event.event_type in {
            AgentTraceEventType.TOOL_STARTED,
            AgentTraceEventType.TOOL_COMPLETED,
            AgentTraceEventType.TOOL_FAILED,
        }:
            event.occurred_at = datetime.now(timezone.utc)
        if event.event_type is AgentTraceEventType.CHAT_COMPLETED:
            event.metadata = {
                **event.metadata,
                "remaining_tool_rounds": state.remaining_tool_rounds,
            }
        if event.summary is None:
            event = event.model_copy(update={"summary": self._trace_summary(event)})
        if event.event_id is None:
            event.event_id = uuid4().hex
        if (
            state.steps
            and event.step_type is not AgentStepType.CHAT
            and event.step_type is state.steps[-1].step_type
        ):
            state.steps[-1].trace_event_id = event.event_id
        self._tag_agent_trace_event(
            state.run_id,
            event,
            owner_id=state.owner_id,
        )
        state.trace.append(event)
        return event

    def _trace_summary(self, event: AgentTraceEvent) -> str:
        if event.event_type is AgentTraceEventType.RUN_STARTED:
            return "Agent run started"
        if event.event_type is AgentTraceEventType.CHAT_DELTA:
            return "Model response delta"
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
        if event.event_type is AgentTraceEventType.TOOL_STARTED:
            return f"Tool {self._event_tool_name(event)} started"
        if event.event_type is AgentTraceEventType.TOOL_COMPLETED:
            tool_name = self._event_tool_name(event)
            return f"Tool {tool_name} completed"
        if event.event_type is AgentTraceEventType.TOOL_FAILED:
            tool_name = self._event_tool_name(event)
            error_type = event.error_type or "error"
            return f"Tool {tool_name} failed with {error_type}"
        if event.event_type is AgentTraceEventType.TOOL_EXECUTION_RESOLVED:
            action = event.metadata.get("resolution")
            return (
                f"Tool execution resolved: {action}"
                if isinstance(action, str)
                else "Tool execution resolved"
            )
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

    def _log_tool_execution(
        self,
        state: AgentRunState,
        call: ToolCall,
        *,
        started: float,
        success: bool,
        error: Exception | None = None,
    ) -> None:
        LOGGER.info(
            "Agent tool execution completed",
            extra={
                "request_id": state.request.metadata.get("request_id"),
                "session_id": state.request.metadata.get("session_id"),
                "run_id": state.run_id,
                "tool_name": self._tool_name(call),
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "success": success,
                "error_type": error.__class__.__name__ if error else None,
            },
        )

    def _check_skill_revisions(self, state: AgentRunState) -> None:
        names = dict.fromkeys(skill.skill_name for skill in state.request.skills or [])
        if not names and not state.skill_revisions:
            return
        if (
            state.skill_revisions is None
            or names.keys() != state.skill_revisions.keys()
        ):
            raise SkillConflictError(
                "Agent skill versions are unavailable; start a new run",
                detail=json.dumps(
                    {
                        "reason": "revision_unavailable",
                        "skill_names": list(names),
                    }
                ),
            )
        for name in names:
            try:
                definition = self._runtime.skills.get_skill(name)
            except SkillNotFoundError as exc:
                raise SkillNotFoundError(
                    str(exc),
                    detail=json.dumps(
                        {
                            "reason": "deleted",
                            "skill_names": [name],
                        }
                    ),
                    cause=exc,
                ) from exc
            if not definition.is_enabled:
                raise SkillDisabledError(
                    f"The skill {name} is disabled",
                    detail=json.dumps(
                        {
                            "reason": "disabled",
                            "skill_names": [name],
                        }
                    ),
                )
            if definition.revision != state.skill_revisions[name]:
                raise SkillConflictError(
                    f"The skill {name} changed during the agent run; start a new run",
                    detail=json.dumps(
                        {
                            "reason": "revision_changed",
                            "skill_names": [name],
                        }
                    ),
                )

    def _new_run_state(self, request: AgentRunRequest) -> AgentRunState:
        run_id = AgentRunMetadata.run_id(request.metadata)
        if run_id is None:
            run_id = uuid4().hex

        return AgentRunState(
            run_id=run_id,
            owner_id=request.owner_id,
            request=request,
            remaining_tool_rounds=request.max_tool_rounds,
            applied_trace_sequence=0,
            metadata=AgentRunMetadata.with_runtime(
                request.metadata,
                history_started_at=datetime.now(timezone.utc).isoformat(),
            ),
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
            usage=_aggregate_run_usage(state),
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

    def _get_agent_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")

        return register.get_state(run_id, principal_scope=principal_scope)

    def _save_agent_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")

        register.save_state(state, principal_scope=principal_scope)

    def _create_agent_state(
        self,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")
        register.create_state(state, principal_scope=principal_scope)

    def _append_agent_trace_event(
        self,
        run_id: str,
        event: AgentTraceEvent,
    ) -> None:
        register = self._runtime.agent_trace_register
        if register is None:
            raise AgentStateError("Agent trace register is not configured")

        self._tag_agent_trace_event(run_id, event)
        event.sequence = register.append_event(run_id, event)

    def _tag_agent_trace_event(
        self,
        run_id: str,
        event: AgentTraceEvent,
        *,
        owner_id: str | None = None,
    ) -> None:
        if event.trace_id is None:
            event.trace_id = run_id
        if event.source is None:
            event.source = "agent"
        if event.subject is None:
            event.subject = TraceSubject(
                kind="agent_run",
                subject_id=run_id,
                owner_id=owner_id,
            )


class _AgentTraceStream:
    def __init__(self, events: AsyncIterator[AgentTraceEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[AgentTraceEvent]:
        return self._events
