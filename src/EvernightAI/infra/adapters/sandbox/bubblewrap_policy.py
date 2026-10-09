from pathlib import Path
from collections.abc import Sequence
import shutil
import sys

from EvernightAI.core.error.sandbox import SandboxConfigurationError
from EvernightAI.core.error.base import NotFoundError, ValidationError
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.sandbox import (
    SandboxExecutionRequest,
    SandboxFilesystemMount,
    SandboxNetworkMode,
    SandboxResourceLimits,
)
from EvernightAI.infra.adapters.sandbox.project_environment import (
    ProjectExecutionEnvironment,
    default_python_runtime_roots,
    resolve_project_environment,
)


class BubblewrapRuntimePolicy:
    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        network_mode: SandboxNetworkMode = SandboxNetworkMode.DISABLED,
        readonly_paths: Sequence[str | Path] | None = None,
        python_runtime_roots: Sequence[str | Path] | None = None,
        protected_paths: Sequence[str | Path] | None = None,
        include_python_environment: bool = False,
        include_uv: bool = False,
        include_node: bool = False,
        limits: SandboxResourceLimits | None = None,
        workspace_directories: WorkspaceDirectoryProtocol | None = None,
    ) -> None:
        if network_mode not in (
            SandboxNetworkMode.DISABLED,
            SandboxNetworkMode.UNRESTRICTED,
        ):
            raise SandboxConfigurationError(
                "The bubblewrap sandbox does not support network allowlists"
            )
        self.network_mode = network_mode
        self.workspace_root = (
            Path(workspace_root).resolve() if workspace_root is not None else None
        )
        self.protected_paths = [Path(path).resolve() for path in protected_paths or []]
        self._workspaces = workspace_directories
        self.limits = limits
        self.python_runtime_roots = [
            Path(path).absolute() for path in python_runtime_roots or []
        ]
        self.python_runtime_roots.extend(default_python_runtime_roots())
        self.python_environment = (
            Path(sys.prefix).absolute() if include_python_environment else None
        )
        self.readonly_paths = [Path(path).resolve() for path in readonly_paths or []]
        self._python_environment_paths: list[Path] = []
        if self.python_environment is not None:
            self._python_environment_paths.extend(
                [self.python_environment, Path(sys.base_prefix).resolve()]
            )
            executable = Path(sys.executable).absolute()
            while executable.is_symlink():
                target = executable.readlink()
                executable = (
                    target if target.is_absolute() else executable.parent / target
                ).absolute()
                self._python_environment_paths.append(executable.parent.parent)
        self.uv_path = shutil.which("uv") if include_uv else None
        if include_uv and self.uv_path is None:
            raise SandboxConfigurationError("uv was requested but is not installed")
        self.node_path = shutil.which("node") if include_node else None
        if include_node and self.node_path is None:
            raise SandboxConfigurationError("Node was requested but is not installed")
        for path in [*self.readonly_paths, *self._python_environment_paths]:
            if not path.exists():
                raise SandboxConfigurationError(
                    f"Sandbox runtime path does not exist: {path}"
                )
            self._check_protected(path)
            self._check_runtime_overlap(path)
        if self.workspace_root is not None:
            self._check_protected(self.workspace_root)
        for executable in [self.uv_path, self.node_path]:
            if executable is not None:
                self._check_protected(Path(executable))
                self._check_runtime_overlap(Path(executable))

    def _check_runtime_overlap(self, path: Path) -> None:
        path = path.resolve()
        root = self.workspace_root
        if root is not None and (
            path.is_relative_to(root) or root.is_relative_to(path)
        ):
            raise SandboxConfigurationError(
                "Read-only runtime mounts must stay outside workspace_root"
            )

    def validate_mounts(self, mounts: list[SandboxFilesystemMount]) -> None:
        for mount in mounts:
            host = Path(mount.host_path).resolve()
            if not host.is_dir():
                raise SandboxConfigurationError(
                    f"Sandbox workspace does not exist: {host}"
                )
            if self.workspace_root is not None and not host.is_relative_to(
                self.workspace_root
            ):
                if self._workspaces is None:
                    raise SandboxConfigurationError(
                        "Sandbox tool directories must stay inside workspace_root"
                    )
                try:
                    self._workspaces.resolve(str(host))
                except (NotFoundError, ValidationError) as exc:
                    raise SandboxConfigurationError(
                        "Sandbox directory must be an added project"
                    ) from exc
            self._check_protected(host)
            runtime_paths = [
                *self.readonly_paths,
                *self._python_environment_paths,
                *self.python_runtime_roots,
                *(
                    Path(executable).resolve()
                    for executable in [self.uv_path, self.node_path]
                    if executable is not None
                ),
            ]
            if any(
                host.is_relative_to(path) or path.is_relative_to(host)
                for path in runtime_paths
            ):
                raise SandboxConfigurationError(
                    "Workspace mounts must not overlap read-only runtime paths"
                )
            if mount.mount_path != "/workspace":
                raise SandboxConfigurationError(
                    "Process tools must mount their directory at /workspace"
                )
        if len(mounts) != 1:
            raise SandboxConfigurationError(
                "Process tools require one explicit workspace mount"
            )

    def _check_protected(self, path: Path) -> None:
        path = path.resolve()
        for protected in self.protected_paths:
            if protected.is_relative_to(path) or path.is_relative_to(protected):
                raise SandboxConfigurationError(
                    "Sandbox mounts must not expose protected service data"
                )

    def project_environment(
        self, request: SandboxExecutionRequest
    ) -> ProjectExecutionEnvironment:
        root = Path(request.policy.filesystem_mounts[0].host_path).resolve()
        project = resolve_project_environment(root, request.command.cwd)
        runtime = project.python_runtime
        if runtime is not None and not runtime.resolve().is_relative_to(root):
            self._check_protected(runtime)
            if not any(
                runtime.resolve().is_relative_to(path.resolve())
                for path in [
                    Path("/usr"),
                    *self.python_runtime_roots,
                    *self.readonly_paths,
                ]
            ):
                raise SandboxConfigurationError(
                    "Project Python installation is not approved; add its directory to runtime.sandbox.python_runtime_roots"
                )
            if runtime != runtime.resolve() and not any(
                runtime.is_relative_to(path)
                for path in [
                    Path("/usr"),
                    *self.python_runtime_roots,
                    *self.readonly_paths,
                ]
            ):
                raise SandboxConfigurationError(
                    "Project Python installation alias is outside approved runtime roots"
                )
            self._check_runtime_overlap(runtime)
        return project

    def runtime_mount_options(self, project: ProjectExecutionEnvironment) -> list[str]:
        options: list[str] = []
        paths = [*self.readonly_paths]
        if project.virtualenv is None:
            paths.extend(self._python_environment_paths)
        for path in dict.fromkeys(paths):
            self._check_protected(path)
            self._check_runtime_overlap(path)
            options.extend(["--ro-bind", str(path), str(path)])
        if (
            project.python_runtime is not None
            and not project.python_runtime.resolve().is_relative_to(project.root)
        ):
            path = project.python_runtime
            self._check_protected(path)
            source = path.resolve()
            options.extend(["--ro-bind", str(source), str(source)])
            if source != path:
                options.extend(["--ro-bind", str(source), str(path)])
        for name, executable in [("uv", self.uv_path), ("node", self.node_path)]:
            if executable is not None:
                self._check_protected(Path(executable).resolve())
                self._check_runtime_overlap(Path(executable))
                options.extend(
                    [
                        "--ro-bind",
                        str(Path(executable).resolve()),
                        f"/opt/evernight/bin/{name}",
                    ]
                )
        return options

    def environment(
        self,
        *,
        project: ProjectExecutionEnvironment,
        network_mode: SandboxNetworkMode | None = None,
    ) -> dict[str, str]:
        mode = self.network_mode if network_mode is None else network_mode
        paths = [
            "/opt/evernight/bin",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/usr/bin",
            "/usr/sbin",
            "/bin",
            "/sbin",
        ]
        env = {
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "UV_CACHE_DIR": "/tmp/uv-cache",
            "UV_OFFLINE": "1" if mode is SandboxNetworkMode.DISABLED else "0",
            "UV_PYTHON_DOWNLOADS": "never",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        if project.virtualenv is not None:
            virtualenv = project.sandbox_path(project.virtualenv)
            paths.insert(0, f"{virtualenv}/bin")
            env["VIRTUAL_ENV"] = virtualenv
        elif self.python_environment is not None:
            paths.insert(0, str(self.python_environment / "bin"))
        paths.insert(0, project.sandbox_path(project.cwd / "node_modules/.bin"))
        root_node_bin = "/workspace/node_modules/.bin"
        if root_node_bin not in paths:
            paths.insert(1, root_node_bin)
        env["PATH"] = ":".join(paths)
        return env

    def effective_limits(
        self, requested: SandboxResourceLimits
    ) -> SandboxResourceLimits:
        if self.limits is None:
            return requested
        values = {}
        for field in (
            "timeout_seconds",
            "max_output_chars",
            "memory_bytes",
            "max_processes",
            "cpu_seconds",
            "file_size_bytes",
            "temporary_storage_bytes",
        ):
            ceiling = getattr(self.limits, field)
            value = getattr(requested, field)
            if ceiling is None:
                values[field] = value
            elif value is None:
                values[field] = ceiling
            else:
                values[field] = min(value, ceiling)
        return SandboxResourceLimits(**values)


def resource_command(command: list[str], limits: SandboxResourceLimits) -> list[str]:
    flags = {
        "as": limits.memory_bytes,
        "nproc": limits.max_processes,
        "cpu": limits.cpu_seconds,
        "fsize": limits.file_size_bytes,
    }
    if not any(value is not None for value in flags.values()):
        return command
    prlimit = shutil.which("prlimit")
    if prlimit is None:
        raise SandboxConfigurationError(
            "prlimit is required for sandbox resource limits"
        )
    return [
        prlimit,
        *(
            f"--{flag}={value}:{value}"
            for flag, value in flags.items()
            if value is not None
        ),
        "--",
        *command,
    ]
