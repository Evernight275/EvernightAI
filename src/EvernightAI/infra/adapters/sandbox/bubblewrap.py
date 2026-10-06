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
    SandboxOutputStream,
)
from EvernightAI.infra.adapters.sandbox.process import terminate_process
from EvernightAI.infra.adapters.sandbox.output import BoundedSandboxOutput
from EvernightAI.infra.adapters.sandbox.bubblewrap_policy import (
    BubblewrapRuntimePolicy,
    resource_command,
)


class BubblewrapSandboxExecutor(SandboxExecuteProtocol):
    def __init__(
        self,
        *,
        bubblewrap_path: str | None = None,
        policy: SandboxPolicyProtocol | None = None,
        runtime_policy: BubblewrapRuntimePolicy | None = None,
    ) -> None:
        self._bubblewrap_path = bubblewrap_path or shutil.which("bwrap")
        self._policy = policy or BasicSandboxPolicy()
        self._runtime_policy = runtime_policy or BubblewrapRuntimePolicy()

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        """执行 bubblewrap 隔离沙盒命令"""
        if self._bubblewrap_path is None:
            raise SandboxConfigurationError("The bwrap executable is not available")
        self._runtime_policy.validate_mounts(request.policy.filesystem_mounts)
        effective_policy = request.policy.model_copy(
            update={
                "resource_limits": self._runtime_policy.effective_limits(
                    request.policy.resource_limits
                ),
            }
        )
        if self._runtime_policy.workspace_root is not None:
            effective_policy = effective_policy.model_copy(
                update={"network_mode": self._runtime_policy.network_mode}
            )
        request = request.model_copy(
            update={
                "policy": effective_policy,
                "command": request.command.model_copy(
                    update={
                        "timeout_seconds": min(
                            request.command.timeout_seconds
                            or effective_policy.resource_limits.timeout_seconds,
                            effective_policy.resource_limits.timeout_seconds,
                        )
                    }
                ),
            }
        )

        decision = self._policy.authorize(request)
        if not decision.allowed:
            raise SandboxPolicyError(
                "The sandbox execution was rejected by policy",
                detail=decision.reason,
            )

        process_command = self._bubblewrap_command(request)
        process: asyncio.subprocess.Process | None = None
        output = BoundedSandboxOutput(request.policy.resource_limits.max_output_chars)
        try:
            process = await asyncio.create_subprocess_exec(
                *process_command,
                env=self._host_env(),
                stdin=(
                    asyncio.subprocess.PIPE
                    if request.command.stdin is not None
                    else asyncio.subprocess.DEVNULL
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
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
            raise SandboxExecutionError(
                f"The command {request.command.command[0]} timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise SandboxExecutionError(
                f"The command {request.command.command[0]} failed to start",
                cause=exc,
            ) from exc
        except BaseException:
            if process is not None:
                await terminate_process(process)
            raise

        return SandboxExecutionResult(
            request_id=request.request_id,
            command=request.command.command,
            returncode=process.returncode,
            stdout=output.stdout,
            stderr=output.stderr,
            events=output.events,
            truncated=output.truncated,
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
                "--unshare-user",
                "--disable-userns",
                "--cap-drop",
                "ALL",
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
        command.extend(self._system_mount_options(request.policy.network_mode))
        command.extend(self._runtime_policy.runtime_mount_options())
        command.extend(self._filesystem_mount_options(request.policy.filesystem_mounts))
        for key, value in self._sandbox_env(request).items():
            command.extend(["--setenv", key, value])
        if request.command.cwd is not None:
            command.extend(["--chdir", request.command.cwd])
        command.append("--")
        command.extend(
            resource_command(
                self._sandbox_command(request), request.policy.resource_limits
            )
        )
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

    def _system_mount_options(self, network_mode: SandboxNetworkMode) -> list[str]:
        options: list[str] = []
        for path in ["/usr", "/bin", "/lib", "/lib64"]:
            if Path(path).exists():
                options.extend(["--ro-bind", path, path])
        for path in ["/etc/ld.so.cache", "/etc/ld.so.conf"]:
            if Path(path).exists():
                options.extend(["--ro-bind", path, path])
        if network_mode is SandboxNetworkMode.UNRESTRICTED:
            for path in [
                "/etc/resolv.conf",
                "/etc/hosts",
                "/etc/nsswitch.conf",
                "/etc/ssl/certs",
                "/etc/pki/tls/certs",
                "/etc/pki/ca-trust/extracted",
            ]:
                if Path(path).exists():
                    options.extend(["--ro-bind", str(Path(path).resolve()), path])
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
        command[0] = self._runtime_policy.map_runtime_executable(command[0])
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
            **self._runtime_policy.environment(
                network_mode=request.policy.network_mode
            ),
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
