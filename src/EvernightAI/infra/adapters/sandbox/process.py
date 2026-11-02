import asyncio
import codecs
import os
import signal
from contextlib import suppress

from EvernightAI.core.protocol.sandbox import SandboxProcessProtocol
from EvernightAI.core.schema.sandbox import (
    SANDBOX_SIDE_CHANNEL_MAX_BYTES,
    SandboxOutputEvent,
    SandboxOutputStream,
)

# Background children may inherit the side channel and keep it open; data the
# command wrote before exiting is already buffered, so the drain stays short.
_SIDE_CHANNEL_DRAIN_SECONDS = 0.2


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.returncode is None:
            process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


class SideChannel:
    """A pipe whose write end a sandboxed command inherits."""

    def __init__(self) -> None:
        self._read_fd, self.write_fd = os.pipe()
        os.set_inheritable(self.write_fd, True)
        self._chunks: list[bytes] = []
        self._size = 0
        self._overflow = False
        self._task: asyncio.Task[None] | None = None
        self._write_closed = False
        self._reader_file = os.fdopen(self._read_fd, "rb", buffering=0)

    def start(self) -> None:
        """Call once the command has started and inherited the write end."""
        self.close_write_end()
        self._task = asyncio.create_task(self._collect())

    def close_write_end(self) -> None:
        if not self._write_closed:
            self._write_closed = True
            os.close(self.write_fd)

    async def result(self) -> str | None:
        if self._task is not None:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._task), _SIDE_CHANNEL_DRAIN_SECONDS
                )
        if self._overflow:
            return None
        return b"".join(self._chunks).decode("utf-8", errors="replace")

    async def close(self) -> None:
        self.close_write_end()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._reader_file.close()

    async def _collect(self) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader),
            self._reader_file,
        )
        try:
            while chunk := await reader.read(65536):
                if self._size + len(chunk) > SANDBOX_SIDE_CHANNEL_MAX_BYTES:
                    self._overflow = True
                    continue
                self._chunks.append(chunk)
                self._size += len(chunk)
        finally:
            transport.close()


class SubprocessSandboxProcess(SandboxProcessProtocol):
    """A started process whose output is read as it is produced."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        lifetime_seconds: float | None = None,
    ) -> None:
        self._process = process
        self._events: asyncio.Queue[SandboxOutputEvent | None] = asyncio.Queue()
        self._open_streams = 2
        self.timed_out = False
        self._pumps = [
            asyncio.create_task(self._pump(process.stdout, SandboxOutputStream.STDOUT)),
            asyncio.create_task(self._pump(process.stderr, SandboxOutputStream.STDERR)),
        ]
        self._deadline = (
            asyncio.create_task(self._expire(lifetime_seconds))
            if lifetime_seconds is not None
            else None
        )

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def read(self) -> SandboxOutputEvent | None:
        while self._open_streams:
            event = await self._events.get()
            if event is not None:
                return event
            self._open_streams -= 1
        return None

    async def write_stdin(self, text: str) -> None:
        stdin = self._process.stdin
        if stdin is None or stdin.is_closing():
            raise BrokenPipeError("The process stdin is closed")
        stdin.write(text.encode())
        await stdin.drain()

    async def close_stdin(self) -> None:
        stdin = self._process.stdin
        if stdin is None or stdin.is_closing():
            return
        stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await stdin.wait_closed()

    async def wait(self) -> int:
        return await self._process.wait()

    async def terminate(self) -> None:
        if self._deadline is not None and self._deadline is not asyncio.current_task():
            self._deadline.cancel()
        await terminate_process(self._process)
        for pump in self._pumps:
            with suppress(asyncio.CancelledError):
                await pump

    async def _expire(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._process.wait(), seconds)
        except asyncio.TimeoutError:
            self.timed_out = True
            await self.terminate()

    async def _pump(
        self, reader: asyncio.StreamReader | None, stream: SandboxOutputStream
    ) -> None:
        try:
            if reader is None:
                return
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while chunk := await reader.read(4096):
                if text := decoder.decode(chunk):
                    self._events.put_nowait(
                        SandboxOutputEvent(stream=stream, text=text)
                    )
            if text := decoder.decode(b"", final=True):
                self._events.put_nowait(SandboxOutputEvent(stream=stream, text=text))
        finally:
            self._events.put_nowait(None)
