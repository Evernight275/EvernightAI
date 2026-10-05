from pathlib import Path

from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.restricted_project import (
    RestrictedProjectTaskTool,
)


def register_restricted_project_tools(
    register: ToolRegisterProtocol,
    *,
    working_directory: str | Path,
    commands: dict[str, list[str]],
    project_commands: dict[str, dict[str, list[str]]] | None = None,
    project_directories: dict[str, str | Path] | None = None,
    workspace_directories: WorkspaceDirectoryProtocol | None = None,
    timeout_seconds: float = 120.0,
    max_output_chars: int = 20000,
    sandbox: SandboxExecuteProtocol | None = None,
) -> None:
    tool = RestrictedProjectTaskTool(
        working_directory=working_directory,
        commands=commands,
        project_commands=project_commands,
        project_directories=project_directories,
        workspace_directories=workspace_directories,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        sandbox=sandbox,
    )
    register.register(
        tool.definition, tool.executor(), preflight_policy=tool.preflight_policy()
    )
