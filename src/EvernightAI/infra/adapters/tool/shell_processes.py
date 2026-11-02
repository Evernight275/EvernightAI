import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from EvernightAI.core.error.tool import ToolInputError, ToolStateError
from EvernightAI.core.protocol.sandbox import (
    SandboxProcessProtocol,
    SandboxSpawnProtocol,
)
from EvernightAI.core.protocol.tool import ToolExecutorProtocol, ToolPreflightPolicy
from EvernightAI.core.schema.tool import (
    ToolApprovalMode,
    ToolDefinition,
    ToolPermission,
    ToolReplayPolicy,
    ToolSafetyDecision,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.tool.restricted_shell import RestrictedShellTool
from EvernightAI.infra.adapters.tool.shell_session import session_key

LOGGER = logging.getLogger(__name__)
MAX_WAIT_SECONDS = 30.0


@dataclass(frozen=True)
class _ProcessScope:
    owner_id: str | None
    session: str | None


@dataclass
class _OutputBuffer:
    """Recent output with offsets that keep counting past dropped text."""

    max_chars: int
    events: list[tuple[int, str, str]] = field(default_factory=list)
    end: int = 0
    size: int = 0

    @property
    def start(self) -> int:
        return self.events[0][0] if self.events else self.end

    def append(self, stream: str, text: str) -> None:
        self.events.append((self.end, stream, text))
        self.end += len(text)
        self.size += len(text)
        while self.size > self.max_chars and len(self.events) > 1:
            _, _, dropped = self.events.pop(0)
            self.size -= len(dropped)
        if self.size > self.max_chars:
            offset, stream, text = self.events[0]
            excess = self.size - self.max_chars
            self.events[0] = (offset + excess, stream, text[excess:])
            self.size -= excess

    def read(self, since: int, max_chars: int) -> tuple[list[dict[str, str]], int]:
        output: list[dict[str, str]] = []
        position = max(since, self.start)
        remaining = max_chars
        for offset, stream, text in self.events:
            if offset + len(text) <= position or remaining <= 0:
                continue
            visible = text[max(position - offset, 0) :][:remaining]
            output.append({"stream": stream, "text": visible})
            position += len(visible)
            remaining -= len(visible)
        return output, position


@dataclass
class _ManagedProcess:
    process_id: str
    scope: _ProcessScope
    command: list[str] | str
    cwd: str
    trusted_input: bool
    handle: SandboxProcessProtocol
    output: _OutputBuffer
    started_at: datetime
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    read_offset: int = 0
    returncode: int | None = None
    finished_at: datetime | None = None
    stopped: bool = False
    pump: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self.finished_at is None

    def summary(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "command": self.command,
            "cwd": self.cwd,
            "status": "running" if self.running else "exited",
            "returncode": self.returncode,
            "stopped": self.stopped,
            "timed_out": bool(getattr(self.handle, "timed_out", False)),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class ShellProcessManager:
    """Long-running shell processes owned by a runtime, never persisted."""

    def __init__(
        self,
        *,
        max_processes_per_owner: int = 4,
        max_processes: int = 16,
        max_output_chars: int = 200_000,
        lifetime_seconds: float = 3600.0,
        max_exited_processes: int = 32,
    ) -> None:
        self.max_processes_per_owner = max_processes_per_owner
        self.max_processes = max_processes
        self.max_output_chars = max_output_chars
        self.lifetime_seconds = lifetime_seconds
        self._max_exited = max_exited_processes
        self._processes: dict[str, _ManagedProcess] = {}
        self._closing = False
        self._start_lock = asyncio.Lock()

    async def start(
        self,
        spawner: SandboxSpawnProtocol,
        shell: RestrictedShellTool,
        arguments: dict[str, Any],
        scope: _ProcessScope,
    ) -> _ManagedProcess:
        async with self._start_lock:
            return await self._start(spawner, shell, arguments, scope)

    async def _start(
        self,
        spawner: SandboxSpawnProtocol,
        shell: RestrictedShellTool,
        arguments: dict[str, Any],
        scope: _ProcessScope,
    ) -> _ManagedProcess:
        if self._closing:
            raise ToolStateError("Shell processes are shutting down")
        running = [process for process in self._processes.values() if process.running]
        if len(running) >= self.max_processes or (
            sum(process.scope.owner_id == scope.owner_id for process in running)
            >= self.max_processes_per_owner
        ):
            raise ToolStateError(
                "Too many shell processes are running; stop one before starting another"
            )
        request, cwd = shell.background_request(
            arguments, lifetime_seconds=self.lifetime_seconds
        )
        command = shell.parse_command(arguments)
        handle = await spawner.spawn(request)
        process = _ManagedProcess(
            process_id=f"proc_{uuid4().hex[:12]}",
            scope=scope,
            command=command,
            cwd=cwd,
            trusted_input=shell.accepts_unapproved_input(arguments),
            handle=handle,
            output=_OutputBuffer(self.max_output_chars),
            started_at=datetime.now(timezone.utc),
        )
        process.pump = asyncio.create_task(
            self._pump(process), name=f"evernight-shell-{process.process_id}"
        )
        self._processes[process.process_id] = process
        self._forget_exited()
        return process

    def get(self, process_id: object, scope: _ProcessScope) -> _ManagedProcess:
        process = (
            self._processes.get(process_id) if isinstance(process_id, str) else None
        )
        if process is None or process.scope != scope:
            raise ToolInputError(
                f"The shell process {process_id} is not found; processes do not "
                "survive a runtime restart"
            )
        return process

    def list(self, scope: _ProcessScope) -> list[_ManagedProcess]:
        return [
            process for process in self._processes.values() if process.scope == scope
        ]

    async def read(
        self,
        process: _ManagedProcess,
        *,
        since: int | None,
        max_chars: int,
        wait_seconds: float,
    ) -> dict[str, Any]:
        position = process.read_offset if since is None else since
        if wait_seconds > 0:
            async with process.changed:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        process.changed.wait_for(
                            lambda: process.output.end > position or not process.running
                        ),
                        wait_seconds,
                    )
        output, next_offset = process.output.read(position, max_chars)
        process.read_offset = max(process.read_offset, next_offset)
        return {
            **process.summary(),
            "output": output,
            "next_offset": next_offset,
            "output_dropped": position < process.output.start,
            "more_output": next_offset < process.output.end,
        }

    async def write(
        self, process: _ManagedProcess, text: str, *, close_stdin: bool
    ) -> None:
        if not process.running:
            raise ToolStateError(f"The shell process {process.process_id} has exited")
        try:
            if text:
                await process.handle.write_stdin(text)
            if close_stdin:
                await process.handle.close_stdin()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ToolStateError(
                f"The shell process {process.process_id} no longer accepts input"
            ) from exc

    async def stop(self, process: _ManagedProcess) -> None:
        if process.running:
            process.stopped = True
            await process.handle.terminate()
        if process.pump is not None:
            await process.pump

    async def close(self) -> None:
        self._closing = True
        async with self._start_lock:
            processes = list(self._processes.values())
        for process in processes:
            try:
                await self.stop(process)
            except Exception:
                LOGGER.exception("Failed to stop shell process %s", process.process_id)

    async def _pump(self, process: _ManagedProcess) -> None:
        try:
            while (event := await process.handle.read()) is not None:
                async with process.changed:
                    process.output.append(event.stream.value, event.text)
                    process.changed.notify_all()
            process.returncode = await process.handle.wait()
        finally:
            async with process.changed:
                process.finished_at = datetime.now(timezone.utc)
                process.changed.notify_all()

    def _forget_exited(self) -> None:
        exited = [
            process for process in self._processes.values() if not process.running
        ]
        for process in exited[: max(len(exited) - self._max_exited, 0)]:
            del self._processes[process.process_id]


class ShellProcessTools:
    def __init__(
        self,
        shell: RestrictedShellTool,
        spawner: SandboxSpawnProtocol,
        manager: ShellProcessManager,
    ) -> None:
        self._shell = shell
        self._spawner = spawner
        self._manager = manager

    def registrations(
        self,
    ) -> list[tuple[ToolDefinition, ToolExecutorProtocol, ToolPreflightPolicy | None]]:
        shell = self._shell.definition
        return [
            (self._start_definition(shell), self._start, self._authorize_start),
            (self._read_definition(), self._read, None),
            (self._write_definition(shell), self._write, self._authorize_write),
            (self._stop_definition(), self._stop, self._authorize_known),
            (self._list_definition(), self._list, None),
        ]

    def _start_definition(self, shell: ToolDefinition) -> ToolDefinition:
        properties = dict((shell.parameters_schema or {}).get("properties", {}))
        properties.pop("timeout_seconds", None)
        properties.pop("reset_session", None)
        properties["wait_seconds"] = {"type": "number", "minimum": 0}
        return shell.model_copy(
            update={
                "name": "shell_process_start",
                "description": (
                    "Start a long-running command, such as a dev server, watcher or "
                    "REPL, and return a process_id at once. The same command rules "
                    "and approvals as restricted_shell apply, and it starts in the "
                    "current shell session directory and environment. Use "
                    "shell_process_read for its output, shell_process_write for "
                    "input and shell_process_stop to end it. Processes stop after "
                    f"{self._manager.lifetime_seconds:g} seconds and when the "
                    "runtime stops."
                ),
                "parameters_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": ["command"],
                },
                "replay_policy": ToolReplayPolicy.NON_REPLAYABLE,
                "metadata": {
                    **shell.metadata,
                    "supports_execution_context": True,
                    "lifetime_seconds": self._manager.lifetime_seconds,
                    "max_processes_per_owner": self._manager.max_processes_per_owner,
                },
            }
        )

    def _read_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shell_process_read",
            description=(
                "Read new output from a process started with shell_process_start. "
                "Each call continues where the previous read stopped unless since "
                "is given. wait_seconds waits for new output or the process to "
                "exit, up to 30 seconds."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                    "since": {"type": "integer", "minimum": 0},
                    "max_chars": {"type": "integer", "minimum": 1},
                    "wait_seconds": {"type": "number", "minimum": 0},
                },
                "required": ["process_id"],
            },
            permissions=[ToolPermission.PROCESS, ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            approval_mode=ToolApprovalMode.NEVER,
            replay_policy=ToolReplayPolicy.SAFE,
            metadata={"supports_execution_context": True},
        )

    def _write_definition(self, shell: ToolDefinition) -> ToolDefinition:
        return ToolDefinition(
            name="shell_process_write",
            description=(
                "Send text to the stdin of a running process, including any "
                "newline it needs. Input to interpreters and other programs "
                "outside the trusted commands requires approval."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"},
                    "input": {"type": "string"},
                    "close_stdin": {"type": "boolean"},
                },
                "required": ["process_id"],
            },
            permissions=[ToolPermission.PROCESS],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=shell.requires_approval,
            approval_mode=shell.approval_mode,
            metadata={"supports_execution_context": True},
        )

    def _stop_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shell_process_stop",
            description="Stop a process started with shell_process_start.",
            parameters_schema={
                "type": "object",
                "properties": {"process_id": {"type": "string"}},
                "required": ["process_id"],
            },
            permissions=[ToolPermission.PROCESS],
            safety_level=ToolSafetyLevel.SAFE,
            approval_mode=ToolApprovalMode.NEVER,
            metadata={"supports_execution_context": True},
        )

    def _list_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shell_process_list",
            description="List the processes this shell session started.",
            parameters_schema={"type": "object", "properties": {}},
            permissions=[ToolPermission.PROCESS, ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            approval_mode=ToolApprovalMode.NEVER,
            replay_policy=ToolReplayPolicy.SAFE,
            metadata={"supports_execution_context": True},
        )

    def _authorize_start(
        self, tool: ToolDefinition, arguments: dict[str, Any]
    ) -> ToolSafetyDecision | None:
        try:
            _wait_seconds(arguments, default=1.0)
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        return self._shell.authorize(tool, arguments)

    def _authorize_write(
        self, _tool: ToolDefinition, arguments: dict[str, Any]
    ) -> ToolSafetyDecision | None:
        try:
            process = self._manager.get(arguments.get("process_id"), _scope(arguments))
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        if process.trusted_input:
            return None
        return ToolSafetyDecision(
            allowed=False,
            reason="Input to an interpreter or untrusted program requires approval",
            requires_approval=True,
            metadata={"process": process.summary()},
        )

    def _authorize_known(
        self, _tool: ToolDefinition, arguments: dict[str, Any]
    ) -> ToolSafetyDecision | None:
        try:
            self._manager.get(arguments.get("process_id"), _scope(arguments))
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        return None

    async def _start(self, arguments: dict[str, Any]) -> dict[str, Any]:
        wait_seconds = _wait_seconds(arguments, default=1.0)
        process = await self._manager.start(
            self._spawner, self._shell, arguments, _scope(arguments)
        )
        return await self._manager.read(
            process,
            since=0,
            max_chars=self._shell_output_chars(),
            wait_seconds=wait_seconds,
        )

    async def _read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        process = self._manager.get(arguments.get("process_id"), _scope(arguments))
        since = arguments.get("since")
        if since is not None and (
            not isinstance(since, int) or isinstance(since, bool) or since < 0
        ):
            raise ToolInputError("The since value must be a nonnegative integer")
        max_chars = arguments.get("max_chars", self._shell_output_chars())
        if (
            not isinstance(max_chars, int)
            or isinstance(max_chars, bool)
            or max_chars < 1
        ):
            raise ToolInputError("The max_chars value must be a positive integer")
        return await self._manager.read(
            process,
            since=since,
            max_chars=min(max_chars, self._manager.max_output_chars),
            wait_seconds=_wait_seconds(arguments, default=0.0),
        )

    async def _write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        process = self._manager.get(arguments.get("process_id"), _scope(arguments))
        text = arguments.get("input", "")
        close_stdin = arguments.get("close_stdin", False)
        if not isinstance(text, str) or "\x00" in text:
            raise ToolInputError("The input must be a string without NUL bytes")
        if not isinstance(close_stdin, bool):
            raise ToolInputError("The close_stdin value must be a boolean")
        await self._manager.write(process, text, close_stdin=close_stdin)
        return process.summary()

    async def _stop(self, arguments: dict[str, Any]) -> dict[str, Any]:
        process = self._manager.get(arguments.get("process_id"), _scope(arguments))
        await self._manager.stop(process)
        output, next_offset = process.output.read(process.read_offset, 0)
        return {**process.summary(), "next_offset": next_offset, "output": output}

    async def _list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "processes": [
                {
                    **process.summary(),
                    "unread_chars": process.output.end - process.read_offset,
                }
                for process in self._manager.list(_scope(arguments))
            ]
        }

    def _shell_output_chars(self) -> int:
        value = self._shell.definition.metadata.get("max_output_chars", 12000)
        return value if isinstance(value, int) else 12000


def _scope(arguments: dict[str, Any]) -> _ProcessScope:
    key = session_key(arguments)
    if key is not None:
        return _ProcessScope(key.owner_id, key.key)
    context = arguments.get("_execution_context")
    owner = context.get("owner_id") if isinstance(context, dict) else None
    return _ProcessScope(owner if isinstance(owner, str) and owner else None, None)


def _wait_seconds(arguments: dict[str, Any], *, default: float) -> float:
    value = arguments.get("wait_seconds", default)
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ToolInputError("The wait_seconds value must be a nonnegative number")
    return min(float(value), MAX_WAIT_SECONDS)
