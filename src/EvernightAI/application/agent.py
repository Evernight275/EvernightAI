import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from weakref import WeakKeyDictionary
from time import perf_counter
from uuid import uuid4

from EvernightAI.core.error.agent import (
    AgentRunCanceledError,
    AgentRunTimeoutError,
    AgentShutdownError,
    AgentStateError,
)
from EvernightAI.core.error.tool import ToolExecutionError
from EvernightAI.core.domain.provider import merge_chat_usage
from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
)
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
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
    ToolExecutionResolution,
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
    ToolReplayPolicy,
)
from EvernightAI.application.chat_request import ChatRequestComposer
from EvernightAI.application.retry import mark_retry_messages
from EvernightAI.application.memory import (
    write_memory_candidate,
)

LOGGER = logging.getLogger("EvernightAI.application.agent")
_AGENT_RUN_LIFECYCLES: WeakKeyDictionary[object, "_AgentRunLifecycle"] = (
    WeakKeyDictionary()
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


def _owner_scope(owner_id: str | None) -> PrincipalScope | None:
    return PrincipalScope(owner_id=owner_id) if owner_id is not None else None


def _require_request_scope(
    request: AgentRunRequest,
    principal_scope: PrincipalScope | None,
) -> None:
    if principal_scope is not None and not principal_scope.permits(request.owner_id):
        raise AgentStateError("Agent run owner does not match the principal scope")


def _agent_run_lifecycle(runtime: RuntimeProtocol) -> "_AgentRunLifecycle":
    key = runtime
    lifecycle = _AGENT_RUN_LIFECYCLES.get(key)
    if lifecycle is None:
        lifecycle = _AgentRunLifecycle()
        _AGENT_RUN_LIFECYCLES[key] = lifecycle

    return lifecycle


class _AgentRunLifecycle:
    def __init__(self) -> None:
        self._closing = False
        self._active_count = 0
        self._condition = asyncio.Condition()

    @asynccontextmanager
    async def active_run(self) -> AsyncIterator[None]:
        await self._enter_run()
        try:
            yield
        finally:
            await self._exit_run()

    async def track_stream(
        self,
        events: AsyncIterator[AgentTraceEvent],
    ) -> AsyncIterator[AgentTraceEvent]:
        async with self.active_run():
            async for event in events:
                yield event

    async def close(
        self,
        *,
        state_register: AgentRunStateRegisterProtocol | None,
        trace_register: AgentTraceRegisterProtocol | None,
        tool_execution_register: ToolExecutionRegisterProtocol | None,
    ) -> None:
        async with self._condition:
            if not self._closing:
                LOGGER.info("EvernightAI agent shutdown: blocking new agent runs")
                self._closing = True

            if self._active_count:
                LOGGER.info(
                    "EvernightAI agent shutdown: waiting for %s active agent run(s)",
                    self._active_count,
                )

            while self._active_count:
                await self._condition.wait()

        LOGGER.info("EvernightAI agent shutdown: active agent runs drained")
        self._pause_running_states(
            state_register=state_register,
            trace_register=trace_register,
            tool_execution_register=tool_execution_register,
        )
        LOGGER.info("EvernightAI agent shutdown: persisted running states reconciled")

    async def _enter_run(self) -> None:
        async with self._condition:
            if self._closing:
                raise AgentShutdownError("Agent runs are shutting down")
            self._active_count += 1

    async def _exit_run(self) -> None:
        async with self._condition:
            self._active_count -= 1
            if self._active_count <= 0:
                self._active_count = 0
                self._condition.notify_all()

    def _pause_running_states(
        self,
        *,
        state_register: AgentRunStateRegisterProtocol | None,
        trace_register: AgentTraceRegisterProtocol | None,
        tool_execution_register: ToolExecutionRegisterProtocol | None,
    ) -> None:
        if state_register is None:
            return

        for state in state_register.list_states():
            if state.status is not AgentRunStatus.RUNNING:
                continue

            trace_events = (
                trace_register.list_events(state.run_id)
                if trace_register is not None
                else state.trace
            )
            tool_executions = (
                tool_execution_register.list_attempts(state.run_id)
                if tool_execution_register is not None
                else None
            )
            if tool_execution_register is not None and tool_executions is not None:
                tool_executions = _mark_started_executions_unknown(
                    tool_execution_register,
                    tool_executions,
                )
            checkpoint = inspect_agent_run_checkpoint(
                state,
                trace_events,
                tool_executions,
            )

            event = AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_PAUSED,
                summary="Agent run paused: shutdown",
                metadata={
                    "reason": "shutdown",
                    "source": "shutdown",
                    "checkpoint": checkpoint.name,
                    "recovery_eligible": checkpoint.eligible,
                },
            )
            state.status = AgentRunStatus.PAUSED
            state.stop_reason = None
            state.metadata = AgentRunMetadata.with_runtime(
                state.metadata,
                **{AgentRunMetadata.MANUAL_PAUSE_KEY: checkpoint.eligible},
                **{AgentRunMetadata.PAUSE_CHECKPOINT_KEY: checkpoint.name},
                **{AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: checkpoint.eligible},
                **{AgentRunMetadata.RECOVERY_REASON_KEY: "shutdown"},
                **{AgentRunMetadata.PAUSE_SOURCE_KEY: "shutdown"},
                shutdown_reason="shutdown",
            )
            state.trace.append(event)
            if trace_register is not None:
                event.sequence = trace_register.append_event(state.run_id, event)
            state_register.save_state(state)


