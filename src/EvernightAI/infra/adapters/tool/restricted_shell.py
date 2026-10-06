import os
import json
from pathlib import Path
import shlex
from typing import Any

from EvernightAI.core.error.tool import ToolInputError
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.infra.adapters.tool.project_roots import ProjectRootResolver
from EvernightAI.core.protocol.tool import (
    ToolExecutorProtocol,
    ToolPreflightPolicy,
)
from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxPolicy,
    SandboxResourceLimits,
)
from EvernightAI.core.schema.tool import (
    ToolApprovalMode,
    ToolDefinition,
    ToolPermission,
    ToolSafetyDecision,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.infra.adapters.tool.shell_policy import (
    approval_reason,
    literal_command_reason,
    inspected_commands,
    contains_deletion,
)


SANDBOX_MOUNT_PATH = "/workspace"


class RestrictedShellTool:
    def __init__(
        self,
        *,
        allowed_commands: set[str],
        working_directory: str | Path,
        blocked_commands: set[str] | None = None,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
        requires_approval: bool = True,
        relaxed_approval: bool = False,
        allowed_env_keys: set[str] | None = None,
        sandbox: SandboxExecuteProtocol | None = None,
        workspace_directories: WorkspaceDirectoryProtocol | None = None,
    ) -> None:
        self._allowed_commands = allowed_commands
        self._blocked_commands = set(blocked_commands or ())
        self._working_directory = Path(working_directory).resolve()
        self._roots = ProjectRootResolver(
            default_root=working_directory, workspace_directories=workspace_directories
        )
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars
        self._requires_approval = requires_approval
        self._relaxed_approval = relaxed_approval
        self._allowed_env_keys = allowed_env_keys
        self._sandbox = sandbox or SubprocessSandboxExecutor()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="restricted_shell",
            description=(
                "Run a command array or shell script. Pipes, redirection and command "
                "chains are supported. Use literal relative or absolute paths, with "
                "platform-correct quoting for special filenames. Environment variables "
                "are supported for ordinary commands. Deletion requires literal paths, "
                "without variable or wildcard expansion. Suspicious commands require approval."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "oneOf": [
                            {"type": "string", "minLength": 1},
                            {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                        ],
                    },
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["command"],
            },
            permissions=[ToolPermission.PROCESS],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=self._requires_approval,
            approval_mode=(
                ToolApprovalMode.REQUIRED
                if self._requires_approval
                else ToolApprovalMode.NEVER
            ),
            metadata={
                "allowed_commands": sorted(self._allowed_commands),
                "blocked_commands": sorted(self._blocked_commands),
                "relaxed_approval": self._relaxed_approval,
                "working_directory": str(self._working_directory),
                "supports_working_directory": True,
                "timeout_seconds": self._timeout_seconds,
                "max_output_chars": self._max_output_chars,
                "allowed_env_keys": sorted(self._allowed_env_keys)
                if self._allowed_env_keys is not None
                else None,
                "sandbox_mount_path": SANDBOX_MOUNT_PATH,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    def preflight_policy(self) -> ToolPreflightPolicy:
        return self.authorize

    def authorize(
        self,
        _tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> ToolSafetyDecision | None:
        try:
            self._host_cwd(arguments)
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        command = self._parse_command(arguments)
        try:
            self._parse_env(arguments)
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        reason = self._command_rejection_reason(command)
        if reason is not None:
            return ToolSafetyDecision(allowed=False, reason=reason)
        reason = approval_reason(
            command, self._allowed_commands, relaxed=self._relaxed_approval
        )
        if reason is not None:
            return ToolSafetyDecision(
                allowed=False,
                reason=reason,
                requires_approval=True,
                metadata={"working_directory": str(self._host_cwd(arguments))},
            )
        return None

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = self._parse_command(arguments)
        reason = self._command_rejection_reason(command)
        if reason is not None:
            raise ToolInputError(reason)
        process_command = self._process_command(command)
        timeout = self._parse_timeout(arguments)
        result = await self._sandbox.execute(
            SandboxExecutionRequest(
                request_id="restricted_shell",
                command=SandboxCommand(
                    command=process_command,
                    cwd=self._parse_cwd(arguments),
                    env=self._parse_env(arguments),
                    timeout_seconds=timeout,
                ),
                policy=self._sandbox_policy(
                    process_command[0], self._selected_root(arguments), timeout
                ),
            )
        )

        return {
            "command": result.command,
            "shell_script": command if isinstance(command, str) else None,
            "cwd": str(self._host_cwd(arguments)),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "events": [
                {
                    "stream": event.stream.value,
                    "text": event.text,
                    "truncated": event.truncated,
                }
                for event in result.events
            ],
            "truncated": result.truncated,
        }

    def _sandbox_policy(
        self, executable: str, root: Path, timeout: float
    ) -> SandboxPolicy:
        return SandboxPolicy(
            command_allowlist=[executable],
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=str(root),
                    mount_path=SANDBOX_MOUNT_PATH,
                    access=SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            allowed_env_keys=sorted(self._allowed_env_keys)
            if self._allowed_env_keys is not None
            else None,
            resource_limits=SandboxResourceLimits(
                timeout_seconds=timeout,
                max_output_chars=self._max_output_chars,
            ),
        )

    def _command_rejection_reason(self, command: list[str] | str) -> str | None:
        reason = literal_command_reason(command)
        if reason is not None:
            return reason
        try:
            commands = inspected_commands(command, ignore_redirections=True)
        except (ValueError, RecursionError):
            commands = [command] if isinstance(command, list) else []
        if any(self._is_blocked_command(parts) for parts in commands):
            return "The command is blocked by a configured command rule"
        return None

    def _is_blocked_command(self, command: list[str]) -> bool:
        return any(
            parts and command[: len(parts)] == parts
            for parts in (
                self._parse_command_rule(rule) for rule in self._blocked_commands
            )
        )

    def _process_command(self, command: list[str] | str) -> list[str]:
        if isinstance(command, list):
            return command
        if os.name == "nt":
            return ["cmd.exe", "/d", "/v:off", "/s", "/c", command]
        return ["/bin/sh", "-c", command]

    def _parse_command_rule(self, rule: str) -> list[str]:
        try:
            parts = shlex.split(rule, posix=os.name != "nt")
        except ValueError:
            return []
        if os.name == "nt":
            return [self._strip_matching_quotes(part) for part in parts]
        return parts

    def _strip_matching_quotes(self, value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value

    def _parse_command(self, arguments: dict[str, Any]) -> list[str] | str:
        command = arguments.get("command")
        if isinstance(command, str) and command.lstrip().startswith("["):
            try:
                decoded = json.loads(command)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(decoded, list):
                    command = decoded
        if isinstance(command, str):
            if not command.strip() or "\x00" in command:
                raise ToolInputError(
                    "The shell script must be non-empty without NUL bytes"
                )
            return command
        if not isinstance(command, list) or not command:
            raise ToolInputError(
                "The restricted shell command must be a non-empty list"
            )
        if not all(isinstance(part, str) and part for part in command):
            raise ToolInputError("The restricted shell command parts must be strings")
        return command

    def _parse_cwd(self, arguments: dict[str, Any]) -> str:
        cwd = self._host_cwd(arguments)
        relative_cwd = cwd.relative_to(self._selected_root(arguments))
        if relative_cwd == Path("."):
            return SANDBOX_MOUNT_PATH
        return f"{SANDBOX_MOUNT_PATH}/{relative_cwd.as_posix()}"

    def _host_cwd(self, arguments: dict[str, Any]) -> Path:
        root = self._selected_root(arguments)
        raw_cwd = arguments.get("cwd")
        if raw_cwd is None:
            return root
        if not isinstance(raw_cwd, str) or not raw_cwd:
            raise ToolInputError("The working directory must be a non-empty string")

        cwd = (root / raw_cwd).resolve()
        try:
            cwd.relative_to(root)
        except ValueError as exc:
            raise ToolInputError(
                "The working directory must stay inside the configured root"
            ) from exc
        if not cwd.is_dir():
            raise ToolInputError(f"The working directory {cwd.name} does not exist")
        return cwd

    def _selected_root(self, arguments: dict[str, Any]) -> Path:
        return self._roots.resolve(
            None,
            require_configured=True,
            working_directory=arguments.get("_working_directory"),
        )[1]

    def _parse_env(self, arguments: dict[str, Any]) -> dict[str, str]:
        raw_env = arguments.get("env")
        if raw_env is None:
            return {}
        if not isinstance(raw_env, dict):
            raise ToolInputError("The env value must be a dictionary")
        if not all(
            isinstance(key, str)
            and key
            and "=" not in key
            and "\x00" not in key
            and isinstance(value, str)
            and "\x00" not in value
            for key, value in raw_env.items()
        ):
            raise ToolInputError("Environment keys and values must be valid strings")
        if raw_env and contains_deletion(self._parse_command(arguments)):
            raise ToolInputError(
                "Environment variable overrides are forbidden for deletion commands"
            )
        if self._allowed_env_keys is not None and not set(raw_env).issubset(
            self._allowed_env_keys
        ):
            raise ToolInputError(
                "Environment keys are outside the configured allowed_env_keys"
            )
        return raw_env

    def _parse_timeout(self, arguments: dict[str, Any]) -> float:
        timeout = arguments.get("timeout_seconds", self._timeout_seconds)
        if not isinstance(timeout, int | float) or timeout <= 0:
            raise ToolInputError("The timeout_seconds value must be positive")
        return float(timeout)
