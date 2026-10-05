import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

from EvernightAI.core.error.agent import (
    AgentRunCanceledError,
    AgentRunTimeoutError,
    AgentStateError,
)
from EvernightAI.core.error.skill import (
    SkillConflictError,
    SkillDisabledError,
    SkillNotFoundError,
)
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.protocol.interface import (
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
)
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
    ToolExecutionAttempt,
    ToolExecutionResolution,
    ToolExecutionStatus,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolCallResult,
    ToolReplayPolicy,
)
from EvernightAI.application.retry import mark_retry_messages

from EvernightAI.application.agent_execution import (
    AgentExecutionApplication,
    _AgentTraceStream,
)
from EvernightAI.application.agent_state import (
    LOGGER,
    AgentRunMetadata,
    AgentRunControl,
    AgentRunRetryPlan,
    AbandonedToolExecution,
    _owner_scope,
    _require_request_scope,
)
from EvernightAI.application.agent_lifecycle import _agent_run_lifecycle
from EvernightAI.application.agent_recovery import (
    inspect_agent_run_checkpoint,
    _latest_tool_execution_attempts,
)


class AgentRunApplication(AgentRunInterfaceProtocol):
    def __init__(
        self,
        runtime: RuntimeProtocol,
        *,
        agent: AgentExecutionApplication | None = None,
    ) -> None:
        self._runtime = runtime
        self._agent = agent if agent is not None else AgentExecutionApplication(runtime)
        self._stream_tasks: set[asyncio.Task[None]] = set()
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
                return await self._run_and_store(
                    self._agent._run_agent_events(stored_request, state),
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
                lambda: self._run_and_store(
                    self._agent._run_agent_events(stored_request, state),
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
        state = self.get_state(run_id, principal_scope=principal_scope)
        if executor is None:
            try:
                return await self._run_and_store(
                    self._agent._resume_agent_events(state, approvals),
                    state,
                    principal_scope=principal_scope,
                )
            except Exception as exc:
                self._mark_failed(
                    run_id,
                    exc,
                    principal_scope=principal_scope,
                )
                raise
        try:
            return await executor.execute(
                run_id,
                lambda: self._run_and_store(
                    self._agent._resume_agent_events(state, approvals),
                    state,
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
        state.applied_trace_sequence = event.sequence
        self._state_register().save_state(
            state,
            principal_scope=principal_scope,
        )
        return state

    async def retry(
        self,
        run_id: str,
        *,
        retried_run_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        plan = self._retry_plan(
            run_id,
            retried_run_id=retried_run_id,
            principal_scope=principal_scope,
        )
        if plan.abandon_unrecoverable_pause:
            self._abandon_unrecoverable_pause(
                plan.source,
                retried_run_id=plan.retried_run_id,
                principal_scope=principal_scope,
            )
        retried = await self.start(plan.request, principal_scope=principal_scope)
        return retried

    def retry_stream(
        self,
        run_id: str,
        *,
        retried_run_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentTraceStreamProtocol:
        plan = self._retry_plan(
            run_id,
            retried_run_id=retried_run_id,
            principal_scope=principal_scope,
        )
        if plan.abandon_unrecoverable_pause:
            self._abandon_unrecoverable_pause(
                plan.source,
                retried_run_id=plan.retried_run_id,
                principal_scope=principal_scope,
            )
        return self.start_stream(plan.request, principal_scope=principal_scope)

    def _retry_plan(
        self,
        run_id: str,
        *,
        retried_run_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunRetryPlan:
        source = self.get_state(run_id, principal_scope=principal_scope)
        abandon_unrecoverable_pause = self._is_unrecoverable_pause(source)
        if not self._can_retry(source, abandon_unrecoverable_pause):
            raise AgentStateError(
                "Only canceled, failed, or unrecoverable paused agent runs can be retried"
            )
        request = self._retry_request(source, retried_run_id=retried_run_id)
        allocated_run_id = AgentRunMetadata.run_id(request.metadata)
        if allocated_run_id is None:
            raise AgentStateError("Retry request did not allocate a run id")
        return AgentRunRetryPlan(
            source=source,
            request=request,
            retried_run_id=allocated_run_id,
            abandon_unrecoverable_pause=abandon_unrecoverable_pause,
        )

    def _is_unrecoverable_pause(self, state: AgentRunState) -> bool:
        return (
            state.status is AgentRunStatus.PAUSED
            and not AgentRunControl.from_state(state).recoverable
        )

    def _can_retry(
        self,
        state: AgentRunState,
        abandon_unrecoverable_pause: bool,
    ) -> bool:
        return (
            state.status
            in {
                AgentRunStatus.CANCELED,
                AgentRunStatus.FAILED,
            }
            or abandon_unrecoverable_pause
        )

    def _retry_request(
        self,
        source: AgentRunState,
        *,
        retried_run_id: str | None = None,
    ) -> AgentRunRequest:
        metadata = dict(source.request.metadata)
        retry_run_id = retried_run_id or uuid4().hex
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
        source.applied_trace_sequence = event.sequence
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
            events = self._keep_stream_running(events)
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
            events = self._keep_stream_running(events)
        return _AgentTraceStream(events)

    async def _keep_stream_running(
        self,
        events: AsyncIterator[AgentTraceEvent],
    ) -> AsyncIterator[AgentTraceEvent]:
        """Keep persisted execution alive when its SSE consumer disconnects."""
        queue: asyncio.Queue[AgentTraceEvent | BaseException | None] = asyncio.Queue()
        connected = True

        async def produce() -> None:
            try:
                async for event in events:
                    if connected:
                        queue.put_nowait(event)
            except (Exception, asyncio.CancelledError) as exc:
                if connected:
                    queue.put_nowait(exc)
            finally:
                if connected:
                    queue.put_nowait(None)

        task = asyncio.create_task(produce(), name="evernight-agent-stream")
        self._stream_tasks.add(task)
        task.add_done_callback(self._stream_tasks.discard)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            connected = False
            while not queue.empty():
                queue.get_nowait()

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
        state.applied_trace_sequence = event.sequence
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
            LOGGER.info("EvernightAI agent shutdown: closing run executor")
            await executor.close()
            LOGGER.info("EvernightAI agent shutdown: run executor closed")

    async def _stream_and_store(
        self,
        events: AsyncIterator[AgentTraceEvent],
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        try:
            async for event in events:
                stored = self.get_state(state.run_id, principal_scope=principal_scope)
                if stored.status is AgentRunStatus.CANCELED:
                    return
                event.sequence = self._trace_register().append_event(
                    state.run_id,
                    event,
                )
                state.applied_trace_sequence = event.sequence
                # Read pending controls before replacing the persisted snapshot.
                pause_event = self._pause_at_checkpoint_if_requested(
                    state,
                    event,
                    principal_scope=principal_scope,
                )
                self._state_register().save_state(
                    state,
                    principal_scope=principal_scope,
                )
                yield event
                if pause_event is None:
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
            stored = self.get_state(state.run_id, principal_scope=principal_scope)
            if stored.status is not AgentRunStatus.CANCELED:
                self._state_register().save_state(
                    state,
                    principal_scope=principal_scope,
                )
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
            if stored.status not in {AgentRunStatus.CANCELED, AgentRunStatus.FAILED}:
                self._state_register().save_state(
                    state,
                    principal_scope=principal_scope,
                )

    async def _run_and_store(
        self,
        events: AsyncIterator[AgentTraceEvent],
        state: AgentRunState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        async with self._lifecycle.active_run():
            async for _ in self._stream_and_store(
                events,
                state,
                principal_scope=principal_scope,
            ):
                pass
        return self.get_state(state.run_id, principal_scope=principal_scope)

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
        stored = self._state_register().get_state(
            state.run_id,
            principal_scope=principal_scope,
        )
        control = AgentRunControl.from_state(stored)
        if stored.status is not AgentRunStatus.RUNNING or not control.pause_requested:
            return None

        if state.status is not AgentRunStatus.RUNNING:
            return None
        if event.event_type not in {
            AgentTraceEventType.RUN_STARTED,
            AgentTraceEventType.CHAT_COMPLETED,
            AgentTraceEventType.TOOL_APPROVAL_REQUESTED,
            AgentTraceEventType.TOOL_APPROVAL_DECIDED,
            AgentTraceEventType.TOOL_COMPLETED,
            AgentTraceEventType.TOOL_FAILED,
        }:
            state.metadata = AgentRunMetadata.with_runtime(
                state.metadata,
                **{AgentRunMetadata.PAUSE_REQUESTED_KEY: True},
                pause_reason=control.pause_reason,
            )
            return None

        checkpoint = event.event_type.value
        pause_reason = control.pause_reason
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
        state.applied_trace_sequence = pause_event.sequence
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
        if state.status is not AgentRunStatus.RUNNING:
            self._state_register().save_state(state, principal_scope=principal_scope)
            return
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
        state.applied_trace_sequence = event.sequence
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

        detail = (
            error.detail
            if isinstance(
                error,
                (
                    SkillConflictError,
                    SkillDisabledError,
                    SkillNotFoundError,
                    ProviderResponseError,
                ),
            )
            else None
        )
        event = self._agent._add_trace(
            state,
            AgentTraceEvent(
                event_type=AgentTraceEventType.RUN_STOPPED,
                error_type=error.__class__.__name__,
                error_message=str(error),
                payload={"error_detail": detail} if detail is not None else None,
                metadata={"reason": "failed"},
            ),
        )
        event.sequence = self._trace_register().append_event(run_id, event)
        state.applied_trace_sequence = event.sequence
        state.status = AgentRunStatus.FAILED
        state.stop_reason = None
        state.pending_tool_calls = []
        state.pending_approval_requests = []
        state.metadata = AgentRunMetadata.with_runtime(
            state.metadata,
            failure_type=error.__class__.__name__,
            failure_message=str(error),
            failure_detail=detail,
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