class AgentRunMetadata:
    RUN_ID_KEY = "run_id"
    RUNTIME_KEY = "agent_runtime"
    PENDING_APPROVAL_COUNT_KEY = "pending_approval_count"
    TOOL_ROUNDS_USED_KEY = "tool_rounds_used"
    MANUAL_PAUSE_KEY = "manual_pause"
    PAUSE_REQUESTED_KEY = "pause_requested"
    PAUSE_CHECKPOINT_KEY = "pause_checkpoint"
    PAUSE_SOURCE_KEY = "pause_source"
    RECOVERY_ELIGIBLE_KEY = "recovery_eligible"
    RECOVERY_REASON_KEY = "recovery_reason"
    RETRY_OF_KEY = "retry_of"
    RETRY_ATTEMPT_KEY = "retry_attempt"

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


@dataclass(frozen=True)
class AgentRunRecoveryCheckpoint:
    eligible: bool
    name: str
    detail: str | None = None


@dataclass(frozen=True)
class AgentRunRetryPlan:
    source: AgentRunState
    request: AgentRunRequest
    retried_run_id: str
    abandon_unrecoverable_pause: bool = False


@dataclass(frozen=True)
class AbandonedToolExecution:
    tool_call_id: str
    attempt: int

    def to_trace_metadata(self) -> dict[str, object]:
        return {
            "tool_call_id": self.tool_call_id,
            "attempt": self.attempt,
        }


def inspect_agent_run_checkpoint(
    state: AgentRunState,
    trace_events: list[AgentTraceEvent] | None = None,
    tool_executions: list[ToolExecutionAttempt] | None = None,
) -> AgentRunRecoveryCheckpoint:
    """Restore checkpoint data from persisted trace and classify resumption safety."""
    events = trace_events if trace_events is not None else state.trace
    _restore_checkpoint_data(state, events)

    if state.response is None:
        if any(step.step_type is not AgentStepType.START for step in state.steps):
            return AgentRunRecoveryCheckpoint(
                eligible=False,
                name="incomplete_trace",
                detail="A persisted run step has no model response checkpoint",
            )
        return AgentRunRecoveryCheckpoint(eligible=True, name="run_started")

    response_tool_calls = list(state.response.message.tool_calls or [])
    completed_tool_call_ids = {
        step.tool_call.tool_call_id
        for step in state.steps
        if step.step_type in {AgentStepType.TOOL, AgentStepType.TOOL_ERROR}
        and step.tool_call is not None
    }
    incomplete_tool_calls = [
        call
        for call in response_tool_calls
        if call.tool_call_id not in completed_tool_call_ids
    ]
    if incomplete_tool_calls:
        pending_approval_call_ids = {
            request.tool_call_id for request in state.pending_approval_requests
        }
        if pending_approval_call_ids and all(
            call.tool_call_id in pending_approval_call_ids
            for call in incomplete_tool_calls
        ):
            return AgentRunRecoveryCheckpoint(
                eligible=True,
                name="approval_pending",
            )
        if tool_executions is not None:
            latest_attempts = _latest_tool_execution_attempts(tool_executions)
            if all(
                _tool_call_can_resume(call.tool_call_id, latest_attempts)
                for call in incomplete_tool_calls
            ):
                return AgentRunRecoveryCheckpoint(
                    eligible=True,
                    name="tool_replay_ready",
                )
        return AgentRunRecoveryCheckpoint(
            eligible=False,
            name="tool_execution_incomplete",
            detail="A tool call has no persisted completion result",
        )

    return AgentRunRecoveryCheckpoint(
        eligible=True,
        name=("tool_round_completed" if response_tool_calls else "chat_completed"),
    )


def _latest_tool_execution_attempts(
    attempts: list[ToolExecutionAttempt],
) -> dict[str, ToolExecutionAttempt]:
    latest: dict[str, ToolExecutionAttempt] = {}
    for attempt in attempts:
        current = latest.get(attempt.tool_call_id)
        if current is None or attempt.attempt > current.attempt:
            latest[attempt.tool_call_id] = attempt
    return latest


def _tool_call_can_resume(
    tool_call_id: str,
    latest_attempts: dict[str, ToolExecutionAttempt],
) -> bool:
    attempt = latest_attempts.get(tool_call_id)
    if attempt is None or attempt.status is ToolExecutionStatus.SCHEDULED:
        return True
    if attempt.status in {ToolExecutionStatus.COMPLETED, ToolExecutionStatus.FAILED}:
        return True
    if attempt.resolution is ToolExecutionResolution.RETRY:
        return True
    return attempt.replay_policy in {
        ToolReplayPolicy.SAFE,
        ToolReplayPolicy.IDEMPOTENT,
    }


