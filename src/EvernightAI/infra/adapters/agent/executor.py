import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, cast
from uuid import uuid4

from EvernightAI.core.error.agent import (
    AgentRunCanceledError,
    AgentRunTimeoutError,
    AgentStateError,
)
from EvernightAI.core.protocol.agent import (
    AgentRunExecutorProtocol,
    AgentRunOperation,
    AgentRunStreamOperation,
    AgentRunStateRegisterProtocol,
)
from EvernightAI.core.schema.agent import AgentRunState, AgentTraceEvent


class SingleProcessAgentRunExecutor(AgentRunExecutorProtocol):
    def __init__(
        self,
        lease_register: AgentRunStateRegisterProtocol,
        *,
        lease_ttl_seconds: float = 30.0,
        heartbeat_interval_seconds: float = 10.0,
        default_timeout_seconds: float | None = 300.0,
        executor_id: str | None = None,
    ) -> None:
        self._lease_register = lease_register
        self._lease_ttl_seconds = lease_ttl_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._default_timeout_seconds = default_timeout_seconds
        self._executor_id = executor_id or f"single-process-{uuid4().hex}"
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._cancel_requested: set[str] = set()
        self._closing = False

    async def execute(
        self,
        run_id: str,
        operation: AgentRunOperation,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentRunState:
        if self._closing:
            raise AgentStateError("Agent run executor is closing")
        active = self._tasks.get(run_id)
        if active is not None and not active.done():
            raise AgentStateError(f"The agent run {run_id} is already executing")

        generation = self._lease_register.acquire_lease(
            run_id,
            self._executor_id,
            ttl_seconds=self._lease_ttl_seconds,
        )
        async def invoke() -> AgentRunState:
            return await operation()

        task = asyncio.create_task(invoke(), name=f"evernight-agent-{run_id}")
        self._tasks[run_id] = task
        heartbeat = asyncio.create_task(
            self._heartbeat(run_id, generation),
            name=f"evernight-agent-heartbeat-{run_id}",
        )
        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        try:
            if timeout is None:
                return await task
            return await asyncio.wait_for(task, timeout=timeout)
        except TimeoutError as exc:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise AgentRunTimeoutError(
                f"The agent run {run_id} exceeded {timeout} seconds"
            ) from exc
        except asyncio.CancelledError as exc:
            if run_id in self._cancel_requested:
                raise AgentRunCanceledError(
                    f"The agent run {run_id} was canceled"
                ) from exc
            raise
        finally:
            await self._finish_execution(
                run_id,
                generation,
                heartbeat,
            )

    def stream(
        self,
        run_id: str,
        operation: AgentRunStreamOperation,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        return self._stream_events(
            run_id,
            operation,
            timeout_seconds=timeout_seconds,
        )

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        self._cancel_requested.add(run_id)
        task.cancel()
        return True

    async def close(self) -> None:
        self._closing = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _heartbeat(self, run_id: str, generation: int) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            renewed = self._lease_register.heartbeat_lease(
                run_id,
                self._executor_id,
                generation,
                ttl_seconds=self._lease_ttl_seconds,
            )
            if not renewed:
                task = self._tasks.get(run_id)
                if task is not None:
                    task.cancel()
                return

    async def _stream_events(
        self,
        run_id: str,
        operation: AgentRunStreamOperation,
        *,
        timeout_seconds: float | None,
    ) -> AsyncIterator[AgentTraceEvent]:
        if self._closing:
            raise AgentStateError("Agent run executor is closing")
        active = self._tasks.get(run_id)
        if active is not None and not active.done():
            raise AgentStateError(f"The agent run {run_id} is already executing")

        generation = self._lease_register.acquire_lease(
            run_id,
            self._executor_id,
            ttl_seconds=self._lease_ttl_seconds,
        )
        task = asyncio.current_task()
        if task is None:
            self._lease_register.release_lease(
                run_id,
                self._executor_id,
                generation,
            )
            raise AgentStateError("Agent stream is not running in an asyncio task")
        self._tasks[run_id] = cast(asyncio.Task[Any], task)
        heartbeat = asyncio.create_task(
            self._heartbeat(run_id, generation),
            name=f"evernight-agent-heartbeat-{run_id}",
        )
        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        try:
            async with asyncio.timeout(timeout):
                async for event in operation():
                    yield event
        except TimeoutError as exc:
            raise AgentRunTimeoutError(
                f"The agent run {run_id} exceeded {timeout} seconds"
            ) from exc
        except asyncio.CancelledError as exc:
            if run_id in self._cancel_requested:
                raise AgentRunCanceledError(
                    f"The agent run {run_id} was canceled"
                ) from exc
            raise
        finally:
            await self._finish_execution(
                run_id,
                generation,
                heartbeat,
            )

    async def _finish_execution(
        self,
        run_id: str,
        generation: int,
        heartbeat: asyncio.Task[None],
    ) -> None:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        self._tasks.pop(run_id, None)
        self._cancel_requested.discard(run_id)
        self._lease_register.release_lease(
            run_id,
            self._executor_id,
            generation,
        )
