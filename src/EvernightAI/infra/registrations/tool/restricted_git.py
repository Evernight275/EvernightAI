from pathlib import Path

from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.restricted_git import (
    RestrictedGitCommitTool,
    RestrictedGitCreateBranchTool,
    RestrictedGitDiffTool,
    RestrictedGitListBranchesTool,
    RestrictedGitStatusTool,
)


def register_restricted_git_tools(
    register: ToolRegisterProtocol,
    *,
    repository_directory: str | Path,
    timeout_seconds: float = 10.0,
    max_output_chars: int = 12000,
) -> None:
    tools = [
        RestrictedGitStatusTool(
            repository_directory=repository_directory,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        ),
        RestrictedGitDiffTool(
            repository_directory=repository_directory,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        ),
        RestrictedGitCommitTool(
            repository_directory=repository_directory,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        ),
        RestrictedGitListBranchesTool(
            repository_directory=repository_directory,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        ),
        RestrictedGitCreateBranchTool(
            repository_directory=repository_directory,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        ),
    ]
    for tool in tools:
        register.register(tool.definition, tool.executor())