def _restore_checkpoint_data(
    state: AgentRunState,
    events: list[AgentTraceEvent],
) -> None:
    if state.response is None:
        for event in reversed(events):
            if (
                event.event_type is AgentTraceEventType.CHAT_COMPLETED
                and event.response is not None
            ):
                state.response = event.response
                state.steps.append(
                    AgentStep(
                        step_type=AgentStepType.CHAT,
                        response=event.response,
                        message=event.message or event.response.message,
                    )
                )
                break

    completed_tool_call_ids = {
        step.tool_call.tool_call_id
        for step in state.steps
        if step.step_type in {AgentStepType.TOOL, AgentStepType.TOOL_ERROR}
        and step.tool_call is not None
    }
    for event in events:
        if (
            event.event_type
            not in {AgentTraceEventType.TOOL_COMPLETED, AgentTraceEventType.TOOL_FAILED}
            or event.tool_call is None
            or event.tool_call.tool_call_id in completed_tool_call_ids
        ):
            continue
        step_type = (
            AgentStepType.TOOL
            if event.event_type is AgentTraceEventType.TOOL_COMPLETED
            else AgentStepType.TOOL_ERROR
        )
        state.steps.append(
            AgentStep(
                step_type=step_type,
                message=event.message,
                tool_call=event.tool_call,
                tool_result=event.tool_result,
                error_type=event.error_type,
                error_message=event.error_message,
            )
        )
        completed_tool_call_ids.add(event.tool_call.tool_call_id)


def recover_interrupted_agent_runs(
    state_register: AgentRunStateRegisterProtocol,
    trace_register: AgentTraceRegisterProtocol,
    tool_execution_register: ToolExecutionRegisterProtocol | None = None,
) -> int:
    recovered = 0
    now = datetime.now(timezone.utc)
    for state in state_register.query_states(status=AgentRunStatus.RUNNING):
        lease = state_register.get_execution_lease(state.run_id)
        if (
            lease is not None
            and lease.expires_at is not None
            and lease.expires_at > now
        ):
            continue

        recovery_reason = "lease_expired" if lease is not None else "shutdown"
        tool_executions = (
            tool_execution_register.list_attempts(state.run_id)
            if tool_execution_register is not None
            else None
        )
        if tool_execution_register is not None and tool_executions is not None:
            tool_executions = _mark_started_executions_unknown(
                tool_execution_register,
                tool_executions,
            )
        checkpoint = inspect_agent_run_checkpoint(
            state,
            trace_register.list_events(state.run_id),
            tool_executions,
        )
        event = AgentTraceEvent(
            event_type=AgentTraceEventType.RUN_PAUSED,
            summary=f"Agent run paused: {recovery_reason}",
            metadata={
                "reason": recovery_reason,
                "source": "startup_recovery",
                "checkpoint": checkpoint.name,
                "recovery_eligible": checkpoint.eligible,
            },
        )
        event.sequence = trace_register.append_event(state.run_id, event)
        state.status = AgentRunStatus.PAUSED
        state.stop_reason = None
        state.trace.append(event)
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: checkpoint.eligible},
            **{AgentRunMetadata.PAUSE_CHECKPOINT_KEY: checkpoint.name},
            **{AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: checkpoint.eligible},
            **{AgentRunMetadata.RECOVERY_REASON_KEY: recovery_reason},
            **{AgentRunMetadata.PAUSE_SOURCE_KEY: recovery_reason},
        )
        state.metadata["interrupted"] = True
        state.metadata["interruption_reason"] = "runtime_restart"
        state_register.save_state(state)
        if lease is not None:
            state_register.clear_execution_lease(state.run_id)
        recovered += 1
    return recovered


def _mark_started_executions_unknown(
    register: ToolExecutionRegisterProtocol,
    attempts: list[ToolExecutionAttempt],
) -> list[ToolExecutionAttempt]:
    reconciled: list[ToolExecutionAttempt] = []
    for attempt in attempts:
        if attempt.status is ToolExecutionStatus.STARTED:
            attempt = attempt.model_copy(
                update={"status": ToolExecutionStatus.UNKNOWN}
            )
            register.save_attempt(attempt)
        reconciled.append(attempt)
    return reconciled


