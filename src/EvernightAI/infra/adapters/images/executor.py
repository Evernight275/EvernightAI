import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from EvernightAI.core.domain.image_task import interrupted
from EvernightAI.core.protocol.image import (
    ImageTaskExecutorProtocol,
    ImageTaskStoreProtocol,
)
from EvernightAI.core.schema.image_task import ImageTask


LOGGER = logging.getLogger("EvernightAI.image_tasks")


class SingleProcessImageTaskExecutor(ImageTaskExecutorProtocol):
    def __init__(
        self,
        store: ImageTaskStoreProtocol,
        operation: Callable[[ImageTask], Awaitable[ImageTask]],
        *,
        concurrency: int = 2,
    ) -> None:
        self._store = store
        self._operation = operation
        self._concurrency = concurrency
        self._workers: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        self._closing = False
        self._owner = uuid4().hex

    async def start(self) -> None:
        if self._closing:
            raise RuntimeError("Image task executor is closing")
        if not self._workers and self._store.has_active():
            self._workers = [
                asyncio.create_task(self._worker(f"{self._owner}-{index}"))
                for index in range(self._concurrency)
            ]

    def wake(self) -> None:
        self._wake.set()

    @staticmethod
    def _lease() -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=30)

    async def _heartbeat(
        self, task: ImageTask, operation: asyncio.Task[ImageTask]
    ) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                renewed = self._store.renew(
                    task.task_id, task.worker_id or "", self._lease()
                )
            except Exception:
                operation.cancel()
                raise
            if not renewed:
                operation.cancel()
                return

    async def _run(self, task: ImageTask) -> ImageTask:
        return await self._operation(task)

    async def _worker(self, worker_id: str) -> None:
        while not self._closing:
            task = None
            try:
                self._store.recover_expired(datetime.now(timezone.utc))
                task = self._store.claim(worker_id, self._lease())
                if task is None:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=1)
                    except TimeoutError:
                        pass
                    continue
                operation = asyncio.create_task(self._run(task))
                heartbeat = asyncio.create_task(self._heartbeat(task, operation))
                try:
                    finished = await operation
                    self._store.finish(finished, worker_id)
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
            except asyncio.CancelledError:
                if task is not None:
                    self._store.finish(interrupted(task), worker_id)
                worker = asyncio.current_task()
                if self._closing or (worker is not None and worker.cancelling()):
                    raise
            except Exception as exc:
                LOGGER.warning("Image worker failed: %s", type(exc).__name__)
                if task is not None:
                    self._store.finish(interrupted(task), worker_id)
                await asyncio.sleep(1)

    async def close(self) -> None:
        self._closing = True
        self._wake.set()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
