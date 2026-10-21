import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from contextvars import Context, copy_context
from typing import Any, TypeVar
from uuid import uuid4

from EvernightAI.core.error.agent import (
    AgentRunCanceledError,
    AgentRunLeaseLostError,
    AgentRunTimeoutError,
    AgentStateError,
)
from EvernightAI.core.protocol.agent import (
    AgentRunExecutorProtocol,
    AgentRunFailureHandler,
    AgentRunOperation,
    AgentRunStateRegisterProtocol,
    AgentRunStreamOperation,
)
from EvernightAI.core.schema.agent import AgentRunState, AgentTraceEvent
from EvernightAI.infra.adapters.agent.lease import (
    HeldAgentRunLease,
    held_agent_run_lease,
)

LOGGER = logging.getLogger("EvernightAI.agent_runs")

T = TypeVar("T")


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
        self._lease_lost: set[str] = set()
        self._closing = False

    async def execute(
        self,
        run_id: str,
        operation: AgentRunOperation,
        *,
        timeout_seconds: float | None = None,
        on_failure: AgentRunFailureHandler | None = None,
    ) -> AgentRunState:
        generation = self._acquire(run_id)
        task = self._start_task(
            run_id,
            generation,
            operation,
            timeout_seconds=timeout_seconds,
            on_failure=on_failure,
        )
        heartbeat = self._start_heartbeat(run_id, generation)
        try:
            return await task
        except asyncio.CancelledError as exc:
            error = self._interruption_error(run_id)
            if error is None:
                raise
            raise error from exc
        finally:
            await self._finish_execution(run_id, generation, heartbeat, task)

    def stream(
        self,
        run_id: str,
        operation: AgentRunStreamOperation,
        *,
        timeout_seconds: float | None = None,
        on_failure: AgentRunFailureHandler | None = None,
    ) -> AsyncIterator[AgentTraceEvent]:
        return self._stream_events(
            run_id,
            operation,
            timeout_seconds=timeout_seconds,
            on_failure=on_failure,
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

    def _acquire(self, run_id: str) -> int:
        if self._closing:
            raise AgentStateError("Agent run executor is closing")
        # A completed producer may still have a stream and heartbeat to clean up.
        if run_id in self._tasks:
            raise AgentStateError(f"The agent run {run_id} is already executing")
        return self._lease_register.acquire_lease(
            run_id,
            self._executor_id,
            ttl_seconds=self._lease_ttl_seconds,
        )

    def _start_task(
        self,
        run_id: str,
        generation: int,
        operation: Callable[[], Awaitable[T]],
        *,
        timeout_seconds: float | None,
        on_failure: AgentRunFailureHandler | None,
    ) -> asyncio.Task[T]:
        # The operation and its failure handling own the lease context; callers
        # awaiting or consuming the run never see it.
        context = self._lease_context(run_id, generation)
        task = asyncio.create_task(
            self._run_operation(run_id, operation, timeout_seconds, on_failure),
            name=f"evernight-agent-{run_id}",
            context=context,
        )
        self._tasks[run_id] = task
        return task

    def _lease_context(self, run_id: str, generation: int) -> Context:
        context = copy_context()
        context.run(
            held_agent_run_lease.set,
            HeldAgentRunLease(run_id, self._executor_id, generation),
        )
        return context

    def _start_heartbeat(self, run_id: str, generation: int) -> asyncio.Task[None]:
        return asyncio.create_task(
            self._heartbeat(run_id, generation),
            name=f"evernight-agent-heartbeat-{run_id}",
        )

    async def _run_operation(
        self,
        run_id: str,
        operation: Callable[[], Awaitable[T]],
        timeout_seconds: float | None,
        on_failure: AgentRunFailureHandler | None,
    ) -> T:
        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                return await operation()
        except Exception as exc:
            error: Exception = exc
            if isinstance(exc, TimeoutError) and deadline.expired():
                error = AgentRunTimeoutError(
                    f"The agent run {run_id} exceeded {timeout} seconds"
                )
            self._report_failure(run_id, error, on_failure)
            if error is exc:
                raise
            raise error from exc

    def _report_failure(
        self,
        run_id: str,
        error: Exception,
        on_failure: AgentRunFailureHandler | None,
    ) -> None:
        if (
            on_failure is None
            or run_id in self._lease_lost
            or isinstance(error, AgentRunLeaseLostError)
        ):
            return
        try:
            on_failure(error)
        except Exception as exc:
            LOGGER.warning("Agent run failure handler failed: %s", type(exc).__name__)

    def _interruption_error(self, run_id: str) -> Exception | None:
        if run_id in self._cancel_requested:
            return AgentRunCanceledError(f"The agent run {run_id} was canceled")
        if run_id in self._lease_lost:
            return AgentRunLeaseLostError(
                f"The agent run {run_id} lost its execution lease"
            )
        return None

    async def _heartbeat(self, run_id: str, generation: int) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            try:
                renewed = self._lease_register.heartbeat_lease(
                    run_id,
                    self._executor_id,
                    generation,
                    ttl_seconds=self._lease_ttl_seconds,
                )
            except Exception as exc:
                LOGGER.warning("Agent run heartbeat failed: %s", type(exc).__name__)
                renewed = False
            if not renewed:
                self._lease_lost.add(run_id)
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
        on_failure: AgentRunFailureHandler | None,
    ) -> AsyncIterator[AgentTraceEvent]:
        generation = self._acquire(run_id)
        queue: asyncio.Queue[AgentTraceEvent] = asyncio.Queue(maxsize=1)

        async def produce() -> None:
            events = operation()
            try:
                async for event in events:
                    await queue.put(event)
            finally:
                aclose = getattr(events, "aclose", None)
                if aclose is not None:
                    await aclose()

        task = self._start_task(
            run_id,
            generation,
            produce,
            timeout_seconds=timeout_seconds,
            on_failure=on_failure,
        )
        heartbeat = self._start_heartbeat(run_id, generation)
        try:
            while True:
                get = asyncio.ensure_future(queue.get())
                try:
                    await asyncio.wait({get, task}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    if not get.done():
                        get.cancel()
                if get.done() and not get.cancelled():
                    yield get.result()
                    continue
                break
            while not queue.empty():
                yield queue.get_nowait()
            await task
        except asyncio.CancelledError as exc:
            if not task.cancelled():
                raise
            error = self._interruption_error(run_id)
            if error is None:
                raise
            raise error from exc
        finally:
            await self._finish_execution(run_id, generation, heartbeat, task)

    async def _finish_execution(
        self,
        run_id: str,
        generation: int,
        heartbeat: asyncio.Task[None],
        task: asyncio.Task[Any],
    ) -> None:
        if not task.done():
            task.cancel()
            await asyncio.wait({task})
        if not task.cancelled():
            # Mark the outcome retrieved when the consumer stopped early.
            task.exception()
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        try:
            self._lease_register.release_lease(
                run_id,
                self._executor_id,
                generation,
            )
        finally:
            if self._tasks.get(run_id) is task:
                self._tasks.pop(run_id)
                self._cancel_requested.discard(run_id)
                self._lease_lost.discard(run_id)
