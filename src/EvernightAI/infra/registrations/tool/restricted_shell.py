from pathlib import Path

from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.restricted_shell import RestrictedShellTool


def register_restricted_shell_tool(
    register: ToolRegisterProtocol,
    *,
    allowed_commands: set[str],
    working_directory: str | Path,
    timeout_seconds: float = 10.0,
    max_output_chars: int = 12000,
) -> None:
    tool = RestrictedShellTool(
        allowed_commands=allowed_commands,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
    register.register(tool.definition, tool.executor())
