import asyncio
import os
import shutil
from pathlib import Path, PurePosixPath

from EvernightAI.core.domain.sandbox import BasicSandboxPolicy
from EvernightAI.core.error.sandbox import (
    SandboxConfigurationError,
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
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxNetworkMode,
    SandboxOutputEvent,
    SandboxOutputStream,
)


class BubblewrapSandboxExecutor(SandboxExecuteProtocol):
    def __init__(
        self,
        *,
        bubblewrap_path: str | None = None,
        policy: SandboxPolicyProtocol | None = None,
    ) -> None:
        self._bubblewrap_path = bubblewrap_path or shutil.which("bwrap")
        self._policy = policy or BasicSandboxPolicy()

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        """执行 bubblewrap 隔离沙盒命令"""
        if self._bubblewrap_path is None:
            raise SandboxConfigurationError("The bwrap executable is not available")

        decision = self._policy.authorize(request)
        if not decision.allowed:
            raise SandboxPolicyError(
                "The sandbox execution was rejected by policy",
                detail=decision.reason,
            )

        process_command = self._bubblewrap_command(request)
        process: asyncio.subprocess.Process | None = None
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        events: list[SandboxOutputEvent] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *process_command,
                env=self._host_env(),
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
                f"The command {request.command.command[0]} timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise SandboxExecutionError(
                f"The command {request.command.command[0]} failed to start",
                cause=exc,
            ) from exc

        stdout = b"".join(stdout_chunks)
        stderr = b"".join(stderr_chunks)
        max_output_chars = request.policy.resource_limits.max_output_chars
        return SandboxExecutionResult(
            request_id=request.request_id,
            command=request.command.command,
            returncode=process.returncode,
            stdout=self._decode_and_truncate(stdout, max_output_chars),
            stderr=self._decode_and_truncate(stderr, max_output_chars),
            events=self._truncate_events(events, max_output_chars),
            truncated=(
                len(self._decode(stdout)) > max_output_chars
                or len(self._decode(stderr)) > max_output_chars
            ),
            metadata={"sandbox_backend": "bubblewrap"},
        )

    def _bubblewrap_command(self, request: SandboxExecutionRequest) -> list[str]:
        bubblewrap_path = self._bubblewrap_path
        if bubblewrap_path is None:
            raise SandboxConfigurationError("The bwrap executable is not available")

        command = [bubblewrap_path]
        command.extend(
            [
                "--die-with-parent",
                "--new-session",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--clearenv",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--dir",
                "/run",
            ]
        )
        command.extend(self._network_options(request))
        command.extend(self._system_mount_options())
        command.extend(self._filesystem_mount_options(request.policy.filesystem_mounts))
        for key, value in self._sandbox_env(request).items():
            command.extend(["--setenv", key, value])
        if request.command.cwd is not None:
            command.extend(["--chdir", request.command.cwd])
        command.append("--")
        command.extend(self._sandbox_command(request))
        return command

    def _network_options(self, request: SandboxExecutionRequest) -> list[str]:
        mode = request.policy.network_mode
        if mode is SandboxNetworkMode.DISABLED:
            return ["--unshare-net"]
        if mode is SandboxNetworkMode.UNRESTRICTED:
            return []
        raise SandboxConfigurationError(
            "The bubblewrap sandbox does not support network allowlists"
        )

    def _system_mount_options(self) -> list[str]:
        options: list[str] = []
        for path in ["/usr", "/bin", "/lib", "/lib64"]:
            if Path(path).exists():
                options.extend(["--ro-bind", path, path])
        for path in ["/etc/ld.so.cache", "/etc/ld.so.conf"]:
            if Path(path).exists():
                options.extend(["--ro-bind", path, path])
        return options

    def _filesystem_mount_options(
        self,
        mounts: list[SandboxFilesystemMount],
    ) -> list[str]:
        options: list[str] = []
        for mount in mounts:
            host_path = str(Path(mount.host_path).resolve())
            flag = (
                "--bind"
                if mount.access is SandboxFilesystemAccess.READ_WRITE
                else "--ro-bind"
            )
            options.extend([flag, host_path, mount.mount_path])
        return options

    def _sandbox_command(self, request: SandboxExecutionRequest) -> list[str]:
        command = list(request.command.command)
        command[0] = self._map_host_path_to_sandbox(
            command[0],
            request.policy.filesystem_mounts,
        )
        return command

    def _map_host_path_to_sandbox(
        self,
        value: str,
        mounts: list[SandboxFilesystemMount],
    ) -> str:
        path = Path(value)
        if not path.is_absolute():
            return value

        resolved_path = path.resolve()
        for mount in mounts:
            host_path = Path(mount.host_path).resolve()
            try:
                relative = resolved_path.relative_to(host_path)
            except ValueError:
                continue
            sandbox_path = self._normalize_path(mount.mount_path) / PurePosixPath(
                *relative.parts
            )
            return sandbox_path.as_posix()
        return value

    def _sandbox_env(self, request: SandboxExecutionRequest) -> dict[str, str]:
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            **request.command.env,
        }

    def _host_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in ["HOME", "USER", "LOGNAME"]:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        return env

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

    def _timeout_seconds(self, request: SandboxExecutionRequest) -> float:
        return (
            request.command.timeout_seconds
            or request.policy.resource_limits.timeout_seconds
        )

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
