import asyncio
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest

from EvernightAI.application.agent import (
    AgentRunApplication,
    recover_interrupted_agent_runs,
)
from EvernightAI.core.error.agent import (
    AgentRunCanceledError,
    AgentRunLeaseLostError,
    AgentRunTimeoutError,
    AgentStateError,
)
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.context import Context
from EvernightAI.infra.adapters.agent.executor import SingleProcessAgentRunExecutor
from EvernightAI.infra.adapters.agent.lease import held_agent_run_lease
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
)
from tests.test_application_agent import (
    BlockingFinalAnswerProvider,
    make_config,
    make_runtime,
)
from tests.test_sqlite_runtime_foundation import _running_state


class _FailingHeartbeatRegister(SQLiteAgentRunStateRegister):
    def heartbeat_lease(self, *args: object, **kwargs: object) -> bool:
        raise sqlite3.OperationalError("database is locked")


@pytest.mark.asyncio
async def test_heartbeat_error_cancels_run_instead_of_running_unleased(
    tmp_path: Path,
) -> None:
    register = _FailingHeartbeatRegister(tmp_path / "runtime.sqlite3")
    register.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(
        register,
        lease_ttl_seconds=30,
        heartbeat_interval_seconds=0.01,
        default_timeout_seconds=None,
    )
    finished_unleased = False

    async def operation() -> AgentRunState:
        nonlocal finished_unleased
        await asyncio.sleep(0.1)
        finished_unleased = True
        return register.get_state("run-1")

    with pytest.raises(AgentStateError, match="lost its execution lease"):
        await executor.execute("run-1", operation)
    assert finished_unleased is False
    assert register.get_execution_lease("run-1") is None
    register.close()


@pytest.mark.asyncio
async def test_stale_executor_cannot_overwrite_recovered_run(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database_path)
    traces = SQLiteAgentTraceRegister(database_path)
    states.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(
        states,
        lease_ttl_seconds=0.05,
        heartbeat_interval_seconds=10,
        default_timeout_seconds=None,
    )

    async def operation() -> AgentRunState:
        state = states.get_state("run-1")
        await asyncio.sleep(0.1)
        assert recover_interrupted_agent_runs(states, traces) == 1
        state.status = AgentRunStatus.FINISHED
        states.save_state(state)
        return state

    with pytest.raises(AgentStateError, match="lost its execution lease"):
        await executor.execute("run-1", operation)

    assert states.get_state("run-1").status is AgentRunStatus.PAUSED
    traces.close()
    states.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("close_stream", [False, True])
async def test_finished_stream_blocks_reentry_until_cleanup(
    tmp_path: Path, close_stream: bool
) -> None:
    states = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    states.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(states, default_timeout_seconds=None)
    producer_finished = asyncio.Event()
    next_started = asyncio.Event()

    async def events():
        yield AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)
        producer_finished.set()

    async def competing_operation() -> AgentRunState:
        return states.get_state("run-1")

    async def operation() -> AgentRunState:
        next_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    stream = cast(
        AsyncGenerator[AgentTraceEvent, None], executor.stream("run-1", events)
    )
    run: asyncio.Task[AgentRunState] | None = None
    try:
        await anext(stream)
        await asyncio.wait_for(producer_finished.wait(), timeout=1)
        lease = states.get_execution_lease("run-1")
        assert lease is not None

        with pytest.raises(AgentStateError, match="already executing"):
            await executor.execute("run-1", competing_operation)
        competing_stream = cast(
            AsyncGenerator[AgentTraceEvent, None], executor.stream("run-1", events)
        )
        with pytest.raises(AgentStateError, match="already executing"):
            await anext(competing_stream)
        assert states.get_execution_lease("run-1") == lease

        if close_stream:
            await stream.aclose()
        else:
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
        assert states.get_execution_lease("run-1") is None

        run = asyncio.create_task(executor.execute("run-1", operation))
        await asyncio.wait_for(next_started.wait(), timeout=1)
        assert executor.cancel("run-1") is True
        with pytest.raises(AgentRunCanceledError):
            await run
        assert states.get_execution_lease("run-1") is None
    finally:
        if run is not None and not run.done():
            executor.cancel("run-1")
            await asyncio.gather(run, return_exceptions=True)
        await stream.aclose()
        states.close()


