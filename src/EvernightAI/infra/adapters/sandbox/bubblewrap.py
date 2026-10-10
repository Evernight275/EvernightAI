import asyncio
import os
import shutil
import sys
from pathlib import Path

from EvernightAI.core.domain.sandbox import BasicSandboxPolicy
from EvernightAI.core.error.sandbox import (
    SandboxConfigurationError,
    SandboxExecutionError,
    SandboxPolicyError,
    SandboxTimeoutError,
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
from EvernightAI.infra.adapters.sandbox.project_environment import (
    ProjectExecutionEnvironment,
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
        descriptors: list[int] = []
        try:
            return await self._execute(request, descriptors)
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    async def _execute(
        self,
        request: SandboxExecutionRequest,
        descriptors: list[int],
    ) -> SandboxExecutionResult:
        # Each workspace is opened once; validation and the bind mounts then refer to
        # that same directory even if its path is replaced afterwards.
        mounts = self._open_mounts(request.policy.filesystem_mounts, descriptors)
        self._runtime_policy.validate_mounts(mounts)
        effective_policy = request.policy.model_copy(
            update={
                "filesystem_mounts": mounts,
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

        project = self._runtime_policy.project_environment(request)
        process_command = self._bubblewrap_command(request, project, descriptors)
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
                pass_fds=descriptors,
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
            raise SandboxTimeoutError(
                f"The command {request.command.command[0]} timed out",
                result=SandboxExecutionResult(
                    request_id=request.request_id,
                    command=request.command.command,
                    returncode=None,
                    stdout=output.stdout,
                    stderr=output.stderr,
                    events=output.events,
                    timed_out=True,
                    truncated=output.truncated,
                    metadata={"sandbox_backend": "bubblewrap"},
                ),
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

    def _open_mounts(
        self,
        mounts: list[SandboxFilesystemMount],
        descriptors: list[int],
    ) -> list[SandboxFilesystemMount]:
        if sys.platform != "linux":
            raise SandboxConfigurationError("The bubblewrap sandbox requires Linux")
        opened: list[SandboxFilesystemMount] = []
        for mount in mounts:
            try:
                descriptor = os.open(
                    mount.host_path, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC
                )
            except OSError as exc:
                raise SandboxConfigurationError(
                    f"Sandbox workspace does not exist: {Path(mount.host_path).resolve()}"
                ) from exc
            descriptors.append(descriptor)
            host_path = os.readlink(f"/proc/self/fd/{descriptor}")
            if host_path != mount.mount_path:
                # bwrap consumes a descriptor per bind, so the original-path mount needs its own.
                descriptors.append(os.dup(descriptor))
            opened.append(mount.model_copy(update={"host_path": host_path}))
        return opened

    def _bubblewrap_command(
        self,
        request: SandboxExecutionRequest,
        project: ProjectExecutionEnvironment,
        descriptors: list[int],
    ) -> list[str]:
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
                "--hostname",
                "sandbox",
                "--clearenv",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                *self._tmpfs_options("/dev/shm", request),
                "--remount-ro",
                "/dev",
                *self._tmpfs_options("/tmp", request),
                "--dir",
                "/run",
            ]
        )
        command.extend(self._network_options(request))
        command.extend(self._system_mount_options(request.policy.network_mode))
        command.extend(self._runtime_policy.runtime_mount_options(project))
        command.extend(
            self._filesystem_mount_options(
                request.policy.filesystem_mounts, descriptors
            )
        )
        for key, value in self._sandbox_env(request, project).items():
            command.extend(["--setenv", key, value])
        if request.command.cwd is not None:
            command.extend(["--chdir", request.command.cwd])
        command.append("--")
        command.extend(
            resource_command(
                list(request.command.command), request.policy.resource_limits
            )
        )
        return command

    def _tmpfs_options(self, path: str, request: SandboxExecutionRequest) -> list[str]:
        size = request.policy.resource_limits.temporary_storage_bytes
        if size is None:
            return ["--tmpfs", path]
        return ["--size", str(size), "--tmpfs", path]

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
        for path in [
            "/etc/ld.so.cache",
            "/etc/ld.so.conf",
            "/etc/alternatives",
            "/etc/fonts",
        ]:
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
        descriptors: list[int],
    ) -> list[str]:
        options: list[str] = []
        remaining = iter(descriptors)
        for mount in mounts:
            flag = (
                "--bind-fd"
                if mount.access is SandboxFilesystemAccess.READ_WRITE
                else "--ro-bind-fd"
            )
            options.extend([flag, str(next(remaining)), mount.mount_path])
            if mount.host_path != mount.mount_path:
                options.extend([flag, str(next(remaining)), mount.host_path])
        return options

    def _sandbox_env(
        self, request: SandboxExecutionRequest, project: ProjectExecutionEnvironment
    ) -> dict[str, str]:
        return {
            **self._runtime_policy.environment(
                project=project, network_mode=request.policy.network_mode
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