class AgentApplication(AgentInterfaceProtocol):
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

    async def start_agent_run(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        stored_request, state = self._prepare_agent_run(
            request,
            principal_scope=principal_scope,
        )
        return await self._execute_prepared_agent_run(
            stored_request,
            state,
            principal_scope=principal_scope,
        )

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

    async def _execute_prepared_agent_run(
        self,
        stored_request: AgentRunRequest,
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        async with self._lifecycle.active_run():
            async for event in self._run_agent_events(stored_request, state):
                self._append_agent_trace_event(state.run_id, event)
                self._save_agent_state(state, principal_scope=principal_scope)

            self._save_agent_state(state, principal_scope=principal_scope)
            return state

    async def resume_agent_run(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        async with self._lifecycle.active_run():
            state = self._get_agent_state(run_id, principal_scope=principal_scope)
            async for event in self._resume_agent_events(state, approvals):
                self._append_agent_trace_event(state.run_id, event)
                self._save_agent_state(state, principal_scope=principal_scope)

            self._save_agent_state(state, principal_scope=principal_scope)
            return state

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
            tools=request.tools,
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
            raise AgentStateError(
                "Agent run cannot resume safely; retry it instead"
            )
        if self._is_manual_pause(state):
            async for event in self._resume_manual_pause_events(state):
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

    async def _resume_manual_pause_events(
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
                approvals=self._tool_approvals_by_call_id(
                    state.request.tool_approvals
                ),
                pending_tool_calls=remaining_tool_calls,
                already_requested_approval_call_ids=set(),
            ):
                yield event
            return

        if response_tool_calls:
            async for event in self._continue_after_completed_tool_round(
                state.request,
                state,
                approvals=self._tool_approvals_by_call_id(
                    state.request.tool_approvals
                ),
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

    def _is_manual_pause(self, state: AgentRunState) -> bool:
        runtime_metadata = state.metadata.get(AgentRunMetadata.RUNTIME_KEY)
        return (
            isinstance(runtime_metadata, dict)
            and runtime_metadata.get(AgentRunMetadata.MANUAL_PAUSE_KEY) is True
        )

    def _is_recovery_eligible(self, state: AgentRunState) -> bool:
        runtime_metadata = state.metadata.get(AgentRunMetadata.RUNTIME_KEY)
        return not (
            isinstance(runtime_metadata, dict)
            and runtime_metadata.get(AgentRunMetadata.RECOVERY_ELIGIBLE_KEY) is False
        )

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

                tool_started = perf_counter()
                try:
                    tool_result = await self._execute_tool_call(state, call)
                    self._log_tool_execution(
                        state,
                        call,
                        started=tool_started,
                        success=True,
                    )
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
                    self._log_tool_execution(
                        state,
                        call,
                        started=tool_started,
                        success=False,
                        error=exc,
                    )
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
                        await self._commit_run_transcript(request.context_id, state)
                        async for event in self._write_memory_events(request, state):
                            yield event
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
        await self._commit_run_transcript(request.context_id, state)
        async for event in self._write_memory_events(request, state):
            yield event
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
            tools=request.tools,
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
                response=response,
                message=response.message,
            )
        )

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
            and latest.status in {ToolExecutionStatus.STARTED, ToolExecutionStatus.UNKNOWN}
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
        if not self._should_stream_chat(metadata):
            response = await self._chat(
                provider_id,
                context_id,
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

        async for event in stream:
            if event.response_id is not None:
                response_id = event.response_id
            if event.model_id is not None:
                model_id = event.model_id
            if event.finish_reason is not None:
                finish_reason = event.finish_reason
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

        text = "".join(text_deltas)
        content = [ContentPart(type=ContentPartType.TEXT, text=text)] if text else None
        response = ChatResponse(
            response_id=response_id,
            model_id=model_id,
            message=Content(
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
        for message in self._run_transcript(state):
            await self._runtime.contexts.append(
                context_id,
                message,
                principal_scope=principal_scope,
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
        if event.summary is None:
            event = event.model_copy(update={"summary": self._trace_summary(event)})
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

    def _new_run_state(self, request: AgentRunRequest) -> AgentRunState:
        run_id = AgentRunMetadata.run_id(request.metadata)
        if run_id is None:
            run_id = uuid4().hex

        return AgentRunState(
            run_id=run_id,
            owner_id=request.owner_id,
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


class AgentRunApplication(AgentRunInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime
        self._agent = AgentApplication(runtime)
        self._lifecycle = _agent_run_lifecycle(runtime)

    async def start(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        _require_request_scope(request, principal_scope)
        await self._runtime.contexts.get(
            request.context_id,
            principal_scope=principal_scope,
        )
        await mark_retry_messages(
            self._runtime,
            request.context_id,
            request.retry_from_message_index,
            principal_scope=principal_scope,
        )
        stored_request, state = self._agent._prepare_agent_run(
            request,
            principal_scope=principal_scope,
        )
        executor = self._runtime.agent_run_executor
        if executor is None:
            try:
                return await self._agent._execute_prepared_agent_run(
                    stored_request,
                    state,
                    principal_scope=principal_scope,
                )
            except Exception as exc:
                self._mark_failed(
                    state.run_id,
                    exc,
                    principal_scope=principal_scope,
                )
                raise
        try:
            return await executor.execute(
                state.run_id,
                lambda: self._agent._execute_prepared_agent_run(
                    stored_request,
                    state,
                    principal_scope=principal_scope,
                ),
                timeout_seconds=request.timeout_seconds,
            )
        except AgentRunTimeoutError:
            self._mark_interrupted(
                state.run_id,
                "timeout",
                principal_scope=principal_scope,
            )
            raise
        except AgentRunCanceledError:
            raise
        except Exception as exc:
            self._mark_failed(
                state.run_id,
                exc,
                principal_scope=principal_scope,
            )
            raise

    async def resume(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        executor = self._runtime.agent_run_executor
        if executor is None:
            try:
                return await self._agent.resume_agent_run(
                    run_id,
                    approvals,
                    principal_scope=principal_scope,
                )
            except Exception as exc:
                self._mark_failed(
                    run_id,
                    exc,
                    principal_scope=principal_scope,
                )
                raise
        state = self.get_state(run_id, principal_scope=principal_scope)
        try:
            return await executor.execute(
                run_id,
                lambda: self._agent.resume_agent_run(
                    run_id,
                    approvals,
                    principal_scope=principal_scope,
                ),
                timeout_seconds=state.request.timeout_seconds,
            )
        except AgentRunTimeoutError:
            self._mark_interrupted(
                run_id,
                "timeout",
                principal_scope=principal_scope,
            )
            raise
        except AgentRunCanceledError:
            raise
        except Exception as exc:
            self._mark_failed(
                run_id,
                exc,
                principal_scope=principal_scope,
            )
            raise

    async def pause(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        state = self.get_state(run_id, principal_scope=principal_scope)
        if state.status is AgentRunStatus.PAUSED:
            return state
        if state.status is not AgentRunStatus.RUNNING:
            raise AgentStateError("Agent run is not running")

        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.PAUSE_REQUESTED_KEY: True},
            pause_reason=reason or "pause",
        )
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )
        return state

    async def cancel(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        state = self.get_state(run_id, principal_scope=principal_scope)
        if state.status is AgentRunStatus.CANCELED:
            return state
        if state.status in {AgentRunStatus.FINISHED, AgentRunStatus.FAILED}:
            raise AgentStateError("Agent run is already stopped")

        executor = self._runtime.agent_run_executor
        if executor is not None:
            executor.cancel(run_id)

        metadata = {"reason": "canceled"}
        if reason:
            metadata["control_reason"] = reason
        event = self._agent._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_STOPPED,
                metadata=metadata,
            ),
        )
        state.status = AgentRunStatus.CANCELED
        state.stop_reason = None
        state.pending_tool_calls = []
        state.pending_approval_requests = []
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: False},
            cancel_reason=reason or "canceled",
        )
        event.sequence = self._trace_register().append_event(run_id, event)
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )
        return state

    async def retry(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        plan = self._retry_plan(run_id, principal_scope=principal_scope)
        if plan.abandon_unrecoverable_pause:
            self._abandon_unrecoverable_pause(
                plan.source,
                retried_run_id=plan.retried_run_id,
                principal_scope=principal_scope,
            )
        retried = await self.start(plan.request, principal_scope=principal_scope)
        return retried

    def _retry_plan(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunRetryPlan:
        source = self.get_state(run_id, principal_scope=principal_scope)
        abandon_unrecoverable_pause = self._is_unrecoverable_pause(source)
        if not self._can_retry(source, abandon_unrecoverable_pause):
            raise AgentStateError(
                "Only canceled, failed, or unrecoverable paused agent runs can be retried"
            )
        request = self._retry_request(source)
        retried_run_id = AgentRunMetadata.run_id(request.metadata)
        if retried_run_id is None:
            raise AgentStateError("Retry request did not allocate a run id")
        return AgentRunRetryPlan(
            source=source,
            request=request,
            retried_run_id=retried_run_id,
            abandon_unrecoverable_pause=abandon_unrecoverable_pause,
        )

    def _is_unrecoverable_pause(self, state: AgentRunState) -> bool:
        runtime_metadata = state.metadata.get(AgentRunMetadata.RUNTIME_KEY)
        return (
            state.status is AgentRunStatus.PAUSED
            and isinstance(runtime_metadata, dict)
            and runtime_metadata.get(AgentRunMetadata.RECOVERY_ELIGIBLE_KEY) is False
        )

    def _can_retry(
        self,
        state: AgentRunState,
        abandon_unrecoverable_pause: bool,
    ) -> bool:
        return state.status in {
            AgentRunStatus.CANCELED,
            AgentRunStatus.FAILED,
        } or abandon_unrecoverable_pause

    def _retry_request(self, source: AgentRunState) -> AgentRunRequest:
        metadata = dict(source.request.metadata)
        retry_run_id = uuid4().hex
        metadata[AgentRunMetadata.RUN_ID_KEY] = retry_run_id
        previous_attempt = metadata.get(AgentRunMetadata.RETRY_ATTEMPT_KEY)
        retry_attempt = previous_attempt + 1 if isinstance(previous_attempt, int) else 1
        metadata[AgentRunMetadata.RETRY_OF_KEY] = source.run_id
        metadata[AgentRunMetadata.RETRY_ATTEMPT_KEY] = retry_attempt
        return source.request.model_copy(
            update={
                "tool_approvals": [],
                "pause_on_approval": True,
                "metadata": metadata,
            }
        )

    def _abandon_unrecoverable_pause(
        self,
        source: AgentRunState,
        *,
        retried_run_id: str,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        abandoned_executions = self._abandon_unrecoverable_tool_executions(
            source,
            principal_scope=principal_scope,
        )
        self._append_retry_resolution_trace(
            source,
            retried_run_id=retried_run_id,
            abandoned_executions=abandoned_executions,
            principal_scope=principal_scope,
        )

    def _abandon_unrecoverable_tool_executions(
        self,
        source: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AbandonedToolExecution]:
        execution_register = self._runtime.tool_execution_register
        if execution_register is None:
            return []

        attempts = execution_register.list_attempts(
            source.run_id,
            principal_scope=principal_scope,
        )
        abandoned: list[AbandonedToolExecution] = []
        resolved_at = datetime.now(timezone.utc)
        for execution in _latest_tool_execution_attempts(attempts).values():
            if not self._should_abandon_for_retry(execution):
                continue
            execution = execution.model_copy(
                update={
                    "resolution": ToolExecutionResolution.ABANDON_AND_RETRY_RUN,
                    "resolution_reason": "run_retried",
                    "resolved_at": resolved_at,
                }
            )
            execution_register.save_attempt(
                execution,
                principal_scope=principal_scope,
            )
            abandoned.append(
                AbandonedToolExecution(
                    tool_call_id=execution.tool_call_id,
                    attempt=execution.attempt,
                )
            )
        return abandoned

    def _should_abandon_for_retry(self, execution: ToolExecutionAttempt) -> bool:
        return (
            execution.status is ToolExecutionStatus.UNKNOWN
            and execution.replay_policy is ToolReplayPolicy.NON_REPLAYABLE
            and execution.resolution is None
        )

    def _append_retry_resolution_trace(
        self,
        source: AgentRunState,
        *,
        retried_run_id: str,
        abandoned_executions: list[AbandonedToolExecution],
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        event = self._agent._add_trace(
            source,
            AgentTraceEvent(
                event_type=AgentTraceEventType.TOOL_EXECUTION_RESOLVED,
                metadata={
                    "resolution": ToolExecutionResolution.ABANDON_AND_RETRY_RUN.value,
                    "retried_run_id": retried_run_id,
                    "tool_executions": [
                        execution.to_trace_metadata()
                        for execution in abandoned_executions
                    ],
                },
            ),
        )
        event.sequence = self._trace_register().append_event(source.run_id, event)
        self._state_register().save_state(
            source,
            principal_scope=principal_scope,
        )

    def start_stream(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentTraceStreamProtocol:
        _require_request_scope(request, principal_scope)
        self._runtime.context_register.get(
            request.context_id,
            principal_scope=principal_scope,
        )
        stored_request = (
            request
            if request.pause_on_approval
            else request.model_copy(update={"pause_on_approval": True})
        )
        state = self._agent._new_run_state(stored_request)
        self._state_register().create_state(
            state,
            principal_scope=principal_scope,
        )
        events = self._lifecycle.track_stream(
            self._stream_and_store(
                self._start_stream_events(stored_request, state),
                state,
                principal_scope=principal_scope,
            )
        )
        executor = self._runtime.agent_run_executor
        if executor is not None:
            base_events = events
            events = self._interrupt_timed_out_stream(
                state.run_id,
                executor.stream(
                    state.run_id,
                    lambda: base_events,
                    timeout_seconds=stored_request.timeout_seconds,
                ),
                principal_scope=principal_scope,
            )
        return _AgentTraceStream(events)

    def resume_stream(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentTraceStreamProtocol:
        state = self.get_state(run_id, principal_scope=principal_scope)
        events = self._lifecycle.track_stream(
            self._stream_and_store(
                self._agent._resume_agent_events(state, approvals),
                state,
                principal_scope=principal_scope,
            )
        )
        executor = self._runtime.agent_run_executor
        if executor is not None:
            base_events = events
            events = self._interrupt_timed_out_stream(
                run_id,
                executor.stream(
                    run_id,
                    lambda: base_events,
                    timeout_seconds=state.request.timeout_seconds,
                ),
                principal_scope=principal_scope,
            )
        return _AgentTraceStream(events)

    def get_state(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        return self._state_register().get_state(
            run_id,
            principal_scope=principal_scope,
        )

    def list_states(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        status: AgentRunStatus | None = None,
        context_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentRunState]:
        return self._state_register().query_states(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            status=status,
            context_id=context_id,
            principal_scope=principal_scope,
        )

    def list_trace(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[AgentTraceEvent]:
        register = self._trace_register()
        self.get_state(run_id, principal_scope=principal_scope)
        return register.list_events(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def list_tool_executions(
        self,
        run_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ToolExecutionAttempt]:
        self.get_state(run_id, principal_scope=principal_scope)
        return self._tool_execution_register().list_attempts(
            run_id,
            principal_scope=principal_scope,
        )

    async def resolve_tool_execution(
        self,
        run_id: str,
        tool_call_id: str,
        attempt: int,
        resolution: ToolExecutionResolution,
        *,
        result: dict[str, object] | None = None,
        reason: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        state = self.get_state(run_id, principal_scope=principal_scope)
        if state.status is not AgentRunStatus.PAUSED:
            raise AgentStateError("Tool execution resolution requires a paused run")
        if resolution is ToolExecutionResolution.ABANDON_AND_RETRY_RUN:
            raise AgentStateError("Use agent run retry to abandon the current run")

        register = self._tool_execution_register()
        execution = register.get_attempt(
            run_id,
            tool_call_id,
            attempt,
            principal_scope=principal_scope,
        )
        if execution.status is not ToolExecutionStatus.UNKNOWN:
            raise AgentStateError("Only unknown tool executions can be resolved")
        if execution.resolution is not None:
            raise AgentStateError("The tool execution is already resolved")

        now = datetime.now(timezone.utc)
        updates: dict[str, object] = {
            "resolution": resolution,
            "resolution_reason": reason,
            "resolved_at": now,
        }
        tool_result = None
        if resolution is ToolExecutionResolution.CONFIRM_COMPLETED:
            tool_result = ToolCallResult(
                tool_call_id=tool_call_id,
                tool_call_result=result or {"status": "confirmed_completed"},
                metadata={"operator_confirmed": True},
            )
            updates.update(
                {
                    "status": ToolExecutionStatus.COMPLETED,
                    "result": tool_result,
                    "finished_at": now,
                }
            )
        execution = execution.model_copy(update=updates)
        register.save_attempt(execution, principal_scope=principal_scope)

        attempts = register.list_attempts(
            run_id,
            principal_scope=principal_scope,
        )
        eligible = not any(
            item.status is ToolExecutionStatus.UNKNOWN
            and item.replay_policy is ToolReplayPolicy.NON_REPLAYABLE
            and item.resolution is None
            for item in _latest_tool_execution_attempts(attempts).values()
        )
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: eligible},
            **{AgentRunMetadata.PAUSE_CHECKPOINT_KEY: "operator_resolution"},
            **{AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: eligible},
        )
        event = self._agent._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.TOOL_EXECUTION_RESOLVED,
                tool_call=execution.tool_call,
                tool_result=tool_result,
                metadata={
                    "resolution": resolution.value,
                    "attempt": attempt,
                    "reason": reason,
                    "recovery_eligible": eligible,
                },
            ),
        )
        event.sequence = self._trace_register().append_event(run_id, event)
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )
        return state

    async def close(self) -> None:
        await self._lifecycle.close(
            state_register=self._runtime.agent_state_register,
            trace_register=self._runtime.agent_trace_register,
            tool_execution_register=self._runtime.tool_execution_register,
        )
        executor = self._runtime.agent_run_executor
        if executor is not None:
            await executor.close()

    async def _stream_and_store(
        self,
        events: AsyncIterator[AgentTraceEvent],
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        try:
            async for event in events:
                event.sequence = self._trace_register().append_event(
                    state.run_id,
                    event,
                )
                self._state_register().save_state(
                    state,
                    principal_scope=principal_scope,
                )
                yield event
                pause_event = self._pause_at_checkpoint_if_requested(
                    state,
                    event,
                    principal_scope=principal_scope,
                )
                if pause_event is not None:
                    yield pause_event
                    return
        except AgentRunCanceledError:
            raise
        except Exception as exc:
            self._mark_failed(
                state.run_id,
                exc,
                principal_scope=principal_scope,
            )
            raise
        finally:
            stored = self._state_register().get_state(
                state.run_id,
                principal_scope=principal_scope,
            )
            if stored.status is not AgentRunStatus.CANCELED:
                self._state_register().save_state(
                    state,
                    principal_scope=principal_scope,
                )

    async def _start_stream_events(
        self,
        request: AgentRunRequest,
        state: AgentRunState,
    ) -> AsyncIterator[AgentTraceEvent]:
        await mark_retry_messages(
            self._runtime,
            request.context_id,
            request.retry_from_message_index,
            principal_scope=_owner_scope(request.owner_id),
        )
        async for event in self._agent._run_agent_events(request, state):
            yield event

    def _state_register(self) -> AgentRunStateRegisterProtocol:
        register = self._runtime.agent_state_register
        if register is None:
            raise AgentStateError("Agent state register is not configured")

        return register

    def _pause_at_checkpoint_if_requested(
        self,
        state: AgentRunState,
        event: AgentTraceEvent,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentTraceEvent | None:
        if event.event_type not in {
            AgentTraceEventType.RUN_STARTED,
            AgentTraceEventType.CHAT_COMPLETED,
            AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
            AgentTraceEventType.TOOL_APPROVAL_DECIDED,
            AgentTraceEventType.TOOL_COMPLETED,
            AgentTraceEventType.TOOL_FAILED,
            AgentTraceEventType.MEMORY_WRITTEN,
        }:
            return None

        stored = self._state_register().get_state(
            state.run_id,
            principal_scope=principal_scope,
        )
        runtime_metadata = stored.metadata.get(AgentRunMetadata.RUNTIME_KEY)
        if (
            stored.status is not AgentRunStatus.RUNNING
            or not isinstance(runtime_metadata, dict)
            or runtime_metadata.get(AgentRunMetadata.PAUSE_REQUESTED_KEY) is not True
        ):
            return None

        checkpoint = event.event_type.value
        pause_reason = runtime_metadata.get("pause_reason")
        state.status = AgentRunStatus.PAUSED
        state.stop_reason = None
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: True},
            **{AgentRunMetadata.PAUSE_REQUESTED_KEY: False},
            **{AgentRunMetadata.PAUSE_CHECKPOINT_KEY: checkpoint},
            **{AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: True},
            **{AgentRunMetadata.RECOVERY_REASON_KEY: "manual_pause"},
            **{AgentRunMetadata.PAUSE_SOURCE_KEY: "manual_pause"},
            pause_reason=pause_reason if isinstance(pause_reason, str) else "pause",
        )
        pause_event = self._agent._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_PAUSED,
                metadata={
                    "reason": "pause",
                    "control_reason": (
                        pause_reason if isinstance(pause_reason, str) else "pause"
                    ),
                    "checkpoint": checkpoint,
                },
            ),
        )
        pause_event.sequence = self._trace_register().append_event(
            state.run_id,
            pause_event,
        )
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )
        return pause_event

    def _trace_register(self) -> AgentTraceRegisterProtocol:
        register = self._runtime.agent_trace_register
        if register is None:
            raise AgentStateError("Agent trace register is not configured")

        return register

    def _tool_execution_register(self) -> ToolExecutionRegisterProtocol:
        register = self._runtime.tool_execution_register
        if register is None:
            raise AgentStateError("Tool execution register is not configured")
        return register

    def _mark_interrupted(
        self,
        run_id: str,
        reason: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        state = self.get_state(run_id, principal_scope=principal_scope)
        if state.status is not AgentRunStatus.RUNNING:
            return
        checkpoint = inspect_agent_run_checkpoint(
            state,
            self._trace_register().list_events(run_id),
            self._reconcile_tool_executions(run_id, principal_scope),
        )
        event = self._agent._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_PAUSED,
                metadata={
                    "reason": reason,
                    "interrupted": True,
                    "checkpoint": checkpoint.name,
                    "recovery_eligible": checkpoint.eligible,
                },
            ),
        )
        event.sequence = self._trace_register().append_event(run_id, event)
        state.status = AgentRunStatus.PAUSED
        state.stop_reason = None
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            **{AgentRunMetadata.MANUAL_PAUSE_KEY: checkpoint.eligible},
            **{AgentRunMetadata.PAUSE_CHECKPOINT_KEY: checkpoint.name},
            **{AgentRunMetadata.RECOVERY_ELIGIBLE_KEY: checkpoint.eligible},
            **{AgentRunMetadata.RECOVERY_REASON_KEY: reason},
            **{AgentRunMetadata.PAUSE_SOURCE_KEY: reason},
            interruption_reason=reason,
        )
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )

    def _reconcile_tool_executions(
        self,
        run_id: str,
        principal_scope: PrincipalScope | None,
    ) -> list[ToolExecutionAttempt] | None:
        register = self._runtime.tool_execution_register
        if register is None:
            return None
        attempts = register.list_attempts(
            run_id,
            principal_scope=principal_scope,
        )
        reconciled: list[ToolExecutionAttempt] = []
        for attempt in attempts:
            if attempt.status is ToolExecutionStatus.STARTED:
                attempt = attempt.model_copy(
                    update={"status": ToolExecutionStatus.UNKNOWN}
                )
                register.save_attempt(
                    attempt,
                    principal_scope=principal_scope,
                )
            reconciled.append(attempt)
        return reconciled

    def _mark_failed(
        self,
        run_id: str,
        error: Exception,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        state = self.get_state(run_id, principal_scope=principal_scope)
        if state.status is not AgentRunStatus.RUNNING:
            return

        event = self._agent._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_STOPPED,
                error_type=error.__class__.__name__,
                error_message=str(error),
                metadata={"reason": "failed"},
            ),
        )
        event.sequence = self._trace_register().append_event(run_id, event)
        state.status = AgentRunStatus.FAILED
        state.stop_reason = None
        state.pending_tool_calls = []
        state.pending_approval_requests = []
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            failure_type=error.__class__.__name__,
            failure_message=str(error),
        )
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )

    async def _interrupt_timed_out_stream(
        self,
        run_id: str,
        events: AsyncIterator[AgentTraceEvent],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        try:
            async for event in events:
                yield event
        except AgentRunTimeoutError:
            self._mark_interrupted(
                run_id,
                "timeout",
                principal_scope=principal_scope,
            )
            raise
