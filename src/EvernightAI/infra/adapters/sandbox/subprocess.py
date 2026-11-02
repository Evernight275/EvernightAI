import asyncio
import os
from pathlib import Path, PurePosixPath

from EvernightAI.core.domain.sandbox import BasicSandboxPolicy
from EvernightAI.core.error.sandbox import (
    SandboxExecutionError,
    SandboxPolicyError,
    SandboxTimeoutError,
)
from EvernightAI.core.protocol.sandbox import (
    SandboxExecuteProtocol,
    SandboxPolicyProtocol,
    SandboxProcessProtocol,
    SandboxSpawnProtocol,
)
from EvernightAI.core.schema.sandbox import (
    SANDBOX_SIDE_CHANNEL_FD_ENV,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxFilesystemMount,
    SandboxOutputStream,
)
from EvernightAI.infra.adapters.sandbox.output import BoundedSandboxOutput
from EvernightAI.infra.adapters.sandbox.process import (
    SideChannel,
    SubprocessSandboxProcess,
    terminate_process,
)


class SubprocessSandboxExecutor(SandboxExecuteProtocol, SandboxSpawnProtocol):
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
        self._authorize(request)
        side_channel = (
            SideChannel()
            if request.command.side_channel and os.name == "posix"
            else None
        )
        try:
            return await self._execute(request, side_channel)
        finally:
            if side_channel is not None:
                await side_channel.close()

    async def spawn(self, request: SandboxExecutionRequest) -> SandboxProcessProtocol:
        """启动沙盒进程，不等待其结束"""
        self._authorize(request)
        try:
            process = await asyncio.create_subprocess_exec(
                *request.command.command,
                cwd=self._resolve_cwd(request),
                env=self._resolve_env(request),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            raise SandboxExecutionError(
                f"The command {request.command.command[0]} failed to start",
                cause=exc,
            ) from exc
        return SubprocessSandboxProcess(
            process, lifetime_seconds=request.command.timeout_seconds
        )

    def _authorize(self, request: SandboxExecutionRequest) -> None:
        decision = self._policy.authorize(request)
        if not decision.allowed:
            raise SandboxPolicyError(
                "The sandbox execution was rejected by policy",
                detail=decision.reason,
            )

    async def _execute(
        self,
        request: SandboxExecutionRequest,
        side_channel: SideChannel | None,
    ) -> SandboxExecutionResult:
        command = request.command.command
        process: asyncio.subprocess.Process | None = None
        output = BoundedSandboxOutput(request.policy.resource_limits.max_output_chars)
        env = self._resolve_env(request)
        if side_channel is not None:
            env[SANDBOX_SIDE_CHANNEL_FD_ENV] = str(side_channel.write_fd)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._resolve_cwd(request),
                env=env,
                stdin=(
                    asyncio.subprocess.PIPE
                    if request.command.stdin is not None
                    else asyncio.subprocess.DEVNULL
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
                pass_fds=(side_channel.write_fd,) if side_channel is not None else (),
            )
            if side_channel is not None:
                side_channel.start()
            await asyncio.wait_for(
                asyncio.gather(
                    self._write_stdin(process, request.command.stdin),
                    output.collect(
                        process.stdout,
                        SandboxOutputStream.STDOUT,
                    ),
                    output.collect(
                        process.stderr,
                        SandboxOutputStream.STDERR,
                    ),
                    process.wait(),
                ),
                timeout=self._timeout_seconds(request),
            )
        except asyncio.TimeoutError as exc:
            if process is not None:
                await terminate_process(process)
            raise SandboxTimeoutError(
                f"The command {command[0]} timed out",
                result=SandboxExecutionResult(
                    request_id=request.request_id,
                    command=command,
                    returncode=None,
                    stdout=output.stdout,
                    stderr=output.stderr,
                    events=output.events,
                    timed_out=True,
                    truncated=output.truncated,
                ),
                cause=exc,
            ) from exc
        except OSError as exc:
            raise SandboxExecutionError(
                f"The command {command[0]} failed to start",
                cause=exc,
            ) from exc
        except BaseException:
            if process is not None:
                await terminate_process(process)
            raise

        return SandboxExecutionResult(
            request_id=request.request_id,
            command=command,
            returncode=process.returncode,
            stdout=output.stdout,
            stderr=output.stderr,
            events=output.events,
            truncated=output.truncated,
            side_channel=(
                await side_channel.result() if side_channel is not None else None
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

    def _resolve_cwd(self, request: SandboxExecutionRequest) -> Path | None:
        cwd = request.command.cwd
        if cwd is None:
            return None

        mount = self._find_mount(cwd, request.policy.filesystem_mounts)
        relative_cwd = self._relative_sandbox_path(cwd, mount.mount_path)
        return (Path(mount.host_path) / relative_cwd).resolve()

    def _resolve_env(self, request: SandboxExecutionRequest) -> dict[str, str]:
        env = {**os.environ, **request.command.env}
        if os.name == "nt":
            # Output is decoded as UTF-8; Windows Python defaults pipes to the ANSI code page.
            env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

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
