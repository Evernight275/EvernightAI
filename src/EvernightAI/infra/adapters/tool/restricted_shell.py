import asyncio
import os
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
        allowed_env_keys: set[str] | None = None,
    ) -> None:
        self._allowed_commands = allowed_commands
        self._working_directory = Path(working_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars
        self._allowed_env_keys = allowed_env_keys

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
            requires_approval=True,
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
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        events: list[dict[str, Any]] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._parse_cwd(arguments),
                env=self._parse_env(arguments),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(
                asyncio.gather(
                    self._collect_stream(
                        process.stdout,
                        "stdout",
                        stdout_chunks,
                        events,
                    ),
                    self._collect_stream(
                        process.stderr,
                        "stderr",
                        stderr_chunks,
                        events,
                    ),
                    process.wait(),
                ),
                timeout=self._parse_timeout(arguments),
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

        stdout = b"".join(stdout_chunks)
        stderr = b"".join(stderr_chunks)
        stdout_text = self._decode_and_truncate(stdout)
        stderr_text = self._decode_and_truncate(stderr)
        truncated = (
            len(self._decode(stdout)) > self._max_output_chars
            or len(self._decode(stderr)) > self._max_output_chars
        )

        return {
            "command": command,
            "returncode": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "events": self._truncate_events(events),
            "truncated": truncated,
        }

    async def _collect_stream(
        self,
        stream: asyncio.StreamReader | None,
        stream_name: str,
        chunks: list[bytes],
        events: list[dict[str, Any]],
    ) -> None:
        if stream is None:
            return

        while True:
            chunk = await stream.readline()
            if not chunk:
                return
            chunks.append(chunk)
            events.append({"stream": stream_name, "text": self._decode(chunk)})

    def _parse_command(self, arguments: dict[str, Any]) -> list[str]:
        command = arguments.get("command")
        if not isinstance(command, list) or not command:
            raise ToolInputError("The restricted shell command must be a non-empty list")
        if not all(isinstance(part, str) and part for part in command):
            raise ToolInputError("The restricted shell command parts must be strings")
        return command

    def _parse_cwd(self, arguments: dict[str, Any]) -> Path:
        raw_cwd = arguments.get("cwd")
        if raw_cwd is None:
            return self._working_directory
        if not isinstance(raw_cwd, str) or not raw_cwd:
            raise ToolInputError("The working directory must be a non-empty string")

        cwd = (self._working_directory / raw_cwd).resolve()
        try:
            cwd.relative_to(self._working_directory)
        except ValueError as exc:
            raise ToolInputError(
                "The working directory must stay inside the configured root"
            ) from exc
        if not cwd.is_dir():
            raise ToolInputError(f"The working directory {cwd.name} does not exist")
        return cwd

    def _parse_env(self, arguments: dict[str, Any]) -> dict[str, str] | None:
        raw_env = arguments.get("env")
        if raw_env is None:
            return None
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

        return {**os.environ, **env}

    def _parse_timeout(self, arguments: dict[str, Any]) -> float:
        timeout = arguments.get("timeout_seconds", self._timeout_seconds)
        if not isinstance(timeout, int | float) or timeout <= 0:
            raise ToolInputError("The timeout_seconds value must be positive")
        return float(timeout)

    def _decode_and_truncate(self, value: bytes) -> str:
        text = self._decode(value)
        if len(text) <= self._max_output_chars:
            return text
        return text[: self._max_output_chars]

    def _decode(self, value: bytes) -> str:
        return value.decode(errors="replace")

    def _truncate_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        remaining = self._max_output_chars
        truncated_events: list[dict[str, Any]] = []
        for event in events:
            text = event["text"]
            if len(text) > remaining:
                truncated_events.append(
                    {
                        **event,
                        "text": text[:remaining],
                        "truncated": True,
                    }
                )
                break

            truncated_events.append({**event, "truncated": False})
            remaining -= len(text)
            if remaining <= 0:
                break

        return truncated_events
