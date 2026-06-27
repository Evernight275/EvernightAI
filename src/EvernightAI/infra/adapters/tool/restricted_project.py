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


class RestrictedProjectTaskTool:
    def __init__(
        self,
        *,
        working_directory: str | Path,
        commands: dict[str, list[str]],
        timeout_seconds: float = 120.0,
        max_output_chars: int = 20000,
    ) -> None:
        self._working_directory = Path(working_directory).resolve()
        self._commands = dict(commands)
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="run_project_task",
            description="Run an allowlisted project task in a fixed working directory",
            parameters_schema={
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
            permissions=[ToolPermission.PROCESS],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "working_directory": str(self._working_directory),
                "tasks": sorted(self._commands),
                "timeout_seconds": self._timeout_seconds,
                "max_output_chars": self._max_output_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task = arguments.get("task")
        if not isinstance(task, str) or not task:
            raise ToolInputError("The project task must be a non-empty string")
        command = self._commands.get(task)
        if command is None:
            raise ToolInputError(f"The project task {task} is not allowed")
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ToolInputError(f"The project task {task} command is invalid")

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
                f"The project task {task} timed out",
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"The project task {task} failed to start",
                cause=exc,
            ) from exc

        stdout_text = _decode(stdout)
        stderr_text = _decode(stderr)
        truncated = (
            len(stdout_text) > self._max_output_chars
            or len(stderr_text) > self._max_output_chars
        )
        return {
            "task": task,
            "command": command,
            "returncode": process.returncode,
            "stdout": stdout_text[: self._max_output_chars],
            "stderr": stderr_text[: self._max_output_chars],
            "truncated": truncated,
        }


def _decode(value: bytes) -> str:
    return value.decode(errors="replace")