@pytest.mark.asyncio
async def test_stale_stream_cannot_overwrite_recovered_run(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database_path)
    traces = SQLiteAgentTraceRegister(database_path)
    states.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(
        states,
        lease_ttl_seconds=0.05,
        heartbeat_interval_seconds=10,
        default_timeout_seconds=None,
    )

    async def events():
        state = states.get_state("run-1")
        await asyncio.sleep(0.1)
        assert recover_interrupted_agent_runs(states, traces) == 1
        state.status = AgentRunStatus.FINISHED
        states.save_state(state)
        yield AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)

    with pytest.raises(AgentStateError, match="lost its execution lease"):
        async for _ in executor.stream("run-1", events):
            pass

    assert states.get_state("run-1").status is AgentRunStatus.PAUSED
    state = states.get_state("run-1")
    states.save_state(state)
    traces.close()
    states.close()


class _FailingAfterReleaseProvider(BlockingFinalAnswerProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.started.set()
        await self.release.wait()
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_failure_after_takeover_does_not_fail_new_owners_run(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database_path)
    traces = SQLiteAgentTraceRegister(database_path)
    provider = _FailingAfterReleaseProvider()
    runtime = make_runtime(
        provider=provider,
        agent_state_register=states,
        agent_trace_register=traces,
        agent_run_executor=SingleProcessAgentRunExecutor(
            states,
            lease_ttl_seconds=0.05,
            heartbeat_interval_seconds=10,
            default_timeout_seconds=None,
        ),
    )
    await runtime.contexts.create(Context(context_id="ctx-1"))
    await runtime.providers.create(make_config())
    run = asyncio.create_task(
        AgentRunApplication(runtime).start(
            AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
                metadata={"run_id": "run-1"},
            )
        )
    )
    await provider.started.wait()
    await asyncio.sleep(0.1)
    states.acquire_lease("run-1", "other-owner", ttl_seconds=30)
    provider.release.set()

    with pytest.raises(AgentRunLeaseLostError):
        await run

    state = states.get_state("run-1")
    assert state.status is AgentRunStatus.RUNNING
    assert state.failure is None
    lease = states.get_execution_lease("run-1")
    assert lease is not None and lease.owner == "other-owner"
    traces.close()
    states.close()


@pytest.mark.asyncio
async def test_stream_closed_from_another_task_leaves_consumer_unfenced(
    tmp_path: Path,
) -> None:
    states = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    states.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(states, default_timeout_seconds=None)

    async def events():
        assert held_agent_run_lease.get() is not None
        yield AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)
        await asyncio.Event().wait()
        yield AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)

    stream = executor.stream("run-1", events)
    await anext(stream)
    assert held_agent_run_lease.get() is None
    await asyncio.create_task(stream.aclose())  # type: ignore[attr-defined]

    assert states.get_execution_lease("run-1") is None
    states.save_state(states.get_state("run-1"))
    states.close()


@pytest.mark.asyncio
async def test_timeout_is_recorded_while_lease_is_held(tmp_path: Path) -> None:
    states = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    states.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(states, default_timeout_seconds=None)
    recorded: list[Exception] = []

    def on_failure(error: Exception) -> None:
        recorded.append(error)
        state = states.get_state("run-1")
        state.status = AgentRunStatus.PAUSED
        states.save_state(state)

    async def operation() -> AgentRunState:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    with pytest.raises(AgentRunTimeoutError):
        await executor.execute(
            "run-1", operation, timeout_seconds=0.01, on_failure=on_failure
        )

    assert [type(error) for error in recorded] == [AgentRunTimeoutError]
    assert states.get_state("run-1").status is AgentRunStatus.PAUSED
    assert states.get_execution_lease("run-1") is None
    states.close()
