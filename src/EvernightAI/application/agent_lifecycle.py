import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

from EvernightAI.core.error.agent import (
    AgentShutdownError,
)
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.agent import (
    AgentPauseCause,
    AgentRunPause,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)

from EvernightAI.application.agent_state import LOGGER
from EvernightAI.application.agent_recovery import (
    inspect_agent_run_checkpoint,
    _mark_started_executions_unknown,
)

_AGENT_RUN_LIFECYCLES: WeakKeyDictionary[object, "_AgentRunLifecycle"] = (
    WeakKeyDictionary()
)


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
            if state.status is not AgentRunStatus.RUNNING:
                state_register.save_state(state)
                continue

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
            state.pause = AgentRunPause(
                cause=AgentPauseCause.SHUTDOWN,
                checkpoint=checkpoint.name,
                resumable=checkpoint.eligible,
            )
            state.trace.append(event)
            if trace_register is not None:
                event.sequence = trace_register.append_event(state.run_id, event)
                state.applied_trace_sequence = event.sequence
            state_register.save_state(state)
