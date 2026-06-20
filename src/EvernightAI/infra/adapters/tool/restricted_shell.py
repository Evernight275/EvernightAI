import asyncio
from pathlib import Path
from typing import Any

from EvernightAI.core.error.tool import ToolExecutionError, ToolInputError
from EvernightAI.core.protocol.tool import ToolExecutorProtocol
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


class RestrictedShellTool:
    def __init__(
        self,
        *,
        allowed_commands: set[str],
        working_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._allowed_commands = allowed_commands
        self._working_directory = Path(working_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

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
                    }
                },
                "required": ["command"],
            },
            permissions=[ToolPermission.PROCESS],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "allowed_commands": sorted(self._allowed_commands),
                "working_directory": str(self._working_directory),
                "timeout_seconds": self._timeout_seconds,
                "max_output_chars": self._max_output_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = self._parse_command(arguments)
        executable = command[0]
        if executable not in self._allowed_commands:
            raise ToolInputError(f"The command {executable} is not allowed")

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._working_directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.wait()
            raise ToolExecutionError(
                f"The command {executable} timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"The command {executable} failed to start",
                cause=exc,
            ) from exc

        stdout_text = self._decode_and_truncate(stdout)
        stderr_text = self._decode_and_truncate(stderr)

        return {
            "command": command,
            "returncode": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "truncated": (
                len(self._decode(stdout)) > self._max_output_chars
                or len(self._decode(stderr)) > self._max_output_chars
            ),
        }

    def _parse_command(self, arguments: dict[str, Any]) -> list[str]:
        command = arguments.get("command")
        if not isinstance(command, list) or not command:
            raise ToolInputError("The restricted shell command must be a non-empty list")
        if not all(isinstance(part, str) and part for part in command):
            raise ToolInputError("The restricted shell command parts must be strings")
        return command

    def _decode_and_truncate(self, value: bytes) -> str:
        text = self._decode(value)
        if len(text) <= self._max_output_chars:
            return text
        return text[: self._max_output_chars]

    def _decode(self, value: bytes) -> str:
        return value.decode(errors="replace")
