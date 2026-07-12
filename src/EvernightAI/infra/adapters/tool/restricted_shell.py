from pathlib import Path
import shlex
from typing import Any

from EvernightAI.core.error.tool import ToolInputError
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.tool import ToolExecutorProtocol
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
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor


SANDBOX_MOUNT_PATH = "/workspace"


class RestrictedShellTool:
    def __init__(
        self,
        *,
        allowed_commands: set[str],
        working_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
        requires_approval: bool = True,
        allowed_env_keys: set[str] | None = None,
        sandbox: SandboxExecuteProtocol | None = None,
    ) -> None:
        self._allowed_commands = allowed_commands
        self._working_directory = Path(working_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars
        self._requires_approval = requires_approval
        self._allowed_env_keys = allowed_env_keys
        self._sandbox = sandbox or SubprocessSandboxExecutor()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="restricted_shell",
            description="Run an allowlisted process in a fixed working directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "cwd": {"type": "string"},
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "timeout_seconds": {"type": "number"},
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
                "working_directory": str(self._working_directory),
                "timeout_seconds": self._timeout_seconds,
                "max_output_chars": self._max_output_chars,
                "allowed_env_keys": (
                    sorted(self._allowed_env_keys)
                    if self._allowed_env_keys is not None
                    else None
                ),
                "sandbox_mount_path": SANDBOX_MOUNT_PATH,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = self._parse_command(arguments)
        if not self._is_allowed_command(command):
            raise ToolInputError(f"The command {' '.join(command)} is not allowed")
        result = await self._sandbox.execute(
            SandboxExecutionRequest(
                request_id="restricted_shell",
                command=SandboxCommand(
                    command=command,
                    cwd=self._parse_cwd(arguments),
                    env=self._parse_env(arguments),
                    timeout_seconds=self._parse_timeout(arguments),
                ),
                policy=self._sandbox_policy(),
            )
        )

        return {
            "command": result.command,
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

    def _sandbox_policy(self) -> SandboxPolicy:
        return SandboxPolicy(
            command_allowlist=sorted(self._allowed_executables()),
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=str(self._working_directory),
                    mount_path=SANDBOX_MOUNT_PATH,
                    access=SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            allowed_env_keys=(
                sorted(self._allowed_env_keys)
                if self._allowed_env_keys is not None
                else None
            ),
            resource_limits=SandboxResourceLimits(
                timeout_seconds=self._timeout_seconds,
                max_output_chars=self._max_output_chars,
            ),
        )

    def _is_allowed_command(self, command: list[str]) -> bool:
        if command[0] in self._allowed_commands:
            return True
        return any(self._parse_command_rule(rule) == command for rule in self._allowed_commands)

    def _allowed_executables(self) -> set[str]:
        executables: set[str] = set()
        for rule in self._allowed_commands:
            parts = self._parse_command_rule(rule)
            if parts:
                executables.add(parts[0])
        return executables

    def _parse_command_rule(self, rule: str) -> list[str]:
        try:
            return shlex.split(rule)
        except ValueError:
            return []

    def _parse_command(self, arguments: dict[str, Any]) -> list[str]:
        command = arguments.get("command")
        if not isinstance(command, list) or not command:
            raise ToolInputError("The restricted shell command must be a non-empty list")
        if not all(isinstance(part, str) and part for part in command):
            raise ToolInputError("The restricted shell command parts must be strings")
        return command

    def _parse_cwd(self, arguments: dict[str, Any]) -> str:
        raw_cwd = arguments.get("cwd")
        if raw_cwd is None:
            return SANDBOX_MOUNT_PATH
        if not isinstance(raw_cwd, str) or not raw_cwd:
            raise ToolInputError("The working directory must be a non-empty string")

        cwd = (self._working_directory / raw_cwd).resolve()
        try:
            relative_cwd = cwd.relative_to(self._working_directory)
        except ValueError as exc:
            raise ToolInputError(
                "The working directory must stay inside the configured root"
            ) from exc
        if not cwd.is_dir():
            raise ToolInputError(f"The working directory {cwd.name} does not exist")
        if relative_cwd == Path("."):
            return SANDBOX_MOUNT_PATH
        return f"{SANDBOX_MOUNT_PATH}/{relative_cwd.as_posix()}"

    def _parse_env(self, arguments: dict[str, Any]) -> dict[str, str]:
        raw_env = arguments.get("env")
        if raw_env is None:
            return {}
        if not isinstance(raw_env, dict):
            raise ToolInputError("The env value must be a dictionary")

        env: dict[str, str] = {}
        for key, value in raw_env.items():
            if not isinstance(key, str) or not key:
                raise ToolInputError("Environment variable names must be strings")
            if self._allowed_env_keys is not None and key not in self._allowed_env_keys:
                raise ToolInputError(f"The environment variable {key} is not allowed")
            if not isinstance(value, str):
                raise ToolInputError("Environment variable values must be strings")
            env[key] = value

        return env

    def _parse_timeout(self, arguments: dict[str, Any]) -> float:
        timeout = arguments.get("timeout_seconds", self._timeout_seconds)
        if not isinstance(timeout, int | float) or timeout <= 0:
            raise ToolInputError("The timeout_seconds value must be positive")
        return float(timeout)
