from dataclasses import dataclass
from datetime import datetime, timezone

from EvernightAI.core.error.agent import (
    AgentStateError,
)
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
from EvernightAI.core.schema.agent import (
    AgentPauseCause,
    AgentRunPause,
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
from EvernightAI.core.schema.tool import (
    ToolReplayPolicy,
)

from EvernightAI.application.agent_state import _aggregate_run_usage


@dataclass(frozen=True)
class AgentRunRecoveryCheckpoint:
    eligible: bool
    name: str
    detail: str | None = None


def inspect_agent_run_checkpoint(
    state: AgentRunState,
    trace_events: list[AgentTraceEvent] | None = None,
    tool_executions: list[ToolExecutionAttempt] | None = None,
) -> AgentRunRecoveryCheckpoint:
    """Restore checkpoint data from persisted trace and classify resumption safety."""
    events = trace_events if trace_events is not None else state.trace
    try:
        _restore_checkpoint_data(state, events)
    except AgentStateError as exc:
        return AgentRunRecoveryCheckpoint(
            eligible=False,
            name="incomplete_trace",
            detail=str(exc),
        )
    if state.status in {
        AgentRunStatus.FINISHED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELED,
    }:
        return AgentRunRecoveryCheckpoint(eligible=False, name="run_stopped")
    if any(
        step.step_type in {AgentStepType.STOP, AgentStepType.MEMORY_WRITE}
        for step in state.steps
    ):
        return AgentRunRecoveryCheckpoint(
            eligible=False,
            name="finalization_incomplete",
            detail="Context or memory writes may already have been committed",
        )

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
    tail = _checkpoint_trace_tail(state, events)
    applied_ids = {step.trace_event_id for step in state.steps if step.trace_event_id}
    for event in tail:
        if event.event_id is not None and event.event_id in applied_ids:
            if event.sequence is not None:
                state.applied_trace_sequence = event.sequence
            continue
        if event.event_type is AgentTraceEventType.CHAT_COMPLETED:
            if event.response is None:
                raise AgentStateError("Completed chat trace has no response")
            remaining = event.metadata.get("remaining_tool_rounds")
            if (
                type(remaining) is int
                and 0 <= remaining <= state.request.max_tool_rounds
            ):
                state.remaining_tool_rounds = remaining
            else:
                completed_chats = sum(
                    step.step_type is AgentStepType.CHAT for step in state.steps
                )
                state.remaining_tool_rounds = max(
                    state.request.max_tool_rounds - completed_chats,
                    0,
                )
            state.response = event.response
            state.pending_tool_calls = []
            state.pending_approval_requests = []
            state.steps.append(
                AgentStep(
                    step_type=AgentStepType.CHAT,
                    trace_event_id=event.event_id,
                    response=event.response,
                    message=event.message or event.response.message,
                )
            )
        elif event.event_type in {
            AgentTraceEventType.TOOL_COMPLETED,
            AgentTraceEventType.TOOL_FAILED,
        }:
            if event.tool_call is None:
                raise AgentStateError("Completed tool trace has no tool call")
            state.steps.append(
                AgentStep(
                    step_type=(
                        AgentStepType.TOOL
                        if event.event_type is AgentTraceEventType.TOOL_COMPLETED
                        else AgentStepType.TOOL_ERROR
                    ),
                    trace_event_id=event.event_id,
                    message=event.message,
                    tool_call=event.tool_call,
                    tool_result=event.tool_result,
                    error_type=event.error_type,
                    error_message=event.error_message,
                )
            )
        elif event.event_type is AgentTraceEventType.TOOL_APPROVAL_REQUESTED:
            if event.approval_request is not None:
                state.pending_approval_requests.append(event.approval_request)
                state.pending_tool_calls = (
                    list(state.response.message.tool_calls or [])
                    if state.response is not None
                    else []
                )
        elif event.event_type is AgentTraceEventType.MEMORY_WRITTEN:
            state.steps.append(
                AgentStep(
                    step_type=AgentStepType.MEMORY_WRITE,
                    trace_event_id=event.event_id,
                    metadata=dict(event.metadata),
                )
            )
        elif event.event_type is AgentTraceEventType.RUN_STOPPED:
            reason = event.metadata.get("reason")
            if reason in {reason.value for reason in AgentStopReason}:
                state.stop_reason = AgentStopReason(reason)
                state.status = (
                    AgentRunStatus.FINISHED
                    if state.stop_reason is AgentStopReason.FINISHED
                    else AgentRunStatus.FAILED
                )
                if not any(
                    step.step_type is AgentStepType.STOP for step in state.steps
                ):
                    state.steps.append(
                        AgentStep(
                            step_type=AgentStepType.STOP,
                            trace_event_id=event.event_id,
                            metadata={"reason": reason},
                        )
                    )
            elif reason in {"failed", "canceled"}:
                state.status = (
                    AgentRunStatus.FAILED
                    if reason == "failed"
                    else AgentRunStatus.CANCELED
                )
                state.stop_reason = None
            else:
                raise AgentStateError("Stopped run trace has no recognized reason")
            state.pending_tool_calls = []
            state.pending_approval_requests = []
        if event.event_id is not None:
            applied_ids.add(event.event_id)
        if event.sequence is not None:
            state.applied_trace_sequence = event.sequence
        if event not in state.trace:
            state.trace.append(event)
    state.tool_rounds_used = state.request.max_tool_rounds - state.remaining_tool_rounds
    state.usage = _aggregate_run_usage(state)


def _checkpoint_trace_tail(
    state: AgentRunState,
    events: list[AgentTraceEvent],
) -> list[AgentTraceEvent]:
    saved_events = {
        event.sequence: event for event in state.trace if event.sequence is not None
    }
    for event in events:
        if event.sequence is None:
            continue
        saved = saved_events.get(event.sequence)
        if (
            saved is not None
            and saved.event_id is not None
            and event.event_id is not None
            and saved.event_id != event.event_id
        ):
            raise AgentStateError("Persisted trace sequence has been reused")
    watermark = state.applied_trace_sequence
    if watermark is None:
        sequences = [
            event.sequence for event in state.trace if event.sequence is not None
        ]
        if sequences:
            watermark = max(sequences)
        else:
            # Legacy snapshots lack a cursor. Align their ordered steps before replay.
            if (
                events
                and events[0].sequence is not None
                and events[0].sequence > 1
                and any(
                    step.trace_event_id is None
                    and step.step_type
                    in {
                        AgentStepType.CHAT,
                        AgentStepType.TOOL,
                        AgentStepType.TOOL_ERROR,
                    }
                    for step in state.steps
                )
            ):
                raise AgentStateError("Cannot align legacy snapshot with pruned trace")
            cursor = 0
            for step in state.steps:
                if step.step_type not in {
                    AgentStepType.CHAT,
                    AgentStepType.TOOL,
                    AgentStepType.TOOL_ERROR,
                }:
                    continue
                match = next(
                    (
                        index
                        for index in range(cursor, len(events))
                        if _trace_matches_step(events[index], step)
                    ),
                    None,
                )
                if match is None:
                    if any(
                        e.event_type is AgentTraceEventType.CHAT_COMPLETED
                        for e in events
                    ):
                        raise AgentStateError(
                            "Cannot align legacy snapshot with retained trace"
                        )
                    continue
                cursor = match + 1
            tail = events[cursor:]
            previous = events[cursor - 1].sequence if cursor else 0
            _require_contiguous_trace(tail, previous)
            return tail
    tail = [
        event
        for event in events
        if event.sequence is None or event.sequence > watermark
    ]
    _require_contiguous_trace(tail, watermark)
    return tail


def _trace_matches_step(event: AgentTraceEvent, step: AgentStep) -> bool:
    if step.trace_event_id is not None:
        return event.event_id == step.trace_event_id
    if step.step_type is AgentStepType.CHAT:
        return (
            event.event_type is AgentTraceEventType.CHAT_COMPLETED
            and event.response == step.response
        )
    expected = (
        AgentTraceEventType.TOOL_COMPLETED
        if step.step_type is AgentStepType.TOOL
        else AgentTraceEventType.TOOL_FAILED
    )
    return event.event_type is expected and event.tool_call == step.tool_call


def _require_contiguous_trace(
    events: list[AgentTraceEvent], previous: int | None
) -> None:
    for event in events:
        if event.sequence is None:
            continue
        if previous is not None and event.sequence != previous + 1:
            raise AgentStateError("Persisted trace tail has missing events")
        previous = event.sequence


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

        cause = (
            AgentPauseCause.LEASE_EXPIRED
            if lease is not None
            else AgentPauseCause.UNCLEAN_SHUTDOWN
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
            trace_register.list_events(state.run_id),
            tool_executions,
        )
        if state.status is not AgentRunStatus.RUNNING:
            state_register.save_state(state)
            if lease is not None:
                state_register.clear_execution_lease(state.run_id)
            recovered += 1
            continue
        event = AgentTraceEvent(
            event_type=AgentTraceEventType.RUN_PAUSED,
            summary=f"Agent run paused: {cause.source}",
            metadata={
                "reason": cause.source,
                "source": "startup_recovery",
                "checkpoint": checkpoint.name,
                "recovery_eligible": checkpoint.eligible,
            },
        )
        event.sequence = trace_register.append_event(state.run_id, event)
        state.applied_trace_sequence = event.sequence
        state.status = AgentRunStatus.PAUSED
        state.stop_reason = None
        state.trace.append(event)
        state.pause = AgentRunPause(
            cause=cause,
            checkpoint=checkpoint.name,
            resumable=checkpoint.eligible,
        )
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
            attempt = attempt.model_copy(update={"status": ToolExecutionStatus.UNKNOWN})
            register.save_attempt(attempt)
        reconciled.append(attempt)
    return reconciled
