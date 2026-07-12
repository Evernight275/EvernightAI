from pathlib import Path
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
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor


SANDBOX_MOUNT_PATH = "/workspace"


class RestrictedProjectTaskTool:
    def __init__(
        self,
        *,
        working_directory: str | Path,
        commands: dict[str, list[str]],
        project_commands: dict[str, dict[str, list[str]]] | None = None,
        timeout_seconds: float = 120.0,
        max_output_chars: int = 20000,
        sandbox: SandboxExecuteProtocol | None = None,
    ) -> None:
        self._working_directory = Path(working_directory).resolve()
        self._commands = dict(commands)
        self._project_commands = {
            project: dict(project_tasks)
            for project, project_tasks in (project_commands or {}).items()
        }
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars
        self._sandbox = sandbox or SubprocessSandboxExecutor()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="run_project_task",
            description="Run an allowlisted project task in a fixed working directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "task": {"type": "string"},
                },
                "required": ["task"],
            },
            permissions=[ToolPermission.PROCESS],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "working_directory": str(self._working_directory),
                "tasks": sorted(self._commands),
                "projects": {
                    project: sorted(tasks)
                    for project, tasks in sorted(self._project_commands.items())
                },
                "timeout_seconds": self._timeout_seconds,
                "max_output_chars": self._max_output_chars,
                "sandbox_mount_path": SANDBOX_MOUNT_PATH,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task = arguments.get("task")
        if not isinstance(task, str) or not task:
            raise ToolInputError("The project task must be a non-empty string")
        project = arguments.get("project")
        if project is not None and (not isinstance(project, str) or not project):
            raise ToolInputError("The project name must be a non-empty string")
        project_tasks = (
            self._project_commands.get(project, {})
            if isinstance(project, str)
            else {}
        )
        command_scope = "project" if task in project_tasks else "global"
        command = (
            project_tasks[task]
            if command_scope == "project"
            else self._commands.get(task)
        )
        if command is None:
            qualifier = f" for project {project}" if project is not None else ""
            raise ToolInputError(f"The project task {task}{qualifier} is not allowed")
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ToolInputError(f"The project task {task} command is invalid")

        result = await self._sandbox.execute(
            SandboxExecutionRequest(
                request_id=f"run_project_task:{task}",
                command=SandboxCommand(
                    command=command,
                    cwd=SANDBOX_MOUNT_PATH,
                    timeout_seconds=self._timeout_seconds,
                ),
                policy=self._sandbox_policy(),
            )
        )

        return {
            "project": project,
            "task": task,
            "command_scope": command_scope,
            "command": result.command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
        }

    def _sandbox_policy(self) -> SandboxPolicy:
        return SandboxPolicy(
            command_allowlist=sorted(
                {command[0] for command in self._commands.values() if command}
            ),
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=str(self._working_directory),
                    mount_path=SANDBOX_MOUNT_PATH,
                    access=SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            resource_limits=SandboxResourceLimits(
                timeout_seconds=self._timeout_seconds,
                max_output_chars=self._max_output_chars,
            ),
        )
