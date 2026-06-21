from pathlib import Path

from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.restricted_filesystem import (
    RestrictedListDirectoryTool,
    RestrictedReadTextFileTool,
    RestrictedWriteTextFileTool,
)


def register_restricted_filesystem_tools(
    register: ToolRegisterProtocol,
    *,
    root_directory: str | Path,
    max_read_chars: int = 12000,
    max_directory_entries: int = 100,
    allow_overwrite: bool = False,
) -> None:
    read_tool = RestrictedReadTextFileTool(
        root_directory=root_directory,
        max_chars=max_read_chars,
    )
    write_tool = RestrictedWriteTextFileTool(
        root_directory=root_directory,
        allow_overwrite=allow_overwrite,
    )
    list_tool = RestrictedListDirectoryTool(
        root_directory=root_directory,
        max_entries=max_directory_entries,
    )

    register.register(read_tool.definition, read_tool.executor())
    register.register(write_tool.definition, write_tool.executor())
    register.register(list_tool.definition, list_tool.executor())
