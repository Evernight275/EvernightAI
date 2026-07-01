import asyncio
import os
from pathlib import Path, PurePosixPath

from EvernightAI.core.domain.sandbox import BasicSandboxPolicy
from EvernightAI.core.error.sandbox import (
    SandboxExecutionError,
    SandboxPolicyError,
)
from EvernightAI.core.protocol.sandbox import (
    SandboxExecuteProtocol,
    SandboxPolicyProtocol,
)
from EvernightAI.core.schema.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxFilesystemMount,
    SandboxOutputEvent,
    SandboxOutputStream,
)


class SubprocessSandboxExecutor(SandboxExecuteProtocol):
    def __init__(
        self,
        *,
        policy: SandboxPolicyProtocol | None = None,
    ) -> None:
        self._policy = policy or BasicSandboxPolicy()

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        """执行沙盒命令"""
        decision = self._policy.authorize(request)
        if not decision.allowed:
            raise SandboxPolicyError(
                "The sandbox execution was rejected by policy",
                detail=decision.reason,
            )

        command = request.command.command
        process: asyncio.subprocess.Process | None = None
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        events: list[SandboxOutputEvent] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._resolve_cwd(request),
                env=self._resolve_env(request),
                stdin=(
                    asyncio.subprocess.PIPE
                    if request.command.stdin is not None
                    else None
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(
                asyncio.gather(
                    self._write_stdin(process, request.command.stdin),
                    self._collect_stream(
                        process.stdout,
                        SandboxOutputStream.STDOUT,
                        stdout_chunks,
                        events,
                    ),
                    self._collect_stream(
                        process.stderr,
                        SandboxOutputStream.STDERR,
                        stderr_chunks,
                        events,
                    ),
                    process.wait(),
                ),
                timeout=self._timeout_seconds(request),
            )
        except asyncio.TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise SandboxExecutionError(
                f"The command {command[0]} timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise SandboxExecutionError(
                f"The command {command[0]} failed to start",
                cause=exc,
            ) from exc

        stdout = b"".join(stdout_chunks)
        stderr = b"".join(stderr_chunks)
        max_output_chars = request.policy.resource_limits.max_output_chars
        return SandboxExecutionResult(
            request_id=request.request_id,
            command=command,
            returncode=process.returncode,
            stdout=self._decode_and_truncate(stdout, max_output_chars),
            stderr=self._decode_and_truncate(stderr, max_output_chars),
            events=self._truncate_events(events, max_output_chars),
            truncated=(
                len(self._decode(stdout)) > max_output_chars
                or len(self._decode(stderr)) > max_output_chars
            ),
        )

    async def _write_stdin(
        self,
        process: asyncio.subprocess.Process,
        stdin: str | None,
    ) -> None:
        if stdin is None or process.stdin is None:
            return
        process.stdin.write(stdin.encode())
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()

    async def _collect_stream(
        self,
        stream: asyncio.StreamReader | None,
        stream_name: SandboxOutputStream,
        chunks: list[bytes],
        events: list[SandboxOutputEvent],
    ) -> None:
        if stream is None:
            return

        while True:
            chunk = await stream.readline()
            if not chunk:
                return
            chunks.append(chunk)
            events.append(
                SandboxOutputEvent(stream=stream_name, text=self._decode(chunk))
            )

    def _resolve_cwd(self, request: SandboxExecutionRequest) -> Path | None:
        cwd = request.command.cwd
        if cwd is None:
            return None

        mount = self._find_mount(cwd, request.policy.filesystem_mounts)
        relative_cwd = self._relative_sandbox_path(cwd, mount.mount_path)
        return (Path(mount.host_path) / relative_cwd).resolve()

    def _resolve_env(self, request: SandboxExecutionRequest) -> dict[str, str]:
        return {**os.environ, **request.command.env}

    def _timeout_seconds(self, request: SandboxExecutionRequest) -> float:
        return (
            request.command.timeout_seconds
            or request.policy.resource_limits.timeout_seconds
        )

    def _find_mount(
        self,
        sandbox_path: str,
        mounts: list[SandboxFilesystemMount],
    ) -> SandboxFilesystemMount:
        path = self._normalize_path(sandbox_path)
        for mount in mounts:
            mount_path = self._normalize_path(mount.mount_path)
            if path == mount_path or mount_path in path.parents:
                return mount
        raise SandboxPolicyError(
            "The sandbox path is outside the configured mounts",
            detail=sandbox_path,
        )

    def _relative_sandbox_path(self, path: str, mount_path: str) -> Path:
        normalized_path = self._normalize_path(path)
        normalized_mount = self._normalize_path(mount_path)
        relative = normalized_path.relative_to(normalized_mount)
        return Path(*relative.parts)

    def _normalize_path(self, value: str) -> PurePosixPath:
        path = PurePosixPath(value)
        if not path.is_absolute():
            path = PurePosixPath("/") / path
        return path

    def _decode_and_truncate(self, value: bytes, max_chars: int) -> str:
        text = self._decode(value)
        if len(text) <= max_chars:
            return text
        return text[:max_chars]

    def _decode(self, value: bytes) -> str:
        return value.decode(errors="replace")

    def _truncate_events(
        self,
        events: list[SandboxOutputEvent],
        max_chars: int,
    ) -> list[SandboxOutputEvent]:
        remaining = max_chars
        truncated_events: list[SandboxOutputEvent] = []
        for event in events:
            text = event.text
            if len(text) > remaining:
                truncated_events.append(
                    event.model_copy(
                        update={
                            "text": text[:remaining],
                            "truncated": True,
                        }
                    )
                )
                break

            truncated_events.append(event.model_copy(update={"truncated": False}))
            remaining -= len(text)
            if remaining <= 0:
                break

        return truncated_events
