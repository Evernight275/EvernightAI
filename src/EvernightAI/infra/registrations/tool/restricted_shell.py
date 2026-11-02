from pathlib import Path

from EvernightAI.core.protocol.sandbox import (
    SandboxExecuteProtocol,
    SandboxSpawnProtocol,
)
from EvernightAI.core.protocol.shell import ShellSessionStoreProtocol
from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.infra.adapters.tool.restricted_shell import RestrictedShellTool
from EvernightAI.infra.adapters.tool.shell_processes import (
    ShellProcessManager,
    ShellProcessTools,
)


def register_restricted_shell_tool(
    register: ToolRegisterProtocol,
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
    session_store: ShellSessionStoreProtocol | None = None,
    process_manager: ShellProcessManager | None = None,
) -> None:
    """Register restricted_shell, plus background process tools when managed."""
    sandbox = sandbox or SubprocessSandboxExecutor()
    tool = RestrictedShellTool(
        allowed_commands=allowed_commands,
        blocked_commands=blocked_commands,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        requires_approval=requires_approval,
        relaxed_approval=relaxed_approval,
        allowed_env_keys=allowed_env_keys,
        sandbox=sandbox,
        workspace_directories=workspace_directories,
        session_store=session_store,
    )
    register.register(
        tool.definition,
        tool.executor(),
        preflight_policy=tool.preflight_policy(),
    )
    if process_manager is None:
        return
    if not isinstance(sandbox, SandboxSpawnProtocol):
        raise ValueError("Shell processes require a sandbox that can spawn processes")
    processes = ShellProcessTools(tool, sandbox, process_manager)
    for definition, executor, preflight in processes.registrations():
        register.register(definition, executor, preflight_policy=preflight)
